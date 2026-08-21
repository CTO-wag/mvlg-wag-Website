"""Aufbau der oeffentlichen Anwendung."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from kern import einstellungen as cfg
from kern import mail, planer
from kern.migration import migriere
from kern.webbasis import baue_app, bremse_aufraeumer_starten
from website.routen import anmeldung, bewerbung, oeffentlich, pwa


@asynccontextmanager
async def lebenszyklus(_app: FastAPI):
    print("\n  Wirtschafts- & Investment-AG · Website")
    print("  " + "-" * 52)
    migriere()
    mail.vordrucke_anlegen()
    bremse_aufraeumer_starten()
    # Die Hintergrundlaeufe (Sicherungen, Erinnerungen, Scoring) haengen am
    # Dashboard-Prozess, nicht hier. Zweimal dieselbe Sicherung anzulegen
    # oder zweimal dieselbe Erinnerung zu verschicken waere genau der Fehler,
    # den eine Trennung in zwei Prozesse leicht einlaedt.
    planer.nur_aufraeumen_starten()
    for zeile in cfg.zusammenfassung():
        print("  " + zeile)
    print("  " + "-" * 52 + "\n")
    yield


app = baue_app("AG-Website", ist_dashboard=False)
app.router.lifespan_context = lebenszyklus

# Das Kalender-Abo gibt es auf beiden Seiten unter derselben Adresse:
# Eine Kalender-App soll nicht daran scheitern, dass gerade der eine
# Name klemmt (kern/kalender_abo.py).
from kern.kalender_abo import baue_router as _kalender_abo  # noqa: E402
app.include_router(_kalender_abo())

app.include_router(oeffentlich.router)
app.include_router(anmeldung.router)
app.include_router(bewerbung.router)
app.include_router(pwa.router)
