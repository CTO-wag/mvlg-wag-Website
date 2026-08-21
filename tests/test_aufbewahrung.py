"""Loeschfristen fuer Bewerbungen."""

import unittest
from datetime import timedelta

from tests import hilfe                                      # noqa: F401

from kern import aufbewahrung
from kern import einstellungen as cfg
from kern.datenbank import SessionLocal
from kern.modelle import Application, ApplicationReview, User
from kern.text import utcnow
from tests.hilfe import frische_datenbank


def _bewerbung(db, status, tage_alt, email="alt@example.org"):
    b = Application(
        vorname="Alt", nachname="Bewerber", klasse="11", email=email,
        telefonnummer="0163 1234567", motivation="Text lang genug fuer alles.",
        interessen="Boerse", department="tech", status=status,
        created_at=utcnow() - timedelta(days=tage_alt))
    db.add(b)
    db.commit()
    return b.id


class TestFristen(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        frische_datenbank()

    def setUp(self):
        db = SessionLocal()
        db.query(ApplicationReview).delete(synchronize_session=False)
        db.query(Application).delete(synchronize_session=False)
        db.commit()
        db.close()

    def _bestand(self):
        db = SessionLocal()
        try:
            return db.query(Application).count()
        finally:
            db.close()

    def test_abgelehnte_verschwinden_nach_der_frist(self):
        db = SessionLocal()
        _bewerbung(db, "abgelehnt", cfg.BEWERBUNG_ABGELEHNT_TAGE + 1)
        db.close()
        self.assertEqual(aufbewahrung.bewerbungen_aufraeumen(),
                         {"abgelehnt": 1})
        self.assertEqual(self._bestand(), 0)

    def test_vorher_nicht(self):
        db = SessionLocal()
        _bewerbung(db, "abgelehnt", cfg.BEWERBUNG_ABGELEHNT_TAGE - 5)
        db.close()
        self.assertEqual(aufbewahrung.bewerbungen_aufraeumen(), {})
        self.assertEqual(self._bestand(), 1)

    def test_angenommene_bleiben_laenger(self):
        db = SessionLocal()
        _bewerbung(db, "angenommen", cfg.BEWERBUNG_ABGELEHNT_TAGE + 1)
        db.close()
        self.assertEqual(aufbewahrung.bewerbungen_aufraeumen(), {})
        self.assertEqual(self._bestand(), 1)

    def test_offene_werden_nie_geloescht(self):
        """Sonst waere das Loeschen die bequemste Art, ein Versaeumnis
        verschwinden zu lassen. Offene mahnt kern/hinweise.py an."""
        db = SessionLocal()
        for status in ("neu", "in_pruefung"):
            _bewerbung(db, status, 3000, email=f"{status}@example.org")
        db.close()
        self.assertEqual(aufbewahrung.bewerbungen_aufraeumen(), {})
        self.assertEqual(self._bestand(), 2)

    def test_einschaetzungen_gehen_mit(self):
        db = SessionLocal()
        kennung = _bewerbung(db, "abgelehnt", cfg.BEWERBUNG_ABGELEHNT_TAGE + 1)
        wer = db.query(User).filter(User.status == "aktiv").first()
        db.add(ApplicationReview(application_id=kennung, user_id=wer.id,
                                 bewertung=2, notiz="Notiz ueber die Person"))
        db.commit()
        db.close()
        aufbewahrung.bewerbungen_aufraeumen()
        db = SessionLocal()
        try:
            self.assertEqual(db.query(ApplicationReview).filter(
                ApplicationReview.application_id == kennung).count(), 0)
        finally:
            db.close()

    def test_ohne_datum_wird_nichts_geraten(self):
        db = SessionLocal()
        kennung = _bewerbung(db, "abgelehnt", 9999)
        db.query(Application).filter(Application.id == kennung).update(
            {"created_at": None})
        db.commit()
        db.close()
        self.assertEqual(aufbewahrung.bewerbungen_aufraeumen(), {})
        self.assertEqual(self._bestand(), 1)

    def test_frist_null_schaltet_ab(self):
        vorher = cfg.BEWERBUNG_ABGELEHNT_TAGE
        cfg.BEWERBUNG_ABGELEHNT_TAGE = 0
        try:
            db = SessionLocal()
            _bewerbung(db, "abgelehnt", 9999)
            db.close()
            self.assertEqual(aufbewahrung.bewerbungen_aufraeumen(), {})
        finally:
            cfg.BEWERBUNG_ABGELEHNT_TAGE = vorher

    def test_bald_faellig_warnt_vorher(self):
        db = SessionLocal()
        _bewerbung(db, "abgelehnt", cfg.BEWERBUNG_ABGELEHNT_TAGE - 10)
        try:
            bald = aufbewahrung.bald_faellig(db)
            self.assertEqual(len(bald), 1)
            self.assertEqual(bald[0]["tage"], 10)
        finally:
            db.close()

    def test_der_lauf_haengt_am_taeglichen_aufraeumen(self):
        import pathlib
        wurzel = pathlib.Path(__file__).resolve().parent.parent
        planer = (wurzel / "kern/planer.py").read_text(encoding="utf-8")
        self.assertIn("bewerbungen_aufraeumen", planer)


if __name__ == "__main__":
    unittest.main()
