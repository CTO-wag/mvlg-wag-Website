"""Kern: Text, Geld, Rechte, Sicherheit."""

import unittest

from tests import hilfe                                      # noqa: F401  (Reihenfolge!)

from kern import einstellungen as cfg
from kern.rechte import (
    PERM_KEYS, darf_person_bearbeiten, perm_gruppen, rollen, zustaendige_abteilungen,
)
from kern.sicherheit import (
    geraete_fingerabdruck, passwort_bewerten, passwort_hashen, passwort_pruefen,
    passwort_vorschlag, totp_code, totp_geheimnis, totp_pruefen,
)
from kern.text import (
    betrag_in_cent, csv_sicher, email_gueltig, euro, kuerzen, telefon_normal,
)


class TestOrdner(unittest.TestCase):
    def test_tests_fassen_den_echten_bestand_nicht_an(self):
        """Die wichtigste Zusicherung der ganzen Suite."""
        self.assertIn("wag-test-", cfg.DATEN_DIR)
        self.assertNotIn("OneDrive", cfg.DATEN_DIR)


class TestGeld(unittest.TestCase):
    def test_deutsche_schreibweise(self):
        self.assertEqual(betrag_in_cent("12,50"), 1250)
        self.assertEqual(betrag_in_cent("1.234,56"), 123456)
        self.assertEqual(betrag_in_cent("12.50"), 1250)
        self.assertEqual(betrag_in_cent("-8"), -800)
        self.assertEqual(betrag_in_cent("12,50 €"), 1250)

    def test_unsinn_wird_abgelehnt(self):
        for eingabe in ("", "abc", "1,2,3", None):
            self.assertIsNone(betrag_in_cent(eingabe), eingabe)

    def test_ausgabe(self):
        self.assertEqual(euro(123456), "1.234,56 €")
        self.assertEqual(euro(0), "0,00 €")
        self.assertEqual(euro(-500), "−5,00 €")

    def test_cent_bleiben_exakt(self):
        """Zehnmal zehn Cent sind genau ein Euro - der Grund fuer Ganzzahlen."""
        summe = sum(betrag_in_cent("0,10") for _ in range(10))
        self.assertEqual(summe, 100)


class TestText(unittest.TestCase):
    def test_csv_injektion(self):
        self.assertEqual(csv_sicher("=cmd|'/c calc'!A0"), "'=cmd|'/c calc'!A0")
        self.assertEqual(csv_sicher("harmlos"), "harmlos")

    def test_email(self):
        self.assertTrue(email_gueltig("a@b.de"))
        self.assertFalse(email_gueltig("kein-at"))
        self.assertFalse(email_gueltig("a@b"))

    def test_telefon(self):
        for eingabe in ("+4915112209314", "015112209314", "0049 151 12209314",
                        "+49 151 12209314"):
            self.assertEqual(telefon_normal(eingabe), "4915112209314", eingabe)

    def test_kuerzen(self):
        self.assertEqual(kuerzen("abcdefghij", 5), "abcd…")
        self.assertEqual(kuerzen("abc", 5), "abc")


class TestPasswort(unittest.TestCase):
    def test_gutes_passwort(self):
        gut, _ = passwort_bewerten("Zirkelschluss7Wand")
        self.assertTrue(gut)

    def test_meldung_nennt_was_fehlt(self):
        gut, meldung = passwort_bewerten("kurz1A")
        self.assertFalse(gut)
        self.assertIn("12 Zeichen", meldung)
        gut, meldung = passwort_bewerten("alleskleingeschrieben1")
        self.assertFalse(gut)
        self.assertIn("Großbuchstaben", meldung)

    def test_naheliegendes_wird_abgelehnt(self):
        for schwach in ("Wirtschaft2026x", "MeinPasswort123", "Koblenz12345A"):
            gut, _ = passwort_bewerten(schwach)
            self.assertFalse(gut, schwach)

    def test_eigener_name_verboten(self):
        gut, meldung = passwort_bewerten("Musterfrau2026X", ("Anna", "Musterfrau"))
        self.assertFalse(gut)
        self.assertIn("Name", meldung)

    def test_vorschlag_ist_gueltig(self):
        for _ in range(20):
            self.assertTrue(passwort_bewerten(passwort_vorschlag())[0])

    def test_hash_und_pruefung(self):
        h = passwort_hashen("Zirkelschluss7Wand")
        self.assertTrue(passwort_pruefen("Zirkelschluss7Wand", h))
        self.assertFalse(passwort_pruefen("falsch", h))


class TestZweiterFaktor(unittest.TestCase):
    def test_code_passt_zu_sich_selbst(self):
        geheim = totp_geheimnis()
        self.assertTrue(totp_pruefen(geheim, totp_code(geheim)))

    def test_falscher_code(self):
        geheim = totp_geheimnis()
        self.assertFalse(totp_pruefen(geheim, "000000"))
        self.assertFalse(totp_pruefen(geheim, "abc"))
        self.assertFalse(totp_pruefen(geheim, ""))

    def test_toleranz_in_beide_richtungen(self):
        """Handys gehen selten sekundengenau - ein Schritt muss durchgehen."""
        import time
        geheim = totp_geheimnis()
        jetzt = time.time()
        for versatz in (-30, 0, 30):
            self.assertTrue(totp_pruefen(geheim, totp_code(geheim, jetzt + versatz)),
                            f"Versatz {versatz}")

    def test_zu_alter_code_faellt_durch(self):
        import time
        geheim = totp_geheimnis()
        alt = totp_code(geheim, time.time() - 300)
        self.assertFalse(totp_pruefen(geheim, alt))


class TestGeraetebindung(unittest.TestCase):
    CHROME_ALT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    CHROME_NEU = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    FIREFOX = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
               "Gecko/20100101 Firefox/121.0")

    def test_browser_update_wirft_niemanden_raus(self):
        """Sonst flögen nach jedem Chrome-Update alle raus."""
        self.assertEqual(geraete_fingerabdruck(self.CHROME_ALT, "geheim"),
                         geraete_fingerabdruck(self.CHROME_NEU, "geheim"))

    def test_anderer_browser_faellt_auf(self):
        self.assertNotEqual(geraete_fingerabdruck(self.CHROME_ALT, "geheim"),
                            geraete_fingerabdruck(self.FIREFOX, "geheim"))


class TestRechte(unittest.TestCase):
    def setUp(self):
        hilfe.frische_datenbank()

    def test_jedes_recht_steht_in_einer_gruppe(self):
        """Ein neu hinzugefuegtes Recht darf nie unsichtbar bleiben."""
        aus_gruppen = {k for _, eintraege in perm_gruppen() for k, _, _ in eintraege}
        self.assertEqual(aus_gruppen, set(PERM_KEYS))

    def test_cto_behaelt_kernrechte(self):
        r = rollen()
        for recht in ("rollen", "accounts_all"):
            self.assertTrue(r["cto"][recht])

    def test_rangregel(self):
        class Person:
            def __init__(self, kennung, rolle):
                self.id = kennung
                self.role = rolle

        cto, mitglied = Person(1, "cto"), Person(2, "member")
        self.assertTrue(darf_person_bearbeiten(cto, mitglied))
        self.assertFalse(darf_person_bearbeiten(mitglied, cto))
        self.assertTrue(darf_person_bearbeiten(mitglied, mitglied))

    def test_vorstand_ist_immer_fuer_exekutive_zustaendig(self):
        class Person:
            role = "cto"
            department = "tech"
            id = 1

        self.assertIn("exekutive", zustaendige_abteilungen(Person()))
        self.assertIn("tech", zustaendige_abteilungen(Person()))

    def test_mitglied_nur_eigene_abteilung(self):
        class Person:
            role = "member"
            department = "tech"
            id = 2

        self.assertEqual(zustaendige_abteilungen(Person()), ("tech",))


if __name__ == "__main__":
    unittest.main()
