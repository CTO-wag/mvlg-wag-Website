"""Aus einer Fehlermeldung heraus den Support erreichen.

Gemeldet: Leute rennen gegen einen Fehler, versuchen es zweimal und geben auf.
Dass es einen Support gibt, wissen sie - nur nicht in dem Moment, in dem sie
ihn brauchen. Auf der Bewerbungsseite ist das die teuerste Stelle der ganzen
Anlage: Eine verlorene Bewerbung sieht niemand.

Deshalb steht der Weg dorthin ab jetzt IN der Meldung. Geprueft wird hier, dass
er auch wirklich ueberall auftaucht - und dass er die Fehlermeldung mitnimmt,
denn ohne sie steht in jedem zweiten Ticket "geht nicht".
"""

import pathlib
import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests import hilfe                                      # noqa: F401

from kern.webbasis import baue_app
from tests.hilfe import angemeldeter_client, csrf_aus, frische_datenbank

WURZEL = pathlib.Path(__file__).resolve().parent.parent
KNOPF = "data-support-melden"


class TestOeffentlicheSeiten(unittest.TestCase):
    """Wer kein Konto hat, wird zum Kontaktformular geschickt."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()
        cls.gast = TestClient(cls.web.app, base_url="http://localhost:8000")

    def test_fehler_im_bewerbungsformular(self):
        seite = self.gast.get("/bewerbung").text
        antwort = self.gast.post("/bewerbung", data={
            "csrf": csrf_aus(seite), "vorname": "", "nachname": "",
            "klasse": "", "email": "", "telefonnummer": "", "abteilung": "",
            "motivation": "", "interessen": ""})
        self.assertIn("meldung-fehler", antwort.text)
        self.assertIn(KNOPF, antwort.text)
        # Der Wortlaut geht mit - sonst beginnt die Rueckfrage bei null.
        self.assertIn('data-support-text="Bitte alle Pflichtfelder',
                      antwort.text)

    def test_fehler_bei_der_anmeldung(self):
        """Der häufigste Fall überhaupt: Jemand kommt nicht rein und weiß
        nicht, an wen er sich wendet."""
        seite = self.gast.get("/login").text
        antwort = self.gast.post("/login", data={
            "csrf": csrf_aus(seite), "email": "gibtsnicht@beispiel.de",
            "passwort": "FalschFalschFalsch1"}, follow_redirects=False)
        self.assertIn("meldung-fehler", antwort.text)
        self.assertIn(KNOPF, antwort.text)

    def test_fehler_im_kontaktformular(self):
        seite = self.gast.get("/").text
        antwort = self.gast.post("/kontakt", data={
            "csrf": csrf_aus(seite), "name": "", "email": "", "nachricht": "",
            "webseite": ""})
        self.assertIn(KNOPF, antwort.text)

    def test_ohne_fehler_kein_knopf(self):
        """Er soll auffallen, wenn etwas schiefgeht - nicht dauernd."""
        self.assertNotIn(KNOPF, self.gast.get("/bewerbung").text)
        self.assertNotIn(KNOPF, self.gast.get("/").text)


class TestFehlerseiten(unittest.TestCase):
    """403, 429 und 500 sind genau die Momente, in denen man melden soll."""

    @classmethod
    def setUpClass(cls):
        frische_datenbank()
        app = baue_app("Probe", ist_dashboard=False)

        @app.get("/stolper/{status}")
        def stolper(status: int):
            raise HTTPException(status_code=status, detail="Beispielgrund")

        cls.k = TestClient(app, raise_server_exceptions=False,
                           base_url="http://localhost:8000")

    def _seite(self, status):
        antwort = self.k.get(f"/stolper/{status}")
        self.assertEqual(antwort.status_code, status)
        return antwort.text

    def test_verboten_zu_viel_und_kaputt_bieten_den_weg_an(self):
        for status in (403, 429, 500):
            with self.subTest(status=status):
                text = self._seite(status)
                self.assertIn(KNOPF, text)
                # Ohne die Adresse steht im Ticket "Fehler 500" und sonst
                # nichts, und die Suche beginnt bei null.
                self.assertIn("/stolper/", text)

    def test_bei_404_nicht(self):
        """Eine fehlende Seite ist meistens ein alter Verweis und kein
        Fehler - ein Meldeknopf daneben wäre Rauschen, und Rauschen ist
        genau das, was ihn im Ernstfall unsichtbar macht."""
        self.assertNotIn(KNOPF, self._seite(404))


class TestDashboard(unittest.TestCase):
    """Angemeldete bleiben im Dashboard - dort gibt es ein echtes Ticket."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_fehlermeldung_traegt_den_knopf(self):
        seite = self.dash.get("/dashboard/aufgaben").text
        antwort = self.dash.post("/dashboard/aufgaben", data={
            "csrf": csrf_aus(seite), "titel": ""})
        self.assertIn("meldung-fehler", antwort.text)
        self.assertIn("data-support", antwort.text)
        self.assertIn('data-support-text="Ohne Titel geht es nicht."',
                      antwort.text)

    def test_erfolgsmeldung_traegt_ihn_nicht(self):
        """Er soll auffallen, wenn etwas schiefgeht - nicht dauernd. Ein
        Knopf, der immer da ist, wird zu Tapete."""
        seite = self.dash.get("/dashboard/aufgaben").text
        antwort = self.dash.post("/dashboard/aufgaben", data={
            "csrf": csrf_aus(seite), "titel": "Eine ganz normale Aufgabe",
            "zustaendig": "a:exekutive", "rang": "mittel"})
        self.assertIn("meldung-gut", antwort.text)
        self.assertNotIn("data-support", antwort.text)


class TestVerdrahtung(unittest.TestCase):
    """Die Knöpfe brauchen beide Seiten: Markup UND das Skript dahinter.

    Ein Knopf, der nichts tut, ist schlimmer als keiner - er verbraucht das
    einzige Mal, das jemand um Hilfe zu bitten bereit war.
    """

    def test_oeffentliches_skript_faengt_den_knopf_ab(self):
        js = (WURZEL / "statisch/js/basis.js").read_text(encoding="utf-8")
        self.assertIn("[data-support-melden]", js)
        self.assertIn("'/#kontakt'", js)
        # Der Anlass geht über sessionStorage, nicht über die Adresszeile:
        # Ein Text aus der URL, der in ein Formular läuft, ist eine
        # Einladung, die man jemandem als Verweis schicken kann.
        self.assertIn("sessionStorage", js)
        self.assertNotIn("innerHTML", js.split("SUPPORT_SCHLUESSEL")[1][:2000])

    def test_dashboard_skript_fuellt_das_formular(self):
        js = (WURZEL / "statisch/js/dashboard.js").read_text(encoding="utf-8")
        self.assertIn("[data-support]", js)
        self.assertIn('data-bereich="support"', js)
        self.assertIn('form[hx-post="/dashboard/support"]', js)

    def test_makro_und_teilvorlage_gibt_es(self):
        makros = (WURZEL / "vorlagen/dashboard/teile/makros.html").read_text(
            encoding="utf-8")
        self.assertIn("macro supportknopf", makros)
        self.assertIn("macro fehlerkasten", makros)
        teil = (WURZEL / "vorlagen/teile/meldungen.html").read_text(
            encoding="utf-8")
        self.assertIn("macro fehler", teil)


if __name__ == "__main__":
    unittest.main()
