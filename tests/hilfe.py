"""Gemeinsame Vorbereitung fuer alle Tests.

Muss importiert werden, BEVOR irgendetwas aus kern/ geladen wird: die
Einstellungen lesen die Umgebung beim Import, und ein spaeter gesetztes
DATEN_DIR kaeme zu spaet - die Tests liefen dann auf dem echten Datenbestand.
"""

import atexit
import os
import shutil
import sys
import tempfile

_ORDNER = tempfile.mkdtemp(prefix="wag-test-")
os.environ.update({
    # Riegel gegen den teuersten denkbaren Testlauf: Ruft irgendetwas
    # unterwegs kern.konfig.einlesen() auf, kaeme von dort DATABASE_URL der
    # Produktion - und die Tests loeschten und legten Tabellen im Livebestand
    # an. Mit diesem Schalter bleibt config.cmd ungelesen.
    "KONFIG_GELESEN": "1",
    # Derselbe Riegel fuer die hochgeladenen Dateien: Wer die Tests aus einem
    # Fenster startet, in dem vorher config.cmd gelaufen ist, haette den
    # Schluessel noch in der Umgebung - und jeder Testlauf legte Bilder in
    # den Bucket der Produktion.
    "SUPABASE_SERVICE_KEY": "",
    "SUPABASE_URL": "",
    "DATEN_DIR": _ORDNER,
    "SECRET_KEY": "t" * 64,
    "APP_ENV": "development",
    "HTTPS_ONLY_COOKIES": "false",
    "SMTP_HOST": "",
    "BACKUPS_ENABLED": "false",
    "REMINDERS_ENABLED": "false",
    "WEBSITE_URL": "http://localhost:8000",
    "DASHBOARD_URL": "http://localhost:8001",
})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@atexit.register
def _aufraeumen():
    shutil.rmtree(_ORDNER, ignore_errors=True)


TESTORDNER = _ORDNER
TESTPASSWORT = "PruefLauf2026xyz"


def frische_datenbank():
    """Legt Tabellen an und gibt einen angemeldeten CTO zurueck."""
    from kern.migration import migriere
    from kern.datenbank import SessionLocal
    from kern.modelle import User
    from kern.rechte import cache_verwerfen
    from kern.sicherheit import passwort_hashen

    migriere(still=True)
    db = SessionLocal()
    person = db.query(User).filter(User.email == "pruef@ag.local").first()
    if not person:
        person = User(vorname="Pruef", nachname="Konto", email="pruef@ag.local",
                      password_hash=passwort_hashen(TESTPASSWORT), role="cto",
                      department="exekutive", status="aktiv")
        db.add(person)
        db.commit()
    cache_verwerfen()
    db.close()
    return "pruef@ag.local"


def angemeldeter_client():
    """(website_client, dashboard_client) - beide angemeldet."""
    import re
    from fastapi.testclient import TestClient
    from website.app import app as web
    from dashboard.app import app as dash

    adresse = frische_datenbank()
    with TestClient(web) as w:
        seite = w.get("/login").text
        token = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
        w.post("/login", data={"email": adresse, "passwort": TESTPASSWORT,
                               "csrf": token}, follow_redirects=False)
        kekse = dict(w.cookies)
    return TestClient(web, cookies=kekse), TestClient(dash, cookies=kekse)


def csrf_aus(text: str) -> str:
    import re
    treffer = re.search(r'name="csrf" value="([^"]+)"', text)
    return treffer.group(1) if treffer else ""
