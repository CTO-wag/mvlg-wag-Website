"""Was sich zwischen SQLite und Postgres unterschiedlich verhaelt.

Die Anwendung lief jahrelang nur auf SQLite. Seit die Datenbank bei Supabase
liegt, gelten andere Regeln - und zwar stillschweigend: Es gibt keine
Fehlermeldung, die Reihenfolge ist nur anders.

Hier laufen die Tests weiterhin gegen SQLite. Geprueft wird deshalb, dass die
Abfragen das gewuenschte Verhalten AUSDRUECKLICH verlangen, statt sich auf die
Voreinstellung einer bestimmten Datenbank zu verlassen.
"""

import datetime
import pathlib
import unittest

from tests import hilfe                                      # noqa: F401

from kern.datenbank import SessionLocal
from kern.modelle import CalendarEvent
from tests.hilfe import frische_datenbank

WURZEL = pathlib.Path(__file__).resolve().parent.parent
NL = chr(10)


class TestLeereWerteBeimSortieren(unittest.TestCase):
    """Ganztaegige Termine haben keine Uhrzeit.

    SQLite stellt leere Werte beim Aufsteigend-Sortieren nach vorn, Postgres
    nach hinten. Ohne ausdrueckliche Angabe rutscht der ganztaegige Termin
    seit dem Umzug ans Ende des Tages.
    """

    def test_der_kalender_verlangt_es_ausdruecklich(self):
        for datei in ("dashboard/routen/organisation.py",
                      "dashboard/routen/uebersicht.py"):
            with self.subTest(datei):
                quelle = (WURZEL / datei).read_text(encoding="utf-8")
                self.assertIn("start_time.asc().nullsfirst()", quelle)

    def test_ohne_uhrzeit_kommt_zuerst(self):
        frische_datenbank()
        tag = datetime.date(2026, 9, 1)
        db = SessionLocal()
        db.add_all([
            CalendarEvent(title="Mit Uhrzeit", start_date=tag,
                          start_time="14:00"),
            CalendarEvent(title="Ganztaegig", start_date=tag,
                          start_time=None),
        ])
        db.commit()
        reihe = (db.query(CalendarEvent)
                 .filter(CalendarEvent.start_date == tag)
                 .order_by(CalendarEvent.start_date,
                           CalendarEvent.start_time.asc().nullsfirst())
                 .all())
        db.close()
        self.assertEqual([t.title for t in reihe],
                         ["Ganztaegig", "Mit Uhrzeit"])


class TestRowLevelSecurity(unittest.TestCase):
    """Neben Supabase steht eine offene REST-Schnittstelle.

    Die Rolle "anon" darf dort standardmaessig jede Tabelle im Schema public
    lesen und schreiben. Zurueck haelt sie allein Row Level Security. Ohne
    die kam jeder mit dem anon-Schluessel an die Passwort-Hashes, an die
    offenen Sitzungen - deren Kennung zugleich der Anmeldeschluessel ist -
    und an die Bewerberdaten.

    Hier laufen die Tests gegen SQLite, wo es kein RLS gibt. Geprueft wird
    deshalb, dass die Anwendung es an jeder Stelle einschaltet, an der eine
    Tabelle entstehen kann, und dass sie auf SQLite nichts versucht.
    """

    def test_auf_sqlite_passiert_nichts(self):
        from kern.datenbank import engine
        from kern.datenumzug import rls_einschalten, rls_luecken
        self.assertEqual(rls_einschalten(engine, melden=lambda _: None), 0)
        self.assertEqual(rls_luecken(engine), [])

    def test_der_start_schaltet_es_ein(self):
        """Sonst stuende eine neu angelegte Tabelle offen."""
        quelle = (WURZEL / "kern/migration.py").read_text(encoding="utf-8")
        self.assertIn("rls_einschalten", quelle)

    def test_der_umzug_schaltet_es_ein(self):
        """Zwischen Umzug und erstem Start laege sonst ein offenes Fenster."""
        quelle = (WURZEL / "kern/datenumzug.py").read_text(encoding="utf-8")
        i = quelle.index("def kopiere(")
        self.assertIn("rls_einschalten", quelle[i:])

    def test_ohne_richtlinien_und_ohne_force(self):
        """Zwei Feinheiten, an denen es kippen wuerde.

        Eine Richtlinie waere eine Erlaubnis - gewollt ist die vollstaendige
        Sperre. Und FORCE ROW LEVEL SECURITY wuerde auch den Eigentuemer
        binden: Dann saehe die Anwendung selbst keine Zeile mehr.
        """
        import ast
        quelle = (WURZEL / "kern/datenumzug.py").read_text(encoding="utf-8")
        baum = ast.parse(quelle)
        funktion = next(k for k in ast.walk(baum)
                        if isinstance(k, ast.FunctionDef)
                        and k.name == "rls_einschalten")
        # Ohne den Erklaertext - der nennt FORCE als Gegenbeispiel.
        ohne_text = NL.join(
            ast.unparse(satz) for satz in funktion.body
            if not (isinstance(satz, ast.Expr)
                    and isinstance(satz.value, ast.Constant)))
        self.assertIn("ENABLE ROW LEVEL SECURITY", ohne_text)
        self.assertNotIn("FORCE ROW LEVEL SECURITY", ohne_text)
        self.assertNotIn("CREATE POLICY", ohne_text)


class TestKeinRohesSQL(unittest.TestCase):
    """Rohes SQL waere die naheliegendste Stelle, an der ein Dialekt durchschlaegt.

    In der Anwendung selbst gibt es keines - alles laeuft ueber die Modelle.
    Die Werkzeuge fuer Umzug, Migration und Sicherung duerfen welches
    enthalten; sie wissen, mit welcher Datenbank sie es zu tun haben.
    """

    ERLAUBT = {"kern/datenumzug.py", "kern/migration.py", "kern/sicherung.py"}

    def test_die_anwendung_kommt_ohne_aus(self):
        import re
        gefunden = []
        for ordner in ("dashboard", "website", "kern"):
            for datei in (WURZEL / ordner).rglob("*.py"):
                kurz = datei.relative_to(WURZEL).as_posix()
                if kurz in self.ERLAUBT:
                    continue
                inhalt = datei.read_text(encoding="utf-8")
                if re.search(r"execute\(\s*text\(", inhalt):
                    gefunden.append(kurz)
        self.assertEqual(gefunden, [])


class TestSuchenOhneGrossKleinSchreibung(unittest.TestCase):
    """SQLites LIKE unterscheidet nicht zwischen gross und klein, Postgres schon.

    Mit like() statt ilike() faende die Suche im Dashboard nach dem Umzug
    nichts mehr, sobald jemand anders tippt, als es gespeichert ist.
    """

    def test_die_suche_benutzt_ilike(self):
        quelle = (WURZEL / "dashboard/routen/uebersicht.py").read_text(
            encoding="utf-8")
        self.assertIn(".ilike(", quelle)
        self.assertNotIn(".like(", quelle.replace(".ilike(", ""))


if __name__ == "__main__":
    unittest.main()
