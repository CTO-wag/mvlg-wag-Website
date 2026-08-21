"""Der Rundgang nach dem Umzug - und die Liste, die bleibt, bis er wirkt.

Geprüft wird das, worauf es fachlich ankommt:

* Die Schritte sind persönlich. Wer seinen Kalender schon neu eingetragen
  hat, darf nicht lesen, dass er ihn neu eintragen soll.
* Die offenen Punkte verschwinden von selbst, sobald sie erledigt sind -
  ohne dass jemand einen Haken setzen muss. Ein Haken zum Selbstsetzen wäre
  eine Lüge in dem Moment, in dem jemand ihn zu früh anklickt.
* Die Einladung kommt nicht zusätzlich zum Erst-Rundgang.
"""

import unittest
from datetime import timedelta

from tests import hilfe                                      # noqa: F401

from kern import umzug
from kern.datenbank import SessionLocal
from kern.modelle import PushSubscription, User, UserPreference
from tests.hilfe import angemeldeter_client, csrf_aus


def _person(db):
    return db.query(User).filter(User.email == "pruef@ag.local").first()


def _vorlieben(db, user_id):
    v = db.query(UserPreference).filter(
        UserPreference.user_id == user_id).first()
    if not v:
        v = UserPreference(user_id=user_id)
        db.add(v)
        db.commit()
    return v


class TestUmzugsstand(unittest.TestCase):
    """kern/umzug.py: Was ist erledigt, was nicht."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def setUp(self):
        db = SessionLocal()
        person = _person(db)
        person.calendar_last_fetch = None
        _vorlieben(db, person.id).als_app_am = None
        db.query(PushSubscription).filter(
            PushSubscription.user_id == person.id).delete()
        db.commit()
        db.close()

    def test_ohne_alles_sind_drei_punkte_offen(self):
        """Der Startbildschirm steht vorn - ohne ihn geht Push auf dem iPhone
        gar nicht, und wer zuerst vergeblich drückt, gibt danach auf."""
        db = SessionLocal()
        punkte = umzug.offene_punkte(db, _person(db))
        db.close()
        self.assertEqual([p["schluessel"] for p in punkte],
                         ["startbildschirm", "kalender", "push"])

    def test_app_start_erledigt_den_startbildschirm(self):
        db = SessionLocal()
        person = _person(db)
        erstmals = umzug.als_app_vermerken(db, person)
        offen = [p["schluessel"] for p in umzug.offene_punkte(db, person)]
        db.close()
        self.assertTrue(erstmals)
        self.assertNotIn("startbildschirm", offen)

    def test_kalenderabruf_erledigt_den_punkt(self):
        db = SessionLocal()
        person = _person(db)
        person.calendar_last_fetch = umzug.UMZUG_AB + timedelta(hours=1)
        db.commit()
        punkte = umzug.offene_punkte(db, person)
        db.close()
        self.assertEqual([p["schluessel"] for p in punkte],
                         ["startbildschirm", "push"])

    def test_alter_abruf_zaehlt_nicht(self):
        """Ein Abruf von vor dem Umzug betraf die alte Adresse."""
        db = SessionLocal()
        person = _person(db)
        person.calendar_last_fetch = umzug.UMZUG_AB - timedelta(days=3)
        db.commit()
        offen = [p["schluessel"] for p in umzug.offene_punkte(db, person)]
        db.close()
        self.assertIn("kalender", offen)

    def test_alte_push_anmeldung_zaehlt_nicht(self):
        db = SessionLocal()
        person = _person(db)
        db.add(PushSubscription(
            user_id=person.id, endpoint="https://push.test/alt", p256dh="k",
            auth="a", ursprung="dashboard",
            created_at=umzug.UMZUG_AB - timedelta(days=5)))
        db.commit()
        stand = umzug.push_stand(db, person)
        db.close()
        self.assertFalse(stand["dashboard"])
        self.assertEqual(len(stand["alte"]), 1)

    def test_dashboard_allein_raeumt_den_push_punkt_weg(self):
        """Die oeffentliche Seite wird nicht mehr verlangt: Von dort kommt
        nichts, was nicht auch im Dashboard steht. Eine Liste, die man nie
        leer bekommt, liest irgendwann niemand mehr."""
        db = SessionLocal()
        person = _person(db)
        db.add(PushSubscription(
            user_id=person.id, endpoint="https://push.test/dashboard",
            p256dh="k", auth="a", ursprung="dashboard",
            created_at=umzug.UMZUG_AB + timedelta(hours=2)))
        person.calendar_last_fetch = umzug.UMZUG_AB + timedelta(hours=2)
        umzug.als_app_vermerken(db, person)
        stand = umzug.stand_fuer(db, person)
        db.close()
        self.assertTrue(stand["fertig"], stand["offen"])
        self.assertEqual(stand["offen"], [])


class TestAusweg(unittest.TestCase):
    """Eine Aufforderung, die man nicht erfüllen kann, lernt man zu übersehen."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def setUp(self):
        db = SessionLocal()
        person = _person(db)
        person.calendar_last_fetch = None
        v = _vorlieben(db, person.id)
        v.umzug_ohne_kalender = 0
        db.commit()
        db.close()

    def tearDown(self):
        self.setUp()

    def test_wer_keinen_kalender_will_wird_nicht_erinnert(self):
        db = SessionLocal()
        v = _vorlieben(db, _person(db).id)
        v.umzug_ohne_kalender = 1
        db.commit()
        offen = [p["schluessel"] for p in umzug.offene_punkte(db, _person(db))]
        db.close()
        self.assertNotIn("kalender", offen)

    def test_knopf_waehlt_den_punkt_ab(self):
        import re
        # Der Knopf sitzt in der Übersicht und trägt sein Token in hx-vals -
        # es gibt dort kein Formular, aus dem sich eines lesen liesse.
        seite = self.dash.get("/dashboard/uebersicht").text
        self.assertIn("ohne-kalender", seite, "Abwahl-Knopf fehlt")
        csrf = re.search(r'hx-vals=.\{"csrf": "([^"]+)"', seite).group(1)
        antwort = self.dash.post("/dashboard/neuerungen/ohne-kalender",
                                 data={"csrf": csrf})
        self.assertEqual(antwort.status_code, 200)
        self.assertNotIn("Kalender neu eintragen", antwort.text)
        db = SessionLocal()
        self.assertEqual(_vorlieben(db, _person(db).id).umzug_ohne_kalender, 1)
        db.close()

    def test_wer_push_abgeschaltet_hat_wird_nicht_erinnert(self):
        from kern import benachrichtigung
        db = SessionLocal()
        person = _person(db)
        pref = benachrichtigung.einstellung(db, person.id)
        pref.webpush = 0
        db.commit()
        offen = [p["schluessel"] for p in umzug.offene_punkte(db, person)]
        pref.webpush = 1
        db.commit()
        db.close()
        self.assertNotIn("push", offen)


class TestStartpasswortHinweis(unittest.TestCase):
    """Ein Rat, keine Vorschrift - man muss ihn abstellen koennen."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def setUp(self):
        db = SessionLocal()
        person = _person(db)
        person.passwort_geaendert_am = None
        _vorlieben(db, person.id).startpasswort_egal = 0
        db.commit()
        db.close()

    def tearDown(self):
        self.setUp()

    def test_hinweis_steht_zuerst_da(self):
        self.assertIn("Du benutzt noch dein Startpasswort",
                      self.dash.get("/dashboard/uebersicht").text)

    def test_ich_behalte_meins_stellt_ihn_ab(self):
        import re
        seite = self.dash.get("/dashboard/uebersicht").text
        self.assertIn("passwort-behalten", seite, "Abwahl-Knopf fehlt")
        csrf = re.search(
            r'hx-post="/dashboard/hinweis/passwort-behalten"\s*'
            r'hx-vals=.\{"csrf": "([^"]+)"', seite).group(1)
        antwort = self.dash.post("/dashboard/hinweis/passwort-behalten",
                                 data={"csrf": csrf})
        self.assertEqual(antwort.status_code, 200)
        self.assertNotIn("Du benutzt noch dein Startpasswort", antwort.text)
        # Und auch beim naechsten Aufruf nicht wieder.
        self.assertNotIn("Du benutzt noch dein Startpasswort",
                         self.dash.get("/dashboard/uebersicht").text)

    def test_passwort_aendern_stellt_ihn_ebenfalls_ab(self):
        db = SessionLocal()
        from kern.text import utcnow
        _person(db).passwort_geaendert_am = utcnow()
        db.commit()
        db.close()
        self.assertNotIn("Du benutzt noch dein Startpasswort",
                         self.dash.get("/dashboard/uebersicht").text)


class TestSchritte(unittest.TestCase):
    """Die Schritte selbst - persönlich, nicht als Rundschreiben."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def _holen(self):
        antwort = self.dash.get("/dashboard/neuerungen")
        self.assertEqual(antwort.status_code, 200)
        return antwort.json()

    def _text(self, schritte) -> str:
        import json
        return json.dumps(schritte, ensure_ascii=False)

    def test_spricht_die_person_mit_namen_an(self):
        self.assertIn("Pruef", self._holen()[0]["titel"])

    def test_enthaelt_die_eigene_kalenderadresse(self):
        db = SessionLocal()
        person = _person(db)
        marke = person.calendar_token
        db.close()
        if marke:
            self.assertIn(marke, self._text(self._holen()))
        else:
            # Wird beim ersten Aufruf erzeugt - dann muss sie danach drinstehen.
            self.assertIn(".ics", self._text(self._holen()))

    def test_enthaelt_das_eigene_ntfy_thema(self):
        from kern import benachrichtigung
        db = SessionLocal()
        thema = benachrichtigung.einstellung(db, _person(db).id).topic
        db.close()
        self.assertIn(thema, self._text(self._holen()))

    def _hinweise(self, teiltitel: str) -> str:
        """Die Hinweiskästen genau eines Schrittes.

        Vorher suchte dieser Test im ganzen Rundgang nach einer Wendung. Das
        ging jahrelang gut und war trotzdem falsch: Getroffen hat er den
        Push-Schritt, nicht den Kalender. Als der Push-Text umformuliert
        wurde, schlug ein Kalender-Test fehl - und zeigte damit auf die
        falsche Stelle.
        """
        for schritt in self._holen():
            if teiltitel in schritt["titel"]:
                return " ".join(t.get("text", "") for t in schritt["teile"]
                                if t.get("art") == "hinweis")
        self.fail(f"Schritt mit „{teiltitel}“ fehlt im Rundgang")

    def test_kalenderschritt_kennt_den_eigenen_stand(self):
        db = SessionLocal()
        person = _person(db)
        person.calendar_last_fetch = None
        db.commit()
        db.close()
        self.assertIn("steht das noch aus", self._hinweise("Kalender"))

        db = SessionLocal()
        person = _person(db)
        person.calendar_last_fetch = umzug.UMZUG_AB + timedelta(hours=1)
        db.commit()
        db.close()
        self.assertIn("erledigt", self._hinweise("Kalender"))

        db = SessionLocal()
        _person(db).calendar_last_fetch = None
        db.commit()
        db.close()

    def test_die_einleitung_zaehlt_richtig(self):
        """Der Satz nannte fest „zwei Handgriffe“, sobald es mehr als einer
        war. Wer merkt, dass die Anlage ihm etwas Falsches erzählt, glaubt
        ihr auch beim nächsten Satz nicht mehr."""
        from kern import umzug
        db = SessionLocal()
        person = _person(db)
        person.calendar_last_fetch = None
        _vorlieben(db, person.id).als_app_am = None
        _vorlieben(db, person.id).umzug_ohne_kalender = 0
        db.query(PushSubscription).filter(
            PushSubscription.user_id == person.id).delete()
        db.commit()
        anzahl = len(umzug.offene_punkte(db, person))
        db.close()
        self.assertEqual(anzahl, 3)
        einleitung = self._text(self._holen()[0])
        self.assertIn("Drei Handgriffe", einleitung)

    def test_startbildschirm_steht_vor_den_benachrichtigungen(self):
        """Auf dem iPhone ist er die Voraussetzung - wer zuerst vergeblich
        auf „anmelden“ drückt, hält die Anlage danach für kaputt."""
        titel = [s["titel"] for s in self._holen()]
        app = next(i for i, x in enumerate(titel) if "Startbildschirm" in x)
        push = next(i for i, x in enumerate(titel) if "Benachrichtigungen" in x)
        self.assertLess(app, push)

    def test_pushschritt_verlangt_nur_noch_das_dashboard(self):
        for schritt in self._holen():
            if "Benachrichtigungen" in schritt["titel"]:
                text = self._text(schritt)
                self.assertNotIn("meldest du am besten beide an", text)
                # Auf der oeffentlichen Seite gibt es gar keinen Knopf mehr.
                self.assertIn("nur noch hier", text)
                return
        self.fail("Push-Schritt fehlt")

    def test_nennt_beide_adressen(self):
        text = self._text(self._holen())
        self.assertIn("localhost:8000", text)
        self.assertIn("localhost:8001", text)

    def test_ohne_anmeldung_kein_zugriff(self):
        from fastapi.testclient import TestClient
        from dashboard.app import app as dash
        with TestClient(dash) as ohne:
            antwort = ohne.get("/dashboard/neuerungen", follow_redirects=False)
        self.assertIn(antwort.status_code, (303, 401))


class TestRundgangKenntDieNeuenSachen(unittest.TestCase):
    """Der Rundgang muss mitwachsen - sonst erklärt er einen Stand, den es
    nicht mehr gibt."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def _text(self):
        import json
        return json.dumps(self.dash.get("/dashboard/neuerungen").json(),
                          ensure_ascii=False)

    def test_nennt_zusage_und_tagesordnung(self):
        text = self._text()
        self.assertIn("absagen", text)
        self.assertIn("Tagesordnung", text)

    def test_nennt_die_erinnerungen(self):
        self.assertIn("Erinnerungen", self._text())

    def test_sagt_dass_die_ruhezeiten_weg_sind(self):
        self.assertIn("Ruhezeiten", self._text())

    def test_ersatzcode_schritt_nur_wer_ihn_braucht(self):
        """Wer den zweiten Faktor aus hat, soll darüber nichts lesen."""
        db = SessionLocal()
        person = _person(db)
        person.totp_aktiv, person.totp_secret = 0, None
        person.totp_ersatzcodes = None
        db.commit()
        db.close()
        self.assertNotIn("Hol dir Ersatzcodes", self._text())

        db = SessionLocal()
        person = _person(db)
        person.totp_aktiv, person.totp_secret = 1, "JBSWY3DPEHPK3PXP"
        person.totp_ersatzcodes = None
        db.commit()
        db.close()
        self.assertIn("Hol dir Ersatzcodes", self._text(),
                      "wer keine Ersatzcodes hat, erfährt es nicht")

        # Und wer welche hat, wird nicht mehr behelligt.
        from kern.sicherheit import ersatzcodes_erzeugen
        db = SessionLocal()
        person = _person(db)
        _, gespeichert = ersatzcodes_erzeugen()
        person.totp_ersatzcodes = gespeichert
        db.commit()
        db.close()
        self.assertNotIn("Hol dir Ersatzcodes", self._text())

        db = SessionLocal()
        person = _person(db)
        person.totp_aktiv, person.totp_secret = 0, None
        person.totp_ersatzcodes = None
        db.commit()
        db.close()

    def test_verwaltungssachen_nur_fuer_verwalter(self):
        """Ein Mitglied ohne Rechte liest nichts über das Einspielen von
        Sicherungen - das kann es ohnehin nicht."""
        from kern.sicherheit import passwort_hashen
        from tests.hilfe import TESTPASSWORT
        from fastapi.testclient import TestClient
        from website.app import app as web_app
        from dashboard.app import app as dash_app
        db = SessionLocal()
        einfach = db.query(User).filter(User.email == "einfach@ag.local").first()
        if not einfach:
            einfach = User(vorname="Einfach", nachname="Mitglied",
                           email="einfach@ag.local",
                           password_hash=passwort_hashen(TESTPASSWORT),
                           role="member", department="tech", status="aktiv")
            db.add(einfach)
            db.commit()
        db.close()
        with TestClient(web_app) as w:
            token = csrf_aus(w.get("/login").text)
            w.post("/login", data={"email": "einfach@ag.local",
                                   "passwort": TESTPASSWORT, "csrf": token},
                   follow_redirects=False)
            kekse = dict(w.cookies)
        import json
        schritte = TestClient(dash_app, cookies=kekse).get(
            "/dashboard/neuerungen").json()
        text = json.dumps(schritte, ensure_ascii=False)
        self.assertIn("AG-Treffen", text, "die gemeinsamen Sachen fehlen")
        self.assertNotIn("Sicherungen:", text)
        self.assertNotIn("Zweiter Faktor zurücksetzen", text)

    def test_fassung_wurde_hochgezaehlt(self):
        """Ohne neue Fassung bekommt den überarbeiteten Rundgang niemand
        zu sehen, der den alten schon abgehakt hatte."""
        self.assertNotEqual(umzug.FASSUNG, "2026-08-umzug")


class TestEinladung(unittest.TestCase):
    """Wann die Einladung erscheint - und wann eben nicht."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def _setzen(self, **werte):
        db = SessionLocal()
        v = _vorlieben(db, _person(db).id)
        for name, wert in werte.items():
            setattr(v, name, wert)
        v.neuerungen_version = umzug.FASSUNG
        db.commit()
        db.close()

    def test_nicht_neben_dem_ersten_rundgang(self):
        """Zwei Einladungen übereinander sind eine zu viel."""
        from dashboard.routen.neuerungen import faellig
        self._setzen(tutorial_erledigt=0, tutorial_gefragt=0,
                     neuerungen_erledigt=0, neuerungen_gefragt=0)
        db = SessionLocal()
        self.assertFalse(faellig(db, _person(db)))
        db.close()

    def test_nach_dem_ersten_rundgang_schon(self):
        from dashboard.routen.neuerungen import faellig
        self._setzen(tutorial_erledigt=1, neuerungen_erledigt=0,
                     neuerungen_gefragt=0)
        db = SessionLocal()
        self.assertTrue(faellig(db, _person(db)))
        db.close()

    def test_hoechstens_dreimal_fragen(self):
        from dashboard.routen.neuerungen import faellig, MAX_FRAGEN
        self._setzen(tutorial_erledigt=1, neuerungen_erledigt=0,
                     neuerungen_gefragt=MAX_FRAGEN)
        db = SessionLocal()
        self.assertFalse(faellig(db, _person(db)))
        db.close()

    def test_gesehen_beendet_die_einladung(self):
        from dashboard.routen.neuerungen import faellig
        self._setzen(tutorial_erledigt=1, neuerungen_erledigt=0,
                     neuerungen_gefragt=0)
        csrf = csrf_aus(self.dash.get("/dashboard/mein-konto").text)
        antwort = self.dash.post("/dashboard/neuerungen/gesehen",
                                 data={"erledigt": "1", "csrf": csrf})
        self.assertEqual(antwort.status_code, 200)
        db = SessionLocal()
        self.assertFalse(faellig(db, _person(db)))
        db.close()


class TestListeAufDerUebersicht(unittest.TestCase):
    """Der Rundgang geht vorbei - die Liste bleibt, bis sie leer ist."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_liste_steht_da_solange_etwas_offen_ist(self):
        db = SessionLocal()
        person = _person(db)
        person.calendar_last_fetch = None
        db.query(PushSubscription).filter(
            PushSubscription.user_id == person.id).delete()
        db.commit()
        db.close()
        text = self.dash.get("/dashboard/uebersicht").text
        self.assertIn("Das fehlt noch bei dir", text)
        self.assertIn("Kalender neu eintragen", text)

    def test_liste_verschwindet_von_selbst(self):
        db = SessionLocal()
        person = _person(db)
        person.calendar_last_fetch = umzug.UMZUG_AB + timedelta(hours=1)
        db.add(PushSubscription(
            user_id=person.id, endpoint="https://push.test/fertig-dashboard",
            p256dh="k", auth="a", ursprung="dashboard",
            created_at=umzug.UMZUG_AB + timedelta(hours=1)))
        umzug.als_app_vermerken(db, person)
        db.close()
        text = self.dash.get("/dashboard/uebersicht").text
        self.assertNotIn("Das fehlt noch bei dir", text)

        # Aufräumen: andere Tests zählen Push-Anmeldungen.
        db = SessionLocal()
        person = _person(db)
        db.query(PushSubscription).filter(
            PushSubscription.user_id == person.id).delete()
        person.calendar_last_fetch = None
        _vorlieben(db, person.id).als_app_am = None
        db.commit()
        db.close()


class TestKalenderAbrufWirdFestgehalten(unittest.TestCase):
    """Ohne diesen Zeitstempel lässt sich der Punkt nie abhaken."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_abruf_setzt_den_zeitstempel(self):
        from kern import kalender
        db = SessionLocal()
        person = _person(db)
        person.calendar_last_fetch = None
        db.commit()
        adresse = kalender.abo_adresse(db, person)
        marke = person.calendar_token
        db.close()
        self.assertIn(marke, adresse)

        antwort = self.dash.get(f"/dashboard/kalender/{marke}.ics")
        self.assertEqual(antwort.status_code, 200)
        self.assertIn("BEGIN:VCALENDAR", antwort.text)

        db = SessionLocal()
        person = _person(db)
        self.assertIsNotNone(person.calendar_last_fetch,
                             "der Abruf wurde nicht festgehalten")
        person.calendar_last_fetch = None
        db.commit()
        db.close()


if __name__ == "__main__":
    unittest.main()
