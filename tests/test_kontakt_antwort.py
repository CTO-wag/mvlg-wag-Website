"""Anfragen von der Startseite per E-Mail beantworten.

Der Weg dahinter ist ungewoehnlich und deshalb einen eigenen Test wert: Wer
ueber das Kontaktformular schreibt, hat kein Konto und wird nie eins bekommen.
Eine Antwort, die nur im Dashboard steht, erreicht ihn also nie - der einzige
Rueckweg ist die Adresse, die er selbst angegeben hat.

Geprueft wird vor allem, was frueher stillschweigend schiefging: dass eine
Anfrage als beantwortet galt, obwohl gar nichts rausging.
"""

import unittest

from tests import hilfe                                      # noqa: F401

from kern import mail
from kern.datenbank import SessionLocal
from kern.modelle import ContactMessage
from tests.hilfe import angemeldeter_client, csrf_aus

ANFRAGE = "Hallo, kann mein Kind auch in der 9. Klasse mitmachen?"


class TestKontaktAntwort(unittest.TestCase):

    def setUp(self):
        self.web, self.dash = angemeldeter_client()
        # Die Testdatenbank ueberlebt den einzelnen Test - alte Anfragen
        # wuerden sonst mitgezaehlt und die Antworten liefen aufeinander.
        db = SessionLocal()
        try:
            db.query(ContactMessage).delete()
            db.commit()
        finally:
            db.close()
        seite = self.web.get("/").text
        self.web.post("/kontakt", data={
            "csrf": csrf_aus(seite), "name": "Maria Musterfrau",
            "email": "maria@beispiel.de", "nachricht": ANFRAGE,
            "webseite": ""})
        db = SessionLocal()
        try:
            self.anfrage_id = db.query(ContactMessage).first().id
        finally:
            db.close()
        # Der echte Versand wird nie aufgerufen - stattdessen wird
        # aufgeschrieben, was rausgegangen waere.
        self.echt_moeglich = mail.versand_moeglich
        self.echt_zustellen = mail._zustellen
        self.post = {}

    def tearDown(self):
        mail.versand_moeglich = self.echt_moeglich
        mail._zustellen = self.echt_zustellen

    #  Hilfen
    def _versand_einschalten(self, erfolg=True, grund=""):
        def _zustellen(empfaenger, betreff, text, antwort_an="",
                       automatisch=True):
            self.post = {"an": empfaenger, "betreff": betreff, "text": text,
                         "antwort_an": antwort_an, "automatisch": automatisch}
            return erfolg, grund
        mail.versand_moeglich = lambda: True
        mail._zustellen = _zustellen

    def _antworten(self, text):
        seite = self.dash.get("/dashboard/nachrichten").text
        return self.dash.post(
            f"/dashboard/nachrichten/kontakt/{self.anfrage_id}/antwort",
            data={"csrf": csrf_aus(seite), "antwort": text})

    def _anfrage(self):
        db = SessionLocal()
        try:
            eintrag = db.get(ContactMessage, self.anfrage_id)
            db.expunge(eintrag)
            return eintrag
        finally:
            db.close()

    #  Tests
    def test_ohne_mailversand_gilt_nichts_als_beantwortet(self):
        """Sonst verschwindet die Anfrage aus der Liste, ohne dass jemand
        etwas bekommen hat - der teuerste stille Fehler dieser Seite."""
        mail.versand_moeglich = lambda: False
        antwort = self._antworten("Ja, klar - meld dich gern.")
        self.assertIsNone(self._anfrage().reply)
        self.assertIn("kein Mailversand", antwort.text)

    def test_antwort_geht_als_persoenliche_mail_raus(self):
        self._versand_einschalten()
        self._antworten("Ja, klar. Klasse 9 ist genau richtig.")

        eintrag = self._anfrage()
        self.assertEqual(eintrag.reply_mail_ok, 1)
        self.assertIsNone(eintrag.reply_mail_fehler)

        self.assertEqual(self.post["an"], "maria@beispiel.de")
        self.assertIn("Maria", self.post["text"])
        self.assertIn("Klasse 9 ist genau richtig", self.post["text"])
        # Die urspruengliche Frage steht mit drin - zwischen Absenden und
        # Antwort liegen leicht Tage.
        self.assertIn(ANFRAGE, self.post["text"])

    def test_kein_dashboard_und_kein_abmeldehinweis_in_der_mail(self):
        """Genau daran krankte der alte Weg: Er benutzte den Vordruck fuer
        Kontobenachrichtigungen und schickte Leuten ohne Konto einen
        Dashboard-Link samt Abmeldehinweis."""
        self._versand_einschalten()
        self._antworten("Kurze Antwort.")
        self.assertNotIn("Dashboard", self.post["text"])
        self.assertNotIn("Benachrichtigungen eingeschaltet", self.post["text"])

    def test_rueckweg_zeigt_auf_die_antwortende_person(self):
        self._versand_einschalten()
        self._antworten("Kurze Antwort.")
        self.assertIn("@", self.post["antwort_an"])
        # Von Hand geschrieben, also kein Auto-Submitted: sonst schluckt das
        # Mailprogramm der Gegenseite die Abwesenheitsnotiz.
        self.assertFalse(self.post["automatisch"])

    def test_fehlgeschlagener_versand_wird_gemeldet_und_bleibt_offen(self):
        self._versand_einschalten(False, "SMTPAuthenticationError: abgelehnt")
        antwort = self._antworten("Ja, klar.")

        eintrag = self._anfrage()
        self.assertEqual(eintrag.reply_mail_ok, 0)
        self.assertIn("abgelehnt", eintrag.reply_mail_fehler)
        self.assertIn("NICHT bei maria@beispiel.de", antwort.text)

    def test_nachfassen_ueberschreibt_die_erste_antwort_nicht(self):
        self._versand_einschalten()
        self._antworten("Erste Antwort.")
        self._antworten("Nachtrag: Treffen ist Dienstag.")
        verlauf = self._anfrage().reply
        self.assertIn("Erste Antwort.", verlauf)
        self.assertIn("Nachtrag: Treffen ist Dienstag.", verlauf)

    def test_leere_antwort_wird_abgewiesen(self):
        self._versand_einschalten()
        self._antworten("   ")
        self.assertIsNone(self._anfrage().reply)


if __name__ == "__main__":
    unittest.main()
