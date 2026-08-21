"""Telefonnummern, wie Menschen sie eintippen.

Der Anlass steht in der echten Datenbank: In den Bewerbungen stand
"17655384493" und "15202707296" – ohne Null, ohne +49, so wie man die Nummer
jemandem zuruft. Das System hat sie genau so gespeichert. Für WhatsApp ist
das eine Auslandsnummer ins Nichts: Die Willkommensnachricht ging nie raus,
und niemand hat es gemerkt.

Deshalb wird die Nummer jetzt gerichtet statt abgelehnt.
"""

import re
import unittest

from tests import hilfe                                      # noqa: F401

from fastapi.testclient import TestClient

from kern.datenbank import SessionLocal
from kern.modelle import Application, User
from kern.text import telefon_anzeige, telefon_gueltig, telefon_normal
from tests.hilfe import angemeldeter_client, csrf_aus
from website.app import app as web_app


class TestNummernRichten(unittest.TestCase):
    def test_ohne_vorwahl_bekommt_die_landesvorwahl(self):
        """Der gemeldete Fall."""
        for eingabe in ("1636177263", "15202707296", "1516 1234567",
                        "176 55384493"):
            with self.subTest(eingabe=eingabe):
                self.assertTrue(telefon_normal(eingabe).startswith("49"),
                                f"{eingabe} bleibt ohne Landesvorwahl")
                self.assertTrue(telefon_gueltig(eingabe))

    def test_bekannte_schreibweisen_bleiben_richtig(self):
        erwartet = "491636177263"
        for eingabe in ("0163 6177263", "+49 163 6177263", "+4916 36 177263",
                        "004916 36177263", "491636177263", "0163/6177263",
                        "0163-617 7263"):
            with self.subTest(eingabe=eingabe):
                self.assertEqual(telefon_normal(eingabe), erwartet)

    def test_landesvorwahl_wird_nicht_verdoppelt(self):
        """"491636177263" darf nicht zu "4949163..." werden."""
        self.assertEqual(telefon_normal("491636177263"), "491636177263")
        self.assertEqual(telefon_normal(telefon_normal("1636177263")),
                         "491636177263")

    def test_auslandsnummern_bleiben_unangetastet(self):
        self.assertEqual(telefon_normal("+43 660 1234567"), "436601234567")
        self.assertEqual(telefon_normal("0043 660 1234567"), "436601234567")

    def test_lesbare_schreibweise(self):
        self.assertEqual(telefon_anzeige("1636177263"), "+49 163 6177263")
        self.assertEqual(telefon_anzeige("0163 6177263"), "+49 163 6177263")
        self.assertEqual(telefon_anzeige(""), "")

    def test_unmoegliches_wird_erkannt(self):
        for eingabe in ("", "abc", "123", "0", "12 34"):
            with self.subTest(eingabe=eingabe):
                self.assertFalse(telefon_gueltig(eingabe))


class TestBewerbungMitKrummerNummer(unittest.TestCase):
    """Der ganze Weg: Formular → Datenbank → Konto → WhatsApp."""

    @classmethod
    def setUpClass(cls):
        hilfe.frische_datenbank()
        cls.c = TestClient(web_app)

    def _bewerben(self, nummer, email):
        seite = self.c.get("/bewerbung").text
        return self.c.post("/bewerbung", data={
            "vorname": "Test", "nachname": "Person", "klasse": "10",
            # Die Wunsch-Abteilung ist seit dem 17.08.2026 Pflicht - ohne
            # sie weist das Formular die Bewerbung zurueck.
            "email": email, "telefonnummer": nummer, "abteilung": "tech",
            "motivation": "Ich interessiere mich sehr für Wirtschaft und "
                          "möchte gerne mitmachen.",
            "interessen": "Aktien, Startups", "vorwissen": "",
            "csrf": csrf_aus(seite)})

    def test_nummer_ohne_vorwahl_wird_gespeichert_als_international(self):
        self._bewerben("1516 1234567", "krumm@ag.local")
        db = SessionLocal()
        bewerbung = db.query(Application).filter(
            Application.email == "krumm@ag.local").first()
        self.assertIsNotNone(bewerbung, "Bewerbung wurde abgelehnt")
        self.assertEqual(bewerbung.telefonnummer, "+49 151 61234567")
        db.close()

    def test_unmoegliche_nummer_wird_freundlich_zurueckgewiesen(self):
        antwort = self._bewerben("123", "zukurz@ag.local")
        self.assertIn("Telefonnummer", antwort.text)
        self.assertIn("0163", antwort.text, "Es fehlt ein Beispiel")
        db = SessionLocal()
        self.assertIsNone(db.query(Application).filter(
            Application.email == "zukurz@ag.local").first())
        db.close()

    def test_eingaben_bleiben_nach_der_rueckfrage_stehen(self):
        antwort = self._bewerben("123", "zukurz2@ag.local")
        self.assertIn("zukurz2@ag.local", antwort.text,
                      "Die Bewerbung müsste komplett neu getippt werden")


class TestKontoUndAnzeige(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_konto_speichert_die_nummer_einheitlich(self):
        csrf = csrf_aus(self.dash.get("/dashboard/konten").text)
        self.dash.post("/dashboard/konten", data={
            "vorname": "Telefon", "nachname": "Probe",
            "email": "telefon.probe@ag.local", "telefon": "1636177263",
            "rolle": "member", "abteilung": "tech",
            "passwort": "Guter-Zufall-2026", "csrf": csrf})
        db = SessionLocal()
        person = db.query(User).filter(
            User.email == "telefon.probe@ag.local").first()
        self.assertIsNotNone(person)
        self.assertEqual(person.telefonnummer, "+49 163 6177263")
        db.delete(person)
        db.commit()
        db.close()

    def test_alte_eintraege_werden_lesbar_angezeigt(self):
        """Ohne die Datenbank anzufassen: der Filter richtet es beim Anzeigen."""
        db = SessionLocal()
        person = db.query(User).filter(User.email == "pruef@ag.local").first()
        vorher = person.telefonnummer
        person.telefonnummer = "17655384493"      # so wie aus V1 übernommen
        db.commit()
        db.close()
        text = self.dash.get("/dashboard/mitglieder").text
        self.assertIn("+49 176 55384493", text)
        self.assertIn('href="tel:+4917655384493"', text)
        db = SessionLocal()
        person = db.query(User).filter(User.email == "pruef@ag.local").first()
        person.telefonnummer = vorher
        db.commit()
        db.close()

    def test_whatsapp_bekommt_die_richtige_nummer(self):
        from kern import whatsapp
        klasse = type("P", (), {"telefonnummer": "15202707296", "id": 1,
                                "vorname": "Test", "nachname": "Person",
                                "name": "Test Person", "role": "member",
                                "department": "tech"})
        self.assertEqual(
            whatsapp.telefon_normal(klasse.telefonnummer, "49"),
            "4915202707296")


if __name__ == "__main__":
    unittest.main()
