"""Aufbau der Dashboard-Anwendung (Port 8001)."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from kern import einstellungen as cfg
from kern import mail, planer
from kern.datenbank import hole_db
from kern.migration import migriere
from kern.modelle import User
from kern.sicherheit import passwort_hashen, passwort_gueltig
from kern.sitzung import angemeldete_person, csrf_token
from kern.vorlagen import zeige
from kern.webbasis import baue_app, bremse_aufraeumer_starten
from dashboard import navigation
from dashboard.hilfen import _Umleitung
from dashboard.routen import (
    arbeit, kommunikation, konto, neuerungen, organisation, personen,
    system, uebersicht, funktionsadressen,
)


def ersten_zugang_sichern() -> None:
    """Sorgt dafuer, dass es mindestens ein handlungsfaehiges Konto gibt.

    Nur bei einer voellig leeren Anlage. Auf einer bestehenden Datenbank
    passiert hier nichts - dort gibt es den CTO laengst.
    """
    from kern.datenbank import sitzung
    from kern.text import email_normal

    with sitzung() as db:
        vorhanden = db.query(User).filter(User.role == "cto",
                                          User.status == "aktiv").first()
        if vorhanden:
            return
        if not cfg.DEFAULT_ADMIN_PASSWORD or not passwort_gueltig(cfg.DEFAULT_ADMIN_PASSWORD):
            raise RuntimeError(
                "Kein aktives CTO-Konto vorhanden. Setze DEFAULT_ADMIN_PASSWORD "
                "in config.cmd auf ein starkes Passwort (mindestens 12 Zeichen, "
                "Groß- und Kleinbuchstaben sowie eine Ziffer).")
        adresse = email_normal(cfg.DEFAULT_ADMIN_EMAIL)
        person = db.query(User).filter(User.email == adresse).first()
        if person:
            person.role, person.status = "cto", "aktiv"
            person.department = "exekutive"
            person.password_hash = passwort_hashen(cfg.DEFAULT_ADMIN_PASSWORD)
            print(f"[Zugang] Bestehendes Konto {adresse} als CTO reaktiviert.")
        else:
            db.add(User(vorname="Vorstand", nachname="Konto", email=adresse,
                        password_hash=passwort_hashen(cfg.DEFAULT_ADMIN_PASSWORD),
                        role="cto", department="exekutive", status="aktiv"))
            print(f"[Zugang] Erstes CTO-Konto angelegt: {adresse}")
        db.commit()


@asynccontextmanager
async def lebenszyklus(_app: FastAPI):
    print("\n  Wirtschafts- & Investment-AG · Dashboard")
    print("  " + "-" * 52)
    migriere()
    mail.vordrucke_anlegen()
    from kern import cloudflare
    from kern.datenbank import sitzung
    with sitzung() as db:
        cloudflare.vorbefuellen(db)
    ersten_zugang_sichern()
    bremse_aufraeumer_starten()
    for zeile in cfg.zusammenfassung():
        print("  " + zeile)
    # Die Hintergrundlaeufe haengen ausschliesslich an diesem Prozess.
    planer.alles_starten()
    print("  " + "-" * 52 + "\n")
    yield


app = baue_app("AG-Dashboard", ist_dashboard=True)
app.router.lifespan_context = lebenszyklus


@app.exception_handler(_Umleitung)
async def _nicht_angemeldet(_request: Request, fehler: _Umleitung):
    return fehler.antwort


def _startinhalt(request: Request, db: Session, user) -> str:
    """Die Übersicht schon fertig in den Rahmen legen.

    Vorher lieferte der Server nur das Gerüst mit einem Platzhalter; das
    Skript klickte danach den ersten Punkt an und holte den Inhalt in einem
    zweiten Rundweg. Auf dem Handy sind das schnell mal 400 Millisekunden, in
    denen jemand auf graue Balken schaut - bei jedem Öffnen des Dashboards.

    Scheitert es hier, bleibt der Platzhalter stehen und das Skript lädt wie
    bisher nach. Die Startseite darf nicht daran hängen, dass ein einzelner
    Bereich hakt.
    """
    from dashboard.hilfen import Anmeldung
    from dashboard.routen.uebersicht import uebersicht as uebersicht_bereich
    try:
        antwort = uebersicht_bereich(Anmeldung(request, db, user))
        return antwort.body.decode("utf-8")
    except Exception as problem:                             # pragma: no cover
        print(f"[Dashboard] Übersicht konnte nicht vorgerendert werden: "
              f"{type(problem).__name__}: {problem}")
        return ""


@app.get("/")
def start(request: Request, db: Session = Depends(hole_db)):
    """Der Rahmen samt fertiger Übersicht. Weitere Bereiche laedt htmx nach."""
    user = angemeldete_person(request, db)
    if not user:
        website, _ = cfg.adressen_fuer(request)
        return RedirectResponse(f"{website}/login", status_code=303)

    from kern.rechte import rechte_von
    rechte = rechte_von(user, db)
    punkte = navigation.bereiche(db, user)

    from dashboard.routen.konto import rundgang_faellig
    from dashboard.routen.neuerungen import faellig as neuerungen_faellig
    # Erst-Rundgang hat Vorrang: Wer die Plattform noch gar nicht kennt,
    # braucht keine Liste der Aenderungen. faellig() beruecksichtigt das.
    rundgang = rundgang_faellig(db, user)
    return zeige("dashboard/rahmen.html", request=request, user=user,
                 navigation=navigation.gruppiert(punkte),
                 zaehler=navigation.zaehler(db, user, rechte),
                 csrf=csrf_token(request),
                 start_bereich="uebersicht",
                 start_inhalt=_startinhalt(request, db, user),
                 rundgang_anbieten=rundgang,
                 neuerungen_anbieten=(not rundgang
                                      and neuerungen_faellig(db, user)),
                 robots="noindex, nofollow")


@app.get("/dashboard")
def dashboard_unter_pfad(request: Request, db: Session = Depends(hole_db)):
    """Dasselbe Dashboard auch unter /dashboard.

    Zwei Gruende: V1 lag unter /dashboard, bestehende Lesezeichen sollen nicht
    ins Leere laufen. Und im Betrieb hinter einem Tunnel laesst sich so alles
    unter EINER Adresse betreiben - /dashboard auf Port 8001, der Rest auf
    8000. Das ist die Voraussetzung dafuer, dass eine einzige auf dem
    Startbildschirm abgelegte App Meldungen aus beiden Teilen bekommt.
    """
    return start(request, db)


# Manifest und Hintergrundskript auch hier: Push haengt am Ursprung, und ohne
# eigenes /sw.js lief die Registrierung im Dashboard in einen 404.
from website.routen.pwa import baue_router as _pwa_router          # noqa: E402
# Das Kalender-Abo gibt es auf beiden Seiten unter derselben Adresse:
# Eine Kalender-App soll nicht daran scheitern, dass gerade der eine
# Name klemmt (kern/kalender_abo.py).
from kern.kalender_abo import baue_router as _kalender_abo  # noqa: E402
app.include_router(_kalender_abo())

app.include_router(_pwa_router(ist_dashboard=True))

app.include_router(uebersicht.router)
app.include_router(arbeit.router)
app.include_router(personen.router)
app.include_router(organisation.router)
app.include_router(kommunikation.router)
app.include_router(system.router)
app.include_router(funktionsadressen.router)
app.include_router(konto.router)
app.include_router(neuerungen.router)
