"""Gemeinsame Kleinteile aller Dashboard-Bereiche.

Jeder Bereich ist ein htmx-Teilstueck: Er liefert kein ganzes HTML-Dokument,
sondern nur den Inhalt fuer #tab-inhalt. Diese Datei nimmt den immer gleichen
Rahmen drumherum ab - Anmeldung pruefen, Rechte pruefen, Rueckmeldung
mitgeben.
"""

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from kern.datenbank import hole_db
from kern.einstellungen import (
    HTTPS_ONLY_COOKIES, TRUST_PROXY_HEADERS, adressen_fuer,
)
from kern.rechte import rechte_von
from kern.sitzung import (
    angemeldete_person, csrf_gueltig, csrf_hinweis, csrf_token, wache,
)
from kern.vorlagen import umgebung


class Anmeldung:
    """Abhaengigkeit: liefert die angemeldete Person oder bricht ab.

        async def bereich(a: Anmeldung = Depends(Anmeldung.pflicht)):
            a.user, a.db, a.request stehen bereit.
    """

    def __init__(self, request: Request, db: Session, user):
        self.request = request
        self.db = db
        self.user = user
        self.rechte = rechte_von(user, db)

    @classmethod
    def pflicht(cls, request: Request, db: Session = Depends(hole_db)):
        user = angemeldete_person(request, db)
        if not user:
            # Kein Redirect: bei einem htmx-Nachladen wuerde die Anmeldeseite
            # im Inhaltsbereich landen. wache() setzt stattdessen HX-Redirect.
            website, _ = adressen_fuer(request)
            antwort = wache(user, request, f"{website}/login")
            raise _Umleitung(antwort)
        return cls(request, db, user)

    # --- Bequemlichkeiten --------------------------------------------------
    def darf(self, *perms) -> bool:
        return any(self.rechte.get(p) for p in perms)

    def verlange(self, *perms) -> None:
        if not self.darf(*perms):
            raise HTTPException(403, "Für diesen Bereich fehlt dir die Berechtigung.")

    @property
    def csrf(self) -> str:
        return csrf_token(self.request)

    def pruefe_csrf(self, token: str) -> None:
        if not csrf_gueltig(self.request, token):
            raise HTTPException(400, csrf_hinweis(
                self.request, HTTPS_ONLY_COOKIES, TRUST_PROXY_HEADERS))


class _Umleitung(Exception):
    """Traegt eine fertige Antwort aus der Abhaengigkeit heraus."""

    def __init__(self, antwort):
        self.antwort = antwort
        super().__init__("Nicht angemeldet")


def teil(name: str, a: Anmeldung, **inhalt) -> HTMLResponse:
    """Ein Bereichs-Teilstueck rendern.

    Setzt die Dinge, die jeder Bereich braucht, damit sie nicht ueberall
    einzeln durchgereicht werden muessen.
    """
    inhalt.setdefault("user", a.user)
    inhalt.setdefault("rechte", a.rechte)
    inhalt.setdefault("csrf", a.csrf)
    inhalt.setdefault("nonce", getattr(a.request.state, "nonce", ""))
    # Wie in kern.vorlagen.zeige(): Verweise sollen auf der Adresse bleiben,
    # ueber die jemand hereingekommen ist.
    website, dash = adressen_fuer(a.request)
    inhalt.setdefault("WEBSITE_URL", website)
    inhalt.setdefault("DASHBOARD_URL", dash)
    return HTMLResponse(umgebung.get_template(name).render(**inhalt))


def meldung(art: str, text: str, bereich: str = "", knopf: str = "") -> dict:
    """Rueckmeldung fuer die Vorlage.

    `bereich` und `knopf` haengen einen Verweis an die Meldung - gedacht fuer
    "Das liegt jetzt im Papierkorb" mit einem Knopf, der auch dorthin fuehrt.
    Ohne den muss man erst suchen, wo das Zurueckholen geht; mit ihm ist ein
    versehentliches Loeschen in zwei Klicks erledigt.
    """
    return {"art": art, "text": text, "bereich": bereich, "knopf": knopf}


def gut(text: str, bereich: str = "", knopf: str = "") -> dict:
    return meldung("gut", text, bereich, knopf)


def papierkorb_hinweis(text: str) -> dict:
    """Erfolgsmeldung mit dem Weg zurueck."""
    return meldung("gut", text, "papierkorb", "Im Papierkorb ansehen")


def fehler(text: str) -> dict:
    return meldung("fehler", text)


def warnung(text: str) -> dict:
    return meldung("warnung", text)


def info(text: str) -> dict:
    return meldung("info", text)


def zahl(wert, standard=None):
    """Eine Zahl aus einem Formularfeld - None statt Absturz bei Unsinn."""
    try:
        return int(str(wert).strip())
    except (TypeError, ValueError):
        return standard


def datum(wert):
    """Ein Datum aus einem Formularfeld (YYYY-MM-DD) - None bei Unsinn."""
    from datetime import date
    text = (wert or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def uhrzeit(wert) -> str:
    """"HH:MM" oder leer. Alles andere wird verworfen."""
    import re
    text = (wert or "").strip()
    return text if re.fullmatch(r"[0-2]\d:[0-5]\d", text) else ""


def als_csv(zeilen, spalten, dateiname: str):
    """Eine Liste als CSV-Datei ausliefern - mit Schutz vor Formel-Injektion."""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    from kern.text import csv_sicher

    puffer = io.StringIO()
    # Semikolon und BOM: so oeffnet Excel im deutschen Sprachraum die Datei
    # direkt richtig, statt alles in eine Spalte zu quetschen.
    puffer.write("﻿")
    schreiber = csv.writer(puffer, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    schreiber.writerow(spalten)
    for zeile in zeilen:
        schreiber.writerow([csv_sicher(w) for w in zeile])
    puffer.seek(0)
    return StreamingResponse(
        iter([puffer.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{dateiname}"'})
