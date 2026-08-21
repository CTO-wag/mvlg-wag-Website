"""Was passiert, wenn jemand Unsinn eintippt?

Leute vertippen sich, lassen Felder leer, fügen aus Word ein, drücken zweimal
und probieren aus, was passiert. Nichts davon darf zu einem Serverfehler
führen, zu falschen Daten in der Kasse oder zu einer Meldung, mit der niemand
etwas anfangen kann.

Jeder Test hier beschreibt einen Fehler, den ein Mensch wirklich macht.
"""

import unittest
from datetime import date, timedelta

from tests import hilfe                                      # noqa: F401

from kern.datenbank import SessionLocal
from kern.modelle import Buchung, Task, User
from kern.text import betrag_in_cent
from tests.hilfe import angemeldeter_client, csrf_aus

GESTERN = (date.today() - timedelta(days=1)).isoformat()


class TestFehleingaben(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()
        cls.csrf = csrf_aus(cls.dash.get("/dashboard/aufgaben").text)

    def post(self, pfad, **daten):
        daten.setdefault("csrf", self.csrf)
        return self.dash.post(pfad, data=daten)

    def meldung(self, antwort):
        """Der Text der Rückmeldung - oder leer."""
        import re
        treffer = re.search(r'meldung-(\w+)[^>]*>\s*<div>(.*?)</div>',
                            antwort.text, re.S)
        if not treffer:
            return "", ""
        text = re.sub(r"<[^>]+>", " ", treffer.group(2))
        return treffer.group(1), " ".join(text.split())

    # --- Leere Formulare ---------------------------------------------------
    def test_alles_leer_abschicken(self):
        """Der Klassiker: Knopf drücken, ohne etwas einzutippen."""
        faelle = [
            ("/dashboard/aufgaben", {}),
            ("/dashboard/kalender", {}),
            ("/dashboard/kassenbuch", {}),
            ("/dashboard/projekte", {}),
            ("/dashboard/treffen", {}),
            ("/dashboard/konten", {}),
            ("/dashboard/support", {}),
            ("/dashboard/rollen", {}),
        ]
        for pfad, daten in faelle:
            with self.subTest(pfad=pfad):
                antwort = self.post(pfad, **daten)
                self.assertEqual(antwort.status_code, 200,
                                 f"{pfad} bricht ab statt zu erklären")
                art, text = self.meldung(antwort)
                self.assertEqual(art, "fehler", f"{pfad}: keine Rückmeldung")
                self.assertGreater(len(text), 15,
                                   f"{pfad}: Meldung zu knapp: {text!r}")

    # --- Kasse -------------------------------------------------------------
    def test_betrag_mit_leerzeichen_wird_nicht_geraten(self):
        """"12 50" darf NICHT 1250 Euro werden - das fällt erst beim
        Abrechnen auf."""
        self.assertIsNone(betrag_in_cent("12 50"))
        antwort = self.post("/dashboard/kassenbuch", zweck="Getränke",
                            betrag="12 50", richtung="aus")
        art, text = self.meldung(antwort)
        self.assertEqual(art, "fehler")
        self.assertIn("12,50", text, "die Meldung zeigt kein Beispiel")
        db = SessionLocal()
        self.assertIsNone(db.query(Buchung).filter(
            Buchung.zweck == "Getränke").first(), "falscher Betrag gebucht")
        db.close()

    def test_betrag_null_wird_abgelehnt(self):
        antwort = self.post("/dashboard/kassenbuch", zweck="Nichts",
                            betrag="0", richtung="aus")
        self.assertEqual(self.meldung(antwort)[0], "fehler")

    def test_vorzeichen_kommt_aus_der_richtung(self):
        """Wer "-20" bei "Einnahme" eintippt, meint eine Einnahme."""
        self.post("/dashboard/kassenbuch", zweck="Spende", betrag="-20",
                  richtung="ein")
        db = SessionLocal()
        buchung = db.query(Buchung).filter(Buchung.zweck == "Spende").first()
        self.assertIsNotNone(buchung)
        self.assertEqual(buchung.betrag_cent, 2000, "Vorzeichen verdreht")
        db.close()

    # --- Text, der Ärger machen könnte -------------------------------------
    def test_html_im_titel_wird_nicht_ausgefuehrt(self):
        boese = '<script>alert("hallo")</script>'
        self.post("/dashboard/aufgaben", titel=boese, zustaendig="a:tech")
        seite = self.dash.get("/dashboard/aufgaben").text
        self.assertNotIn("<script>alert", seite, "Markup landet ungefiltert im HTML")
        self.assertIn("&lt;script&gt;", seite, "Der Text sollte lesbar dastehen")

    def test_sehr_langer_text_wird_gekuerzt_statt_abzustuerzen(self):
        self.post("/dashboard/aufgaben", titel="A" * 5000,
                  beschreibung="B" * 50000, zustaendig="a:tech")
        db = SessionLocal()
        aufgabe = db.query(Task).filter(Task.titel.like("AAAA%")).first()
        self.assertIsNotNone(aufgabe, "nichts angelegt")
        self.assertLessEqual(len(aufgabe.titel), 160)
        self.assertLessEqual(len(aufgabe.beschreibung or ""), 4000)
        db.close()

    def test_aus_word_eingefuegt(self):
        """Geschützte Leerzeichen und typografische Zeichen kommen mit."""
        antwort = self.post("/dashboard/aufgaben",
                            titel="Plakate drucken – Auflage 50",
                            zustaendig="a:tech")
        self.assertEqual(self.meldung(antwort)[0], "gut")

    # --- Unmögliche Auswahl ------------------------------------------------
    def test_person_die_es_nicht_gibt(self):
        antwort = self.post("/dashboard/aufgaben", titel="Geisteraufgabe",
                            zustaendig="p:999999")
        self.assertEqual(self.meldung(antwort)[0], "fehler")

    def test_abteilung_die_es_nicht_gibt(self):
        antwort = self.post("/dashboard/aufgaben", titel="Geisterabteilung",
                            zustaendig="a:erfunden")
        self.assertEqual(self.meldung(antwort)[0], "fehler")

    def test_ohne_zustaendigkeit(self):
        """Eine Aufgabe ohne Verantwortliche wird nie erledigt."""
        antwort = self.post("/dashboard/aufgaben", titel="Niemand zuständig")
        art, text = self.meldung(antwort)
        self.assertEqual(art, "fehler")
        self.assertIn("Person", text)

    # --- Doppelt gedrückt --------------------------------------------------
    def test_zweimal_abschicken_legt_zweimal_an(self):
        """Zweimal drücken heisst zwei Einträge - deshalb sperrt die
        Oberfläche den Knopf. Hier wird nur festgehalten, dass der Server
        dabei nicht durcheinanderkommt."""
        for _ in range(2):
            antwort = self.post("/dashboard/aufgaben", titel="Doppelt gedrückt",
                                zustaendig="a:tech")
            self.assertEqual(antwort.status_code, 200)

    # --- Sich selbst ins Knie schiessen ------------------------------------
    def test_eigenes_konto_nicht_ueber_die_kontenliste_loeschen(self):
        db = SessionLocal()
        ich = db.query(User).filter(User.email == "pruef@ag.local").first()
        meine_id = ich.id
        db.close()
        antwort = self.post(f"/dashboard/konten/{meine_id}/loeschen")
        art, text = self.meldung(antwort)
        self.assertEqual(art, "fehler")
        self.assertIn("Mein Konto", text, "Der Hinweis nennt nicht den Weg")
        db = SessionLocal()
        self.assertIsNotNone(db.get(User, meine_id), "Konto ist weg!")
        db.close()

    def test_letztes_cto_konto_bleibt(self):
        """Ohne handlungsfähiges Konto käme niemand mehr ins System."""
        db = SessionLocal()
        ich = db.query(User).filter(User.email == "pruef@ag.local").first()
        meine_id = ich.id
        db.close()
        antwort = self.post(f"/dashboard/konten/{meine_id}/aendern",
                            vorname="Pruef", nachname="Konto",
                            email="pruef@ag.local", rolle="member",
                            abteilung="exekutive", status="aktiv")
        self.assertEqual(self.meldung(antwort)[0], "fehler")
        db = SessionLocal()
        self.assertEqual(db.get(User, meine_id).role, "cto")
        db.close()

    def test_rolle_mit_hoeherem_rang_als_die_eigene(self):
        antwort = self.post("/dashboard/rollen", schluessel="ueberflieger",
                            name="Überflieger", rang="999")
        db = SessionLocal()
        from kern.modelle import Role
        rolle = db.query(Role).filter(Role.key == "ueberflieger").first()
        if rolle:
            self.assertLessEqual(rolle.rang, 100,
                                 "jemand hat sich eine Rolle über dem CTO gebaut")
        db.close()
        self.assertEqual(antwort.status_code, 200)

    # --- Unsinnige Daten ---------------------------------------------------
    def test_termin_in_der_vergangenheit_ist_erlaubt(self):
        """Nachtragen muss möglich sein - aber es darf nicht abstürzen."""
        antwort = self.post("/dashboard/kalender", titel="Nachgetragen",
                            von=GESTERN, ziel="alle")
        self.assertEqual(antwort.status_code, 200)

    def test_kaputtes_datum(self):
        antwort = self.post("/dashboard/kalender", titel="Krummes Datum",
                            von="31.02.2026", ziel="alle")
        art, text = self.meldung(antwort)
        self.assertEqual(art, "fehler", "krummes Datum wurde stillschweigend "
                                        "verschluckt")
        self.assertIn("Datum", text)

    def test_frist_als_unsinn(self):
        """Ein unlesbares Datum darf die Aufgabe nicht verhindern - es wird
        einfach keine Frist gesetzt."""
        antwort = self.post("/dashboard/aufgaben", titel="Ohne echte Frist",
                            zustaendig="a:tech", frist="irgendwann")
        self.assertEqual(self.meldung(antwort)[0], "gut")
        db = SessionLocal()
        aufgabe = db.query(Task).filter(Task.titel == "Ohne echte Frist").first()
        self.assertIsNone(aufgabe.deadline)
        db.close()

    # --- Formular zu lange offen ------------------------------------------
    def test_abgelaufenes_formular_erklaert_sich(self):
        antwort = self.dash.post("/dashboard/aufgaben",
                                 data={"titel": "Mit falschem Token",
                                       "zustaendig": "a:tech", "csrf": "quatsch"})
        self.assertEqual(antwort.status_code, 400)
        self.assertIn("noch einmal", antwort.text.lower(),
                      "Die Meldung sagt nicht, was zu tun ist")


if __name__ == "__main__":
    unittest.main()
