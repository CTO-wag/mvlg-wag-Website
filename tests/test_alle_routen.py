"""Jede Adresse einmal aufrufen - und zwar aus verschiedenen Blickwinkeln.

Der Sinn: Ein Tippfehler in einer Vorlage oder ein vergessener Parameter
fällt sonst erst auf, wenn jemand den Bereich zum ersten Mal öffnet. Hier
wird jede GET-Adresse beider Server aufgerufen und darauf gesehen, dass
nirgends ein Serverfehler herauskommt - weder angemeldet noch nicht
angemeldet, weder als CTO noch als einfaches Mitglied.
"""

import re
import unittest

from tests import hilfe                                      # noqa: F401

from fastapi.testclient import TestClient

from kern.datenbank import SessionLocal
from kern.modelle import User
from kern.sicherheit import passwort_hashen
from tests.hilfe import TESTPASSWORT, angemeldeter_client
from website.app import app as web_app
from dashboard.app import app as dash_app


def _adressen(app, ohne_platzhalter=True):
    """Alle GET-Adressen einer Anwendung."""
    gefunden = []
    for route in app.routes:
        pfade = getattr(route, "path", None)
        methoden = getattr(route, "methods", set()) or set()
        if not pfade or "GET" not in methoden:
            continue
        if ohne_platzhalter and "{" in pfade:
            continue
        gefunden.append(pfade)
    return sorted(set(gefunden))


class TestAlleAdressen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()
        cls.offen_web = TestClient(web_app)
        cls.offen_dash = TestClient(dash_app)

        # Ein einfaches Mitglied: sieht wenig, darf wenig - und darf trotzdem
        # nirgends einen Serverfehler auslösen.
        db = SessionLocal()
        if not db.query(User).filter(User.email == "mitglied@ag.local").first():
            db.add(User(vorname="Ein", nachname="Mitglied",
                        email="mitglied@ag.local",
                        password_hash=passwort_hashen(TESTPASSWORT),
                        role="member", department="marketing", status="aktiv"))
            db.commit()
        db.close()
        seite = cls.offen_web.get("/login").text
        token = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
        cls.offen_web.post("/login", data={"email": "mitglied@ag.local",
                                           "passwort": TESTPASSWORT,
                                           "csrf": token},
                           follow_redirects=False)
        kekse = dict(cls.offen_web.cookies)
        cls.mitglied_web = TestClient(web_app, cookies=kekse)
        cls.mitglied_dash = TestClient(dash_app, cookies=kekse)

    def _durchgehen(self, klient, app, name, erlaubt):
        fehlerhaft = []
        for pfad in _adressen(app):
            if pfad in ("/logout",):        # meldet ab, kommt zuletzt
                continue
            antwort = klient.get(pfad, follow_redirects=False)
            if antwort.status_code not in erlaubt:
                fehlerhaft.append(f"{pfad} -> {antwort.status_code}")
        self.assertEqual(fehlerhaft, [], f"{name}: unerwartete Antworten")

    def test_website_ohne_anmeldung(self):
        self._durchgehen(TestClient(web_app), web_app, "Website (offen)",
                         {200, 303, 304, 401, 403, 404})

    def test_website_angemeldet(self):
        self._durchgehen(self.web, web_app, "Website (angemeldet)",
                         {200, 303, 304, 404})

    def test_dashboard_als_cto(self):
        self._durchgehen(self.dash, dash_app, "Dashboard (CTO)",
                         {200, 303, 304, 403, 404})

    def test_dashboard_als_mitglied(self):
        """Ein Mitglied bekommt 403 statt 500, wo es nichts zu suchen hat."""
        self._durchgehen(self.mitglied_dash, dash_app, "Dashboard (Mitglied)",
                         {200, 303, 304, 403, 404})

    def test_dashboard_ohne_anmeldung_fuehrt_zur_anmeldung(self):
        for pfad in ("/", "/dashboard", "/dashboard/aufgaben"):
            antwort = self.offen_dash.get(pfad, follow_redirects=False)
            self.assertIn(antwort.status_code, (303, 401),
                          f"{pfad} war ohne Anmeldung erreichbar")

    def test_unbekannte_adresse_ist_404_und_sagt_es_auch(self):
        antwort = self.web.get("/gibt-es-nicht")
        self.assertEqual(antwort.status_code, 404)
        self.assertIn("404", antwort.text)

    def test_csv_ausgaben(self):
        for pfad in ("/dashboard/aufgaben/export.csv",
                     "/dashboard/konten/export.csv",
                     "/dashboard/kassenbuch/export.csv"):
            antwort = self.dash.get(pfad)
            self.assertIn(antwort.status_code, (200, 403), pfad)
            if antwort.status_code == 200:
                self.assertTrue(antwort.text.startswith("﻿"),
                                f"{pfad}: ohne BOM öffnet Excel es falsch")

    def test_jede_seite_hat_die_sicherheitskoepfe(self):
        for klient, pfad in ((self.web, "/"), (self.dash, "/")):
            kopf = klient.get(pfad).headers
            self.assertIn("Content-Security-Policy", kopf)
            self.assertNotIn("unsafe-inline", kopf["Content-Security-Policy"]
                             .split("script-src")[1].split(";")[0])
            self.assertEqual(kopf.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(kopf.get("Referrer-Policy"),
                             "strict-origin-when-cross-origin")
            self.assertIn("X-Frame-Options", kopf)

    def test_dashboard_bleibt_aus_suchmaschinen(self):
        kopf = self.dash.get("/").headers
        self.assertIn("noindex", kopf.get("X-Robots-Tag", ""))


if __name__ == "__main__":
    unittest.main()
