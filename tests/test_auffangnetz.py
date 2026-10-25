"""Das Auffangnetz vor der Plattform - beide Hälften.

Der Worker selbst läuft bei Cloudflare; sein Verhalten wird von
`tests/auffangnetz.mjs` unter Laborbedingungen geprüft und hier mit angestoßen,
damit es bei jedem Lauf mitgeht und nicht nur an dem Tag, an dem es geschrieben
wurde.

Die andere Hälfte steht hier in Python: Aus einer Meldung, die während des
Ausfalls beim Worker liegen blieb, muss ein echtes Support-Ticket werden. Genau
das ist der Teil, der still versagen könnte - eine Push-Nachricht am
Freitagabend ist am Montag vergessen, ein Ticket steht noch da.
"""

import json
import pathlib
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from tests import hilfe                                      # noqa: F401

from kern import ausfallmeldungen
from kern import einstellungen as cfg
from kern.datenbank import SessionLocal
from kern.modelle import Application, ContactMessage, SupportTicket, User
from tests.hilfe import frische_datenbank

WURZEL = pathlib.Path(__file__).resolve().parent.parent
SCHLUESSEL = "pruefschluessel-" + "x" * 30


class _NachgebauterWorker(BaseHTTPRequestHandler):
    """Ein Cloudflare-Worker, der nur das Nötigste kann."""

    meldungen = []
    bewerbungen = []
    nachrichten = []
    bestaetigt = []
    schluessel = SCHLUESSEL

    def log_message(self, *_):                               # still bleiben
        pass

    def _erlaubt(self):
        return self.headers.get("x-ausfall-schluessel") == self.schluessel

    def do_GET(self):
        if not self._erlaubt():
            self.send_response(403); self.end_headers(); return
        koerper = json.dumps({"meldungen": self.meldungen,
                              "bewerbungen": self.bewerbungen,
                              "nachrichten": self.nachrichten}).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(koerper)))
        self.end_headers()
        self.wfile.write(koerper)

    def do_POST(self):
        if not self._erlaubt():
            self.send_response(403); self.end_headers(); return
        laenge = int(self.headers.get("content-length") or 0)
        daten = json.loads(self.rfile.read(laenge) or b"{}")
        type(self).bestaetigt.extend(daten.get("kennungen", []))
        koerper = json.dumps({"entfernt": len(daten.get("kennungen", []))}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(koerper)))
        self.end_headers()
        self.wfile.write(koerper)


class TestWorkerVerhalten(unittest.TestCase):
    """Was der Worker tut, wenn nichts mehr antwortet."""

    def test_das_labor_laeuft_durch(self):
        node = None
        for name in ("node", "node.exe"):
            try:
                subprocess.run([name, "--version"], capture_output=True,
                               timeout=20, check=True)
                node = name
                break
            except Exception:
                continue
        if not node:
            self.skipTest("node ist hier nicht installiert")
        ziel = (WURZEL / "cloudflare/worker.js").as_uri()
        lauf = subprocess.run([node, str(WURZEL / "tests/auffangnetz.mjs"), ziel],
                              capture_output=True, text=True, timeout=120,
                              encoding="utf-8", errors="replace")
        self.assertEqual(lauf.returncode, 0,
                         (lauf.stdout or "") + (lauf.stderr or ""))
        self.assertIn("ALLE PRUEFUNGEN BESTANDEN", lauf.stdout or "")


class TestWorkerDateien(unittest.TestCase):
    """Die Seite muss ohne die Plattform funktionieren - sonst ist sie sinnlos."""

    def setUp(self):
        self.js = (WURZEL / "cloudflare/worker.js").read_text(encoding="utf-8")
        self.eingebettet = (WURZEL / "cloudflare/eingebettet.js").read_text(
            encoding="utf-8")

    def test_keine_steuerzeichen_in_der_quelle(self):
        """Beim Schreiben hatte sich einmal ein Nullbyte eingeschlichen. Das
        macht die Datei zu einer Binärdatei, und wrangler lädt sie nicht."""
        roh = (WURZEL / "cloudflare/worker.js").read_bytes()
        schlimm = {b for b in roh
                   if b < 9 or b in (11, 12) or 14 <= b < 32 or b == 127}
        self.assertEqual(schlimm, set())

    def test_die_seite_holt_nichts_von_aussen(self):
        """Der Server, von dem Bilder und Schriften kämen, ist genau der, der
        gerade nicht antwortet.

        Ein Textverweis zählt nicht dazu: Im Fuß steht seit jeher ein Link zur
        Schule, und der lädt nichts - er wartet auf einen Klick. Gesucht wird
        also nach dem, was der Browser von selbst holen würde.
        """
        for verdacht in ('src="http', "@import", "fonts.googleapis",
                         "fonts.gstatic", "url(http", "url('http",
                         'url("http'):
            self.assertNotIn(verdacht, self.js, verdacht)
            self.assertNotIn(verdacht, self.eingebettet, verdacht)
        # <link> zieht immer etwas nach. Erlaubt ist nur eine data:-Adresse
        # oder der Platzhalter, in den beim Bauen eine eingesetzt wird - dass
        # das wirklich passiert, prüft tests/auffangnetz.mjs an der fertigen
        # Seite.
        for zeile in self.js.split("\n"):
            if "<link" in zeile:
                self.assertRegex(zeile, r'href="(data:|%%[A-Z]+%%)',
                                 zeile.strip())

    def test_die_eingebetteten_sachen_sind_da(self):
        """Ohne Stylesheet und Schriften sähe die Notfassung aus wie ein
        Textdokument - und genau daran erkennt man sie sonst sofort."""
        for name in ("SCHRIFTEN", "STIL", "WAPPEN", "LOGO", "FAVICON",
                     "INHALTE", "NETLIFY_SITE"):
            self.assertIn(f"export const {name} = ", self.eingebettet, name)
        self.assertIn("data:font/woff2;base64,", self.eingebettet)
        # Ein Stück aus statisch/stil/basis.css - kommt es nicht mit, ist die
        # Datei zwar da, aber leer gebaut worden.
        self.assertIn("--seitenrand", self.eingebettet)
        self.assertIn(".marke-logo", self.eingebettet)

    def test_der_besucher_erfaehrt_den_ausfall_nicht(self):
        """Der ganze Sinn des Umbaus: Wer zum ersten Mal auf die Seite kommt,
        soll die Startseite sehen und keine Störungsmeldung. Erst wer sich
        anmelden will, bekommt sie - für ihn ist sie die richtige Antwort."""
        # Das alte Band ganz oben darf nicht zurückkommen.
        self.assertNotIn("Die Plattform ist gerade nicht erreichbar", self.js)
        self.assertNotIn("Diese Notfassung liefert Cloudflare aus", self.js)
        # Die Meldung liegt zugeklappt in der Seite und hängt am Login.
        self.assertIn('id="ausfall" hidden', self.js)
        self.assertIn("data-anmelden", self.js)

    def test_ein_500_der_anwendung_wird_nicht_ueberdeckt(self):
        """Ein 500 heißt: Die Anwendung hat geantwortet, sie läuft also. Ihre
        eigene Fehlerseite ist dann die richtige - nicht unsere."""
        zeile = [z for z in self.js.split("\n") if "NICHT_ERREICHBAR = " in z
                 or (z.strip().startswith("[50") and "502" in z)]
        block = "\n".join(zeile)
        self.assertIn("502", block)
        self.assertNotIn("500,", block)

    def test_die_anleitung_nennt_den_rueckweg(self):
        """Wer etwas vor seine Domain hängt, muss wissen, wie er es wieder
        abhängt - und zwar bevor er es braucht."""
        text = (WURZEL / "cloudflare/ANLEITUNG.md").read_text(encoding="utf-8")
        self.assertIn("Domains & Routes", text)
        self.assertIn("Wenn etwas schiefgeht", text)
        self.assertIn("entfernen", text)


class TestMeldungenWerdenTickets(unittest.TestCase):
    """Die Plattform-Hälfte: abholen, Ticket anlegen, bestätigen."""

    @classmethod
    def setUpClass(cls):
        frische_datenbank()
        _NachgebauterWorker.meldungen = []
        _NachgebauterWorker.bewerbungen = []
        _NachgebauterWorker.nachrichten = []
        _NachgebauterWorker.bestaetigt = []
        cls.server = HTTPServer(("127.0.0.1", 0), _NachgebauterWorker)
        cls.faden = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.faden.start()
        cls.adresse = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.vorher = (cfg.AUSFALL_WORKER_URL, cfg.AUSFALL_SCHLUESSEL)
        cfg.AUSFALL_WORKER_URL = cls.adresse
        cfg.AUSFALL_SCHLUESSEL = SCHLUESSEL

    @classmethod
    def tearDownClass(cls):
        cfg.AUSFALL_WORKER_URL, cfg.AUSFALL_SCHLUESSEL = cls.vorher
        cls.server.shutdown()

    def setUp(self):
        _NachgebauterWorker.meldungen = []
        _NachgebauterWorker.bewerbungen = []
        _NachgebauterWorker.nachrichten = []
        _NachgebauterWorker.bestaetigt = []
        db = SessionLocal()
        db.query(SupportTicket).filter(
            SupportTicket.subject.like("Ausfallmeldung%")).delete(
                synchronize_session=False)
        db.commit()
        db.close()

    def _tickets(self):
        db = SessionLocal()
        try:
            return (db.query(SupportTicket)
                    .filter(SupportTicket.subject.like("Ausfallmeldung%"))
                    .order_by(SupportTicket.id).all())
        finally:
            db.close()

    def test_ohne_einrichtung_passiert_nichts(self):
        cfg.AUSFALL_WORKER_URL = ""
        try:
            self.assertFalse(ausfallmeldungen.eingerichtet())
            bilanz = ausfallmeldungen.abholen()
            self.assertEqual(bilanz["neu"], 0)
            self.assertEqual(bilanz["bewerbungen"], 0)
            self.assertEqual(bilanz["fehler"], "")
        finally:
            cfg.AUSFALL_WORKER_URL = self.adresse

    def test_aus_einer_meldung_wird_ein_ticket(self):
        _NachgebauterWorker.meldungen = [{
            "kennung": "meldung:2026-08-18T10:00:00.000Z-abcd1234",
            "text": "Ich wollte meine Aufgaben ansehen. Umlaute: äöüß",
            "name": "Max Muster", "kontakt": "", "lage": "/dashboard/aufgaben",
            "seite": "mvlg-wag.de", "zeitpunkt": "2026-08-18T10:00:00.000Z",
        }]
        bilanz = ausfallmeldungen.abholen()
        self.assertEqual(bilanz["neu"], 1, bilanz)
        tickets = self._tickets()
        self.assertEqual(len(tickets), 1)
        self.assertIn("Max Muster", tickets[0].subject)
        self.assertIn("äöüß", tickets[0].message)
        self.assertIn("/dashboard/aufgaben", tickets[0].message)
        self.assertEqual(tickets[0].status, "offen")

    def test_erst_bestaetigen_wenn_das_ticket_steht(self):
        """Andersherum wäre eine Meldung verloren, wenn die Plattform zwischen
        Abholen und Speichern abstürzt - und zwar unbemerkt."""
        _NachgebauterWorker.meldungen = [{
            "kennung": "meldung:2026-08-18T11:00:00.000Z-11111111",
            "text": "Geht nicht", "name": "Lena",
        }]
        ausfallmeldungen.abholen()
        self.assertEqual(_NachgebauterWorker.bestaetigt,
                         ["meldung:2026-08-18T11:00:00.000Z-11111111"])

    def test_dieselbe_meldung_wird_kein_zweites_ticket(self):
        """Schlägt das Bestätigen fehl, kommt die Meldung wieder - dann darf
        sie nicht ein zweites Ticket erzeugen."""
        _NachgebauterWorker.meldungen = [{
            "kennung": "meldung:2026-08-18T12:00:00.000Z-22222222",
            "text": "Nichts geht", "name": "Jonas",
        }]
        erst = ausfallmeldungen.abholen()
        zweit = ausfallmeldungen.abholen()
        self.assertEqual(erst["neu"], 1)
        self.assertEqual(zweit["neu"], 0)
        self.assertEqual(zweit["doppelt"], 1)
        self.assertEqual(len(self._tickets()), 1)

    def test_bekannte_mailadresse_macht_das_ticket_persoenlich(self):
        db = SessionLocal()
        person = db.query(User).filter(User.status == "aktiv").first()
        post, name = person.email, person.name
        db.close()
        _NachgebauterWorker.meldungen = [{
            "kennung": "meldung:2026-08-18T13:00:00.000Z-33333333",
            "text": "Komme nicht drauf", "name": "egal", "kontakt": post,
        }]
        ausfallmeldungen.abholen()
        ticket = self._tickets()[0]
        db = SessionLocal()
        try:
            self.assertEqual(ticket.user_id,
                             db.query(User).filter(User.email == post).first().id)
        finally:
            db.close()
        self.assertIn(name, ticket.subject)
        self.assertNotIn("kam anonym", ticket.message)

    def test_ein_erfundener_name_bekommt_kein_fremdes_ticket(self):
        """Ein Name aus einem offenen Feld beweist nichts."""
        db = SessionLocal()
        opfer = db.query(User).filter(User.status == "aktiv").first()
        name = opfer.name
        db.close()
        _NachgebauterWorker.meldungen = [{
            "kennung": "meldung:2026-08-18T14:00:00.000Z-44444444",
            "text": "Ich bin es wirklich", "name": name,
            "kontakt": "niemand@example.invalid",
        }]
        ausfallmeldungen.abholen()
        ticket = self._tickets()[0]
        self.assertIn("kam anonym", ticket.message)

    def test_ein_unerreichbares_auffangnetz_ist_kein_absturz(self):
        cfg.AUSFALL_WORKER_URL = "http://127.0.0.1:1"
        try:
            bilanz = ausfallmeldungen.abholen()
        finally:
            cfg.AUSFALL_WORKER_URL = self.adresse
        self.assertEqual(bilanz["neu"], 0)
        self.assertTrue(bilanz["fehler"])

    def test_falscher_schluessel_wird_gemeldet_nicht_verschluckt(self):
        cfg.AUSFALL_SCHLUESSEL = "falsch"
        try:
            bilanz = ausfallmeldungen.abholen()
        finally:
            cfg.AUSFALL_SCHLUESSEL = SCHLUESSEL
        self.assertIn("403", bilanz["fehler"])


class TestBewerbungenAusDerAusfallzeit(unittest.TestCase):
    """Der wichtigste Weg: Eine Bewerbung darf nie verloren gehen.

    Ein Interessent, der zufällig in einen Ausfall gerät, kommt nicht wieder -
    und niemand erfährt je davon. Deshalb nimmt das Auffangnetz Bewerbungen
    entgegen, und hier werden sie zu echten Einträgen.
    """

    @classmethod
    def setUpClass(cls):
        frische_datenbank()
        cls.server = HTTPServer(("127.0.0.1", 0), _NachgebauterWorker)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.adresse = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.vorher = (cfg.AUSFALL_WORKER_URL, cfg.AUSFALL_SCHLUESSEL)
        cfg.AUSFALL_WORKER_URL = cls.adresse
        cfg.AUSFALL_SCHLUESSEL = SCHLUESSEL

    @classmethod
    def tearDownClass(cls):
        cfg.AUSFALL_WORKER_URL, cfg.AUSFALL_SCHLUESSEL = cls.vorher
        cls.server.shutdown()
        cls._bewerbungen_weg()

    @staticmethod
    def _bewerbungen_weg():
        db = SessionLocal()
        db.query(Application).delete(synchronize_session=False)
        db.commit()
        db.close()

    def setUp(self):
        _NachgebauterWorker.meldungen = []
        _NachgebauterWorker.bewerbungen = []
        _NachgebauterWorker.nachrichten = []
        _NachgebauterWorker.bestaetigt = []
        # Auch HINTERHER aufraeumen, nicht nur davor: Die eingespielten
        # Bewerbungen tragen ein festes Datum. Sobald das alt genug ist,
        # haelt der Hinweisdienst sie fuer liegengeblieben - und ein Test
        # in einer ganz anderen Datei faellt um, ohne selbst etwas falsch
        # gemacht zu haben.
        self._bewerbungen_weg()

    def _roh(self, **zusatz):
        daten = {
            "kennung": "bewerbung:2026-08-18T09:00:00.000Z-aaaa1111",
            "vorname": "Mara", "nachname": "Winkler", "klasse": "11",
            "abteilung": "tech", "email": "mara@example.org",
            "telefonnummer": "0163 1234567",
            "motivation": "Ich will endlich verstehen, wie das mit der Börse "
                          "wirklich funktioniert.",
            "interessen": "Börse, Gründen", "vorwissen": "Keines",
            "zeitpunkt": "2026-08-18T09:00:00.000Z",
        }
        daten.update(zusatz)
        return daten

    def _bewerbungen(self):
        db = SessionLocal()
        try:
            return db.query(Application).order_by(Application.id).all()
        finally:
            db.close()

    def test_aus_der_hinterlegten_wird_eine_echte_bewerbung(self):
        _NachgebauterWorker.bewerbungen = [self._roh()]
        bilanz = ausfallmeldungen.abholen()
        self.assertEqual(bilanz["bewerbungen"], 1, bilanz)
        alle = self._bewerbungen()
        self.assertEqual(len(alle), 1)
        self.assertEqual(alle[0].vorname, "Mara")
        self.assertEqual(alle[0].email, "mara@example.org")
        self.assertEqual(alle[0].department, "tech")
        self.assertEqual(alle[0].status, "neu")
        self.assertIn("Börse", alle[0].motivation)

    def test_der_zeitpunkt_kommt_aus_der_bewerbung(self):
        """Sonst begänne die Erinnerung „liegt seit drei Tagen" zu spät."""
        _NachgebauterWorker.bewerbungen = [self._roh()]
        ausfallmeldungen.abholen()
        self.assertEqual(self._bewerbungen()[0].created_at.date().isoformat(),
                         "2026-08-18")

    def test_die_telefonnummer_wird_in_form_gebracht(self):
        _NachgebauterWorker.bewerbungen = [self._roh(telefonnummer="1516 1234567")]
        ausfallmeldungen.abholen()
        self.assertTrue(self._bewerbungen()[0].telefonnummer)

    def test_dem_worker_wird_nichts_geglaubt(self):
        """Er steht im offenen Netz. Alles wird hier noch einmal geprüft."""
        for name, kaputt in (
            ("keine E-Mail", {"email": "unsinn"}),
            ("fremde Abteilung", {"abteilung": "vorstand"}),
            ("geschützte Abteilung", {"abteilung": "exekutive"}),
            ("Pflichtfeld leer", {"vorname": ""}),
        ):
            with self.subTest(name):
                _NachgebauterWorker.bewerbungen = [self._roh(**kaputt)]
                ausfallmeldungen.abholen()
                self.assertEqual(self._bewerbungen(), [], name)

    def test_unbrauchbares_wird_weggeworfen_statt_liegenzubleiben(self):
        """Sonst wird sie vier Wochen lang bei jedem Lauf neu geprüft."""
        _NachgebauterWorker.bewerbungen = [self._roh(email="unsinn")]
        ausfallmeldungen.abholen()
        self.assertIn("bewerbung:2026-08-18T09:00:00.000Z-aaaa1111",
                      _NachgebauterWorker.bestaetigt)

    def test_erst_bestaetigen_wenn_sie_eingetragen_ist(self):
        _NachgebauterWorker.bewerbungen = [self._roh()]
        ausfallmeldungen.abholen()
        self.assertEqual(_NachgebauterWorker.bestaetigt,
                         ["bewerbung:2026-08-18T09:00:00.000Z-aaaa1111"])

    def test_zweimal_beworben_gibt_einen_eintrag(self):
        _NachgebauterWorker.bewerbungen = [
            self._roh(),
            self._roh(kennung="bewerbung:2026-08-18T09:05:00.000Z-bbbb2222"),
        ]
        bilanz = ausfallmeldungen.abholen()
        self.assertEqual(bilanz["bewerbungen"], 1)
        self.assertEqual(bilanz["bewerbungen_doppelt"], 1)
        self.assertEqual(len(self._bewerbungen()), 1)

    def test_meldungen_und_bewerbungen_kommen_zusammen_herein(self):
        _NachgebauterWorker.meldungen = [{
            "kennung": "meldung:2026-08-18T09:00:00.000Z-cccc3333",
            "text": "Komme nicht drauf", "name": "Tom"}]
        _NachgebauterWorker.bewerbungen = [self._roh()]
        bilanz = ausfallmeldungen.abholen()
        self.assertEqual((bilanz["neu"], bilanz["bewerbungen"]), (1, 1), bilanz)

    def test_die_alte_form_bricht_nichts(self):
        """Ein Worker, der noch nicht neu ausgerollt ist, liefert eine blanke
        Liste. Das darf die Abholung nicht anhalten."""
        class _Alt(_NachgebauterWorker):
            def do_GET(self):
                koerper = json.dumps([{
                    "kennung": "meldung:alt", "text": "Alte Form"}]).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(koerper)))
                self.end_headers()
                self.wfile.write(koerper)
        server = HTTPServer(("127.0.0.1", 0), _Alt)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        cfg.AUSFALL_WORKER_URL = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            bilanz = ausfallmeldungen.abholen()
            self.assertEqual(bilanz["neu"], 1, bilanz)
        finally:
            cfg.AUSFALL_WORKER_URL = self.adresse
            server.shutdown()


class TestNachrichtenAusDerAusfallzeit(unittest.TestCase):
    """Was über das Kontaktformular der Notfassung hereinkam.

    Seit die Notfassung aussieht wie die richtige Startseite, steht dort auch
    das Kontaktformular - und wer es ausfüllt, erwartet zu Recht eine Antwort.
    Aus den Angaben muss deshalb dasselbe werden wie im Normalbetrieb: eine
    Anfrage im Dashboard, die sich per E-Mail beantworten lässt.
    """

    @classmethod
    def setUpClass(cls):
        frische_datenbank()
        cls.server = HTTPServer(("127.0.0.1", 0), _NachgebauterWorker)
        cls.faden = threading.Thread(target=cls.server.serve_forever,
                                     daemon=True)
        cls.faden.start()
        cls.adresse = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.vorher = (cfg.AUSFALL_WORKER_URL, cfg.AUSFALL_SCHLUESSEL)
        cfg.AUSFALL_WORKER_URL = cls.adresse
        cfg.AUSFALL_SCHLUESSEL = SCHLUESSEL

    @classmethod
    def tearDownClass(cls):
        cfg.AUSFALL_WORKER_URL, cfg.AUSFALL_SCHLUESSEL = cls.vorher
        cls.server.shutdown()

    def setUp(self):
        _NachgebauterWorker.meldungen = []
        _NachgebauterWorker.bewerbungen = []
        _NachgebauterWorker.nachrichten = []
        _NachgebauterWorker.bestaetigt = []
        db = SessionLocal()
        db.query(ContactMessage).delete()
        db.commit()
        db.close()

    def _anfragen(self):
        db = SessionLocal()
        try:
            return db.query(ContactMessage).order_by(ContactMessage.id).all()
        finally:
            db.close()

    def _hinlegen(self, **zusatz):
        eintrag = {
            "kennung": "nachricht:2026-08-27T09:00:00.000Z-abcd1234",
            "name": "Maria Musterfrau", "email": "maria@example.org",
            "nachricht": "Kann mein Kind auch in der neunten Klasse "
                         "mitmachen? Umlaute: äöüß",
            "zeitpunkt": "2026-08-27T09:00:00.000Z",
        }
        eintrag.update(zusatz)
        _NachgebauterWorker.nachrichten = [eintrag]

    def test_aus_einer_nachricht_wird_eine_anfrage(self):
        self._hinlegen()
        bilanz = ausfallmeldungen.abholen()
        self.assertEqual(bilanz["nachrichten"], 1, bilanz)
        anfragen = self._anfragen()
        self.assertEqual(len(anfragen), 1)
        self.assertEqual(anfragen[0].name, "Maria Musterfrau")
        self.assertEqual(anfragen[0].email, "maria@example.org")
        self.assertIn("äöüß", anfragen[0].message)
        # Noch unbeantwortet - sie steht also in der offenen Liste.
        self.assertIsNone(anfragen[0].reply)

    def test_der_zeitpunkt_kommt_aus_der_nachricht(self):
        """Sonst stünde dort der Moment, in dem der Rechner wieder anging -
        und niemand sähe, wie lange jemand schon auf Antwort wartet."""
        self._hinlegen()
        ausfallmeldungen.abholen()
        self.assertEqual(self._anfragen()[0].created_at.strftime("%Y-%m-%d"),
                         "2026-08-27")

    def test_unbrauchbares_wird_weggeworfen_statt_liegenzubleiben(self):
        self._hinlegen(email="keine-adresse")
        bilanz = ausfallmeldungen.abholen()
        self.assertEqual(bilanz["nachrichten"], 0)
        self.assertEqual(self._anfragen(), [])
        # Trotzdem bestätigt - sonst wird es bei jedem Lauf neu geprüft.
        self.assertEqual(len(_NachgebauterWorker.bestaetigt), 1)

    def test_zweimal_abholen_legt_nicht_zweimal_an(self):
        """Bestätigt der Worker nicht, kommt dieselbe Nachricht wieder. Zwei
        Einträge hießen: Der Vorstand antwortet zweimal auf dasselbe."""
        self._hinlegen()
        ausfallmeldungen.abholen()
        self._hinlegen()
        zweit = ausfallmeldungen.abholen()
        self.assertEqual(zweit["nachrichten"], 0, zweit)
        self.assertEqual(len(self._anfragen()), 1)


class TestAnbindungAnDenPlaner(unittest.TestCase):

    def test_der_faden_haengt_am_eingerichtet_sein(self):
        """Ohne Auffangnetz soll kein Faden laufen, der alle fünf Minuten
        vergeblich ins Netz greift."""
        quelle = (WURZEL / "kern/planer.py").read_text(encoding="utf-8")
        self.assertIn("ausfallmeldungen.eingerichtet()", quelle)
        self.assertIn('_faden("ausfallmeldungen"', quelle)

    def test_beim_start_wird_sofort_nachgesehen(self):
        """Der häufigste Fall ist genau der: Rechner war aus, jemand hat es
        gemeldet, jetzt läuft es wieder."""
        quelle = (WURZEL / "kern/planer.py").read_text(encoding="utf-8")
        i = quelle.index("def _ausfallmeldungen")
        block = quelle[i:i + 1400]
        self.assertIn("zuerst", block)


if __name__ == "__main__":
    unittest.main()
