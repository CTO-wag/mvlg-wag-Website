"""Das Kopieren zwischen zwei Datenbanken.

Gegen ein echtes Postgres laesst sich hier nicht testen - dafuer braeuchte es
einen Server. Was sich testen laesst, ist alles, was beim Umzug schiefgehen
kann und nichts mit dem Dialekt zu tun hat: dass jede Tabelle mitkommt, dass
die Reihenfolge die Fremdschluessel beachtet, dass ein zweiter Lauf nicht
verdoppelt.
"""

import pathlib
import tempfile
import unittest

from tests import hilfe                                      # noqa: F401

from kern import datenumzug
from kern.datenbank import SessionLocal
from kern.modelle import Application, User
from tests.hilfe import frische_datenbank


class TestKopieren(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        frische_datenbank()
        from kern.einstellungen import DATENBANK_DATEI
        cls.quelle = "sqlite:///" + DATENBANK_DATEI.replace("\\", "/")
        cls.ordner = tempfile.mkdtemp(prefix="wag-umzug-")

    def _ziel(self, name="ziel.db"):
        return "sqlite:///" + str(
            pathlib.Path(self.ordner, name)).replace("\\", "/")

    def test_alle_tabellen_kommen_mit(self):
        ziel = self._ziel("alle.db")
        bilanz = datenumzug.kopiere(self.quelle, ziel, melden=lambda _: None)
        erwartet = len(datenumzug.tabellen_in_reihenfolge())
        self.assertEqual(len(bilanz), erwartet)

    def test_die_zeilen_stimmen(self):
        ziel = self._ziel("zeilen.db")
        datenumzug.kopiere(self.quelle, ziel, melden=lambda _: None)
        vorher = datenumzug.zaehle(datenumzug.verbinde(self.quelle))
        nachher = datenumzug.zaehle(datenumzug.verbinde(ziel))
        abweichung = {t: (vorher[t], nachher.get(t))
                      for t in vorher if nachher.get(t) != vorher[t]}
        self.assertEqual(abweichung, {})

    def test_zweiter_lauf_verdoppelt_nicht(self):
        """Ohne das Leeren gaebe es beim zweiten Mal doppelte Schluessel."""
        ziel = self._ziel("zweimal.db")
        datenumzug.kopiere(self.quelle, ziel, melden=lambda _: None)
        erst = datenumzug.zaehle(datenumzug.verbinde(ziel))
        datenumzug.kopiere(self.quelle, ziel, melden=lambda _: None)
        zweit = datenumzug.zaehle(datenumzug.verbinde(ziel))
        self.assertEqual(erst, zweit)

    def test_inhalte_kommen_unveraendert_an(self):
        db = SessionLocal()
        person = db.query(User).filter(User.status == "aktiv").first()
        db.add(Application(
            vorname="Umzug", nachname="Prüfling", klasse="9",
            email="umzug@example.org", telefonnummer="0163 1234567",
            motivation="Umlaute prüfen: äöüß und ein Komma, sowie \"Zitat\".",
            interessen="Börse", department="tech", status="neu"))
        db.commit()
        db.close()

        ziel = self._ziel("inhalt.db")
        datenumzug.kopiere(self.quelle, ziel, melden=lambda _: None)

        motor = datenumzug.verbinde(ziel)
        from sqlalchemy.orm import Session
        with Session(motor) as sitzung:
            geholt = sitzung.query(Application).filter(
                Application.email == "umzug@example.org").first()
            self.assertIsNotNone(geholt)
            self.assertEqual(geholt.nachname, "Prüfling")
            self.assertIn("äöüß", geholt.motivation)
            self.assertIn('"Zitat"', geholt.motivation)

    def test_reihenfolge_beachtet_die_fremdschluessel(self):
        """users muss vor user_sessions kommen, sonst zeigt eine Sitzung auf
        ein Konto, das es noch nicht gibt."""
        namen = [t.name for t in datenumzug.tabellen_in_reihenfolge()]
        self.assertLess(namen.index("users"), namen.index("user_sessions"))
        self.assertLess(namen.index("applications"),
                        namen.index("application_reviews"))
        self.assertLess(namen.index("meetings"),
                        namen.index("meeting_rueckmeldungen"))


class TestTypenFuerPostgres(unittest.TestCase):
    """DATETIME kennt Postgres nicht - der ALTER-Befehl braeche mitten im
    Hochfahren ab."""

    def test_uebersetzung(self):
        from kern import migration
        self.assertEqual(migration.TYPEN_POSTGRES["DATETIME"], "TIMESTAMP")

    def test_alle_verwendeten_typen_sind_bedacht(self):
        import re
        wurzel = pathlib.Path(__file__).resolve().parent.parent
        quelle = (wurzel / "kern/migration.py").read_text(encoding="utf-8")
        # Die Typen aus der Spaltenliste der Migration
        typen = set(re.findall(r'"((?:VARCHAR\(\d+\)|INTEGER|TEXT|DATETIME|DATE'
                               r'|REAL|BOOLEAN)[^"]*)"', quelle))
        gueltig_in_postgres = {"VARCHAR", "INTEGER", "TEXT", "DATE", "BOOLEAN",
                               "NUMERIC"}
        from kern.migration import TYPEN_POSTGRES
        for typ in typen:
            grund = typ.split()[0].split("(")[0].upper()
            with self.subTest(typ):
                self.assertTrue(
                    grund in gueltig_in_postgres or grund in TYPEN_POSTGRES,
                    f"{grund} ist in Postgres unbekannt und wird nicht übersetzt")


class TestSicherungOhneLokaleDatei(unittest.TestCase):
    """Liegt die Datenbank bei Supabase, gibt es keine Datei zum Kopieren."""

    def test_das_modul_kennt_beide_faelle(self):
        wurzel = pathlib.Path(__file__).resolve().parent.parent
        quelle = (wurzel / "kern/sicherung.py").read_text(encoding="utf-8")
        self.assertIn("_liegt_lokal", quelle)
        self.assertIn("_auszug", quelle)

    def test_bei_sqlite_bleibt_es_beim_alten_weg(self):
        from kern import sicherung
        self.assertTrue(sicherung._liegt_lokal(),
                        "die Tests laufen auf SQLite")

    def test_auch_die_migration_sichert_ohne_datei(self):
        wurzel = pathlib.Path(__file__).resolve().parent.parent
        quelle = (wurzel / "kern/migration.py").read_text(encoding="utf-8")
        i = quelle.index("def _sicherung_vor_migration")
        block = quelle[i:i + 1600]
        self.assertIn("datenumzug", block,
                      "ohne lokale Datei gäbe es sonst gar keine Sicherung")


class TestAdresseDerDatenbank(unittest.TestCase):

    def test_leerer_eintrag_faellt_auf_sqlite_zurueck(self):
        """In der config.cmd steht ein Wert oft als  set "X="  da. Ohne diesen
        Rueckfall braeche die Anwendung beim Start ab."""
        import importlib
        import os
        alt = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = ""
        try:
            from kern import einstellungen
            neu = importlib.reload(einstellungen)
            self.assertTrue(neu.DATABASE_URL.startswith("sqlite"))
        finally:
            if alt is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = alt
            importlib.reload(importlib.import_module("kern.einstellungen"))

    def test_der_startbericht_zeigt_kein_passwort(self):
        import importlib
        import os
        alt = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = (
            "postgresql+psycopg2://postgres.abc:GEHEIMESPASSWORT@"
            "aws-0-eu-central-1.pooler.supabase.com:6543/postgres")
        try:
            from kern import einstellungen
            neu = importlib.reload(einstellungen)
            zeile = neu._datenbank_kurz()
            self.assertNotIn("GEHEIMESPASSWORT", zeile)
            self.assertIn("Supabase", zeile)
        finally:
            if alt is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = alt
            importlib.reload(importlib.import_module("kern.einstellungen"))


if __name__ == "__main__":
    unittest.main()
