"""Was im Betrieb schon einmal kaputt war - damit es das nicht wieder wird.

Jeder Test hier steht für einen Fehler, den jemand gemeldet hat.
"""

import unittest
import unittest.mock

from tests import hilfe                                      # noqa: F401

from kern.datenbank import SessionLocal
from kern.modelle import PushSubscription, Task, TrashItem, User
from kern.text import utcnow
from tests.hilfe import angemeldeter_client, csrf_aus


class TestAufgaben(unittest.TestCase):
    """Löschen ging nicht, und Person UND Abteilung waren gleichzeitig wählbar."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def _csrf(self):
        return csrf_aus(self.dash.get("/dashboard/aufgaben").text)

    def test_loeschknopf_steckt_in_keinem_formular(self):
        """Ein <form> im <form> wirft der Browser weg - dann speichert der
        Knopf, statt zu löschen. Genau das war der Fehler."""
        text = self.dash.get("/dashboard/aufgaben").text
        self.assertNotRegex(text.replace("\n", " "), r"<form[^>]*>(?:(?!</form>).)*<form",
                            "verschachteltes Formular in der Aufgabenliste")

    def test_aufgabe_anlegen_und_loeschen(self):
        csrf = self._csrf()
        self.dash.post("/dashboard/aufgaben",
                       data={"titel": "Testaufgabe Löschen", "zustaendig": "a:tech",
                             "csrf": csrf})
        db = SessionLocal()
        aufgabe = db.query(Task).filter(Task.titel == "Testaufgabe Löschen").first()
        self.assertIsNotNone(aufgabe, "Aufgabe wurde nicht angelegt")
        self.assertEqual(aufgabe.assignee_department, "tech")
        self.assertIsNone(aufgabe.assignee_id, "Abteilung UND Person gesetzt")
        aufgaben_id = aufgabe.id
        db.close()

        antwort = self.dash.post(f"/dashboard/aufgaben/{aufgaben_id}/loeschen",
                                 data={"csrf": csrf})
        self.assertEqual(antwort.status_code, 200)
        db = SessionLocal()
        self.assertIsNone(db.get(Task, aufgaben_id), "Aufgabe liegt noch da")
        eintraege = db.query(TrashItem).filter(
            TrashItem.label.like("%Testaufgabe Löschen%")).all()
        self.assertEqual(len(eintraege), 1, "nicht im Papierkorb gelandet")
        # Aufräumen: alle Tests teilen sich eine Datenbank, und andernorts wird
        # geprüft, dass der Papierkorb leer ist.
        for e in eintraege:
            db.delete(e)
        db.commit()
        db.close()

    def test_zuteilung_ist_entweder_oder(self):
        """Ein einziges Auswahlfeld - zwei nebeneinander liessen beides zu."""
        text = self.dash.get("/dashboard/aufgaben").text
        self.assertIn('name="zustaendig"', text)
        self.assertNotIn('name="abteilung"', text)
        self.assertNotIn('<select name="person"', text)

    def test_person_setzt_abteilung_zurueck(self):
        csrf = self._csrf()
        db = SessionLocal()
        person = db.query(User).filter(User.status == "aktiv").first()
        person_id = person.id
        db.close()
        self.dash.post("/dashboard/aufgaben",
                       data={"titel": "Nur eine Person", "zustaendig": f"p:{person_id}",
                             "csrf": csrf})
        db = SessionLocal()
        aufgabe = db.query(Task).filter(Task.titel == "Nur eine Person").first()
        self.assertEqual(aufgabe.assignee_id, person_id)
        self.assertIsNone(aufgabe.assignee_department)
        db.close()

    def test_suchleiste_ist_da(self):
        text = self.dash.get("/dashboard/aufgaben").text
        self.assertIn('data-suche="#aufgaben-liste"', text)
        self.assertIn("data-suchbar", text)


class TestGeschwindigkeit(unittest.TestCase):
    """Die WhatsApp-Seite hing an einer Steckverbindung."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_whatsapp_zustand_wird_zwischengespeichert(self):
        """web_zustand() darf beim Rendern nicht auf den Dienst warten.

        Die Abfrage selbst darf laufen - aber in einem anderen Faden. Genau
        daran hingen vier Sekunden auf der WhatsApp-Seite und je zwei auf
        Sicherheit und Datenbank, wenn der Dienst nicht lief.
        """
        import threading
        import time
        from kern import whatsapp

        faeden = []

        def gemerkt(*args, **rest):
            faeden.append(threading.current_thread().name)
            time.sleep(0.05)
            return {"zustand": "aus", "meldung": "Test", "qr": "", "nummer": None}

        with unittest.mock.patch.object(whatsapp, "modus", return_value="web"), \
                unittest.mock.patch.object(whatsapp, "_web_zustand_holen", gemerkt):
            whatsapp._web_stand["wert"] = None
            whatsapp._web_stand["zeit"] = 0.0
            begonnen = time.monotonic()
            erste = whatsapp.web_zustand()
            gedauert = time.monotonic() - begonnen

            self.assertEqual(erste["zustand"], "pruefung")
            self.assertLess(gedauert, 0.03, "der Aufruf hat gewartet")
            time.sleep(0.2)                      # dem Hintergrund Zeit geben
            self.assertEqual(faeden, ["whatsapp-zustand"],
                             "die Abfrage lief nicht im Hintergrund")
            # Jetzt liegt der Wert bereit und wird ohne neue Abfrage geliefert.
            self.assertEqual(whatsapp.web_zustand()["zustand"], "aus")
            self.assertEqual(len(faeden), 1, "es wurde erneut gefragt")

        whatsapp._web_stand["wert"] = None
        whatsapp._web_stand["zeit"] = 0.0

    def test_konten_liefert_keine_rechtetafel_je_person(self):
        """283 KB waren es, weil jede Person die ganze Tafel mitbekam."""
        text = self.dash.get("/dashboard/konten").text
        self.assertIn("/rechte", text, "Nachladen der Rechte fehlt")
        self.assertLess(len(text), 120_000, "Kontenseite ist wieder zu gross")


class TestPushBeideSeiten(unittest.TestCase):
    """Angemeldet wird nur noch im Dashboard.

    Frueher bot auch die oeffentliche Seite einen Knopf an - eine Anmeldung
    gilt schliesslich nur fuer den Ursprung, auf dem sie erteilt wurde. In der
    Praxis hat das mehr verwirrt als genuetzt: zwei Knoepfe, zwei Zustaende,
    und eine Liste unter "Das fehlt noch bei dir", die nie leer wurde.

    Bestehende Anmeldungen von der oeffentlichen Seite bleiben gueltig und
    stellen weiter zu - eine Push-Adresse haengt am Geraet, nicht an der
    Seite, die sie einmal erzeugt hat.
    """

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_die_oeffentliche_seite_bietet_keine_anmeldung_mehr(self):
        for weg in ("/benachrichtigungen", "/push-schluessel"):
            with self.subTest(weg):
                self.assertEqual(self.web.get(weg).status_code, 404)

    def test_und_nimmt_auch_keine_mehr_entgegen(self):
        self.assertEqual(
            self.web.post("/push-anmelden", data={"endpoint": "https://x"})
            .status_code, 404)

    def test_das_dashboard_kann_es_weiterhin(self):
        seite = self.dash.get("/dashboard/nachrichten")
        self.assertEqual(seite.status_code, 200)
        self.assertIn("push-anmelden", seite.text)

    def test_alte_anmeldungen_von_der_website_stellen_weiter_zu(self):
        from kern import push
        db = SessionLocal()
        person = db.query(User).filter(User.email == "pruef@ag.local").first()
        db.query(PushSubscription).filter(
            PushSubscription.user_id == person.id).delete()
        db.add(PushSubscription(user_id=person.id, endpoint="https://push/alt",
                                p256dh="x", auth="y", ursprung="website"))
        db.commit()
        self.assertEqual(len(push.empfaenger(db, person.id)), 1)
        db.close()

    def test_anmeldung_auf_beiden_seiten_zaehlt_als_ein_geraet(self):
        from kern import push
        db = SessionLocal()
        person = db.query(User).filter(User.email == "pruef@ag.local").first()
        db.query(PushSubscription).filter(
            PushSubscription.user_id == person.id).delete()
        for name, ursprung in (("A", "website"), ("B", "dashboard")):
            db.add(PushSubscription(user_id=person.id, endpoint=f"https://push/{name}",
                                    p256dh="x", auth="y", ursprung=ursprung,
                                    geraete_id="dasselbe-handy"))
        # Ein zweites, echtes Gerät mit eigener Kennung.
        db.add(PushSubscription(user_id=person.id, endpoint="https://push/C",
                                p256dh="x", auth="y", ursprung="dashboard",
                                geraete_id="anderes-handy"))
        db.commit()

        alle = push.geraete(db, person.id)
        ziele = push.empfaenger(db, person.id)
        db.close()
        self.assertEqual(len(alle), 3)
        self.assertEqual(len(ziele), 2, "dasselbe Handy bekäme die Meldung doppelt")

    def test_alte_anmeldungen_ohne_kennung_bleiben_erreichbar(self):
        """Aus V1 übernommene Geräte haben keine Kennung - sie zählen einzeln."""
        from kern import push
        db = SessionLocal()
        person = db.query(User).filter(User.email == "pruef@ag.local").first()
        db.query(PushSubscription).filter(
            PushSubscription.user_id == person.id).delete()
        for name in ("alt1", "alt2"):
            db.add(PushSubscription(user_id=person.id, endpoint=f"https://push/{name}",
                                    p256dh="x", auth="y"))
        db.commit()
        self.assertEqual(len(push.empfaenger(db, person.id)), 2)
        db.close()


class TestCookieBereich(unittest.TestCase):
    """Zwei Namen derselben Domain brauchen ein Domain-Cookie."""

    def test_gemeinsame_domain(self):
        from kern.einstellungen import _gemeinsame_domain as g
        self.assertEqual(g("https://mvlg-wag.de", "https://app.mvlg-wag.de"),
                         ".mvlg-wag.de")
        self.assertEqual(g("https://mvlg-wag.de", "https://mvlg-wag.de/dashboard"), "")
        self.assertEqual(g("http://localhost:8000", "http://localhost:8001"), "")
        self.assertEqual(g("https://mvlg-wag.de", "https://fremde-seite.de"), "")


class TestKeineFremdenServer(unittest.TestCase):
    """Die Seite soll ohne Verbindung zu Dritten auskommen."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_keine_fremden_quellen_im_html(self):
        for klient, pfad in ((self.web, "/"), (self.dash, "/")):
            text = klient.get(pfad).text
            for fremd in ("fonts.googleapis.com", "fonts.gstatic.com",
                          "cdn.jsdelivr.net", "unpkg.com"):
                self.assertNotIn(fremd, text, f"{pfad} lädt von {fremd}")

    def test_richtlinie_erlaubt_keine_fremden_schriften(self):
        kopf = self.web.get("/").headers.get("Content-Security-Policy", "")
        self.assertIn("font-src 'self'", kopf)
        self.assertNotIn("fonts.gstatic.com", kopf)


if __name__ == "__main__":
    unittest.main()


class TestWegeZurueck(unittest.TestCase):
    """Was passiert, nachdem jemand etwas falsch gemacht hat?"""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_nach_dem_loeschen_fuehrt_ein_knopf_in_den_papierkorb(self):
        """Wer versehentlich löscht, soll nicht suchen müssen."""
        csrf = csrf_aus(self.dash.get("/dashboard/aufgaben").text)
        self.dash.post("/dashboard/aufgaben",
                       data={"titel": "Weg-zurück-Probe", "zustaendig": "a:tech",
                             "csrf": csrf})
        db = SessionLocal()
        aufgabe = db.query(Task).filter(Task.titel == "Weg-zurück-Probe").first()
        aufgaben_id = aufgabe.id
        db.close()
        antwort = self.dash.post(f"/dashboard/aufgaben/{aufgaben_id}/loeschen",
                                 data={"csrf": csrf})
        self.assertIn('data-springe="papierkorb"', antwort.text,
                      "kein Weg zurück in der Meldung")
        db = SessionLocal()
        for e in db.query(TrashItem).filter(
                TrashItem.label.like("%Weg-zurück-Probe%")).all():
            db.delete(e)
        db.commit()
        db.close()

    def test_startpasswort_wird_angesprochen(self):
        """Wer sein Passwort nie selbst gesetzt hat, wird darauf hingewiesen."""
        db = SessionLocal()
        person = db.query(User).filter(User.email == "pruef@ag.local").first()
        vorher = person.passwort_geaendert_am
        person.passwort_geaendert_am = None
        db.commit()
        db.close()
        text = self.dash.get("/dashboard/uebersicht").text
        self.assertIn("Startpasswort", text)

        db = SessionLocal()
        person = db.query(User).filter(User.email == "pruef@ag.local").first()
        person.passwort_geaendert_am = utcnow()
        db.commit()
        db.close()
        self.assertNotIn("Startpasswort", self.dash.get("/dashboard/uebersicht").text,
                         "Der Hinweis bleibt stehen, obwohl das Passwort geändert wurde")
        db = SessionLocal()
        person = db.query(User).filter(User.email == "pruef@ag.local").first()
        person.passwort_geaendert_am = vorher
        db.commit()
        db.close()

    def test_abgelaufene_anmeldung_wirft_niemanden_sofort_hinaus(self):
        from fastapi.testclient import TestClient
        from dashboard.app import app as dash_app
        ohne = TestClient(dash_app)
        antwort = ohne.get("/dashboard/aufgaben", headers={"HX-Request": "true"})
        self.assertEqual(antwort.status_code, 401)
        self.assertNotIn("HX-Redirect", antwort.headers,
                         "Die Seite springt weg und nimmt die Eingabe mit")
        self.assertIn("kopier", antwort.text.lower())


class TestListeBleibtUebersichtlich(unittest.TestCase):
    """Erledigtes darf sich nicht ewig ansammeln."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_altes_erledigtes_wird_ausgeblendet_aber_nicht_versteckt(self):
        from datetime import timedelta
        from kern.aufgaben import ERLEDIGT_SICHTBAR_TAGE
        db = SessionLocal()
        person = db.query(User).filter(User.email == "pruef@ag.local").first()
        alt = Task(titel="Uraltes Erledigtes", assignee_id=person.id,
                   task_department="exekutive", status="erledigt",
                   creator_id=person.id,
                   completed_at=utcnow() - timedelta(days=ERLEDIGT_SICHTBAR_TAGE + 10))
        neu = Task(titel="Frisch Erledigtes", assignee_id=person.id,
                   task_department="exekutive", status="erledigt",
                   creator_id=person.id, completed_at=utcnow())
        db.add_all([alt, neu])
        db.commit()
        alt_id, neu_id = alt.id, neu.id
        db.close()

        text = self.dash.get("/dashboard/aufgaben").text
        self.assertIn("Frisch Erledigtes", text)
        self.assertNotIn("Uraltes Erledigtes", text,
                         "alles Erledigte wird weiter mitgeschleppt")
        self.assertIn("ausgeblendet", text, "kein Hinweis auf die Ausgeblendeten")

        alles = self.dash.get("/dashboard/aufgaben?alles=1").text
        self.assertIn("Uraltes Erledigtes", alles,
                      "auch mit alles=1 nicht zu finden - das wäre Datenverlust")

        db = SessionLocal()
        for kennung in (alt_id, neu_id):
            db.delete(db.get(Task, kennung))
        db.commit()
        db.close()

    def test_anlegen_formular_bleibt_nach_dem_speichern_offen(self):
        """Nach einer Sitzung trägt man selten nur eine Aufgabe ein."""
        csrf = csrf_aus(self.dash.get("/dashboard/aufgaben").text)
        antwort = self.dash.post("/dashboard/aufgaben",
                                 data={"titel": "Erste von mehreren",
                                       "zustaendig": "a:tech", "csrf": csrf})
        self.assertRegex(antwort.text, r'<details class="block"\s+open>')
        db = SessionLocal()
        aufgabe = db.query(Task).filter(Task.titel == "Erste von mehreren").first()
        db.delete(aufgabe)
        db.commit()
        db.close()

    def test_leerer_bereich_zeigt_den_weg(self):
        """Ein leerer Bereich soll sagen, wie man ihn füllt."""
        text = self.dash.get("/dashboard/anwesenheit").text
        if "Noch nichts erfasst" in text:
            self.assertIn("data-anlegen", text)
