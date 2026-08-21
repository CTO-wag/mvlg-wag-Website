"""Treffen: wer darf was, und was zählt für den Leadership-Wert.

Zwei Meldungen aus dem Betrieb:

* „Gerade kann jeder einzelne AG-Treffen bearbeiten." Anlegen, Ändern und
  Löschen hingen von Anfang an am Recht „AG-Treffen" - das Abhaken der
  Tagesordnung nicht. Und das ist keine Kleinigkeit: Ein Haken sagt „das
  haben wir besprochen".
* „Die Angabe, ob jemand kommt oder nicht, soll in die Leadership-Performance
  mit aufgenommen werden, automatisch."

Der zweite Punkt hat eine Falle, die diese Tests festhalten: Eine Zusage ist
kein Erschienensein. Würde man sie einfach zählen, belohnte man das Zusagen
statt das Kommen.
"""

import unittest
from datetime import date, timedelta

from tests import hilfe                                      # noqa: F401

from kern import leistung
from kern.datenbank import SessionLocal
from kern.modelle import (
    Attendance, Leistung, Meeting, MeetingPunkt, MeetingRueckmeldung, Role,
    User,
)
from kern.sicherheit import passwort_hashen
from tests.hilfe import angemeldeter_client, frische_datenbank


def _person(db, email: str, rolle: str = "member") -> User:
    vorhanden = db.query(User).filter(User.email == email).first()
    if vorhanden:
        return vorhanden
    neu = User(vorname=email.split("@")[0].title(), nachname="Test",
               email=email, password_hash=passwort_hashen("EgalEgal2026x"),
               role=rolle, department="exekutive", status="aktiv")
    db.add(neu)
    db.commit()
    return neu


class TestNurBerechtigteHakenAb(unittest.TestCase):
    """Das Abhaken gehört dem, der das Treffen führt."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def _treffen_mit_punkt(self):
        db = SessionLocal()
        treffen = Meeting(title="Probetreffen", date=date.today())
        db.add(treffen)
        db.commit()
        wer = db.query(User).filter(User.status == "aktiv").first()
        punkt = MeetingPunkt(meeting_id=treffen.id, user_id=wer.id,
                             text="Kassenbericht")
        db.add(punkt)
        db.commit()
        kennungen = (treffen.id, punkt.id)
        db.close()
        return kennungen

    def _recht_setzen(self, an: bool):
        db = SessionLocal()
        rolle = db.get(Role, "cto")
        rolle.meetings_manage = 1 if an else 0
        db.commit()
        db.close()
        from kern.rechte import cache_verwerfen
        cache_verwerfen()

    def tearDown(self):
        self._recht_setzen(True)

    def test_mit_recht_laesst_sich_abhaken(self):
        import re
        _, punkt_id = self._treffen_mit_punkt()
        self._recht_setzen(True)
        seite = self.dash.get("/dashboard/treffen").text
        marke = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
        antwort = self.dash.post(f"/dashboard/treffen/punkt/{punkt_id}/abhaken",
                                 data={"csrf": marke})
        self.assertEqual(antwort.status_code, 200)
        db = SessionLocal()
        try:
            self.assertEqual(db.get(MeetingPunkt, punkt_id).erledigt, 1)
        finally:
            db.close()

    def test_ohne_recht_geht_es_nicht(self):
        import re
        _, punkt_id = self._treffen_mit_punkt()
        seite = self.dash.get("/dashboard/treffen").text
        marke = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
        self._recht_setzen(False)
        antwort = self.dash.post(f"/dashboard/treffen/punkt/{punkt_id}/abhaken",
                                 data={"csrf": marke})
        self.assertIn(antwort.status_code, (403, 302, 303))
        db = SessionLocal()
        try:
            self.assertEqual(db.get(MeetingPunkt, punkt_id).erledigt, 0,
                             "der Haken wurde trotzdem gesetzt")
        finally:
            db.close()

    def test_ohne_recht_wird_der_knopf_gar_nicht_erst_gezeigt(self):
        """Ein Knopf, der beim Drücken „darfst du nicht" sagt, ist schlechter
        als kein Knopf."""
        self._treffen_mit_punkt()
        self._recht_setzen(False)
        seite = self.dash.get("/dashboard/treffen").text
        self.assertNotIn("/abhaken", seite)
        # Sehen darf man den Stand trotzdem.
        self.assertIn("haken-stand", seite)

    def test_eintragen_bleibt_fuer_alle_offen(self):
        """Die Tagesordnung ist der Weg, ein Anliegen aufs Treffen zu bringen.
        Sie einzuschränken hieße, genau das abzuschaffen."""
        import re
        treffen_id, _ = self._treffen_mit_punkt()
        seite = self.dash.get("/dashboard/treffen").text
        marke = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
        self._recht_setzen(False)
        antwort = self.dash.post(f"/dashboard/treffen/{treffen_id}/punkt",
                                 data={"csrf": marke, "text": "Mein Anliegen"})
        self.assertEqual(antwort.status_code, 200)
        self.assertIn("Mein Anliegen", antwort.text)

    def test_zusagen_bleibt_fuer_alle_offen(self):
        import re
        treffen_id, _ = self._treffen_mit_punkt()
        seite = self.dash.get("/dashboard/treffen").text
        marke = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
        self._recht_setzen(False)
        antwort = self.dash.post(f"/dashboard/treffen/{treffen_id}/antwort",
                                 data={"csrf": marke, "antwort": "ja"})
        self.assertEqual(antwort.status_code, 200)


class TestZusageZaehltFuerLeadership(unittest.TestCase):
    """Nur ein Fall bringt Punkte: zugesagt und dann auch da gewesen."""

    @classmethod
    def setUpClass(cls):
        frische_datenbank()

    def setUp(self):
        db = SessionLocal()
        db.query(Leistung).filter(Leistung.art == "rueckmeldung").delete(
            synchronize_session=False)
        # Reihenfolge zaehlt: Alles, was auf ein Treffen zeigt, muss vorher
        # weg - sonst schlaegt der Fremdschluessel zu.
        db.query(MeetingRueckmeldung).delete(synchronize_session=False)
        db.query(MeetingPunkt).delete(synchronize_session=False)
        db.query(Attendance).delete(synchronize_session=False)
        db.query(Meeting).delete(synchronize_session=False)
        db.commit()
        self.wer = _person(db, "zusage@ag.local").id
        db.close()

    def _treffen(self, wann: date) -> int:
        db = SessionLocal()
        treffen = Meeting(title="AG-Treffen", date=wann)
        db.add(treffen)
        db.commit()
        kennung = treffen.id
        db.close()
        return kennung

    def _antwort(self, treffen_id: int, wert: str, wer: int = None):
        db = SessionLocal()
        eintrag = MeetingRueckmeldung(meeting_id=treffen_id,
                                      user_id=wer or self.wer, antwort=wert)
        db.add(eintrag)
        db.flush()
        leistung.rueckmeldung_erfasst(db, eintrag)
        db.commit()
        db.close()

    def _anwesend(self, treffen_id: int, wann: date, wer: int = None):
        db = SessionLocal()
        db.add(Attendance(user_id=wer or self.wer, meeting_id=treffen_id,
                          event_type="Treffen", event_date=wann))
        db.commit()
        db.close()

    def _punkte(self, wer: int = None) -> int:
        db = SessionLocal()
        try:
            return sum(l.punkte for l in db.query(Leistung).filter(
                Leistung.user_id == (wer or self.wer),
                Leistung.art == "rueckmeldung").all())
        finally:
            db.close()

    def test_die_zusage_wird_sofort_gutgeschrieben(self):
        """Ein Wert, der sich erst in zwei Wochen rührt, steuert nichts."""
        treffen = self._treffen(date.today() + timedelta(days=3))
        self._antwort(treffen, "ja")
        self.assertEqual(self._punkte(), leistung.PUNKTE_ZUGESAGT)

    def test_eine_absage_bringt_nichts_und_kostet_nichts(self):
        treffen = self._treffen(date.today() + timedelta(days=3))
        self._antwort(treffen, "nein")
        self.assertEqual(self._punkte(), 0)

    def test_umentscheiden_nimmt_die_gutschrift_wieder_weg(self):
        treffen = self._treffen(date.today() + timedelta(days=3))
        self._antwort(treffen, "ja")
        db = SessionLocal()
        eintrag = db.query(MeetingRueckmeldung).filter(
            MeetingRueckmeldung.meeting_id == treffen).first()
        eintrag.antwort = "nein"
        leistung.rueckmeldung_erfasst(db, eintrag)
        db.commit()
        db.close()
        self.assertEqual(self._punkte(), 0)

    def test_wort_gehalten_zaehlt_doppelt(self):
        gestern = date.today() - timedelta(days=1)
        treffen = self._treffen(gestern)
        self._antwort(treffen, "ja")
        self._anwesend(treffen, gestern)
        self.assertEqual(leistung.treffen_abrechnen(), 1)
        self.assertEqual(self._punkte(), leistung.PUNKTE_WORT_GEHALTEN)

    def test_zugesagt_und_nicht_gekommen_bringt_nichts(self):
        gestern = date.today() - timedelta(days=1)
        treffen = self._treffen(gestern)
        self._antwort(treffen, "ja")
        # Jemand anderes war da, diese Person nicht.
        db = SessionLocal()
        anderer = _person(db, "andere@ag.local").id
        db.close()
        self._anwesend(treffen, gestern, wer=anderer)
        leistung.treffen_abrechnen()
        self.assertEqual(self._punkte(), 0,
                         "die vorläufige Gutschrift blieb stehen")

    def test_ohne_anwesenheitsliste_wird_nichts_abgerechnet(self):
        """Sonst wäre eine vergessene Liste eine Strafe für alle, die
        zugesagt hatten - für das Versäumnis eines anderen."""
        gestern = date.today() - timedelta(days=1)
        treffen = self._treffen(gestern)
        self._antwort(treffen, "ja")
        self.assertEqual(leistung.treffen_abrechnen(), 0)
        self.assertEqual(self._punkte(), leistung.PUNKTE_ZUGESAGT)
        db = SessionLocal()
        try:
            self.assertIsNone(db.get(Meeting, treffen).leistung_verrechnet,
                              "das Treffen gilt als erledigt, ist es aber nicht")
        finally:
            db.close()

    def test_nachgetragene_liste_holt_es_nach(self):
        gestern = date.today() - timedelta(days=1)
        treffen = self._treffen(gestern)
        self._antwort(treffen, "ja")
        leistung.treffen_abrechnen()          # noch keine Liste
        self._anwesend(treffen, gestern)
        self.assertEqual(leistung.treffen_abrechnen(), 1)
        self.assertEqual(self._punkte(), leistung.PUNKTE_WORT_GEHALTEN)

    def test_zweimal_abrechnen_verdoppelt_nichts(self):
        gestern = date.today() - timedelta(days=1)
        treffen = self._treffen(gestern)
        self._antwort(treffen, "ja")
        self._anwesend(treffen, gestern)
        leistung.treffen_abrechnen()
        self.assertEqual(leistung.treffen_abrechnen(), 0)
        self.assertEqual(self._punkte(), leistung.PUNKTE_WORT_GEHALTEN)

    def test_kuenftige_treffen_bleiben_unangetastet(self):
        treffen = self._treffen(date.today() + timedelta(days=7))
        self._antwort(treffen, "ja")
        self.assertEqual(leistung.treffen_abrechnen(), 0)
        self.assertEqual(self._punkte(), leistung.PUNKTE_ZUGESAGT)

    def test_gezaehlt_wird_zum_datum_des_treffens(self):
        """Sonst wäre eine Zusage von vor zwei Wochen im Zeitfenster älter
        als das Treffen selbst."""
        gestern = date.today() - timedelta(days=1)
        treffen = self._treffen(gestern)
        self._antwort(treffen, "ja")
        db = SessionLocal()
        try:
            eintrag = db.query(Leistung).filter(
                Leistung.art == "rueckmeldung",
                Leistung.user_id == self.wer).first()
            self.assertEqual(eintrag.zeitpunkt.date(), gestern)
        finally:
            db.close()


class TestDerWertSinktNiemandem(unittest.TestCase):
    """Die Ansage kann den Anwesenheitswert heben, nie senken.

    Ohne diese Regel wäre der Wert JEDES Mitglieds an dem Tag gesunken, an
    dem die Zählung eingeführt wurde - für ein Verhalten, das vorher niemand
    zeigen konnte.
    """

    @classmethod
    def setUpClass(cls):
        frische_datenbank()

    def setUp(self):
        db = SessionLocal()
        self.wer = _person(db, "nurda@ag.local").id
        db.query(Leistung).filter(Leistung.user_id == self.wer).delete(
            synchronize_session=False)
        db.commit()
        db.close()

    def test_wer_nur_kommt_verliert_nichts(self):
        db = SessionLocal()
        heute = date.today()
        for i in range(6):
            eintrag = Attendance(user_id=self.wer, event_type="Treffen",
                                 event_date=heute - timedelta(days=14 * i))
            db.add(eintrag)
            db.flush()
            leistung.anwesenheit_erfasst(db, eintrag)
        db.commit()
        ohne_ansage = leistung.werte_fuer(db, self.wer)["anwesenheit"]
        db.close()
        self.assertGreater(ohne_ansage, 0)

        # Dieselbe Person, jetzt zusätzlich mit gehaltenen Zusagen.
        db = SessionLocal()
        for i in range(6):
            leistung.vermerke(db, self.wer, "rueckmeldung", 9000 + i,
                              "AG-Treffen", leistung.PUNKTE_WORT_GEHALTEN)
        db.commit()
        mit_ansage = leistung.werte_fuer(db, self.wer)["anwesenheit"]
        db.close()
        self.assertGreater(mit_ansage, ohne_ansage,
                           "die gehaltene Zusage wirkt sich nicht aus")

    def test_wer_nur_absagt_bekommt_keine_anwesenheit(self):
        """Acht Monate zuverlässig absagen heißt acht Monate nicht da sein."""
        db = SessionLocal()
        try:
            self.assertEqual(leistung.werte_fuer(db, self.wer)["anwesenheit"], 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
