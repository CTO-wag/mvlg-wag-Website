"""Der WhatsApp-Bot - besonders die Fallstricke der Meta-Cloud-API."""

import unittest

from tests import hilfe                                      # noqa: F401

from kern import whatsapp, werte
from kern.datenbank import SessionLocal
from kern.modelle import User, WhatsAppNachricht
from kern.text import telefon_normal


class TestVorlagenParameter(unittest.TestCase):
    """Meta lehnt Parameter mit Zeilenumbruch, Tabulator oder vier
    aufeinanderfolgenden Leerzeichen ab - mit einem Fehlertext, der die
    Ursache nicht nennt. Deshalb wird hier vorher sauber gemacht."""

    def test_zeilenumbruch_wird_entfernt(self):
        self.assertNotIn("\n", whatsapp._parameter_saeubern("Hallo\nWelt"))
        self.assertEqual(whatsapp._parameter_saeubern("Hallo\nWelt"), "Hallo Welt")

    def test_tabulator_und_wagenruecklauf(self):
        for zeichen in ("\t", "\r", "\r\n"):
            self.assertNotIn(zeichen.strip() or "\t",
                             whatsapp._parameter_saeubern(f"a{zeichen}b"))

    def test_viele_leerzeichen_werden_gekuerzt(self):
        gesaeubert = whatsapp._parameter_saeubern("a" + " " * 10 + "b")
        self.assertNotIn("    ", gesaeubert)

    def test_laenge_begrenzt(self):
        self.assertLessEqual(len(whatsapp._parameter_saeubern("x" * 5000)), 1000)

    def test_der_ganze_willkommenstext_waere_ungueltig_gewesen(self):
        """Genau der Fehler, den die Vorlagenparameter früher hatten."""
        roh = whatsapp.WILLKOMMEN_STANDARD
        self.assertIn("\n", roh, "Der Standardtext hat Umbrüche - so gewollt")
        self.assertNotIn("\n", whatsapp._parameter_saeubern(roh))


class TestParameterZuordnung(unittest.TestCase):
    def setUp(self):
        hilfe.frische_datenbank()
        self.db = SessionLocal()
        self.person = self.db.query(User).filter(
            User.email == "pruef@ag.local").first()
        # Die Einstellung liegt in der Datenbank und ueberlebt sonst den
        # vorigen Test - dann prueft man nicht mehr die Vorgabe.
        werte.setze(self.db, whatsapp.WERTE_VORLAGE_PARAMETER, "vorname")

    def tearDown(self):
        self.db.close()

    def test_vorgabe_ist_der_vorname(self):
        parameter = whatsapp.vorlagen_parameter(self.db, self.person)
        self.assertEqual(parameter, [self.person.vorname])

    def test_reihenfolge_wird_eingehalten(self):
        werte.setze(self.db, whatsapp.WERTE_VORLAGE_PARAMETER,
                    "vorname,dashboard,gruppe")
        parameter = whatsapp.vorlagen_parameter(self.db, self.person)
        self.assertEqual(len(parameter), 3)
        self.assertEqual(parameter[0], self.person.vorname)
        self.assertIn("http", parameter[1])

    def test_kein_parameter_hat_einen_umbruch(self):
        werte.setze(self.db, whatsapp.WERTE_VORLAGE_PARAMETER,
                    "vorname,nachname,name,abteilung,rolle,dashboard,gruppe,discord")
        for wert in whatsapp.vorlagen_parameter(self.db, self.person):
            self.assertNotIn("\n", wert)
            self.assertNotIn("\t", wert)


class TestKorb(unittest.TestCase):
    def setUp(self):
        hilfe.frische_datenbank()
        self.db = SessionLocal()
        self.db.query(WhatsAppNachricht).delete()
        self.db.commit()
        self.person = self.db.query(User).filter(
            User.email == "pruef@ag.local").first()
        self.person.telefonnummer = "0151 12345678"
        self.person.willkommen_gesendet_am = None
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_willkommen_landet_im_korb(self):
        eintrag = whatsapp.willkommen_ausloesen(self.db, self.person)
        self.db.commit()
        self.assertIsNotNone(eintrag)
        self.assertEqual(eintrag.nummer, "4915112345678")
        self.assertEqual(eintrag.status, "offen")
        self.assertIn(self.person.vorname, eintrag.text)

    def test_nur_einmal_je_person(self):
        whatsapp.willkommen_ausloesen(self.db, self.person)
        self.db.commit()
        zweiter = whatsapp.willkommen_ausloesen(self.db, self.person)
        self.assertIsNone(zweiter, "Niemand soll zweimal begrüßt werden")

    def test_ohne_nummer_kein_endloser_versuch(self):
        self.person.telefonnummer = None
        self.person.willkommen_gesendet_am = None
        self.db.commit()
        eintrag = whatsapp.willkommen_ausloesen(self.db, self.person)
        self.db.commit()
        self.assertEqual(eintrag.status, "keine_nummer")
        self.assertNotIn(eintrag, whatsapp.offene(self.db))

    def test_automatik_laesst_sich_abschalten(self):
        werte.schalte(self.db, werte.WHATSAPP_AUTOMATIK, False)
        self.person.willkommen_gesendet_am = None
        self.db.commit()
        self.assertIsNone(whatsapp.willkommen_ausloesen(self.db, self.person))
        # Von Hand geht es trotzdem
        self.assertIsNotNone(
            whatsapp.willkommen_ausloesen(self.db, self.person, erzwingen=True))
        werte.schalte(self.db, werte.WHATSAPP_AUTOMATIK, True)

    def test_klicklink_ist_richtig_kodiert(self):
        link = whatsapp.wa_link("0151 12345678", "Hallo Welt & Co")
        self.assertTrue(link.startswith("https://wa.me/4915112345678?text="))
        self.assertNotIn(" ", link)


class TestBetriebsarten(unittest.TestCase):
    def test_vorgabe_ist_manuell(self):
        self.assertEqual(whatsapp.modus(), "manuell")

    def test_manuell_ist_immer_bereit(self):
        bereit, _ = whatsapp.einsatzbereit()
        self.assertTrue(bereit)

    def test_cloud_ohne_vorlage_meldet_das_problem(self):
        """Ohne genehmigte Vorlage kommt bei neuen Mitgliedern nie etwas an."""
        from kern import einstellungen as cfg
        alt = (cfg.WHATSAPP_MODUS, cfg.WHATSAPP_TOKEN, cfg.WHATSAPP_NUMMER_ID,
               cfg.WHATSAPP_VORLAGE_NAME)
        try:
            cfg.WHATSAPP_MODUS = "cloud"
            cfg.WHATSAPP_TOKEN = "test"
            cfg.WHATSAPP_NUMMER_ID = "123"
            cfg.WHATSAPP_VORLAGE_NAME = ""
            bereit, meldung = whatsapp.einsatzbereit()
            self.assertFalse(bereit)
            self.assertIn("Vorlage", meldung)

            cfg.WHATSAPP_VORLAGE_NAME = "willkommen_ag"
            bereit, meldung = whatsapp.einsatzbereit()
            self.assertTrue(bereit)
            self.assertIn("automatisch", meldung)
        finally:
            (cfg.WHATSAPP_MODUS, cfg.WHATSAPP_TOKEN, cfg.WHATSAPP_NUMMER_ID,
             cfg.WHATSAPP_VORLAGE_NAME) = alt

    def test_fehler_werden_erklaert(self):
        text = whatsapp._cloud_fehler_erklaeren(400, 132000, "Parameter mismatch")
        self.assertIn("Zeilenumbruch", text)
        text = whatsapp._cloud_fehler_erklaeren(401, 190, "expired")
        self.assertIn("Zugriffstoken", text)
        # Unbekannte Codes duerfen nicht verschluckt werden.
        text = whatsapp._cloud_fehler_erklaeren(500, 99999, "irgendwas")
        self.assertIn("99999", text)


class TestNummern(unittest.TestCase):
    def test_alle_schreibweisen_werden_gleich(self):
        for eingabe in ("+49 151 12345678", "0151 12345678", "004915112345678",
                        "+4915112345678", "0151/1234-5678"):
            self.assertEqual(telefon_normal(eingabe), "4915112345678", eingabe)


if __name__ == "__main__":
    unittest.main()
