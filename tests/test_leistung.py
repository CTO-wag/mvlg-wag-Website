"""Das automatische Scoring - vor allem: Punkte überleben das Löschen.

Das ist die Zusage, die dem Ganzen zugrunde liegt. In V1 wurde der Wert direkt
aus der Aufgabentabelle gerechnet; wer aufräumte, verlor rückwirkend Punkte.
Genau das darf hier nicht mehr passieren, und genau das prüft dieser Test.
"""

import unittest
from datetime import date, timedelta

from tests import hilfe                                      # noqa: F401

from kern import leistung, papierkorb
from kern.aufgaben import status_setzen
from kern.datenbank import SessionLocal
from kern.modelle import Leistung, Task, User
from kern.text import utcnow


class TestLeistung(unittest.TestCase):
    def setUp(self):
        hilfe.frische_datenbank()
        self.db = SessionLocal()
        self.person = self.db.query(User).filter(
            User.email == "pruef@ag.local").first()
        # Sauberer Start je Test. Auch der Papierkorb wird geleert: alle Tests
        # teilen sich eine Datenbank, und hier wird gleich gezählt, was darin
        # liegt - ein Rest aus einem anderen Test würde das verfälschen.
        from kern.modelle import TrashItem
        self.db.query(Leistung).delete()
        self.db.query(Task).delete()
        self.db.query(TrashItem).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _aufgabe(self, titel="Testaufgabe", frist=None, rang="mittel"):
        aufgabe = Task(titel=titel, assignee_id=self.person.id,
                       task_department="exekutive", deadline=frist,
                       priority=rang, creator_id=self.person.id)
        self.db.add(aufgabe)
        self.db.commit()
        return aufgabe

    def test_erledigen_schreibt_nachweis(self):
        aufgabe = self._aufgabe()
        status_setzen(self.db, aufgabe, "erledigt", self.person)
        self.db.commit()
        self.assertEqual(self.db.query(Leistung).filter(
            Leistung.art == "aufgabe", Leistung.quelle_id == aufgabe.id).count(), 1)

    def test_punkte_ueberleben_das_loeschen(self):
        """Der Kern der Sache: aufräumen darf nicht bestrafen."""
        aufgabe = self._aufgabe("Wird gelöscht")
        status_setzen(self.db, aufgabe, "erledigt", self.person)
        self.db.commit()
        vorher = self.db.query(Leistung).filter(
            Leistung.user_id == self.person.id, Leistung.art == "aufgabe").count()

        papierkorb.hinein(self.db, "task", aufgabe, self.person.id)
        self.db.commit()

        self.assertEqual(self.db.query(Task).count(), 0, "Aufgabe muss weg sein")
        nachher = self.db.query(Leistung).filter(
            Leistung.user_id == self.person.id, Leistung.art == "aufgabe").count()
        self.assertEqual(vorher, nachher, "Der Nachweis muss bleiben")

    def test_punkte_ueberleben_auch_endgueltiges_loeschen(self):
        from kern.modelle import TrashItem
        aufgabe = self._aufgabe("Endgültig weg")
        status_setzen(self.db, aufgabe, "erledigt", self.person)
        self.db.commit()
        eintrag = papierkorb.hinein(self.db, "task", aufgabe, self.person.id)
        self.db.commit()
        papierkorb.endgueltig(self.db, eintrag.id)
        self.db.commit()
        self.assertEqual(self.db.query(TrashItem).count(), 0)
        self.assertEqual(self.db.query(Leistung).filter(
            Leistung.art == "aufgabe").count(), 1)

    def test_zurueckholen_nimmt_punkte_zurueck(self):
        """Eine irrtümlich abgehakte Aufgabe soll keine Punkte hinterlassen."""
        aufgabe = self._aufgabe()
        status_setzen(self.db, aufgabe, "erledigt", self.person)
        self.db.commit()
        status_setzen(self.db, aufgabe, "offen", self.person)
        self.db.commit()
        self.assertEqual(self.db.query(Leistung).filter(
            Leistung.art == "aufgabe").count(), 0)

    def test_kein_doppeltes_zaehlen(self):
        aufgabe = self._aufgabe()
        for _ in range(3):
            status_setzen(self.db, aufgabe, "erledigt", self.person)
            self.db.commit()
            status_setzen(self.db, aufgabe, "in_bearbeitung", self.person)
            self.db.commit()
        status_setzen(self.db, aufgabe, "erledigt", self.person)
        self.db.commit()
        self.assertEqual(self.db.query(Leistung).filter(
            Leistung.art == "aufgabe", Leistung.quelle_id == aufgabe.id).count(), 1)

    def test_puenktlich_gibt_mehr_punkte(self):
        frueh = self._aufgabe("Pünktlich", frist=date.today() + timedelta(days=5))
        status_setzen(self.db, frueh, "erledigt", self.person)
        spaet = self._aufgabe("Zu spät", frist=date.today() - timedelta(days=5))
        status_setzen(self.db, spaet, "erledigt", self.person)
        self.db.commit()
        p_frueh = self.db.query(Leistung).filter(
            Leistung.quelle_id == frueh.id).first().punkte
        p_spaet = self.db.query(Leistung).filter(
            Leistung.quelle_id == spaet.id).first().punkte
        self.assertGreater(p_frueh, p_spaet)

    def test_ueberfaellige_druecken_die_zuverlaessigkeit(self):
        for n in range(4):
            self._aufgabe(f"Überfällig {n}", frist=date.today() - timedelta(days=10))
        self.db.commit()
        werte = leistung.werte_fuer(self.db, self.person.id)
        self.assertLess(werte["zuverlaessigkeit"], 50)

    def test_alles_erledigt_gibt_hohe_zuverlaessigkeit(self):
        for n in range(10):
            aufgabe = self._aufgabe(f"Erledigt {n}",
                                    frist=date.today() + timedelta(days=3))
            status_setzen(self.db, aufgabe, "erledigt", self.person)
        self.db.commit()
        werte = leistung.werte_fuer(self.db, self.person.id)
        self.assertGreaterEqual(werte["zuverlaessigkeit"], 90)

    def test_werte_bleiben_im_rahmen(self):
        for n in range(60):
            aufgabe = self._aufgabe(f"Viel {n}")
            status_setzen(self.db, aufgabe, "erledigt", self.person)
        self.db.commit()
        werte = leistung.werte_fuer(self.db, self.person.id)
        for name, wert in werte.items():
            if isinstance(wert, int) and name not in ("erledigt_gesamt", "ueberfaellig"):
                self.assertGreaterEqual(wert, 0, name)
                self.assertLessEqual(wert, 100, name)

    def test_speichern_legt_score_an(self):
        aufgabe = self._aufgabe()
        status_setzen(self.db, aufgabe, "erledigt", self.person)
        self.db.commit()
        eintrag = leistung.speichere(self.db, self.person.id)
        self.db.commit()
        self.assertIsNotNone(eintrag.gesamt)
        self.assertIn(eintrag.leadership_potential,
                      ("developing", "emerging", "high"))

    def test_alte_leistungen_zaehlen_weniger(self):
        """Sonst trägt jemand seinen Einsatz aus der 10. Klasse bis zum Abi vor sich her."""
        alt = Leistung(user_id=self.person.id, art="aufgabe", quelle_id=9001,
                       titel="Alt", punkte=1,
                       zeitpunkt=utcnow() - timedelta(days=200))
        neu = Leistung(user_id=self.person.id, art="aufgabe", quelle_id=9002,
                       titel="Neu", punkte=1, zeitpunkt=utcnow())
        self.db.add_all([alt, neu])
        self.db.commit()
        gewicht_alt = leistung._gewicht_nach_alter(alt.zeitpunkt, utcnow())
        gewicht_neu = leistung._gewicht_nach_alter(neu.zeitpunkt, utcnow())
        self.assertLess(gewicht_alt, gewicht_neu)
        self.assertGreater(gewicht_alt, 0)


if __name__ == "__main__":
    unittest.main()
