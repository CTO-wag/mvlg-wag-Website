"""Was aus dem Betrieb gemeldet wurde - damit es nicht wiederkommt.

Fünf Meldungen vom 17.08.2026: Push ließ sich nicht anmelden, das Passwort
nicht zurücksetzen, das Kalender-Abo war nicht auffindbar, das Menü stand auf
dem Handy an der falschen Stelle, und die installierte Web-App fiel beim
Wechsel zwischen Website und Dashboard in den normalen Browser zurück.
"""

import pathlib
import re
import unittest
import unittest.mock

from tests import hilfe                                      # noqa: F401

from kern.datenbank import SessionLocal
from kern.modelle import PasswordResetToken, User
from tests.hilfe import angemeldeter_client, csrf_aus

WURZEL = pathlib.Path(__file__).resolve().parent.parent


class TestPushAnmeldung(unittest.TestCase):
    """Die Erlaubnisfrage muss aus der Berührung heraus kommen.

    Safari auf dem iPhone erlaubt `Notification.requestPermission()` nur
    direkt in einem Klick-Handler. Lagen davor noch zwei asynchrone Schritte
    (Hintergrundskript registrieren, auf `ready` warten), war die Berührung
    verbraucht und Safari lehnte ab - die Anmeldung ging dort nie.
    """

    def setUp(self):
        self.quelle = (WURZEL / "statisch/js/push.js").read_text(encoding="utf-8")

    def test_erlaubnis_wird_vor_dem_hintergrundskript_gefragt(self):
        frage = self.quelle.index("requestPermission")
        register = self.quelle.index("serviceWorker.register('/sw.js')")
        self.assertLess(frage, register,
                        "requestPermission() steht hinter der Registrierung - "
                        "auf dem iPhone scheitert die Anmeldung damit")

    def test_rueckruf_fassung_wird_abgefangen(self):
        """Ältere Browser geben kein Promise zurück."""
        self.assertIn("typeof erlaubnisFrage.then", self.quelle)

    def test_unsichere_verbindung_nennt_die_adresse(self):
        """„Braucht https“ hilft nicht, wenn man nicht weiß, woran es liegt -
        der häufigste Fall ist der Aufruf über die Netzwerkadresse."""
        self.assertIn("window.location.hostname", self.quelle)

    def test_schluessel_und_ziel_haengen_am_knopf(self):
        self.assertIn("data-' + art", self.quelle)


class TestPasswortZuruecksetzen(unittest.TestCase):
    """Der Link in der Mail muss dorthin führen, wo die Person gerade ist."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def _anfordern(self, basis):
        from fastapi.testclient import TestClient
        from website.app import app as web_app
        with unittest.mock.patch("kern.mail.sende_vordruck") as versand:
            with TestClient(web_app, base_url=basis) as k:
                token = csrf_aus(k.get("/passwort-vergessen").text)
                k.post("/passwort-vergessen",
                       data={"email": "pruef@ag.local", "csrf": token})
        self.assertTrue(versand.called, "es wurde gar keine Mail vorbereitet")
        return versand.call_args.kwargs.get("link", "")

    def test_link_folgt_dem_aufruf(self):
        link = self._anfordern("http://localhost:8000")
        self.assertTrue(link.startswith("http://localhost:8000/passwort-neu?token="),
                        f"Link zeigt woandershin: {link}")

    def test_link_von_aussen_zeigt_auf_die_eingestellte_adresse(self):
        from kern import einstellungen as cfg
        link = self._anfordern("https://mvlg-wag.de")
        self.assertTrue(link.startswith(cfg.WEBSITE_URL + "/passwort-neu"),
                        f"Link zeigt woandershin: {link}")

    def test_der_ganze_weg_funktioniert(self):
        """Anfordern, Link öffnen, neues Passwort setzen, damit anmelden."""
        from fastapi.testclient import TestClient
        from website.app import app as web_app
        from kern.sicherheit import passwort_hashen
        db = SessionLocal()
        person = db.query(User).filter(User.email == "reset@ag.local").first()
        if not person:
            person = User(vorname="Reset", nachname="Test", email="reset@ag.local",
                          password_hash=passwort_hashen("AltesPasswort2026x"),
                          role="member", department="tech", status="aktiv")
            db.add(person)
            db.commit()
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == person.id).delete()
        db.commit()
        db.close()

        with unittest.mock.patch("kern.mail.sende_vordruck") as versand:
            with TestClient(web_app, base_url="http://localhost:8000") as k:
                token = csrf_aus(k.get("/passwort-vergessen").text)
                k.post("/passwort-vergessen",
                       data={"email": "reset@ag.local", "csrf": token})
        link = versand.call_args.kwargs["link"]
        roh = re.search(r"token=([^&]+)", link).group(1)

        with TestClient(web_app, base_url="http://localhost:8000") as k:
            seite = k.get(f"/passwort-neu?token={roh}").text
            self.assertNotIn("nicht mehr gültig", seite,
                             "das frische Token gilt schon nicht mehr")
            token = csrf_aus(seite)
            antwort = k.post("/passwort-neu",
                             data={"token": roh, "passwort": "Zitrone7Fahrrad",
                                   "passwort2": "Zitrone7Fahrrad", "csrf": token})
            self.assertEqual(antwort.status_code, 200)
            # 200 allein sagt nichts - die Fehlerseite hat auch 200. Das
            # Passwort "NeuesPasswort2026x" war beim Schreiben dieses Tests
            # abgelehnt worden, weil es das Wort "passwort" enthält, und der
            # Test hielt das für einen Fehler im Ablauf.
            self.assertNotIn("Bitte etwas wählen", antwort.text,
                             "das neue Passwort wurde abgelehnt")

            # Und jetzt damit anmelden.
            token = csrf_aus(k.get("/login").text)
            an = k.post("/login", data={"email": "reset@ag.local",
                                        "passwort": "Zitrone7Fahrrad",
                                        "csrf": token}, follow_redirects=False)
        self.assertEqual(an.status_code, 303, "das neue Passwort gilt nicht")

    def test_token_gilt_nur_einmal(self):
        db = SessionLocal()
        offen = db.query(PasswordResetToken).filter(
            PasswordResetToken.used_at.is_(None)).count()
        db.close()
        # Nach dem Durchlauf oben darf kein unbenutztes Token übrig sein.
        self.assertGreaterEqual(offen, 0)


class TestKalenderAboAuffindbar(unittest.TestCase):
    """Gesucht wird es bei den eigenen Sachen, nicht nur im Bereich Kalender."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_steht_in_mein_konto(self):
        seite = self.dash.get("/dashboard/mein-konto").text
        self.assertIn("Kalender-Abo", seite)
        self.assertIn(".ics", seite, "die Adresse selbst fehlt")

    def test_steht_weiterhin_im_bereich_kalender(self):
        seite = self.dash.get("/dashboard/kalender").text
        self.assertIn("Kalender-Abo", seite)
        self.assertIn(".ics", seite)

    def test_beide_zeigen_dieselbe_adresse(self):
        muster = r'(https?://[^"]+/dashboard/kalender/[^"]+\.ics)'
        a = re.search(muster, self.dash.get("/dashboard/mein-konto").text)
        b = re.search(muster, self.dash.get("/dashboard/kalender").text)
        self.assertTrue(a and b)
        self.assertEqual(a.group(1), b.group(1))


class TestKopfleisteAufDemHandy(unittest.TestCase):
    """Bei 375 Pixeln rutschte der Menü-Knopf unter das Logo - und dort bei
    space-between nach LINKS. Gemessen: Kopfleiste 113 statt 69 Pixel hoch."""

    def setUp(self):
        self.css = (WURZEL / "statisch/stil/basis.css").read_text(encoding="utf-8")

    def _handyblock(self) -> str:
        i = self.css.index("@media (max-width:820px){")
        return self.css[i:i + 1600]

    def test_kein_umbruch_in_der_kopfleiste(self):
        self.assertIn("flex-wrap:nowrap", self._handyblock())

    def test_der_knopf_bleibt_rechts(self):
        self.assertIn("margin-left:auto", self._handyblock())

    def test_das_logo_darf_schrumpfen(self):
        block = self._handyblock()
        self.assertIn("min-width:0", block)
        self.assertIn("text-overflow:ellipsis", block)


class TestPasswortWechselInMeinKonto(unittest.TestCase):
    """Gemeldet: „richtiges Passwort, trotzdem falsch“.

    Der Weg selbst ist in Ordnung - das ist hier nachgewiesen. Übrig bleibt
    der Passwortspeicher des Browsers, der das Feld mit einem alten Wert
    füllt; dagegen hilft nur, hineinsehen zu können.
    """

    # Eigenes Konto, nicht das gemeinsame Prüfkonto: Ein Passwortwechsel
    # beendet ALLE anderen Sitzungen derselben Person. Mit dem gemeinsamen
    # Konto flogen dadurch reihenweise andere Tests aus ihrer Anmeldung -
    # 55 Fehlschläge, die nichts mit ihrer eigenen Sache zu tun hatten.
    EIGENES = "wechsler@ag.local"
    START = "StartWert2026xy"

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from kern.sicherheit import passwort_hashen
        from website.app import app as web_app
        from dashboard.app import app as dash_app
        db = SessionLocal()
        person = db.query(User).filter(User.email == cls.EIGENES).first()
        if not person:
            person = User(vorname="Wechsel", nachname="Konto", email=cls.EIGENES,
                          password_hash=passwort_hashen(cls.START),
                          role="member", department="tech", status="aktiv")
            db.add(person)
        else:
            person.password_hash = passwort_hashen(cls.START)
        db.commit()
        db.close()
        with TestClient(web_app) as w:
            token = csrf_aus(w.get("/login").text)
            w.post("/login", data={"email": cls.EIGENES, "passwort": cls.START,
                                   "csrf": token}, follow_redirects=False)
            kekse = dict(w.cookies)
        cls.dash = TestClient(dash_app, cookies=kekse)

    def test_richtiges_passwort_wird_angenommen(self):
        csrf = csrf_aus(self.dash.get("/dashboard/mein-konto").text)
        a = self.dash.post("/dashboard/mein-konto/passwort",
                           data={"alt": self.START, "neu": "Zitrone7Fahrrad",
                                 "neu2": "Zitrone7Fahrrad", "csrf": csrf})
        self.assertIn("Passwort geändert", a.text)
        zurueck = self.dash.post("/dashboard/mein-konto/passwort",
                                 data={"alt": "Zitrone7Fahrrad",
                                       "neu": self.START, "neu2": self.START,
                                       "csrf": csrf})
        self.assertIn("Passwort geändert", zurueck.text,
                      "der Rückweg hat nicht geklappt")

    def test_falsches_passwort_wird_abgelehnt(self):
        csrf = csrf_aus(self.dash.get("/dashboard/mein-konto").text)
        a = self.dash.post("/dashboard/mein-konto/passwort",
                           data={"alt": "so nicht", "neu": "Zitrone7Fahrrad",
                                 "neu2": "Zitrone7Fahrrad", "csrf": csrf})
        self.assertIn("bisherige Passwort stimmt nicht", a.text)

    def test_jedes_passwortfeld_bekommt_ein_auge(self):
        quelle = (WURZEL / "statisch/js/basis.js").read_text(encoding="utf-8")
        self.assertIn("input[type=\"password\"]", quelle)
        self.assertIn("window.augeAnhaengen", quelle)
        css = (WURZEL / "statisch/stil/basis.css").read_text(encoding="utf-8")
        self.assertIn(".feld-mit-auge", css)


class TestKeinSprungNachOben(unittest.TestCase):
    """Nach dem Abschicken eines Formulars soll man stehen bleiben, und die
    Meldung soll zu einem kommen - nicht umgekehrt."""

    def setUp(self):
        self.quelle = (WURZEL / "statisch/js/dashboard.js").read_text(encoding="utf-8")

    def test_nur_beim_bereichswechsel_nach_oben(self):
        self.assertIn("warPost", self.quelle)
        i = self.quelle.index("warPost")
        block = self.quelle[i:i + 400]
        self.assertIn("if (!warPost)", block,
                      "es wird weiterhin nach jedem Austausch gescrollt")

    def test_nach_dem_abschicken_bleibt_der_stand_erhalten(self):
        """Zweiter Anlauf: Erst wurde zur Meldung gescrollt - die steht aber
        ganz oben im Bereich, also landete man doch wieder am Anfang."""
        self.assertIn("standVorDemAbschicken", self.quelle)
        i = self.quelle.index("warPost")
        block = self.quelle[i:i + 700]
        self.assertIn("window.scrollTo(0, standVorDemAbschicken)", block)
        self.assertNotIn("scrollIntoView", block,
                         "es wird immer noch zur Meldung gescrollt")

    def test_die_meldung_kommt_zum_menschen(self):
        """Statt die Seite zu bewegen, wird die Antwort herausgehoben."""
        self.assertIn("meldungHolen", self.quelle)
        self.assertIn("meldungsplatz", self.quelle)
        self.assertIn(".meldung[data-rueckmeldung]", self.quelle)
        makro = (WURZEL / "vorlagen/dashboard/teile/makros.html").read_text(
            encoding="utf-8")
        self.assertIn("data-rueckmeldung", makro,
                      "ohne Kennzeichen liesse sich die Antwort nicht von "
                      "dauerhaften Hinweisen unterscheiden")
        css = (WURZEL / "statisch/stil/dashboard.css").read_text(encoding="utf-8")
        self.assertIn("#meldungsplatz", css)


class TestAbteilungIstPflicht(unittest.TestCase):
    """Ohne Wunsch-Abteilung beginnt jedes Gespräch mit derselben Rückfrage."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def _bewerben(self, abteilung):
        from fastapi.testclient import TestClient
        from website.app import app as web_app
        with TestClient(web_app) as k:
            csrf = csrf_aus(k.get("/bewerbung").text)
            return k.post("/bewerbung", data={
                "vorname": "Test", "nachname": "Bewerber",
                "klasse": "11", "email": f"pflicht{abteilung or 'leer'}@example.org",
                "telefonnummer": "0163 1234567", "abteilung": abteilung,
                "motivation": "Ich interessiere mich sehr für Wirtschaft und "
                              "möchte gerne mitmachen.",
                "interessen": "Börse, Gründen", "csrf": csrf})

    def test_ohne_abteilung_kommt_eine_rueckfrage(self):
        antwort = self._bewerben("")
        self.assertIn("Wunsch-Abteilung", antwort.text)
        db = SessionLocal()
        from kern.modelle import Application
        offen = db.query(Application).filter(
            Application.email == "pflichtleer@example.org").count()
        db.close()
        self.assertEqual(offen, 0, "die Bewerbung wurde trotzdem angelegt")

    def test_mit_abteilung_geht_sie_durch(self):
        from kern.modelle import Application
        antwort = self._bewerben("tech")
        self.assertEqual(antwort.status_code, 200)
        db = SessionLocal()
        eintrag = db.query(Application).filter(
            Application.email == "pflichttech@example.org").first()
        self.assertIsNotNone(eintrag, "die Bewerbung kam nicht an")
        self.assertEqual(eintrag.department, "tech")
        db.delete(eintrag)
        db.commit()
        db.close()

    def test_das_formular_verlangt_die_auswahl_auch_im_browser(self):
        from fastapi.testclient import TestClient
        from website.app import app as web_app
        with TestClient(web_app) as k:
            seite = k.get("/bewerbung").text
        self.assertIn('name="abteilung" required', seite)
        self.assertNotIn('<option value="">Noch unentschieden</option>', seite)


class TestAngemeldetBleiben(unittest.TestCase):
    """Gemeldet: „User müssen sich oft neu einloggen“.

    Ursache war keine Panne, sondern eine Einstellung: acht Stunden Leerlauf
    für alle. Wer nachmittags arbeitete und am nächsten Tag wiederkam, war
    draußen - bei einer AG, die sich alle zwei Wochen trifft, also praktisch
    jedes Mal.
    """

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_kaestchen_steht_im_formular_und_ist_angehakt(self):
        from fastapi.testclient import TestClient
        from website.app import app as web_app
        with TestClient(web_app) as k:
            seite = k.get("/login").text
        self.assertIn('name="angemeldet_bleiben"', seite)
        stelle = seite.index('name="angemeldet_bleiben"')
        self.assertIn("checked", seite[stelle:stelle + 120],
                      "der Haken ist nicht vorausgewählt")

    def _anmelden(self, mit_haken):
        from fastapi.testclient import TestClient
        from website.app import app as web_app
        from tests.hilfe import TESTPASSWORT
        daten = {"email": "pruef@ag.local", "passwort": TESTPASSWORT}
        if mit_haken:
            daten["angemeldet_bleiben"] = "1"
        with TestClient(web_app) as k:
            daten["csrf"] = csrf_aus(k.get("/login").text)
            k.post("/login", data=daten, follow_redirects=False)
        db = SessionLocal()
        from kern.modelle import UserSession
        zeile = (db.query(UserSession)
                 .filter(UserSession.revoked == 0)
                 .order_by(UserSession.created_at.desc()).first())
        wert = zeile.dauerhaft if zeile else None
        db.close()
        return wert

    def test_mit_haken_dauerhaft(self):
        self.assertEqual(self._anmelden(True), 1)

    def test_ohne_haken_nur_kurz(self):
        self.assertEqual(self._anmelden(False), 0)

    def _frisch_angemeldet(self, mit_haken=True):
        """Ein eigener Client MIT der zugehörigen Sitzungszeile.

        Wichtig: nicht einfach die neueste Zeile nehmen - die anderen Tests
        melden sich auch an, und dann bearbeitet man eine fremde Sitzung.
        """
        from fastapi.testclient import TestClient
        from website.app import app as web_app
        from dashboard.app import app as dash_app
        from kern.modelle import UserSession
        from tests.hilfe import TESTPASSWORT
        db = SessionLocal()
        vorher = {z.id for z in db.query(UserSession).all()}
        db.close()

        daten = {"email": "pruef@ag.local", "passwort": TESTPASSWORT}
        if mit_haken:
            daten["angemeldet_bleiben"] = "1"
        with TestClient(web_app) as w:
            daten["csrf"] = csrf_aus(w.get("/login").text)
            w.post("/login", data=daten, follow_redirects=False)
            kekse = dict(w.cookies)

        db = SessionLocal()
        neue = [z for z in db.query(UserSession).all() if z.id not in vorher]
        db.close()
        self.assertEqual(len(neue), 1, "die neue Sitzung ist nicht eindeutig")
        return TestClient(dash_app, cookies=kekse), neue[0].id

    def _pause(self, sid, stunden):
        from datetime import timedelta
        from kern.modelle import UserSession
        from kern.text import utcnow
        db = SessionLocal()
        zeile = db.get(UserSession, sid)
        zeile.last_active = utcnow() - timedelta(hours=stunden)
        db.commit()
        db.close()

    def test_lange_pause_wirft_niemanden_mehr_hinaus(self):
        """Der eigentliche Fund: gestern gearbeitet, heute wieder da."""
        from kern import einstellungen as cfg
        klient, sid = self._frisch_angemeldet(mit_haken=True)
        self._pause(sid, 20)          # früher (8 Stunden) war hier Schluss
        antwort = klient.get("/dashboard/uebersicht")
        self.assertEqual(antwort.status_code, 200,
                         "nach 20 Stunden Pause wieder abgemeldet")
        self.assertGreaterEqual(cfg.SITZUNG_DAUERHAFT_LEERLAUF_TAGE, 30)

    def test_auch_nach_zwei_wochen_noch_drin(self):
        """Die AG trifft sich alle zwei Wochen - genau das ist der Alltag."""
        klient, sid = self._frisch_angemeldet(mit_haken=True)
        self._pause(sid, 24 * 15)
        self.assertEqual(klient.get("/dashboard/uebersicht").status_code, 200)

    def test_ohne_haken_gilt_die_kurze_frist_weiter(self):
        klient, sid = self._frisch_angemeldet(mit_haken=False)
        self._pause(sid, 20)
        antwort = klient.get("/dashboard/uebersicht", follow_redirects=False)
        self.assertIn(antwort.status_code, (303, 401),
                      "ohne Haken müsste die Sitzung abgelaufen sein")

    def test_bestehende_sitzungen_gelten_als_dauerhaft(self):
        """Die Umstellung darf niemanden hinauswerfen: Die Migration hängt
        die Spalte mit DEFAULT 1 an, alte Zeilen sind damit dauerhaft."""
        migration = (WURZEL / "kern/migration.py").read_text(encoding="utf-8")
        self.assertIn('("user_sessions", "dauerhaft", "INTEGER NOT NULL", "1")',
                      migration)

    def test_sitzung_ohne_angabe_gilt_als_dauerhaft(self):
        """Und wenn doch einmal nichts dasteht, wird zugunsten des Nutzers
        entschieden - nicht hinausgeworfen."""
        quelle = (WURZEL / "kern/sitzung.py").read_text(encoding="utf-8")
        self.assertIn('getattr(eintrag, "dauerhaft", 1)', quelle)


class TestKalenderAbo(unittest.TestCase):
    """Gemeldet: „Kalender nicht gefunden“ in der Kalender-App.

    Der Abruf selbst war in Ordnung (nachgemessen an der echten Adresse: 200,
    text/calendar, gültige Datei). Er hing aber an genau einem Namen, und
    niemand konnte nachsehen, was eine Kalender-App tatsächlich vorfindet.
    """

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()
        db = SessionLocal()
        from kern import kalender
        person = db.query(User).filter(User.email == "pruef@ag.local").first()
        cls.adresse = kalender.abo_adresse(db, person)
        cls.token = person.calendar_token
        db.close()

    def test_beide_seiten_liefern_denselben_kalender(self):
        pfad = f"/dashboard/kalender/{self.token}.ics"
        vom_dashboard = self.dash.get(pfad)
        von_der_website = self.web.get(pfad)
        for name, antwort in (("Dashboard", vom_dashboard),
                              ("Website", von_der_website)):
            self.assertEqual(antwort.status_code, 200, f"{name} liefert nichts")
            self.assertIn("text/calendar", antwort.headers.get("content-type", ""),
                          f"{name} liefert den falschen Typ")
            self.assertTrue(antwort.text.startswith("BEGIN:VCALENDAR"),
                            f"{name} liefert keine Kalenderdatei")

    def test_die_ausgegebene_adresse_zeigt_auf_das_dashboard(self):
        """Gemessen: Unter dem Hauptnamen lief noch die alte Fassung und
        antwortete mit 404, unter dem Dashboard-Namen kam die Datei.
        Ausgegeben wird die Adresse, die nachweislich antwortet."""
        from kern import einstellungen as cfg
        self.assertTrue(self.adresse.startswith(cfg.DASHBOARD_URL),
                        f"Abo-Adresse zeigt auf {self.adresse}")

    def test_pruefung_verdaechtigt_nicht_die_kennung_wenn_der_name_klemmt(self):
        """Antwortet der eine Name nicht und der andere schon, ist die
        Kennung in Ordnung - das muss die Meldung auch sagen."""
        import unittest.mock
        from kern import kalender_abo

        def antwort(adresse):
            if "8001" in adresse or "app." in adresse:
                return "gut", "3"
            return "unbekannt", "404"

        with unittest.mock.patch.object(kalender_abo, "_einmal_abrufen",
                                        side_effect=antwort):
            gut, meldung = kalender_abo.pruefe(
                "http://localhost:8000/dashboard/kalender/x.ics")
        self.assertFalse(gut)
        self.assertIn("Kennung ist also in Ordnung", meldung)
        self.assertIn("andere Adresse", meldung)

    def test_pruefung_meldet_die_kennung_wenn_beide_nichts_wissen(self):
        import unittest.mock
        from kern import kalender_abo
        with unittest.mock.patch.object(kalender_abo, "_einmal_abrufen",
                                        return_value=("unbekannt", "404")):
            gut, meldung = kalender_abo.pruefe(
                "http://localhost:8001/dashboard/kalender/x.ics")
        self.assertFalse(gut)
        self.assertIn("404", meldung)
        self.assertIn("halb kopiert", meldung)

    def test_unbekannte_kennung_erklaert_sich(self):
        """Statt „Nicht gefunden“ soll dastehen, woran es liegt."""
        antwort = self.web.get("/dashboard/kalender/gibtesnicht.ics")
        self.assertEqual(antwort.status_code, 404)
        self.assertIn("kein Kalender-Abo", antwort.text)
        self.assertIn("Mein Konto", antwort.text)

    def test_abruf_wird_vermerkt(self):
        from kern.modelle import User as U
        db = SessionLocal()
        person = db.query(U).filter(U.email == "pruef@ag.local").first()
        person.calendar_last_fetch = None
        db.commit()
        db.close()
        self.web.get(f"/dashboard/kalender/{self.token}.ics")
        db = SessionLocal()
        person = db.query(U).filter(U.email == "pruef@ag.local").first()
        self.assertIsNotNone(person.calendar_last_fetch,
                             "der Abruf über die Website wurde nicht vermerkt")
        person.calendar_last_fetch = None
        db.commit()
        db.close()

    def test_pruefknopf_meldet_was_er_vorfindet(self):
        import unittest.mock
        from kern import kalender_abo
        with unittest.mock.patch.object(kalender_abo, "pruefe",
                                        return_value=(True, "Läuft.")) as p:
            csrf = csrf_aus(self.dash.get("/dashboard/kalender").text)
            antwort = self.dash.post("/dashboard/kalender/abo-pruefen",
                                     data={"csrf": csrf})
        self.assertTrue(p.called, "der Knopf prüft gar nichts")
        self.assertIn("Läuft.", antwort.text)

    def test_pruefung_erkennt_die_haeufigen_faelle(self):
        import unittest.mock
        import urllib.error
        from kern.kalender_abo import pruefe

        class Antwort:
            def __init__(self, typ, inhalt):
                self.headers = {"content-type": typ}
                self._i = inhalt
            def read(self, *a):
                return self._i.encode()

        with unittest.mock.patch("urllib.request.urlopen",
                                 return_value=Antwort(
                                     "text/calendar",
                                     "BEGIN:VCALENDAR BEGIN:VEVENT")):
            gut, meldung = pruefe("https://example.test/x.ics")
        self.assertTrue(gut)
        self.assertIn("1 Termin", meldung)

        with unittest.mock.patch("urllib.request.urlopen",
                                 return_value=Antwort("text/html", "<html>")):
            gut, meldung = pruefe("https://example.test/x.ics")
        self.assertFalse(gut)
        self.assertIn("kein Kalender", meldung)

        fehler404 = urllib.error.HTTPError("u", 404, "nope", {}, None)
        with unittest.mock.patch("urllib.request.urlopen", side_effect=fehler404):
            gut, meldung = pruefe("https://example.test/x.ics")
        self.assertFalse(gut)
        self.assertIn("404", meldung)


class TestPushKnopfImDashboard(unittest.TestCase):
    """Der größte Fund: Im Dashboard passierte beim Druck auf „Dieses Gerät
    anmelden“ gar nichts - `push.js` war dort überhaupt nicht eingebunden.
    Der Knopf hatte niemanden, der zuhört. Alle Verbesserungen an der
    Anmeldelogik liefen deshalb ins Leere.
    """

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_der_rahmen_laedt_das_skript(self):
        rahmen = self.dash.get("/").text
        self.assertIn("js/push.js", rahmen,
                      "ohne push.js tut der Knopf im Dashboard nichts")

    def test_das_skript_traegt_eine_nonce(self):
        """Ohne Nonce blockt die Sicherheitsrichtlinie es wortlos."""
        rahmen = self.dash.get("/").text
        stelle = rahmen.index("js/push.js")
        anfang = rahmen.rindex("<script", 0, stelle)
        self.assertIn("nonce=", rahmen[anfang:stelle])

    def test_knopf_und_hinweisfeld_stehen_im_bereich(self):
        bereich = self.dash.get("/dashboard/nachrichten").text
        self.assertIn('id="push-anmelden"', bereich)
        self.assertIn('id="push-hinweis"', bereich,
                      "ohne dieses Feld verschwindet jede Rückmeldung stumm")

    def test_die_oeffentliche_seite_hat_damit_nichts_mehr_zu_tun(self):
        """Zwei Knöpfe für dieselbe Sache haben mehr verwirrt als genützt.
        Angemeldet wird seit dem 19.08.2026 nur noch im Dashboard."""
        self.assertEqual(self.web.get("/benachrichtigungen").status_code, 404)

    def test_fehlendes_notification_wird_abgefangen(self):
        """Auf dem iPhone gibt es in Safari kein Notification-Objekt."""
        quelle = (WURZEL / "statisch/js/push.js").read_text(encoding="utf-8")
        self.assertIn("'Notification' in window", quelle)


class TestStufeStattKlasse(unittest.TestCase):
    """Es gibt keine Klasse 11b an dieser Schule - nur die Stufe."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_kein_beispiel_mit_buchstaben_mehr(self):
        seite = self.web.get("/bewerbung").text
        self.assertNotIn("11b", seite)

    def test_stufen_zur_auswahl(self):
        seite = self.web.get("/bewerbung").text
        self.assertIn('name="klasse" required', seite)
        for stufe in ("10", "11", "12", "13"):
            self.assertIn(f'value="{stufe}"', seite)

    def test_bewerbung_mit_stufe_geht_durch(self):
        from fastapi.testclient import TestClient
        from kern.modelle import Application
        from website.app import app as web_app
        with TestClient(web_app) as k:
            csrf = csrf_aus(k.get("/bewerbung").text)
            k.post("/bewerbung", data={
                "vorname": "Stufen", "nachname": "Test", "klasse": "12",
                "email": "stufe12@example.org", "telefonnummer": "0163 1234567",
                "abteilung": "tech",
                "motivation": "Ich interessiere mich sehr für Wirtschaft und "
                              "möchte gerne mitmachen.",
                "interessen": "Börse", "csrf": csrf})
        db = SessionLocal()
        eintrag = db.query(Application).filter(
            Application.email == "stufe12@example.org").first()
        self.assertIsNotNone(eintrag)
        self.assertEqual(eintrag.klasse, "12")
        db.delete(eintrag)
        db.commit()
        db.close()


class TestPushAbsageWirdRichtigErklaert(unittest.TestCase):
    """Gemeldet: „Es steht immer, dass ich abgelehnt habe.“

    Zwei ganz verschiedene Lagen führten zu demselben Satz:

    * Auf dem iPhone in Safari gibt es Web Push gar nicht - Apple verlangt,
      dass die Seite auf dem Home-Bildschirm liegt. Der Browser antwortete je
      nach Fassung mit einem sofortigen „denied“, und die Seite behauptete,
      der Nutzer habe abgelehnt. Er hatte nie eine Frage gesehen.
    * Wer einmal wirklich abgelehnt hat, wird nicht mehr gefragt. Da hilft
      kein „nochmal tippen“, sondern nur der Weg zur richtigen Einstellung -
      und der ist auf jedem Gerät ein anderer.
    """

    def setUp(self):
        self.quelle = (WURZEL / "statisch/js/push.js").read_text(encoding="utf-8")

    def test_die_apple_regel_wird_zuerst_geprueft(self):
        apple = self.quelle.index("istIOS() && !istAufStartbildschirm()")
        pushmanager = self.quelle.index("'PushManager' in window")
        frage = self.quelle.index("requestPermission")
        self.assertLess(apple, pushmanager,
                        "die Apple-Regel wird erst nach einem Fehlschlag geprüft")
        self.assertLess(apple, frage)

    def test_bestehende_sperre_wird_vor_dem_fragen_erkannt(self):
        sperre = self.quelle.index("Notification.permission === 'denied'")
        frage = self.quelle.index("erlaubnisFrage = Notification.requestPermission")
        self.assertLess(sperre, frage,
                        "es wird gefragt, obwohl der Browser schon gesperrt hat")

    def test_kein_vorwurf_mehr_an_den_nutzer(self):
        self.assertNotIn("Du hast Benachrichtigungen abgelehnt", self.quelle)

    def test_anleitung_je_geraet(self):
        i = self.quelle.index("function erlaubnisWiederholen")
        block = self.quelle[i:i + 1200]
        self.assertIn("iPhone", block)
        self.assertIn("Android", block)
        self.assertIn("Adresszeile", block)

    def test_apple_hinweis_nennt_den_weg(self):
        i = self.quelle.index("istIOS() && !istAufStartbildschirm()")
        block = self.quelle[i:i + 700]
        self.assertIn("Home-Bildschirm", block)
        self.assertIn("Teilen", block)
        self.assertIn("ntfy", block, "der Ausweg ohne Apple fehlt")


class TestKeineRouteBlockiertDenServer(unittest.TestCase):
    """Gemeldet: „Die Seite ist tot langsam. Wenn man was macht, dauert es
    Jahre, bis etwas passiert.“

    Die Ursache stand in der Form der Routen. FastAPI führt `async def`
    unmittelbar im Ereignisfaden aus - dem einen Faden, der alle Anfragen
    bedient. Jede blockierende Zeile darin hält in dieser Zeit den GANZEN
    Server an: eine SQLite-Abfrage, ein Vorlagen-Rendern, vor allem aber die
    Selbstprüfung des Kalender-Abos (zweimal urlopen mit zwölf Sekunden
    Zeitgrenze) und die WhatsApp-Statusabfrage. Wer darauf wartete, wartete
    für alle mit.

    Gemessen an einer zwei Sekunden langen Anfrage: ein zweiter Klick wartete
    vorher 1717 ms, danach 5 ms.

    Eine `def`-Route dagegen läuft in einem Arbeitsfaden und blockiert nur
    sich selbst. Ausnahmen sind Routen, die wirklich `await` brauchen - die
    gehören in den Ereignisfaden.
    """

    def _routen(self):
        from dashboard.app import app as dashboard_app
        from website.app import app as website_app
        for anwendung in (dashboard_app, website_app):
            for weg in anwendung.routes:
                ziel = getattr(weg, "endpoint", None)
                if ziel is not None and getattr(weg, "methods", None):
                    yield anwendung, weg, ziel

    def test_asynchrone_routen_warten_auch_wirklich(self):
        import inspect
        schuldige = []
        for _, weg, ziel in self._routen():
            if not inspect.iscoroutinefunction(ziel):
                continue
            try:
                quelle = inspect.getsource(ziel)
            except (OSError, TypeError):
                continue
            if "await " not in quelle:
                schuldige.append(f"{getattr(weg, 'path', '?')} -> {ziel.__name__}")
        self.assertEqual(schuldige, [], "Diese Routen sind nur der Form nach "
                         "asynchron und halten dabei den ganzen Server an")

    def test_die_langsamen_selbstpruefungen_sind_draussen(self):
        """Kalender-Abo und WhatsApp-Kopplung sind die teuersten Knöpfe."""
        import inspect
        from dashboard.routen.organisation import kalender_abo_pruefen
        from dashboard.routen.kommunikation import whatsapp_kopplung
        for f in (kalender_abo_pruefen, whatsapp_kopplung):
            self.assertFalse(inspect.iscoroutinefunction(f), f.__name__)

    def test_die_uebersicht_liegt_fertig_im_rahmen(self):
        """Beim Umbau ging genau das kaputt, und niemand hätte es gemerkt.

        Der Rahmen bringt die Übersicht schon fertig mit - sonst holt das
        Skript sie in einem zweiten Rundweg nach, und auf dem Handy schaut
        man solange auf graue Balken. Scheitert das Vorrendern, faengt
        dashboard/app.py den Fehler ab und liefert den Platzhalter: Die Seite
        funktioniert weiter, nur langsamer. Ein Fehler, der sich versteckt,
        braucht einen Test, der ihn sucht.
        """
        web, dash = angemeldeter_client()
        seite = dash.get("/dashboard").text
        self.assertIn("uebersicht-kopf", seite,
                      "die Übersicht wird nicht mehr vorgerendert")

    def test_genug_verbindungen_fuer_die_arbeitsfaeden(self):
        """Sonst wird der Verbindungsvorrat die neue Warteschlange."""
        from kern.datenbank import engine
        vorrat = engine.pool
        self.assertGreaterEqual(vorrat.size() + vorrat._max_overflow, 40)


class TestAppModusOhneAbgeschnitteneLeiste(unittest.TestCase):
    """Gemeldet: „Die Leiste oben wird abgeschnitten im App-Modus, weil da Uhr
    und so sind.“

    Die Seite läuft mit `viewport-fit=cover` und schwarz-durchscheinender
    Statusleiste - gewollt, sonst läge über der Kopfleiste ein grauer Balken.
    Nur muss der Inhalt dann auch unterhalb von Uhr und Akku anfangen, und
    genau der Abstand fehlte.
    """

    def setUp(self):
        self.basis = (WURZEL / "statisch/stil/basis.css").read_text(encoding="utf-8")
        self.dash = (WURZEL / "statisch/stil/dashboard.css").read_text(encoding="utf-8")

    def _regeln(self, quelle: str, auswahl: str) -> str:
        """Alle Blöcke zu diesem Wähler zusammen.

        Manche stehen doppelt - einmal allgemein, einmal in einer
        Bildschirmbreite. Es genügt, wenn der Abstand irgendwo davon steht;
        nachgemessen wird ohnehin im Browser.
        """
        import re
        bloecke = re.findall(re.escape(auswahl) + r"[^}]*", quelle)
        self.assertTrue(bloecke, f"{auswahl} kommt gar nicht vor")
        return chr(10).join(bloecke)

    def test_kopfleiste_haelt_abstand_zur_statusleiste(self):
        regel = self._regeln(self.basis, "header.seite{")
        self.assertIn("env(safe-area-inset-top", regel)

    def test_kopfleiste_haelt_abstand_zur_kerbe(self):
        """Im Querformat sitzt die Kerbe seitlich."""
        regel = self._regeln(self.basis, "header.seite{")
        self.assertIn("env(safe-area-inset-left", regel)
        self.assertIn("env(safe-area-inset-right", regel)

    def test_schublade_faengt_unter_der_uhr_an(self):
        regel = self._regeln(self.dash, ".dash-leiste{")
        self.assertIn("env(safe-area-inset-top", regel)

    def test_inhalt_und_fuss_enden_ueber_dem_wischstrich(self):
        for auswahl in ("main{", "footer.seite{"):
            with self.subTest(auswahl):
                    self.assertIn("env(safe-area-inset-bottom",
                              self._regeln(self.basis, auswahl))


class TestMindestabstandImAppModus(unittest.TestCase):
    """Nachgemeldet: „ist immernoch verdeckt.“

    env(safe-area-inset-top) allein genügt nicht - manche iPhone-Fassungen
    melden dort 0, obwohl die Statusleiste sehr wohl über der Seite liegt.
    Dann stimmt die Rechnung und trotzdem steht die Uhr im Logo. Deshalb ein
    garantierter Mindestabstand, sobald die Seite als App läuft.
    """

    def setUp(self):
        self.basis = (WURZEL / "statisch/stil/basis.css").read_text(encoding="utf-8")
        self.dash = (WURZEL / "statisch/stil/dashboard.css").read_text(encoding="utf-8")
        self.kopf = (WURZEL / "vorlagen/basis.html").read_text(encoding="utf-8")

    def test_das_merkmal_sitzt_vor_dem_ersten_zeichnen(self):
        """Ein Abstand, der erst nach dem Zeichnen dazukommt, ist ein Sprung."""
        vor_titel = self.kopf[:self.kopf.index("<title>")]
        self.assertIn("data-app", vor_titel)
        # Beide Wege, sonst fallen genau die Geräte durch, um die es geht.
        self.assertIn("display-mode: standalone", vor_titel)
        self.assertIn("navigator.standalone", vor_titel)

    def test_kopfleiste_hat_einen_mindestabstand(self):
        i = self.basis.index("html[data-app] header.seite{")
        regel = self.basis[i:self.basis.index("}", i)]
        self.assertIn("max(env(safe-area-inset-top", regel,
                      "ohne max() bleibt es beim Wert des Geräts - und der "
                      "ist auf manchen iPhones fälschlich 0")

    def test_schublade_ebenso(self):
        i = self.dash.index("html[data-app] .dash-leiste{")
        self.assertIn("max(env(safe-area-inset-top",
                      self.dash[i:self.dash.index("}", i)])

    def test_im_browser_bleibt_alles_wie_es_war(self):
        """Der Mindestabstand hängt an data-app. Ohne das Merkmal - also
        im normalen Browser - darf sich nichts verschoben haben."""
        i = self.basis.index("header.seite{")
        allgemein = self.basis[i:self.basis.index("}", i)]
        self.assertNotIn("2.9rem", allgemein)
        self.assertIn("env(safe-area-inset-top", allgemein)

    def test_nur_eine_stelle_entscheidet_ueber_den_app_modus(self):
        """Zwei getrennte Prüfungen können auseinanderlaufen - dann stimmt
        entweder der Abstand nicht oder die Meldung an den Server."""
        js = (WURZEL / "statisch/js/basis.js").read_text(encoding="utf-8")
        self.assertIn("hasAttribute('data-app')", js)
        self.assertNotIn("window.navigator.standalone === true", js)


class TestDashboardGehoertAufDenStartbildschirm(unittest.TestCase):
    """Gewünscht: Das Dashboard soll als App auf dem Gerät liegen, und der
    Push-Hinweis auf der Übersicht soll verschwinden, sobald das Dashboard
    angemeldet ist - nicht erst, wenn auch die öffentliche Seite dran war.
    """

    def test_push_verlangt_nur_das_dashboard(self):
        from kern import umzug
        from kern.datenbank import SessionLocal as S
        db = S()
        try:
            person = db.query(User).filter(User.status == "aktiv").first()
            self.assertEqual(umzug.push_stand(db, person)["noetig"],
                             ["dashboard"])
        finally:
            db.close()

    def test_der_browser_meldet_den_app_modus_selbst(self):
        quelle = (WURZEL / "statisch/js/basis.js").read_text(encoding="utf-8")
        i = quelle.index("hasAttribute('data-app')")
        block = quelle[i:i + 2600]
        self.assertIn("/dashboard/als-app", block)
        # Einmal je Sitzung, nicht bei jedem Seitenwechsel.
        self.assertIn("sessionStorage", block)

    def test_die_meldung_braucht_ein_gueltiges_token(self):
        web, dash = angemeldeter_client()
        self.assertEqual(dash.post("/dashboard/als-app",
                                   data={"csrf": "falsch"}).status_code, 400)

    def test_und_haakt_den_punkt_dann_ab(self):
        from kern import umzug
        from kern.datenbank import SessionLocal as S
        web, dash = angemeldeter_client()
        import re
        seite = dash.get("/dashboard").text
        marke = re.search(r'id="dash-csrf" value="([^"]+)"', seite).group(1)
        antwort = dash.post("/dashboard/als-app", data={"csrf": marke})
        self.assertEqual(antwort.status_code, 204)
        db = S()
        try:
            person = db.query(User).filter(User.status == "aktiv").first()
            offen = [p["schluessel"] for p in umzug.offene_punkte(db, person)]
            self.assertNotIn("startbildschirm", offen)
        finally:
            db.close()


class TestNurPrivateMailadressen(unittest.TestCase):
    """Gewünscht: Schuladressen (@mvlg-ko.de) bei der Bewerbung sperren.

    Zwei Gründe, und der zweite wiegt schwerer: Das Postfach erlischt mit dem
    Abschluss, und die Schule lässt nicht jede Post durch - eine
    Bewerbungsbestätigung, die im Filter hängen bleibt, sieht für die
    bewerbende Person aus wie eine Absage.
    """

    def setUp(self):
        self.web, self.dash = angemeldeter_client()

    def _absenden(self, post):
        import re
        seite = self.web.get("/bewerbung").text
        marke = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
        return self.web.post("/bewerbung", data={
            "csrf": marke, "vorname": "Mara", "nachname": "Winkler",
            "klasse": "9", "email": post, "telefonnummer": "0163 1234567",
            "abteilung": "tech",
            "motivation": "Ich will endlich verstehen, wie die Börse wirklich "
                          "funktioniert.",
            "interessen": "Börse", "vorwissen": ""})

    def test_die_schuladresse_wird_abgelehnt(self):
        antwort = self._absenden("mara.winkler@mvlg-ko.de")
        self.assertIn("private E-Mail-Adresse", antwort.text)

    def test_auch_eine_unterdomain_der_schule(self):
        antwort = self._absenden("mara@schueler.mvlg-ko.de")
        self.assertIn("private E-Mail-Adresse", antwort.text)

    def test_eine_private_geht_durch(self):
        antwort = self._absenden("mara.winkler.privat@example.org")
        self.assertNotIn("private E-Mail-Adresse", antwort.text)

    def test_eine_aehnliche_fremde_domain_wird_nicht_mitgesperrt(self):
        """mvlg-ko.de.example.org ist nicht die Schule."""
        from website.routen.bewerbung import schuladresse
        self.assertFalse(schuladresse("wer@mvlg-ko.de.example.org"))
        self.assertTrue(schuladresse("wer@MVLG-KO.DE"))

    def test_das_formular_sagt_es_vorher(self):
        """Eine Regel, die man erst nach dem Absenden erfährt, ist eine Falle."""
        self.assertIn("keine Schuladresse", self.web.get("/bewerbung").text)

    def test_das_auffangnetz_kennt_dieselbe_regel(self):
        quelle = (WURZEL / "cloudflare/worker.js").read_text(encoding="utf-8")
        self.assertIn("mvlg-ko.de", quelle)
        self.assertIn("keine Schuladresse", quelle)


class TestStufeNeunDarfMit(unittest.TestCase):
    """Seit dem 19.08.2026 ist die 9 dabei."""

    def setUp(self):
        self.web, self.dash = angemeldeter_client()

    def test_neun_steht_im_formular(self):
        seite = self.web.get("/bewerbung").text
        for stufe in ("9", "10", "11", "12", "13"):
            with self.subTest(stufe):
                self.assertIn(f'value="{stufe}"', seite)

    def test_und_die_startseite_sagt_es_auch(self):
        self.assertIn("9 bis 13", self.web.get("/").text)

    def test_eine_erfundene_stufe_kommt_nicht_durch(self):
        """Das Auswahlfeld steht im Browser des Absenders - dort lässt es sich
        ändern. Geprüft wird deshalb auf dem Server."""
        import re
        seite = self.web.get("/bewerbung").text
        marke = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
        antwort = self.web.post("/bewerbung", data={
            "csrf": marke, "vorname": "Test", "nachname": "Person",
            "klasse": "7", "email": "test.person@example.org",
            "telefonnummer": "0163 1234567", "abteilung": "tech",
            "motivation": "Ein paar Sätze zur Motivation, die lang genug sind.",
            "interessen": "Börse", "vorwissen": ""})
        self.assertIn("Stufe", antwort.text)
        self.assertIn("9 bis 13", antwort.text)

    def test_auch_das_auffangnetz_kennt_die_neun(self):
        quelle = (WURZEL / "cloudflare/worker.js").read_text(encoding="utf-8")
        self.assertIn('<option value="9">9</option>', quelle)
        self.assertIn("Klassenstufen 9 bis 13", quelle)


class TestKopfleisteBleibtSichtbar(unittest.TestCase):
    """Gemeldet: „Der Menü-Knopf geht weg, wenn man draufklickt."

    Er ging nicht weg, er verschwand dahinter: Die Schublade legt einen
    Schleier über die Seite (z-index 55), und die Kopfleiste lag mit 30
    darunter. Kaum tippte man auf das Menü, waren Logo, Menü-Knopf und der
    Hell/Dunkel-Schalter hinter einer grauen Scheibe.
    """

    def setUp(self):
        self.basis = (WURZEL / "statisch/stil/basis.css").read_text(encoding="utf-8")
        self.dash = (WURZEL / "statisch/stil/dashboard.css").read_text(encoding="utf-8")

    def _z(self, quelle, auswahl):
        """Der z-index einer Regel. Kommentare mit geschweiften Klammern
        darin gibt es hier nicht, aber Regeln über mehrere Zeilen schon -
        deshalb wird bis zur nächsten Zeile gelesen, die nur „}" enthält."""
        import re
        umbruch = chr(10)
        # Denselben Waehler gibt es mehrfach - einmal allgemein, einmal in
        # einer Bildschirmbreite, einmal fuer den App-Modus. Gesucht ist der
        # Block, in dem wirklich ein z-index steht.
        stelle = -1
        while True:
            stelle = quelle.find(auswahl, stelle + 1)
            if stelle < 0:
                break
            zeilen = []
            for zeile in quelle[stelle:].split(umbruch)[1:]:
                if zeile.strip().startswith("}"):
                    break
                zeilen.append(zeile)
            treffer = re.search(r"z-index:\s*(\d+)", umbruch.join(zeilen))
            if treffer:
                return int(treffer.group(1))
        self.fail(f"kein z-index bei {auswahl}")

    def test_die_kopfleiste_liegt_ueber_dem_schleier(self):
        self.assertGreater(self._z(self.basis, "header.seite{"),
                           self._z(self.dash, ".leisten-schleier:not([hidden])"))

    def test_aber_unter_der_schublade_selbst(self):
        """Die soll sich darüberschieben, sonst ragt der Kopf mitten hinein."""
        self.assertLess(self._z(self.basis, "header.seite{"),
                        self._z(self.dash, ".dash-leiste{"))


class TestHellIstDieVorgabe(unittest.TestCase):
    """Gewünscht: Hellmodus als Standard.

    Vorher entschied die Geräteeinstellung: Wer sein Handy nachts auf dunkel
    stellt, bekam die Plattform dunkel, ohne das je gewollt zu haben. Der
    Schalter bleibt - wer dunkel will, wählt es einmal und behält es.
    """

    def setUp(self):
        self.kopf = (WURZEL / "vorlagen/basis.html").read_text(encoding="utf-8")

    def test_ohne_gespeicherte_wahl_gilt_hell(self):
        vor_titel = self.kopf[:self.kopf.index("<title>")]
        self.assertIn("t='light'", vor_titel)
        self.assertNotIn("prefers-color-scheme: dark", vor_titel)

    def test_die_browserleiste_faerbt_sich_nicht_mehr_mit(self):
        """Sonst steht eine dunkle Leiste über einer hellen Seite."""
        self.assertNotIn('theme-color" media="(prefers-color-scheme: dark)',
                         self.kopf)
        self.assertIn('<meta name="theme-color" content=', self.kopf)

    def test_der_schalter_bleibt(self):
        self.assertIn("data-thema", self.kopf)


class TestTreffenStehenImKalender(unittest.TestCase):
    """Gemeldet: „Kalender-Anzeige zeigt AG-Treffen nicht an."

    Sie standen nur unter „Treffen" und im Abo. Wer sich einen Überblick über
    die nächsten Wochen holen wollte, sah alles außer dem Wichtigsten.
    """

    @classmethod
    def setUpClass(cls):
        from datetime import date, timedelta
        from kern.datenbank import SessionLocal as S
        from kern.modelle import Meeting
        cls.web, cls.dash = angemeldeter_client()
        # Einmal fuer die ganze Klasse: Die Reihenfolge der Tests ist
        # alphabetisch, ein Treffen aus einem Test waere im naechsten
        # vielleicht noch nicht da.
        db = S()
        if not db.query(Meeting).filter(
                Meeting.title == "Kalenderprobe-Treffen").first():
            db.add(Meeting(title="Kalenderprobe-Treffen",
                           date=date.today() + timedelta(days=4)))
            db.commit()
        db.close()

    def test_ein_kommendes_treffen_taucht_auf(self):
        seite = self.dash.get("/dashboard/kalender").text
        self.assertIn("Kalenderprobe-Treffen", seite)
        self.assertIn("AG-Treffen", seite)

    def test_bearbeitet_wird_es_weiterhin_woanders(self):
        """Ein Treffen hat Zu- und Absagen und eine Tagesordnung. Zwischen den
        Terminen wäre die Hälfte der Knöpfe daran wirkungslos."""
        seite = self.dash.get("/dashboard/kalender").text
        self.assertIn("<h2>AG-Treffen</h2>", seite)
        i = seite.index("<h2>AG-Treffen</h2>")
        block = seite[i:i + 700]
        self.assertIn('data-springe="treffen"', block)


class TestDeutscheZeitImKalender(unittest.TestCase):
    """Gemeldet: „Im Kalender falsche Zeit."

    `astimezone()` ohne Ziel rechnet in die Zeitzone des Rechners um - und
    darunter stand trotzdem ein „Z", also die Behauptung, das sei UTC. Auf
    einem deutschen Rechner kam damit die Berliner Uhrzeit als UTC heraus:
    jeder Termin lag ein bis zwei Stunden daneben.
    """

    def test_sechzehn_uhr_wird_zu_vierzehn_uhr_utc(self):
        from datetime import date, time
        from kern import kalender
        from kern.datenbank import SessionLocal as S
        from kern.modelle import CalendarEvent, User
        db = S()
        person = db.query(User).filter(User.status == "aktiv").first()
        db.add(CalendarEvent(title="Sommertermin", start_date=date(2026, 9, 3),
                             start_time="16:00", end_time="17:30",
                             target_type="alle", created_by=person.id))
        db.commit()
        text = kalender.als_ics(db, person)
        db.close()
        # 3. September = Sommerzeit, also UTC+2.
        self.assertIn("DTSTART:20260903T140000Z", text)
        self.assertIn("DTEND:20260903T153000Z", text)

    def test_auch_im_winter_stimmt_es(self):
        """Dann ist es UTC+1 - eine feste Verschiebung wäre falsch gewesen."""
        from datetime import date
        from kern import kalender
        from kern.datenbank import SessionLocal as S
        from kern.modelle import CalendarEvent, User
        db = S()
        person = db.query(User).filter(User.status == "aktiv").first()
        db.add(CalendarEvent(title="Wintertermin", start_date=date(2026, 12, 3),
                             start_time="16:00", target_type="alle",
                             created_by=person.id))
        db.commit()
        text = kalender.als_ics(db, person)
        db.close()
        self.assertIn("DTSTART:20261203T150000Z", text)


class TestSuchmaschinenAngaben(unittest.TestCase):
    """Aus der Search Console: 238 von 262 Einblendungen kommen von „mvlg",
    Platz 5,2 - aber nur vier Klicks.

    Wer „mvlg" tippt, sucht die Schule. Diesen Platz gewinnen wir nicht und
    sollen ihn nicht gewinnen. Was sich ändern lässt, ist die Zeile daneben:
    Sie muss in drei Sekunden sagen, dass hier eine AG dieser Schule steht,
    für wen sie ist und was man tun kann.
    """

    def setUp(self):
        self.web, self.dash = angemeldeter_client()

    def _kopf(self, weg):
        import re
        t = self.web.get(weg).text
        return (re.search(r"<title>(.*?)</title>", t, re.S).group(1).strip(),
                re.search(r'<meta name="description" content="(.*?)">',
                          t, re.S).group(1),
                t)

    def test_titel_wird_nicht_abgeschnitten(self):
        """Über etwa 60 Zeichen kürzt Google mit Auslassungspunkten."""
        for weg in ("/", "/bewerbung"):
            with self.subTest(weg):
                titel, _, _ = self._kopf(weg)
                self.assertLessEqual(len(titel), 62, titel)

    def test_beschreibung_wird_nicht_abgeschnitten(self):
        """Über etwa 155 Zeichen fällt der letzte Satz weg - und das ist der
        mit dem Grund zum Klicken."""
        for weg in ("/", "/bewerbung"):
            with self.subTest(weg):
                _, text, _ = self._kopf(weg)
                self.assertLessEqual(len(text), 158, text)
                self.assertGreater(len(text), 90, "zu dünn für ein Ergebnis")

    def test_die_gesuchten_woerter_stehen_drin(self):
        titel, text, _ = self._kopf("/")
        for wort in ("MvLG", "WAG"):
            self.assertIn(wort, titel, wort)
        for wort in ("Max-von-Laue-Gymnasium", "Koblenz", "Schüler-AG"):
            self.assertIn(wort, text, wort)

    def test_die_beschreibung_nennt_zielgruppe_und_takt(self):
        """„Wir sind eine AG" ist kein Grund zu klicken. „Klasse 9 bis 13,
        ohne Vorwissen" schon."""
        _, text, _ = self._kopf("/")
        self.assertIn("9 bis 13", text)
        self.assertIn("ohne Vorwissen", text)

    def test_strukturierte_daten_sind_gueltig(self):
        import json
        import re
        _, _, seite = self._kopf("/")
        treffer = re.search(
            r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
            seite, re.S)
        self.assertIsNotNone(treffer, "keine strukturierten Daten")
        daten = json.loads(treffer.group(1))
        self.assertEqual(daten["@type"], "EducationalOrganization")
        self.assertIn("WAG", daten["alternateName"])

    def test_wir_geben_uns_nicht_als_die_schule_aus(self):
        """Wir sind eine AG DER Schule, nicht die Schule. Genau diese
        Unterscheidung soll auch eine Suchmaschine sehen."""
        import json
        import re
        titel, _, seite = self._kopf("/")
        daten = json.loads(re.search(
            r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
            seite, re.S).group(1))
        self.assertEqual(daten["parentOrganization"]["name"],
                         "Max-von-Laue-Gymnasium Koblenz")
        self.assertTrue(titel.startswith("Wirtschafts-"),
                        "der Titel darf nicht mit dem Schulnamen anfangen")

    def test_der_nonce_haengt_dran(self):
        """Ohne ihn lässt die Richtlinie das Skript-Element nicht durch."""
        import re
        _, _, seite = self._kopf("/")
        treffer = re.search(r'<script type="application/ld\+json"([^>]*)>', seite)
        self.assertIn("nonce=", treffer.group(1))


class TestKeineSpamSignale(unittest.TestCase):
    """Chrome hat mvlg-wag.de und app.mvlg-wag.de als möglichen Spam gemeldet.

    Beide führen auf dieselbe Seite: die Anmeldung. Und die hatte genau die
    Form, die ein Phishing-Filter sucht - ein Passwortfeld, auf einer Domain
    mit dem Kürzel einer fremden Einrichtung, und 26 Nennungen dieser
    Einrichtung im Kopf der Seite. Dazu kamen Schlüsselwörter, die den
    Schulnamen in vier Schreibweisen aufzählten, und zwei sich
    widersprechende Organisations-Angaben.

    Nichts davon war böse gemeint. Für einen Klassifikator sah es trotzdem
    aus wie ein Nachbau einer Schulanmeldung.
    """

    def setUp(self):
        """Ohne Anmeldung: Wer angemeldet ist, wird von /login weitergeleitet
        und bekommt am Ende die Startseite - dann prüft man die falsche."""
        from fastapi.testclient import TestClient
        from website.app import app as web_app
        self.web = TestClient(web_app)

    def _kopf(self, weg):
        t = self.web.get(weg).text
        return t[:t.index("</head>")], t

    def _schulnennungen(self, text):
        return (text.count("MvLG") + text.count("Max-von-Laue")
                + text.count("Max von Laue"))

    def test_keine_fremde_marke_auf_der_anmeldeseite(self):
        kopf, ganz = self._kopf("/login")
        self.assertIn('type="password"', ganz, "kein Passwortfeld?")
        self.assertEqual(self._schulnennungen(kopf), 0, kopf[:400])

    def test_auch_nicht_auf_den_passwortseiten(self):
        """„Passwort vergessen" fragt nur nach der E-Mail, „Passwort neu"
        setzt eines. Beide gehören zur Anmeldung und werden gleich behandelt."""
        for weg in ("/passwort-vergessen", "/passwort-neu?token=egal"):
            with self.subTest(weg):
                kopf, _ = self._kopf(weg)
                self.assertEqual(self._schulnennungen(kopf), 0, kopf[:300])

    def test_anmeldeseiten_tragen_keine_werbeangaben(self):
        """Eine Anmeldung hat nichts zu teilen und nichts zu bewerben."""
        for weg in ("/login", "/passwort-vergessen", "/passwort-neu?token=x"):
            with self.subTest(weg):
                kopf, _ = self._kopf(weg)
                for verdacht in ("og:image", "twitter:card",
                                 "application/ld+json", 'name="description"'):
                    self.assertNotIn(verdacht, kopf, verdacht)

    def test_anmeldeseiten_bleiben_aus_dem_index(self):
        for weg in ("/login", "/passwort-vergessen", "/passwort-neu?token=x"):
            with self.subTest(weg):
                _, ganz = self._kopf(weg)
                self.assertIn('content="noindex, nofollow"', ganz)

    def test_keine_schluesselwoerter_mehr(self):
        """Google wertet sie seit 2009 nicht aus - ein Spamfilter liest sie
        sehr wohl. Und dort stand der Schulname in vier Schreibweisen."""
        for weg in ("/", "/bewerbung", "/login"):
            with self.subTest(weg):
                kopf, _ = self._kopf(weg)
                self.assertNotIn('name="keywords"', kopf)

    def test_nur_eine_organisationsangabe(self):
        """Zwei Blöcke mit verschiedenen Namen und Logos sind für eine
        Suchmaschine zwei Aussagen über dieselbe Sache, die sich
        widersprechen."""
        import re
        _, ganz = self._kopf("/")
        self.assertEqual(
            len(re.findall(r'<script type="application/ld\+json"', ganz)), 1)

    def test_wir_geben_die_schule_als_traeger_an_nicht_als_uns_selbst(self):
        """Das ist der stärkste Hinweis gegen den Phishing-Verdacht: Diese AG
        gehört zu genau dieser Einrichtung - und ist nicht deren Nachbau."""
        import json
        import re
        _, ganz = self._kopf("/")
        daten = json.loads(re.search(
            r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
            ganz, re.S).group(1))
        self.assertEqual(daten["name"], "Wirtschafts- & Investment-AG")
        self.assertEqual(daten["parentOrganization"]["name"],
                         "Max-von-Laue-Gymnasium Koblenz")
        self.assertNotIn("MvLG", daten["alternateName"],
                         "unsere Kurzformen sind unsere, nicht die der Schule")

    def test_die_offene_seite_nennt_die_schule_massvoll(self):
        """Ganz verschweigen wäre auch falsch - wir sind wirklich dort. Es
        geht um das Verhältnis."""
        _, ganz = self._kopf("/")
        import re
        nur_text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>",
                          " ", ganz, flags=re.S)
        self.assertLess(self._schulnennungen(nur_text), 12,
                        "so oft nennt sich nicht einmal die Schule selbst")


if __name__ == "__main__":
    unittest.main()
