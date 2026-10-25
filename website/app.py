"""Aufbau der oeffentlichen Anwendung."""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

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
# Meldeweg fuer die Geraetediagnose. Auch hier und nicht nur im
# Dashboard: Ein JavaScript-Fehler auf der oeffentlichen Seite ist
# genauso eine Supportfrage, und die Push-Anmeldung passiert sogar
# ueberwiegend dort. Siehe kern/diagnose.py.
from kern.diagnose import baue_router as _diagnose_router  # noqa: E402
app.include_router(_diagnose_router())

app.include_router(oeffentlich.router)
app.include_router(anmeldung.router)
app.include_router(bewerbung.router)
app.include_router(pwa.router)

# Die Netlify-Landingpage wird hier ebenfalls ausgeliefert, damit der
# öffentliche Ursprung und der Cloudflare-Fallback dieselben Dateien nutzen.
_NETLIFY_DIST = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "wag-koblenz", "dist")
app.mount("/", StaticFiles(directory=_NETLIFY_DIST), name="netlify-site")
