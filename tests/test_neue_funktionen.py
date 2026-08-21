"""Die sechs Funktionen, die nach der Lückensuche dazugekommen sind.

Reihenfolge wie in der Liste: Ersatzcodes, Störungsmeldung, Erinnerungen an
Treffen und Termine, Zu-/Absage samt Tagesordnung, Anstoß bei liegengebliebenen
Bewerbungen, Einspielen einer Sicherung.
"""

import re
import unittest
import unittest.mock
from datetime import date, timedelta

from tests import hilfe                                      # noqa: F401

from kern.datenbank import SessionLocal
from kern.modelle import (
    Application, CalendarEvent, Meeting, MeetingPunkt, MeetingRueckmeldung, User,
)
from kern.sicherheit import (
    ersatzcode_einloesen, ersatzcodes_erzeugen, ersatzcodes_offen,
)
from tests.hilfe import angemeldeter_client, csrf_aus


def _pruefer(db):
    return db.query(User).filter(User.email == "pruef@ag.local").first()


#  1. Zweiter Faktor: Ersatzcodes und der Weg des Vorstands
class TestErsatzcodes(unittest.TestCase):
    """Ein zweiter Faktor ohne Rückweg sperrt Leute aus ihrem Konto aus."""

    def test_code_gilt_genau_einmal(self):
        klar, gespeichert = ersatzcodes_erzeugen()
        self.assertEqual(len(klar), 8)
        self.assertEqual(ersatzcodes_offen(gespeichert), 8)
        ok, rest = ersatzcode_einloesen(gespeichert, klar[3])
        self.assertTrue(ok)
        self.assertEqual(ersatzcodes_offen(rest), 7)
        nochmal, _ = ersatzcode_einloesen(rest, klar[3])
        self.assertFalse(nochmal, "derselbe Code ging ein zweites Mal")

    def test_gross_klein_und_leerzeichen_egal(self):
        """Wer den Zettel abtippt, tippt nicht auf das Zeichen genau."""
        klar, gespeichert = ersatzcodes_erzeugen()
        ok, _ = ersatzcode_einloesen(gespeichert, f"  {klar[0].upper()} ")
        self.assertTrue(ok)

    def test_klartext_steht_nicht_in_der_datenbank(self):
        klar, gespeichert = ersatzcodes_erzeugen()
        for code in klar:
            self.assertNotIn(code, gespeichert)

    def test_falscher_code_aendert_nichts(self):
        _, gespeichert = ersatzcodes_erzeugen()
        ok, rest = ersatzcode_einloesen(gespeichert, "0000-0000")
        self.assertFalse(ok)
        self.assertEqual(ersatzcodes_offen(rest), 8)


class TestZweiterFaktorImBetrieb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_einschalten_liefert_acht_codes(self):
        from kern.sicherheit import totp_code
        seite = self.dash.get("/dashboard/mein-konto").text
        csrf = csrf_aus(seite)
        self.dash.post("/dashboard/mein-konto/2fa/start", data={"csrf": csrf})
        db = SessionLocal()
        geheimnis = _pruefer(db).totp_secret
        db.close()
        antwort = self.dash.post("/dashboard/mein-konto/2fa/bestaetigen",
                                 data={"code": totp_code(geheimnis), "csrf": csrf})
        self.assertEqual(antwort.status_code, 200)
        codes = re.findall(r"<li>([0-9a-f]{4}-[0-9a-f]{4})</li>", antwort.text)
        self.assertEqual(len(codes), 8, "keine acht Ersatzcodes angezeigt")

        db = SessionLocal()
        person = _pruefer(db)
        self.assertEqual(person.totp_aktiv, 1)
        self.assertEqual(ersatzcodes_offen(person.totp_ersatzcodes), 8)
        for code in codes:
            self.assertNotIn(code, person.totp_ersatzcodes or "")
        # Aufräumen für die übrigen Tests.
        person.totp_aktiv, person.totp_secret = 0, None
        person.totp_ersatzcodes = None
        db.commit()
        db.close()

    def test_anmeldung_nimmt_einen_ersatzcode_an(self):
        from fastapi.testclient import TestClient
        from website.app import app as web
        from tests.hilfe import TESTPASSWORT
        db = SessionLocal()
        person = _pruefer(db)
        klar, gespeichert = ersatzcodes_erzeugen()
        person.totp_secret = "JBSWY3DPEHPK3PXP"
        person.totp_aktiv = 1
        person.totp_ersatzcodes = gespeichert
        db.commit()
        db.close()

        with TestClient(web) as k:
            token = csrf_aus(k.get("/login").text)
            k.post("/login", data={"email": "pruef@ag.local",
                                   "passwort": TESTPASSWORT, "csrf": token},
                   follow_redirects=False)
            seite = k.get("/login").text
            token = csrf_aus(seite)
            self.assertIn("Ersatzcode", seite, "kein Hinweis auf die Notluke")
            antwort = k.post("/login/zweiter-faktor",
                             data={"code": klar[0], "csrf": token},
                             follow_redirects=False)
        self.assertEqual(antwort.status_code, 303, "Ersatzcode wurde abgelehnt")

        db = SessionLocal()
        person = _pruefer(db)
        self.assertEqual(ersatzcodes_offen(person.totp_ersatzcodes), 7,
                         "der Code wurde nicht verbraucht")
        person.totp_aktiv, person.totp_secret = 0, None
        person.totp_ersatzcodes = None
        db.commit()
        db.close()

    def test_vorstand_kann_zuruecksetzen(self):
        """Der letzte Rückweg, wenn auch die Ersatzcodes weg sind."""
        db = SessionLocal()
        opfer = db.query(User).filter(User.email == "gesperrt@ag.local").first()
        if not opfer:
            from kern.sicherheit import passwort_hashen
            opfer = User(vorname="Gesperrt", nachname="Konto",
                         email="gesperrt@ag.local",
                         password_hash=passwort_hashen("GesperrtTest2026x"),
                         role="member", department="tech", status="aktiv")
            db.add(opfer)
        opfer.totp_aktiv, opfer.totp_secret = 1, "JBSWY3DPEHPK3PXP"
        _, gespeichert = ersatzcodes_erzeugen()
        opfer.totp_ersatzcodes = gespeichert
        db.commit()
        opfer_id = opfer.id
        db.close()

        csrf = csrf_aus(self.dash.get("/dashboard/konten").text)
        with unittest.mock.patch("kern.mail.sende_vordruck"):
            antwort = self.dash.post(
                f"/dashboard/konten/{opfer_id}/2fa-zuruecksetzen",
                data={"csrf": csrf})
        self.assertEqual(antwort.status_code, 200)

        db = SessionLocal()
        opfer = db.get(User, opfer_id)
        self.assertEqual(opfer.totp_aktiv, 0)
        self.assertIsNone(opfer.totp_secret)
        self.assertIsNone(opfer.totp_ersatzcodes)
        db.close()


#  2. Störungen gehen an den Vorstand
class TestStoerungsmeldung(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def setUp(self):
        from kern import werte
        db = SessionLocal()
        werte.setze(db, "stoerung_pruefung", "")
        db.commit()
        db.close()

    def test_meldet_einmal_und_dann_erst_wieder_nach_der_ruhefrist(self):
        from kern import stoerung
        with unittest.mock.patch("kern.benachrichtigung.melde_vielen") as melde:
            erste = stoerung.melde("pruefung", "Test", "Text")
            zweite = stoerung.melde("pruefung", "Test", "Text")
        self.assertTrue(erste, "die erste Meldung ging nicht raus")
        self.assertFalse(zweite, "dieselbe Störung meldete sich sofort erneut")
        self.assertEqual(melde.call_count, 1)

    def test_entwarnung_nur_wenn_vorher_etwas_war(self):
        from kern import stoerung
        with unittest.mock.patch("kern.benachrichtigung.melde_vielen"):
            ohne = stoerung.entwarnung("pruefung", "Wieder da", "Text")
            self.assertFalse(ohne, "Entwarnung ohne vorherige Störung")
            stoerung.melde("pruefung", "Test", "Text")
            mit = stoerung.entwarnung("pruefung", "Wieder da", "Text")
        self.assertTrue(mit)

    def test_geht_an_den_vorstand(self):
        from kern import stoerung
        db = SessionLocal()
        empfaenger = stoerung._empfaenger(db)
        db.close()
        self.assertTrue(empfaenger, "niemand würde benachrichtigt")
        self.assertTrue(all(p.status == "aktiv" for p in empfaenger))


#  3. + 5. Tägliche Hinweise
class TestHinweise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_erinnert_an_das_treffen_von_morgen(self):
        from kern import hinweise
        db = SessionLocal()
        morgen = date.today() + timedelta(days=1)
        treffen = Meeting(title="Probetreffen Hinweis", date=morgen)
        db.add(treffen)
        db.commit()
        tid = treffen.id
        db.close()

        with unittest.mock.patch("kern.benachrichtigung.melde_vielen") as melde:
            anzahl = hinweise.treffen_erinnern()
            # Zweiter Lauf am selben Tag: darf nichts mehr schicken.
            nochmal = hinweise.treffen_erinnern()
        self.assertGreaterEqual(anzahl, 1)
        self.assertEqual(nochmal, 0, "am selben Tag zweimal erinnert")
        self.assertIn("morgen", melde.call_args[0][3])

        db = SessionLocal()
        db.delete(db.get(Meeting, tid))
        db.commit()
        db.close()

    def test_erinnert_nur_die_betroffenen_an_einen_termin(self):
        from kern import hinweise
        db = SessionLocal()
        termin = CalendarEvent(title="Probetermin", start_date=date.today(),
                               target_type="alle")
        db.add(termin)
        db.commit()
        tid = termin.id
        db.close()
        with unittest.mock.patch("kern.benachrichtigung.melde_vielen") as melde:
            hinweise.termine_erinnern()
        self.assertTrue(melde.called)
        db = SessionLocal()
        db.delete(db.get(CalendarEvent, tid))
        db.commit()
        db.close()

    def test_liegengebliebene_bewerbung_stoesst_an(self):
        from kern import hinweise
        from kern.text import utcnow
        db = SessionLocal()
        alt = Application(vorname="Lang", nachname="Wartend", klasse="11",
                          email="wartend@example.org", telefonnummer="+4916312345",
                          motivation="x", interessen="y", status="neu",
                          created_at=utcnow() - timedelta(days=9))
        db.add(alt)
        db.commit()
        aid = alt.id
        db.close()

        with unittest.mock.patch(
                "kern.benachrichtigung.melde_rechteinhabern") as melde:
            anzahl = hinweise.bewerbungen_anstossen()
            sofort_nochmal = hinweise.bewerbungen_anstossen()
        self.assertGreaterEqual(anzahl, 1)
        self.assertEqual(sofort_nochmal, 0, "gleich noch einmal angestoßen")
        self.assertEqual(melde.call_args[0][1], "bewerbungen",
                         "ging nicht an die Zuständigen")

        db = SessionLocal()
        db.delete(db.get(Application, aid))
        db.commit()
        db.close()

    def test_frische_bewerbung_stoesst_nicht_an(self):
        from kern import hinweise
        from kern.text import utcnow
        db = SessionLocal()
        neu = Application(vorname="Ganz", nachname="Frisch", klasse="10",
                          email="frisch@example.org", telefonnummer="+4916312346",
                          motivation="x", interessen="y", status="neu",
                          created_at=utcnow())
        db.add(neu)
        db.commit()
        nid = neu.id
        db.close()
        with unittest.mock.patch("kern.benachrichtigung.melde_rechteinhabern"):
            anzahl = hinweise.bewerbungen_anstossen()
        self.assertEqual(anzahl, 0)
        db = SessionLocal()
        db.delete(db.get(Application, nid))
        db.commit()
        db.close()


#  4. Zu- und Absage, Tagesordnung
class TestTreffenRueckmeldung(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()
        db = SessionLocal()
        treffen = Meeting(title="Treffen mit Rückmeldung",
                          date=date.today() + timedelta(days=2))
        db.add(treffen)
        db.commit()
        cls.tid = treffen.id
        db.close()

    @classmethod
    def tearDownClass(cls):
        db = SessionLocal()
        db.query(MeetingRueckmeldung).filter(
            MeetingRueckmeldung.meeting_id == cls.tid).delete()
        db.query(MeetingPunkt).filter(MeetingPunkt.meeting_id == cls.tid).delete()
        eintrag = db.get(Meeting, cls.tid)
        if eintrag:
            db.delete(eintrag)
        db.commit()
        db.close()

    def _csrf(self):
        return csrf_aus(self.dash.get("/dashboard/treffen").text)

    def test_zusagen_und_wieder_absagen(self):
        csrf = self._csrf()
        self.dash.post(f"/dashboard/treffen/{self.tid}/antwort",
                       data={"antwort": "ja", "csrf": csrf})
        db = SessionLocal()
        eintrag = db.query(MeetingRueckmeldung).filter(
            MeetingRueckmeldung.meeting_id == self.tid).first()
        self.assertIsNotNone(eintrag)
        self.assertEqual(eintrag.antwort, "ja")
        db.close()

        self.dash.post(f"/dashboard/treffen/{self.tid}/antwort",
                       data={"antwort": "nein", "grund": "Klausur", "csrf": csrf})
        db = SessionLocal()
        zeilen = db.query(MeetingRueckmeldung).filter(
            MeetingRueckmeldung.meeting_id == self.tid).all()
        self.assertEqual(len(zeilen), 1, "Umentscheiden legte eine zweite Zeile an")
        self.assertEqual(zeilen[0].antwort, "nein")
        self.assertEqual(zeilen[0].grund, "Klausur")
        db.close()

    def test_tagesordnung_eintragen_abhaken_entfernen(self):
        csrf = self._csrf()
        antwort = self.dash.post(f"/dashboard/treffen/{self.tid}/punkt",
                                 data={"text": "Kassenstand besprechen",
                                       "csrf": csrf})
        self.assertIn("Kassenstand besprechen", antwort.text)
        db = SessionLocal()
        punkt = db.query(MeetingPunkt).filter(
            MeetingPunkt.meeting_id == self.tid).first()
        self.assertIsNotNone(punkt)
        self.assertEqual(punkt.erledigt, 0)
        pid = punkt.id
        db.close()

        self.dash.post(f"/dashboard/treffen/punkt/{pid}/abhaken",
                       data={"csrf": csrf})
        db = SessionLocal()
        self.assertEqual(db.get(MeetingPunkt, pid).erledigt, 1)
        db.close()

        self.dash.post(f"/dashboard/treffen/punkt/{pid}/loeschen",
                       data={"csrf": csrf})
        db = SessionLocal()
        self.assertIsNone(db.get(MeetingPunkt, pid))
        db.close()

    def test_leerer_punkt_wird_abgelehnt(self):
        csrf = self._csrf()
        antwort = self.dash.post(f"/dashboard/treffen/{self.tid}/punkt",
                                 data={"text": "   ", "csrf": csrf})
        self.assertIn("Ohne Text", antwort.text)

    def test_treffen_loeschen_geht_trotz_rueckmeldungen(self):
        """Ohne Eintrag in papierkorb.KINDER bricht das mit einem
        Fremdschlüssel-Fehler ab - genau der Fall, der bei Projekten schon
        einmal zugeschlagen hat."""
        from kern import papierkorb
        db = SessionLocal()
        treffen = Meeting(title="Treffen zum Löschen",
                          date=date.today() + timedelta(days=5))
        db.add(treffen)
        db.commit()
        db.add(MeetingRueckmeldung(meeting_id=treffen.id,
                                   user_id=_pruefer(db).id, antwort="ja"))
        db.add(MeetingPunkt(meeting_id=treffen.id, user_id=_pruefer(db).id,
                            text="Punkt"))
        db.commit()
        tid = treffen.id
        papierkorb.hinein(db, "meeting", treffen, tid, "Treffen zum Löschen")
        db.commit()
        self.assertIsNone(db.get(Meeting, tid))
        eintraege = [e for e in papierkorb.inhalt(db)
                     if e.label == "Treffen zum Löschen"]
        for e in eintraege:
            papierkorb.endgueltig(db, e.id)
        db.commit()
        db.close()


#  6. Sicherung einspielen
class TestSicherungEinspielen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_ohne_bestaetigung_passiert_nichts(self):
        csrf = csrf_aus(self.dash.get("/dashboard/papierkorb").text)
        with unittest.mock.patch("kern.sicherung.einspielen") as spielen:
            antwort = self.dash.post(
                "/dashboard/papierkorb/sicherung/egal.db/einspielen",
                data={"bestaetigung": "ja", "csrf": csrf})
        self.assertFalse(spielen.called, "ohne das Wort wurde eingespielt")
        self.assertIn("EINSPIELEN", antwort.text)

    def test_einspielen_stellt_den_alten_stand_her(self):
        """Der ganze Weg: sichern, etwas ändern, zurückspielen."""
        from kern import sicherung
        db = SessionLocal()
        merkmal = "Vor der Sicherung"
        db.add(Meeting(title=merkmal, date=date.today()))
        db.commit()
        db.close()

        name = sicherung.erstelle()
        self.assertTrue(name, "keine Sicherung angelegt")

        db = SessionLocal()
        db.add(Meeting(title="Nach der Sicherung", date=date.today()))
        db.commit()
        db.close()

        geklappt, meldung = sicherung.einspielen(name)
        self.assertTrue(geklappt, meldung)

        db = SessionLocal()
        titel = [m.title for m in db.query(Meeting).all()]
        db.close()
        self.assertIn(merkmal, titel)
        self.assertNotIn("Nach der Sicherung", titel,
                         "der Stand nach der Sicherung ist noch da")

        # Der Stand von vorher muss als eigene Datei danebenliegen.
        namen = [e["name"] for e in sicherung.vorhandene()]
        self.assertTrue(any(n.startswith("vor-einspielen_") for n in namen),
                        "kein Sicherheitsnetz vor dem Einspielen")

        db = SessionLocal()
        for m in db.query(Meeting).filter(Meeting.title == merkmal).all():
            db.delete(m)
        db.commit()
        db.close()

    def test_unbekannte_datei_wird_abgewiesen(self):
        from kern import sicherung
        geklappt, meldung = sicherung.einspielen("../../config.cmd")
        self.assertFalse(geklappt)
        self.assertIn("gibt es nicht", meldung)


if __name__ == "__main__":
    unittest.main()
