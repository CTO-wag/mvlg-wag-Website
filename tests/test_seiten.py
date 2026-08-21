"""Beide Server: erreichbar, geschützt, und die Sichtbarkeitsregel stimmt."""

import unittest

from tests import hilfe                                      # noqa: F401

from fastapi.testclient import TestClient

from website.app import app as web_app
from dashboard.app import app as dash_app


class TestWebsite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hilfe.frische_datenbank()
        cls.c = TestClient(web_app)
        cls.c.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.c.__exit__(None, None, None)

    def test_startseite(self):
        a = self.c.get("/")
        self.assertEqual(a.status_code, 200)
        self.assertIn("Deine erste Aktie", a.text)

    def test_startseitentext_ist_erhalten(self):
        """Der Text der Startseite wurde aus V1 übernommen und bleibt."""
        text = self.c.get("/").text
        for satz in ("An alle, die größer denken.",
                     "Von Schülern geleitet. Sonst niemandem.",
                     "Zwei Halbjahre, zwei Welten",
                     "Was wir konkret machen",
                     "Du fängst an, wo du stehst"):
            self.assertIn(satz, text, satz)

    def test_fusszeile_ohne_klarnamen(self):
        """Nach außen tritt die AG auf, nicht eine einzelne Person."""
        text = self.c.get("/").text
        self.assertNotIn("Janis Hahn", text)
        self.assertIn("© 2026", text)
        self.assertIn("Wirtschafts- &amp; Investment-AG", text)

    def test_kein_mitgliederzaehler_mehr(self):
        """Eine AG mit acht Mitgliedern wirbt mit der Zahl gegen sich selbst."""
        text = self.c.get("/").text
        self.assertNotIn("aufmacher-zahl", text)
        self.assertNotIn("Mitglieder</span>", text)

    def test_angebot_kommt_aus_der_datenbank(self):
        from kern.datenbank import SessionLocal
        from kern.modelle import Inhalt
        from kern import inhalte

        db = SessionLocal()
        db.add(Inhalt(bereich="angebot", titel="Testbaustein",
                      text="Aus der Datenbank.", reihenfolge=999))
        db.commit()
        db.close()
        inhalte.verwerfen()
        self.assertIn("Testbaustein", self.c.get("/").text)

    def test_portfolio_erscheint_erst_mit_eintraegen(self):
        """Eine leere Erfolgsliste wirbt gegen die AG - dann lieber weg."""
        from kern.datenbank import SessionLocal
        from kern.modelle import Inhalt
        from kern import inhalte

        db = SessionLocal()
        db.query(Inhalt).filter(Inhalt.bereich == "portfolio").delete()
        db.commit()
        db.close()
        inhalte.verwerfen()
        self.assertNotIn("Was dabei herausgekommen ist", self.c.get("/").text)

        db = SessionLocal()
        db.add(Inhalt(bereich="portfolio", titel="Planspiel Börse 2025",
                      text="Mit zwei Teams angetreten.",
                      zeitraum="Herbst 2025",
                      ergebnis="2. Platz im Landesfinale", reihenfolge=10))
        db.commit()
        db.close()
        inhalte.verwerfen()
        seite = self.c.get("/").text
        self.assertIn("Was dabei herausgekommen ist", seite)
        self.assertIn("Planspiel Börse 2025", seite)
        self.assertIn("Herbst 2025", seite)
        self.assertIn("2. Platz im Landesfinale", seite)

    def test_weitere_seiten(self):
        for pfad, wort in (("/bewerbung", "Warum willst du mitmachen"),
                           ("/quiz", "Wirtschafts-Quiz"),
                           ("/impressum", "Südallee"),
                           ("/datenschutz", "Verantwortlicher"),
                           ("/login", "Anmelden"),
                           ("/passwort-vergessen", "Passwort vergessen")):
            with self.subTest(pfad=pfad):
                a = self.c.get(pfad)
                self.assertEqual(a.status_code, 200)
                self.assertIn(wort, a.text)

    def test_seo(self):
        self.assertIn("<urlset", self.c.get("/sitemap.xml").text)
        self.assertIn("Sitemap:", self.c.get("/robots.txt").text)

    def test_unbekannte_seite(self):
        a = self.c.get("/gibtsnicht")
        self.assertEqual(a.status_code, 404)
        self.assertIn("nicht gefunden", a.text)

    def test_sicherheitskopfzeilen(self):
        a = self.c.get("/")
        csp = a.headers.get("content-security-policy", "")
        self.assertIn("nonce-", csp)
        # Kein 'unsafe-inline' bei Skripten - das war die groesste Luecke in V1.
        skript_teil = [t for t in csp.split(";") if "script-src" in t][0]
        self.assertNotIn("unsafe-inline", skript_teil)
        for kopf in ("x-content-type-options", "x-frame-options",
                     "referrer-policy", "cross-origin-opener-policy"):
            self.assertIn(kopf, a.headers, kopf)

    def test_kontakt_braucht_csrf(self):
        a = self.c.post("/kontakt", data={
            "name": "X", "email": "x@x.de", "nachricht": "Lange genug hier",
            "csrf": "falsch"})
        self.assertIn("zu lange offen", a.text)

    def test_honigtopf_faengt_automaten(self):
        from kern.datenbank import SessionLocal
        from kern.modelle import ContactMessage
        token = hilfe.csrf_aus(self.c.get("/").text)
        self.c.post("/kontakt", data={
            "name": "Bot", "email": "bot@spam.de", "nachricht": "Werbung hier",
            "webseite": "http://spam.example", "csrf": token})
        db = SessionLocal()
        treffer = db.query(ContactMessage).filter(
            ContactMessage.email == "bot@spam.de").count()
        db.close()
        self.assertEqual(treffer, 0, "Der Honigtopf hat nichts abgefangen")


class TestDashboardOhneAnmeldung(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hilfe.frische_datenbank()
        cls.c = TestClient(dash_app)
        cls.c.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.c.__exit__(None, None, None)

    def test_umleitung_zur_anmeldung(self):
        a = self.c.get("/", follow_redirects=False)
        self.assertEqual(a.status_code, 303)
        self.assertIn("/login", a.headers["location"])

    def test_htmx_bekommt_hinweis_statt_umleitung(self):
        """Kein Sprung zur Anmeldeseite mitten in der Arbeit.

        Ein HX-Redirect würde die Seite auf der Stelle wechseln - wer gerade
        einen langen Text getippt hat, verliert ihn dann ersatzlos. Deshalb
        kommt eine Erklärung mit Anmeldeknopf zurück; das Fenster bleibt
        stehen, der Text lässt sich noch kopieren.
        """
        a = self.c.get("/dashboard/konten", headers={"HX-Request": "true"})
        self.assertEqual(a.status_code, 401)
        self.assertNotIn("HX-Redirect", a.headers)
        self.assertIn("abgelaufen", a.text)
        self.assertIn("/login", a.text)

    def test_dashboard_nicht_im_index(self):
        a = self.c.get("/", follow_redirects=False)
        self.assertIn("noindex", a.headers.get("x-robots-tag", ""))


class TestDashboardAngemeldet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = hilfe.angemeldeter_client()
        cls.web.__enter__()
        cls.dash.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.dash.__exit__(None, None, None)
        cls.web.__exit__(None, None, None)

    def test_alle_bereiche_laden(self):
        bereiche = ["uebersicht", "aufgaben", "treffen", "kalender", "kassenbuch",
                    "bewerbungen", "konten", "mitglieder", "anwesenheit",
                    "nachrichten", "support", "vordrucke", "whatsapp", "projekte",
                    "wettbewerbe", "leistung", "rollen", "startseite",
                    "statistiken", "sicherheit", "datenbank", "papierkorb",
                    "mein-konto"]
        for bereich in bereiche:
            with self.subTest(bereich=bereich):
                a = self.dash.get(f"/dashboard/{bereich}")
                self.assertEqual(a.status_code, 200, a.text[:400])

    def test_rundgang_liefert_schritte(self):
        """Reines JSON - ein nachgeladenes Skript würde die CSP blockieren."""
        a = self.dash.get("/dashboard/rundgang")
        self.assertEqual(a.status_code, 200)
        self.assertIn("application/json", a.headers.get("content-type", ""))
        schritte = a.json()
        self.assertGreater(len(schritte), 5)
        for schritt in schritte:
            self.assertIn("titel", schritt)
            self.assertIn("teile", schritt)

    def test_dashboard_ist_eine_eigene_app(self):
        """Ohne eigenes sw.js scheitert die Push-Anmeldung mit einem 404."""
        self.assertEqual(self.dash.get("/sw.js").status_code, 200)
        manifest = self.dash.get("/manifest.webmanifest")
        self.assertEqual(manifest.status_code, 200)
        self.assertEqual(manifest.json()["start_url"], "/dashboard")

    def test_dashboard_auch_unter_pfad(self):
        """Für den Betrieb hinter einem Tunnel unter einer Adresse."""
        a = self.dash.get("/dashboard")
        self.assertEqual(a.status_code, 200)
        self.assertIn("Mein Konto", a.text)

    def test_bereiche_ohne_eingebettete_skripte(self):
        """Ein per htmx nachgeladenes <script> läuft unter der
        Nonce-Richtlinie nicht - genau daran war der Rundgang gescheitert."""
        for bereich in ("uebersicht", "kalender", "rollen", "whatsapp",
                        "nachrichten", "aufgaben", "konten"):
            with self.subTest(bereich=bereich):
                text = self.dash.get(f"/dashboard/{bereich}").text
                self.assertNotIn("<script nonce", text)
                # Reine Datenblöcke sind in Ordnung: sie werden nicht
                # ausgeführt, sondern nur gelesen.
                for stueck in text.split("<script")[1:]:
                    self.assertIn('type="application/json"', stueck[:60],
                                  f"ausführbares Skript in {bereich}")

    def test_datenbank_verbirgt_geheimnisse(self):
        a = self.dash.get("/dashboard/datenbank/tabelle/users")
        self.assertEqual(a.status_code, 200)
        self.assertIn("verborgen", a.text)
        self.assertNotIn("$2b$", a.text, "Ein Passwort-Hash ist sichtbar!")

    def test_schreiben_ohne_csrf_wird_abgelehnt(self):
        a = self.dash.post("/dashboard/aufgaben",
                           data={"titel": "X", "person": "1", "csrf": "falsch"})
        self.assertEqual(a.status_code, 400)

    def test_aufgabe_braucht_zuteilung(self):
        token = hilfe.csrf_aus(self.dash.get("/dashboard/aufgaben").text)
        a = self.dash.post("/dashboard/aufgaben",
                           data={"titel": "Ohne alles", "csrf": token})
        self.assertIn("fühlt sich niemand", a.text)

    def test_datenexport(self):
        a = self.dash.get("/dashboard/mein-konto/meine-daten.json")
        self.assertEqual(a.status_code, 200)
        self.assertIn("konto", a.json())


class TestAufgabenSichtbarkeit(unittest.TestCase):
    """Die Regel steht zweimal im Code - als Datenbankfilter und als
    Einzelprüfung. Beide müssen dasselbe sagen."""

    def setUp(self):
        hilfe.frische_datenbank()
        from kern.datenbank import SessionLocal
        from kern.modelle import Task, User
        from kern.sicherheit import passwort_hashen

        self.db = SessionLocal()
        self.db.query(Task).delete()
        self.db.query(User).filter(User.email.like("s-%")).delete()
        self.db.commit()

        def person(kennung, rolle, abteilung):
            p = User(vorname=kennung, nachname="Test", email=f"s-{kennung}@ag.local",
                     password_hash=passwort_hashen("Egal12345678Aa"),
                     role=rolle, department=abteilung, status="aktiv")
            self.db.add(p)
            return p

        self.chef = person("chef", "ceo", "tech")
        self.tech = person("tech", "member", "tech")
        self.markt = person("markt", "member", "marketing")
        self.db.commit()

        self.aufgaben = [
            Task(titel="Für Tech-Person", assignee_id=self.tech.id,
                 task_department="tech", creator_id=self.chef.id),
            Task(titel="Für Marketing-Abteilung", assignee_department="marketing",
                 task_department="marketing", creator_id=self.chef.id),
            Task(titel="Für Tech-Abteilung", assignee_department="tech",
                 task_department="tech", creator_id=self.chef.id),
            Task(titel="Chef privat", assignee_id=self.chef.id,
                 task_department="exekutive", creator_id=self.chef.id),
        ]
        self.db.add_all(self.aufgaben)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_filter_und_einzelpruefung_sind_sich_einig(self):
        from kern.aufgaben import darf_sehen, sichtbar_filter
        from kern.modelle import Task

        for person in (self.chef, self.tech, self.markt):
            with self.subTest(person=person.vorname):
                aus_filter = {t.id for t in self.db.query(Task).filter(
                    sichtbar_filter(person, self.db)).all()}
                aus_pruefung = {t.id for t in self.db.query(Task).all()
                                if darf_sehen(person, t, self.db)}
                self.assertEqual(aus_filter, aus_pruefung)

    def test_mitglied_sieht_fremde_abteilung_nicht(self):
        from kern.aufgaben import darf_sehen
        fremd = [t for t in self.aufgaben if t.titel == "Für Marketing-Abteilung"][0]
        self.assertFalse(darf_sehen(self.tech, fremd, self.db))
        self.assertTrue(darf_sehen(self.markt, fremd, self.db))

    def test_leitung_sieht_eigene_abteilung(self):
        from kern.aufgaben import darf_sehen
        tech_sache = [t for t in self.aufgaben if t.titel == "Für Tech-Abteilung"][0]
        self.assertTrue(darf_sehen(self.chef, tech_sache, self.db))

    def test_exekutive_bleibt_privat(self):
        """Sonst läge die Arbeit jedes Vorstandsmitglieds vor dem ganzen
        übrigen Vorstand offen - jede C-Rolle ist für die Exekutive zuständig."""
        from kern.aufgaben import darf_sehen
        from kern.datenbank import SessionLocal
        from kern.modelle import Task, User
        from kern.sicherheit import passwort_hashen

        zweiter = User(vorname="zweit", nachname="Chef", email="s-zweit@ag.local",
                       password_hash=passwort_hashen("Egal12345678Aa"),
                       role="coo", department="marketing", status="aktiv")
        self.db.add(zweiter)
        self.db.commit()
        privat = [t for t in self.aufgaben if t.titel == "Chef privat"][0]
        self.assertFalse(darf_sehen(zweiter, privat, self.db))


if __name__ == "__main__":
    unittest.main()
