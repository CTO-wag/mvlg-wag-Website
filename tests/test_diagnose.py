"""Die Nutzer-Analyse im Support.

Der Bereich beantwortet die Frage, mit der jede zweite Support-Anfrage
anfaengt: "Bei mir geht das nicht." Geprueft wird hier dreierlei, in dieser
Reihenfolge der Wichtigkeit:

  1. Dass niemand hineinsieht, der es nicht darf. Hier stehen IP-Adressen und
     Geraete von Minderjaehrigen; eine Luecke waere schlimmer als ein
     fehlendes Werkzeug.
  2. Dass die Angaben stimmen und nichts durchrutscht, was ein fremder
     Browser sich ausgedacht hat.
  3. Dass die Erfassung selbst nichts kaputtmacht - keinen Seitenaufruf, kein
     Formular, keine Anmeldung.
"""

import json
import unittest

from tests import hilfe                                      # noqa: F401

from kern import diagnose
from kern.datenbank import SessionLocal
from kern.modelle import ClientFehler, Geraeteprofil, User
from tests.hilfe import TESTPASSWORT, frische_datenbank

# Ein echter Chrome auf Android - samt der Client Hints, ohne die Chrome bei
# jedem Handy dasselbe behauptet.
HANDY = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like "
         "Gecko) Chrome/131.0.0.0 Mobile Safari/537.36")
HINTS = {
    "User-Agent": HANDY,
    "Accept-Language": "de-DE,de;q=0.9",
    "Sec-CH-UA-Platform": '"Android"',
    "Sec-CH-UA-Platform-Version": '"14.0.0"',
    "Sec-CH-UA-Model": '"Pixel 8 Pro"',
    "Sec-CH-UA-Mobile": "?1",
}
BROWSERDATEN = {
    "bildschirm": "412 × 915", "gpu": "Mali-G715-Immortalis MC11",
    "cpu_kerne": 9, "speicher_gb": 8, "netz_art": "4g", "netz_rtt": 150,
    "zeitzone": "Europe/Berlin", "sprachen": "de-DE, de",
    "als_app": True, "push_erlaubnis": "granted", "ladezeit": 1840,
}


class TestZerlegung(unittest.TestCase):
    """Aus Kennung und Client Hints das Geraet erkennen."""

    def test_client_hints_schlagen_die_kennung(self):
        """Der Kern der Sache: Chrome friert die Kennung ein.

        Im User-Agent steht bei JEDEM Android-Geraet "Android 10; K". Nur
        die Hints nennen das echte Modell und die echte Fassung - sonst
        stuende im Support-Dossier bei allen dasselbe.
        """
        ohne = diagnose.zerlegen(HANDY, {})
        self.assertEqual(ohne["plattform"], "Android 10")
        self.assertEqual(ohne["modell"], "")

        kopf = {"ch_plattform": "Android", "ch_version": "14.0.0",
                "ch_modell": "Pixel 8 Pro", "ch_mobil": "ja"}
        mit = diagnose.zerlegen(HANDY, kopf)
        self.assertEqual(mit["plattform"], "Android 14")
        self.assertEqual(mit["modell"], "Pixel 8 Pro")
        self.assertEqual(mit["browser"], "Chrome 131")
        self.assertTrue(mit["ist_mobil"])

    def test_die_uebrigen_geraete(self):
        iphone = diagnose.zerlegen(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
            "Mobile/15E148 Safari/604.1")
        self.assertEqual(iphone["browser"], "Safari 17")
        self.assertEqual(iphone["plattform"], "iOS 17.5.1")
        self.assertTrue(iphone["ist_mobil"])

        rechner = diagnose.zerlegen(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) "
            "Gecko/20100101 Firefox/133.0")
        self.assertEqual(rechner["browser"], "Firefox 133")
        self.assertEqual(rechner["plattform"], "Windows 10/11")
        self.assertFalse(rechner["ist_mobil"])

    def test_unsinn_stuerzt_nicht_ab(self):
        for kennung in ("", None, "irgendwas", "<script>"):
            teile = diagnose.zerlegen(kennung)
            self.assertIn("browser", teile)
            self.assertTrue(diagnose.beschreiben(teile))


class TestHerkunft(unittest.TestCase):
    """Antworten beider Dienste lesen und den VPN-Verdacht bilden."""

    def test_beide_dienste_ergeben_dieselben_schluessel(self):
        ipwho = diagnose._ip_antwort_lesen({
            "country": "Netherlands", "country_code": "NL", "city": "Amsterdam",
            "connection": {"isp": "M247 Europe SRL", "asn": 9009}})
        ipapi = diagnose._ip_antwort_lesen({
            "country": "Germany", "countryCode": "DE", "city": "Koblenz",
            "isp": "Deutsche Telekom AG", "as": "AS3320", "mobile": True})
        self.assertEqual(ipwho["land_code"], "NL")
        self.assertEqual(ipwho["anbieter"], "M247 Europe SRL")
        self.assertEqual(ipwho["asn"], "AS9009")
        self.assertEqual(ipapi["land_code"], "DE")
        self.assertTrue(ipapi["mobil"])

    def test_kaputte_antwort_ergibt_leer(self):
        for roh in (None, [], "nein", {}, {"nichts": "da"}):
            self.assertIsInstance(diagnose._ip_antwort_lesen(roh), dict)

    def test_handy_an_der_telekom_ist_kein_verdacht(self):
        """Der Normalfall darf nicht auffaellig aussehen.

        Ein Werkzeug, das bei jedem Mitglied VPN meldet, wird nach dem
        dritten Mal nicht mehr angesehen.
        """
        daten = diagnose._ip_antwort_lesen({
            "country": "Germany", "countryCode": "DE",
            "isp": "Deutsche Telekom AG", "mobile": True})
        punkte, gruende = diagnose.vpn_bewerten(
            daten, {"zeitzone": "Europe/Berlin", "sprachen": "de-DE"}, {})
        self.assertEqual(punkte, 0)
        self.assertEqual(gruende, "")

    def test_zeitzone_gegen_land_faellt_auf(self):
        """Das staerkste Anzeichen, das ohne fremden Dienst auskommt."""
        daten = {"land_code": "NL", "anbieter": "M247 Europe SRL"}
        punkte, gruende = diagnose.vpn_bewerten(
            daten, {"zeitzone": "Europe/Berlin", "sprachen": "de-DE"}, {})
        self.assertGreaterEqual(punkte, 45)
        # Die Begruendung muss dastehen: Einer nackten Zahl glaubt man oder
        # nicht, nachvollziehen kann man sie nicht.
        self.assertIn("Zeitzone", gruende)
        self.assertIn("Rechenzentrum", gruende)

    def test_ohne_angaben_kein_verdacht(self):
        self.assertEqual(diagnose.vpn_bewerten({}, {}, {}), (0, ""))
        self.assertEqual(diagnose.vpn_bewerten(None, None, None), (0, ""))

    def test_eigene_netze_gehen_an_keinen_dienst(self):
        """Zu 192.168.x weiss kein Dienst etwas - und muss es nicht erfahren."""
        for ip in ("192.168.1.5", "10.0.0.1", "127.0.0.1", "172.16.0.9", "::1"):
            self.assertTrue(diagnose.ist_privat(ip), ip)
            self.assertEqual(diagnose.ip_infos(ip), {})
        self.assertFalse(diagnose.ist_privat("8.8.8.8"))


class TestAnnahme(unittest.TestCase):
    """Was der Browser schickt, ist eine Behauptung - keine Wahrheit."""

    def test_nur_bekannte_felder(self):
        sauber = diagnose._bereinigen({
            "gpu": "Mali-G715", "erfunden": "boeses", "cpu_kerne": 8})
        self.assertEqual(set(sauber), {"gpu", "cpu_kerne"})

    def test_werte_werden_gekuerzt_und_uebersetzt(self):
        sauber = diagnose._bereinigen({
            "gpu": "x" * 900, "als_app": True, "netz_tempo": 8.4567,
            "netz_art": "   4g   "})
        self.assertEqual(len(sauber["gpu"]), 200)
        self.assertEqual(sauber["als_app"], "ja")
        self.assertEqual(sauber["netz_tempo"], 8.46)
        self.assertEqual(sauber["netz_art"], "4g")

    def test_unsinn_statt_eines_objekts(self):
        for roh in (None, [], "nein", 5):
            self.assertEqual(diagnose._bereinigen(roh), {})


def angemeldet_als_handy():
    """Ein Dashboard-Client, der von Anfang an wie ein Handy aussieht.

    Nicht angemeldeter_client() mit nachtraeglich gesetzten Kopfzeilen: Eine
    Sitzung ist an den Browser gebunden (kern/sitzung.py). Wer sich mit der
    einen Kennung anmeldet und mit einer anderen weitermacht, fliegt raus -
    genau so, wie es bei einer gestohlenen Sitzungs-ID passieren soll. Beim
    ersten Anlauf dieses Tests war das die Ursache fuer lauter 404: Der
    Client landete abgemeldet auf der Anmeldeseite der Website.
    """
    import re

    from fastapi.testclient import TestClient

    from dashboard.app import app as dash_app
    from website.app import app as web_app

    adresse = frische_datenbank()
    with TestClient(web_app, headers=HINTS) as w:
        seite = w.get("/login").text
        token = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
        w.post("/login", data={"email": adresse, "passwort": TESTPASSWORT,
                               "csrf": token}, follow_redirects=False)
        kekse = dict(w.cookies)
    return TestClient(dash_app, cookies=kekse, headers=HINTS)


class TestBereich(unittest.TestCase):
    """Der ganze Weg: erfassen, melden, ansehen."""

    @classmethod
    def setUpClass(cls):
        cls.dash = angemeldet_als_handy()

    def test_client_hints_werden_angefordert(self):
        """Ohne diese Kopfzeile schickt Chrome das Modell nie mit."""
        antwort = self.dash.get("/dashboard/support")
        self.assertIn("Sec-CH-UA-Model", antwort.headers.get("Accept-CH", ""))

    def test_profil_entsteht_beim_bereichsaufruf(self):
        self.dash.get("/dashboard/support")
        db = SessionLocal()
        try:
            profil = db.query(Geraeteprofil).order_by(
                Geraeteprofil.id.desc()).first()
            self.assertIsNotNone(profil)
            # Aus den Hints, nicht aus der eingefrorenen Kennung.
            self.assertEqual(profil.modell, "Pixel 8 Pro")
            self.assertIn("Android 14", profil.beschreibung)
            self.assertEqual(profil.ist_mobil, 1)
        finally:
            db.close()

    def test_browser_meldet_und_dossier_zeigt_es(self):
        antwort = self.dash.post("/diagnose/melden", json=BROWSERDATEN,
                                 headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(antwort.status_code, 204)

        db = SessionLocal()
        try:
            person = db.query(User).filter(User.email == "pruef@ag.local").one()
            # Ausdruecklich das zuletzt angelegte Profil: Andere Testklassen
            # legen fuer dieselbe Person eigene an, und .first() ohne
            # Sortierung haengt sonst an deren Reihenfolge.
            profil = (db.query(Geraeteprofil)
                      .filter(Geraeteprofil.user_id == person.id)
                      .order_by(Geraeteprofil.id.desc()).first())
            gemeldet = json.loads(profil.browserdaten)
            self.assertEqual(gemeldet["gpu"], "Mali-G715-Immortalis MC11")
            self.assertEqual(gemeldet["als_app"], "ja")
            kennung = person.id
        finally:
            db.close()

        seite = self.dash.get(f"/dashboard/analyse/{kennung}").text
        for erwartet in ("Mali-G715-Immortalis MC11", "Pixel 8 Pro",
                         "Europe/Berlin", "Als App gestartet",
                         "Push-Berechtigung"):
            self.assertIn(erwartet, seite)

    def test_browserfehler_wird_festgehalten(self):
        self.dash.post("/diagnose/melden", headers={"Sec-Fetch-Site": "same-origin"},
                       json={"art": "js", "meldung": "TypeError: k ist nichts",
                             "quelle": "/statisch/js/dashboard.js", "zeile": 42,
                             "adresse": "/dashboard/aufgaben"})
        db = SessionLocal()
        try:
            eintrag = db.query(ClientFehler).order_by(
                ClientFehler.id.desc()).first()
            self.assertIsNotNone(eintrag)
            self.assertEqual(eintrag.meldung, "TypeError: k ist nichts")
            self.assertEqual(eintrag.zeile, 42)
        finally:
            db.close()

    def test_derselbe_fehler_wird_nicht_hundertmal_geschrieben(self):
        """Eine Schleife im Skript darf die Datenbank nicht vollschreiben."""
        meldung = "RangeError: immer wieder dasselbe"
        for _ in range(5):
            self.dash.post("/diagnose/melden",
                           headers={"Sec-Fetch-Site": "same-origin"},
                           json={"art": "js", "meldung": meldung})
        db = SessionLocal()
        try:
            anzahl = db.query(ClientFehler).filter(
                ClientFehler.meldung == meldung).count()
            self.assertEqual(anzahl, 1)
        finally:
            db.close()

    def test_fremder_ursprung_wird_abgewiesen(self):
        """Sonst koennte eine fremde Seite falsche Angaben unterschieben."""
        vorher = self._fehlerzahl()
        antwort = self.dash.post(
            "/diagnose/melden", headers={"Sec-Fetch-Site": "cross-site"},
            json={"art": "js", "meldung": "von einer fremden Seite"})
        # Still, nicht mit einem Fehler - sonst meldet das Skript den
        # abgewiesenen Aufruf gleich als naechsten Fehler.
        self.assertEqual(antwort.status_code, 204)
        self.assertEqual(self._fehlerzahl(), vorher)

    @staticmethod
    def _fehlerzahl() -> int:
        db = SessionLocal()
        try:
            return db.query(ClientFehler).count()
        finally:
            db.close()

    def test_uebersicht_und_dossier_laden(self):
        uebersicht = self.dash.get("/dashboard/analyse")
        self.assertEqual(uebersicht.status_code, 200)
        self.assertIn("Nutzer-Analyse", uebersicht.text)
        self.assertIn("pruef@ag.local", uebersicht.text)

    def test_einsicht_steht_im_protokoll(self):
        """Eine Einsicht, die niemand nachvollziehen kann, ist Überwachung."""
        from kern.modelle import ActivityLog
        db = SessionLocal()
        try:
            person = db.query(User).filter(User.email == "pruef@ag.local").one()
            kennung = person.id
        finally:
            db.close()

        self.dash.get(f"/dashboard/analyse/{kennung}")
        db = SessionLocal()
        try:
            eintrag = (db.query(ActivityLog)
                       .filter(ActivityLog.event_type == "analyse_eingesehen")
                       .order_by(ActivityLog.id.desc()).first())
            self.assertIsNotNone(eintrag)
            self.assertIn("#", eintrag.value)
        finally:
            db.close()

    def test_verschwundene_person_ergibt_keine_fehlerseite(self):
        antwort = self.dash.get("/dashboard/analyse/999999")
        self.assertEqual(antwort.status_code, 200)
        self.assertIn("Nutzer-Analyse", antwort.text)


class TestZugang(unittest.TestCase):
    """Die wichtigste Prüfung: Wer darf hineinsehen?"""

    @classmethod
    def setUpClass(cls):
        import re
        from fastapi.testclient import TestClient
        from dashboard.app import app as dash_app
        from kern.sicherheit import passwort_hashen
        from website.app import app as web_app

        frische_datenbank()
        db = SessionLocal()
        try:
            if not db.query(User).filter(User.email == "einfach@ag.local").first():
                db.add(User(vorname="Einfaches", nachname="Mitglied",
                            email="einfach@ag.local",
                            password_hash=passwort_hashen(TESTPASSWORT),
                            role="member", department="exekutive",
                            status="aktiv"))
                db.commit()
        finally:
            db.close()

        with TestClient(web_app) as w:
            seite = w.get("/login").text
            token = re.search(r'name="csrf" value="([^"]+)"', seite).group(1)
            w.post("/login", data={"email": "einfach@ag.local",
                                   "passwort": TESTPASSWORT, "csrf": token},
                   follow_redirects=False)
            kekse = dict(w.cookies)
        cls.mitglied = TestClient(dash_app, cookies=kekse)

    def test_mitglied_kommt_nicht_hinein(self):
        self.assertEqual(
            self.mitglied.get("/dashboard/analyse").status_code, 403)
        self.assertEqual(
            self.mitglied.get("/dashboard/analyse/1").status_code, 403)

    def test_mitglied_sieht_den_weg_dorthin_gar_nicht(self):
        """Ein Knopf, der zu 403 fuehrt, ist schlechter als kein Knopf."""
        seite = self.mitglied.get("/dashboard/support").text
        self.assertNotIn("/dashboard/analyse", seite)

    def test_mitglied_darf_die_eigenen_angaben_melden(self):
        """Erfasst wird bei allen - nur ansehen darf es der CTO."""
        antwort = self.mitglied.post(
            "/diagnose/melden", json={"gpu": "Adreno 730"},
            headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(antwort.status_code, 204)

    def test_ohne_anmeldung_geht_gar_nichts(self):
        from fastapi.testclient import TestClient
        gast = TestClient(self.mitglied.app)
        antwort = gast.post("/diagnose/melden", json={"gpu": "x"},
                            headers={"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(antwort.status_code, 204)
        self.assertEqual(gast.get("/diagnose/stand").status_code, 404)


class TestAufbewahrung(unittest.TestCase):
    """Diagnosedaten entstehen ohne Zutun der Mitglieder - also mit Frist."""

    def test_altes_wird_entfernt_neues_nicht(self):
        from datetime import timedelta

        from kern import einstellungen as cfg
        from kern.text import utcnow

        frische_datenbank()
        db = SessionLocal()
        try:
            person = db.query(User).filter(User.email == "pruef@ag.local").one()
            alt = utcnow() - timedelta(days=cfg.DIAGNOSE_TAGE + 5)
            db.add(Geraeteprofil(user_id=person.id, geraete_id="alt",
                                 beschreibung="Uraltes Gerät", zuletzt=alt))
            db.add(Geraeteprofil(user_id=person.id, geraete_id="neu",
                                 beschreibung="Frisches Gerät",
                                 zuletzt=utcnow()))
            db.add(ClientFehler(user_id=person.id, meldung="alter Fehler",
                                created_at=alt))
            db.commit()
        finally:
            db.close()

        diagnose.aufraeumen()

        db = SessionLocal()
        try:
            uebrig = {p.geraete_id for p in db.query(Geraeteprofil).all()}
            self.assertIn("neu", uebrig)
            self.assertNotIn("alt", uebrig)
            self.assertEqual(db.query(ClientFehler).filter(
                ClientFehler.meldung == "alter Fehler").count(), 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
