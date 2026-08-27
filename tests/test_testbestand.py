"""Der mitgelieferte Testbestand in daten-entwicklung/.

Diese eine Datenbankdatei liegt im Repository, damit andere die Plattform
ausprobieren koennen, ohne Zugang zu den echten Daten zu brauchen. Alles
andere unter daten/ und daten-entwicklung/ ist in .gitignore gesperrt.

Genau daraus folgt die Pflicht, die dieser Test wahrnimmt:

  * Es darf **nichts Echtes** darin stehen. Spielt jemand eine Sicherung der
    Produktion ein, um etwas nachzustellen, und committet danach, stehen die
    Daten von Minderjaehrigen auf GitHub. Das faellt sonst niemandem auf -
    eine Datenbankdatei sieht im Diff aus wie jede andere.
  * Das Testkonto muss wirklich alles duerfen. Ein Konto, dem drei Rechte
    fehlen, kostet den Naechsten eine Stunde Suche an der falschen Stelle.

Der Test liest die Datei unmittelbar mit sqlite3 - nicht ueber die
Anwendung. Die Tests laufen auf einer eigenen Wegwerfdatenbank, und geprueft
werden soll die Datei, die wirklich ausgeliefert wird.
"""

import pathlib
import sqlite3
import unittest

WURZEL = pathlib.Path(__file__).resolve().parent.parent
BESTAND = WURZEL / "daten-entwicklung" / "ag_plattform.db"

# Nur diese Absender sind erlaubt. Alles andere ist im Zweifel ein echter
# Mensch - und der gehoert nicht in ein oeffentliches Repository.
ERFUNDENE_DOMAENEN = ("beispiel.de", "example.org", "example.com",
                      "invalid.local")

TESTKONTO = "test@beispiel.de"


def _lesen(sql, *werte):
    verbindung = sqlite3.connect(f"file:{BESTAND}?mode=ro", uri=True)
    try:
        return verbindung.execute(sql, werte).fetchall()
    finally:
        verbindung.close()


def _tabellen():
    return {z[0] for z in _lesen(
        "SELECT name FROM sqlite_master WHERE type='table'")}


@unittest.skipUnless(BESTAND.exists(),
                     "kein Testbestand da - python werkzeuge/testdaten.py")
class TestTestbestand(unittest.TestCase):

    def test_es_steht_nichts_echtes_darin(self):
        """Der wichtigste Test dieser Datei.

        Nicht nach Namen gesucht, sondern nach E-Mail-Adressen: Ein Name
        beweist nichts, eine Adresse schon. Wer hier auffaellt, ist mit
        grosser Wahrscheinlichkeit ein echter Mensch.
        """
        tabellen = _tabellen()
        verdaechtig = []
        for tabelle, spalte in (("users", "email"),
                                ("applications", "email"),
                                ("contact_messages", "email"),
                                ("email_routes", "ziel")):
            if tabelle not in tabellen:
                continue
            try:
                zeilen = _lesen(f"SELECT {spalte} FROM {tabelle}")
            except sqlite3.OperationalError:
                continue                       # Spalte gibt es hier nicht
            for (adresse,) in zeilen:
                adresse = (adresse or "").strip().lower()
                if not adresse:
                    continue
                if not adresse.endswith(ERFUNDENE_DOMAENEN):
                    verdaechtig.append(f"{tabelle}.{spalte} = {adresse}")

        self.assertEqual(
            verdaechtig, [],
            "Im mitgelieferten Testbestand stehen Adressen, die nicht "
            "erfunden aussehen. Wurde eine echte Sicherung eingespielt? "
            "Dann bitte  python werkzeuge/testdaten.py --neu  laufen lassen, "
            "BEVOR das committet wird:\n  " + "\n  ".join(verdaechtig))

    def test_der_bestand_bleibt_klein(self):
        """Ein echter Datenstand ist ein Vielfaches groesser. Die Grenze ist
        grosszuegig - sie soll nicht bei jedem Klick anschlagen, sondern
        auffallen, wenn jemand versehentlich den Livebestand einspielt."""
        mb = BESTAND.stat().st_size / (1024 * 1024)
        self.assertLess(mb, 5, f"Testbestand ist {mb:.1f} MB gross - "
                               "steckt da mehr drin als gedacht?")

    def test_das_testkonto_darf_alles(self):
        from kern.rechte import PERM_KEYS

        konten = _lesen("SELECT id, role, status FROM users WHERE email = ?",
                        TESTKONTO)
        self.assertEqual(len(konten), 1, f"{TESTKONTO} fehlt im Testbestand")
        konto_id, rolle, status = konten[0]
        self.assertEqual(status, "aktiv")
        self.assertEqual(rolle, "cto")

        freigaben = {p for (p, w) in _lesen(
            "SELECT perm, wert FROM user_permissions WHERE user_id = ?",
            konto_id) if w}
        fehlend = sorted(set(PERM_KEYS) - freigaben)
        self.assertEqual(fehlend, [],
                         "Dem Testkonto fehlen Rechte: " + ", ".join(fehlend))

    def test_die_abteilungsfunktionen_sind_frei(self):
        """Redaktionsplan, Ideensammlung und Bewerbungen sichten haengen an
        der Abteilung, nicht an der Person - sie fallen sonst durchs Raster."""
        from kern.rechte import DEPT_FEATURE_KEYS

        spalten = ", ".join(DEPT_FEATURE_KEYS)
        zeilen = _lesen(
            f"SELECT {spalten} FROM departments WHERE key = 'exekutive'")
        self.assertTrue(zeilen, "Abteilung 'exekutive' fehlt")
        aus = [name for name, wert in zip(DEPT_FEATURE_KEYS, zeilen[0])
               if not wert]
        self.assertEqual(aus, [], "Nicht freigeschaltet: " + ", ".join(aus))

    def test_es_gibt_ein_zweites_gewoehnliches_konto(self):
        """Ohne jemanden, der NICHT man selbst ist, lassen sich Aufgaben
        zuteilen, Anwesenheit und Leistungswerte nicht ausprobieren."""
        andere = _lesen("SELECT email FROM users WHERE role = 'member' "
                        "AND status = 'aktiv'")
        self.assertTrue(andere, "kein einfaches Mitglied im Testbestand")

    def test_die_anleitung_liegt_daneben(self):
        liesmich = WURZEL / "daten-entwicklung" / "LIESMICH.md"
        self.assertTrue(liesmich.exists())
        text = liesmich.read_text(encoding="utf-8")
        self.assertIn(TESTKONTO, text)
        self.assertIn("testdaten.py --neu", text)


class TestNurDieseEineDateiIstFrei(unittest.TestCase):
    """Die Ausnahme in .gitignore muss eng bleiben.

    Ein `!daten-entwicklung/` allein wuerde den ganzen Ordner freigeben -
    samt Sicherungen und hochgeladenen Dateien.
    """

    def test_gitignore_gibt_nur_die_datenbank_frei(self):
        text = (WURZEL / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("daten-entwicklung/*", text,
                      "ohne diese Zeile ist der ganze Ordner frei")
        self.assertIn("!daten-entwicklung/ag_plattform.db", text)
        # Der Produktivordner bleibt in jedem Fall gesperrt.
        self.assertIn("\ndaten/\n", text)
        self.assertNotIn("!daten/", text)


if __name__ == "__main__":
    unittest.main()
