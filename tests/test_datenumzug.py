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


class TestZuLangeWerte(unittest.TestCase):
    """SQLite behandelt VARCHAR(200) als Notiz, Postgres als Regel.

    Aufgefallen ist das beim echten Umzug: In activity_log.value stand
    eine Rechteliste mit 319 Zeichen. Der Umzug brach mitten im Kopieren
    ab, mit einem Fehler, dem man die Ursache nicht ansah.
    """

    def setUp(self):
        frische_datenbank()
        from kern.einstellungen import DATENBANK_DATEI
        self.quelle = "sqlite:///" + DATENBANK_DATEI.replace("\\", "/")

    def test_saubere_datenbank_meldet_nichts(self):
        motor = datenumzug.verbinde(self.quelle)
        self.assertEqual(datenumzug.zu_lange_werte(motor), [])

    def test_ein_zu_langer_wert_wird_gefunden(self):
        from kern.modelle import ActivityLog
        motor = datenumzug.verbinde(self.quelle)
        grenze = ActivityLog.__table__.c["event_type"].type.length
        self.assertTrue(grenze, "event_type braucht eine Laengenangabe")

        # SQLite nimmt das klaglos an - genau darum geht es hier.
        db = SessionLocal()
        eintrag = ActivityLog(event_type="x" * (grenze + 50))
        db.add(eintrag)
        db.commit()
        nummer = eintrag.id
        db.close()

        # Wieder wegraeumen: frische_datenbank() legt nur an, es leert
        # nicht. Sonst faende der naechste Test diesen Wert vor.
        def aufraeumen():
            sitzung = SessionLocal()
            sitzung.query(ActivityLog).filter(
                ActivityLog.id == nummer).delete()
            sitzung.commit()
            sitzung.close()
        self.addCleanup(aufraeumen)

        treffer = {(t, s): (n, m)
                   for t, s, g, n, m in datenumzug.zu_lange_werte(motor)}
        self.assertIn(("activity_log", "event_type"), treffer)
        anzahl, laengster = treffer[("activity_log", "event_type")]
        self.assertEqual(anzahl, 1)
        self.assertEqual(laengster, grenze + 50)


class TestVerbreiterteSpalten(unittest.TestCase):

    def test_activity_log_value_hat_keine_grenze(self):
        """Die Rechteliste waechst mit jedem neuen Recht. Eine feste
        Laenge waere wieder eine Zeitbombe."""
        from kern.modelle import ActivityLog
        self.assertIsNone(ActivityLog.__table__.c["value"].type.length)

    def test_auf_sqlite_wird_nicht_verbreitert(self):
        """ALTER COLUMN kennt SQLite nicht - der Start braeche ab."""
        from kern import migration
        self.assertEqual(migration._spalten_verbreitern(), 0)

    def test_jede_verbreiterte_spalte_gibt_es_auch(self):
        from kern import migration
        from kern.datenbank import Base
        for (tabelle, spalte) in migration.VERBREITERT:
            with self.subTest(f'{tabelle}.{spalte}'):
                self.assertIn(tabelle, Base.metadata.tables)
                self.assertIn(
                    spalte, Base.metadata.tables[tabelle].c)

class TestRechteSpalten(unittest.TestCase):
    """Der Fehler, der beim echten Umzug jede Rolle entrechtet hat.

    Die 28 Rechtespalten stehen nicht in kern/modelle.py - kern/rechte.py
    haengt sie beim Import an Role und Department. Wer nur modelle importiert,
    sieht eine roles-Tabelle mit 6 Spalten. Der Umzug kopierte deshalb die
    Rechte nicht, legte sie im Ziel per DEFAULT 0 neu an, und meldete
    vollstaendige Zeilenzahlen. Im Dashboard hatte danach jede Rolle null
    Rechte.
    """

    def setUp(self):
        frische_datenbank()
        from kern.einstellungen import DATENBANK_DATEI
        self.quelle = "sqlite:///" + DATENBANK_DATEI.replace("\\", "/")
        self.ordner = tempfile.mkdtemp(prefix="wag-rechte-")

    def _ziel(self, name):
        return "sqlite:///" + str(
            pathlib.Path(self.ordner, name)).replace("\\", "/")

    def test_das_modul_importiert_rechte(self):
        """Die Ursache selbst. Faellt der Import weg, faellt es hier auf."""
        wurzel = pathlib.Path(__file__).resolve().parent.parent
        quelle = (wurzel / "kern/datenumzug.py").read_text(encoding="utf-8")
        self.assertIn("from kern import rechte", quelle)

    def test_roles_hat_die_rechtespalten(self):
        from kern.datenbank import Base
        from kern.rechte import PERM_KEYS
        spalten = Base.metadata.tables["roles"].c
        for schluessel in PERM_KEYS:
            with self.subTest(schluessel):
                self.assertIn(schluessel, spalten)

    def test_gesetzte_rechte_kommen_mit(self):
        from sqlalchemy import text
        from kern.rechte import PERM_KEYS

        motor = datenumzug.verbinde(self.quelle)
        with motor.begin() as verbindung:
            for name in PERM_KEYS:
                verbindung.execute(text(
                    f'UPDATE roles SET "{name}" = 1 WHERE key = :k'),
                    {"k": "cto"})

        ziel = self._ziel("rechte.db")
        datenumzug.kopiere(self.quelle, ziel, melden=lambda _: None)

        liste = ", ".join(f'"{s}"' for s in PERM_KEYS)
        with datenumzug.verbinde(ziel).connect() as verbindung:
            werte = verbindung.execute(text(
                f"SELECT {liste} FROM roles WHERE key = :k"),
                {"k": "cto"}).one()
        self.assertEqual(list(werte), [1] * len(PERM_KEYS),
                         "die Rechte sind beim Kopieren verloren gegangen")

    def test_eine_spalte_ausserhalb_des_modells_kommt_mit(self):
        """Kopiert wird, was in der Datenbank steht - nicht, was das Modell
        kennt. Sonst haengt alles daran, welche Module importiert wurden."""
        from sqlalchemy import text
        motor = datenumzug.verbinde(self.quelle)
        with motor.begin() as verbindung:
            verbindung.execute(text(
                "ALTER TABLE departments ADD COLUMN pruefwert VARCHAR(20)"))
            verbindung.execute(text(
                "UPDATE departments SET pruefwert = :w"), {"w": "erhalten"})

        ziel = self._ziel("zusatz.db")
        datenumzug.kopiere(self.quelle, ziel, melden=lambda _: None)

        with datenumzug.verbinde(ziel).connect() as verbindung:
            werte = verbindung.execute(text(
                "SELECT DISTINCT pruefwert FROM departments")).scalars().all()
        self.assertEqual(werte, ["erhalten"])


class TestTabellenOhneModell(unittest.TestCase):
    """chats, chat_participants, chat_messages und news stammen aus V1.

    Die Anwendung liest sie nicht, aber wenn sie beim Umzug fehlen, sind
    Datei und Ziel nicht mehr dasselbe - und der Rueckweg stimmt nicht mehr.
    """

    def setUp(self):
        frische_datenbank()
        from kern.einstellungen import DATENBANK_DATEI
        self.quelle = "sqlite:///" + DATENBANK_DATEI.replace("\\", "/")
        self.ordner = tempfile.mkdtemp(prefix="wag-altlast-")

    def test_eine_fremde_tabelle_wird_mitgenommen(self):
        from sqlalchemy import text
        motor = datenumzug.verbinde(self.quelle)
        with motor.begin() as verbindung:
            verbindung.execute(text(
                "CREATE TABLE altbestand (id INTEGER PRIMARY KEY, "
                "notiz VARCHAR(50))"))
            verbindung.execute(text(
                "INSERT INTO altbestand (id, notiz) VALUES (1, :n)"),
                {"n": "aus V1"})

        ziel = "sqlite:///" + str(
            pathlib.Path(self.ordner, "fremd.db")).replace("\\", "/")
        bilanz = datenumzug.kopiere(self.quelle, ziel, melden=lambda _: None)
        self.assertIn("altbestand", bilanz)

        with datenumzug.verbinde(ziel).connect() as verbindung:
            notiz = verbindung.execute(text(
                "SELECT notiz FROM altbestand WHERE id = 1")).scalar()
        self.assertEqual(notiz, "aus V1")

    def test_die_zaehlung_erfasst_sie_auch(self):
        """Sonst meldet --pruefen Gleichstand, obwohl etwas fehlt."""
        from sqlalchemy import text
        motor = datenumzug.verbinde(self.quelle)
        with motor.begin() as verbindung:
            verbindung.execute(text(
                "CREATE TABLE altbestand2 (id INTEGER PRIMARY KEY)"))
            verbindung.execute(text("INSERT INTO altbestand2 (id) VALUES (1)"))
        self.assertEqual(datenumzug.zaehle(motor).get("altbestand2"), 1)


class TestReihenfolgeNachDemZiel(unittest.TestCase):
    """Kopiert wird in der Reihenfolge des Ziels, nicht der Quelle.

    In der echten SQLite-Datei ist bei email_templates kein Fremdschluessel
    hinterlegt - SQLite prueft sie ohnehin nur auf ausdruecklichen Wunsch.
    Sortiert man danach, landet email_templates vor users, und Postgres
    lehnt den Verweis auf ein noch nicht vorhandenes Konto ab.
    """

    def test_die_schleife_folgt_dem_ziel(self):
        wurzel = pathlib.Path(__file__).resolve().parent.parent
        quelle = (wurzel / "kern/datenumzug.py").read_text(encoding="utf-8")
        self.assertIn("for ziel_tabelle in nach.sorted_tables", quelle)

    def test_das_modell_kennt_den_fremdschluessel(self):
        """Im Modell steht er - deshalb ist die Zielreihenfolge die richtige."""
        from kern.datenbank import Base
        verweise = {f.column.table.name for f
                    in Base.metadata.tables["email_templates"].foreign_keys}
        self.assertIn("users", verweise)

    def test_geloeschte_konten_blockieren_den_altbestand_nicht(self):
        """Die Tabellen ohne Modell werden ohne Fremdschluessel angelegt.

        In chat_participants stehen Verweise auf Konten, die es nicht mehr
        gibt. Mit Fremdschluessel liesse sich der Altbestand nicht mehr
        uebertragen.
        """
        wurzel = pathlib.Path(__file__).resolve().parent.parent
        quelle = (wurzel / "kern/datenumzug.py").read_text(encoding="utf-8")
        i = quelle.index("def _fehlende_tabellen_anlegen")
        block = quelle[i:i + 2200]
        self.assertIn("Fremdschluessel werden weggelassen", block)
        self.assertIn("as_generic", block,
                      "sonst scheitert CREATE TABLE an SQLites DATETIME")


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
