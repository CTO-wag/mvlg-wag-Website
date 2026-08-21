"""Betrieb unter zwei Namen: mvlg-wag.de und app.mvlg-wag.de.

So läuft die Anlage der AG. Der Fall lässt sich nicht mit den Einstellungen
der übrigen Tests prüfen, weil die Adressen beim Import gelesen werden -
deshalb startet dieser Test einen eigenen Prozess mit der echten Aufstellung
und lässt ihn berichten.

Geprüft wird das, was an zwei Namen tatsächlich hängt:

* Die Anmeldung auf der Website muss auch für das Dashboard gelten. Ohne
  Domain-Cookie gilt sie nur für den Namen, unter dem man sich angemeldet hat.
* Die Gerätekennung für Push muss auf beiden Namen dieselbe sein, sonst
  bekommt ein Handy jede Meldung zweimal.
* Die Sicherheitsrichtlinie muss Formulare an beide Namen zulassen.
"""

import json
import os
import subprocess
import sys
import unittest

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KIND = r'''
import json, os, re, sys, tempfile
sys.path.insert(0, sys.argv[1])
os.environ.update({
    "DATEN_DIR": tempfile.mkdtemp(prefix="wag-zwei-"),
    "SECRET_KEY": "z" * 64,
    "APP_ENV": "development",
    "HTTPS_ONLY_COOKIES": "false",
    "SMTP_HOST": "",
    "BACKUPS_ENABLED": "false",
    "REMINDERS_ENABLED": "false",
    "WHATSAPP_MODUS": "manuell",
    "WEBSITE_URL": "https://mvlg-wag.de",
    "DASHBOARD_URL": "https://app.mvlg-wag.de",
})

from http.cookies import SimpleCookie
from fastapi.testclient import TestClient

from kern import einstellungen as cfg
from kern.migration import migriere
from kern.datenbank import SessionLocal
from kern.modelle import PushSubscription, User
from kern.sicherheit import passwort_hashen
from website.app import app as web_app
from dashboard.app import app as dash_app

PASSWORT = "ZweiAdressen2026x"
migriere(still=True)
db = SessionLocal()
person = User(vorname="Zwei", nachname="Adressen", email="zwei@ag.local",
              password_hash=passwort_hashen(PASSWORT), role="cto",
              department="exekutive", status="aktiv")
db.add(person)
db.commit()
person_id = person.id
db.close()

# Ein eigenes Cookie-Glas, das die Domain-Regel anwendet - genau wie ein
# Browser. Der Client von httpx bringt zwar eines mit, verwechselt aber
# gleichnamige Cookies verschiedener Namen; und genau darum geht es hier.
GLAS = {}          # name -> (wert, domain oder "", host)


def kekse_annehmen(antwort, host):
    for schluessel, wert in antwort.headers.multi_items():
        if schluessel.lower() != "set-cookie":
            continue
        keks = SimpleCookie()
        keks.load(wert)
        for name, teil in keks.items():
            GLAS[name] = (teil.value, teil["domain"] or "", host)


def kekse_fuer(host):
    """Was ein Browser an diesen Namen schicken würde."""
    passend = []
    for name, (wert, domain, quelle) in GLAS.items():
        if domain:
            rein = domain.lstrip(".")
            if host == rein or host.endswith("." + rein):
                passend.append(f"{name}={wert}")
        elif host == quelle:
            passend.append(f"{name}={wert}")
    return "; ".join(passend)


web = TestClient(web_app, base_url="https://mvlg-wag.de")
dash = TestClient(dash_app, base_url="https://app.mvlg-wag.de")
WEB_HOST, DASH_HOST = "mvlg-wag.de", "app.mvlg-wag.de"


def hole(klient, host, pfad, **rest):
    rest.setdefault("headers", {})["Cookie"] = kekse_fuer(host)
    rest.setdefault("follow_redirects", False)
    antwort = klient.get(pfad, **rest)
    kekse_annehmen(antwort, host)
    return antwort


def sende(klient, host, pfad, daten, **rest):
    rest.setdefault("headers", {})["Cookie"] = kekse_fuer(host)
    rest.setdefault("follow_redirects", False)
    antwort = klient.post(pfad, data=daten, **rest)
    kekse_annehmen(antwort, host)
    return antwort


ergebnis = {"cookie_domain": cfg.COOKIE_DOMAIN,
            "gleicher_ursprung": cfg.GLEICHER_URSPRUNG}

# --- Anmelden auf der Website ---------------------------------------------
seite = hole(web, WEB_HOST, "/login")
csrf = re.search(r'name="csrf" value="([^"]+)"', seite.text).group(1)
antwort = sende(web, WEB_HOST, "/login",
                {"email": "zwei@ag.local", "passwort": PASSWORT, "csrf": csrf})
ergebnis["login_status"] = antwort.status_code
ergebnis["login_ziel"] = antwort.headers.get("location", "")
ergebnis["cookie_kopf"] = "; ".join(
    w for k, w in antwort.headers.multi_items() if k.lower() == "set-cookie")
ergebnis["cookie_geht_ans_dashboard"] = "wag_sitzung" in kekse_fuer(DASH_HOST)

# --- Dashboard mit derselben Anmeldung ------------------------------------
rahmen = hole(dash, DASH_HOST, "/")
ergebnis["dashboard_status"] = rahmen.status_code
ergebnis["dashboard_zeigt_namen"] = "Zwei Adressen" in rahmen.text

bereich = hole(dash, DASH_HOST, "/dashboard/aufgaben",
               headers={"HX-Request": "true"})
ergebnis["bereich_status"] = bereich.status_code

# --- Sicherheitsrichtlinie -------------------------------------------------
csp = rahmen.headers.get("Content-Security-Policy", "")
ergebnis["csp_erlaubt_beide"] = ("https://mvlg-wag.de" in csp
                                 and "https://app.mvlg-wag.de" in csp)
ergebnis["csp_ohne_fremde_schriften"] = "fonts.gstatic.com" not in csp

# --- Push auf beiden Namen -------------------------------------------------
dash_csrf = re.search(r'id="dash-csrf" value="([^"]+)"', rahmen.text).group(1)
a1 = sende(dash, DASH_HOST, "/dashboard/nachrichten/push-anmelden",
           {"endpoint": "https://push.test/d", "p256dh": "k", "auth": "a",
            "csrf": dash_csrf})
ergebnis["push_dashboard"] = a1.status_code
# Die Kennung kommt als Cookie zurück - und muss für beide Namen gelten.
ergebnis["geraete_cookie"] = "; ".join(
    w for k, w in a1.headers.multi_items() if k.lower() == "set-cookie")
ergebnis["kennung_geht_an_website"] = "wag_geraet" in kekse_fuer(WEB_HOST)

# Auf der oeffentlichen Seite gibt es seit dem 19.08.2026 keine Anmeldung
# mehr - nachgewiesen wird jetzt, dass sie wirklich weg ist.
ergebnis["website_seite"] = hole(web, WEB_HOST, "/benachrichtigungen").status_code
ergebnis["push_website"] = sende(web, WEB_HOST, "/push-anmelden",
                                 {"endpoint": "https://push.test/w"}).status_code

from kern import push
db = SessionLocal()
zeilen = db.query(PushSubscription).filter(
    PushSubscription.user_id == person_id).all()
ergebnis["anmeldungen"] = [(z.ursprung, z.geraete_id) for z in zeilen]
ergebnis["empfaenger_anzahl"] = len(push.empfaenger(db, person_id))
db.close()

# --- Hinweis im Dashboard --------------------------------------------------
nachrichten = hole(dash, DASH_HOST, "/dashboard/nachrichten",
                   headers={"HX-Request": "true"})
ergebnis["hinweis_im_dashboard"] = "Startseite getrennt anmelden" in nachrichten.text
ergebnis["verweist_auf_website"] = "https://mvlg-wag.de/benachrichtigungen" in nachrichten.text
ergebnis["dashboard_kann_push"] = 'id="push-anmelden"' in nachrichten.text

# --- Abmelden gilt auch für beide -----------------------------------------
ab = hole(web, WEB_HOST, "/logout")
ergebnis["logout_status"] = ab.status_code
nach = hole(dash, DASH_HOST, "/")
ergebnis["dashboard_nach_logout"] = nach.status_code

# --- Oertlich testen trotz eingetragener Live-Adressen ---------------------
# Wer http://localhost:8001 aufruft, will die Fassung auf diesem Rechner
# sehen. Keine einzige Weiterleitung und kein Verweis darf ihn nach
# mvlg-wag.de schicken.
oertlich_web = TestClient(web_app, base_url="http://localhost:8000")
oertlich_dash = TestClient(dash_app, base_url="http://localhost:8001")

o1 = oertlich_dash.get("/", follow_redirects=False)
ergebnis["ortlich_dash_status"] = o1.status_code
ergebnis["ortlich_dash_ziel"] = o1.headers.get("location", "")

o2 = oertlich_web.get("/login", follow_redirects=False)
ergebnis["ortlich_login_status"] = o2.status_code
# Anklickbare Verweise muessen auf localhost bleiben. Nicht gemeint sind
# canonical und og:url - die zeigen absichtlich auf die veroeffentlichte
# Fassung, sonst traegt eine Testseite falsche Angaben fuer Suchmaschinen.
verweise = re.findall(r'<a [^>]*href="(https?://[^"]+)"', o2.text)
ergebnis["ortlich_fremde_verweise"] = sorted(
    {v for v in verweise if "mvlg-wag.de" in v})
ergebnis["ortlich_login_csp"] = o2.headers.get("Content-Security-Policy", "")

# Anmelden auf localhost muss ins oertliche Dashboard fuehren.
o_csrf = re.search(r'name="csrf" value="([^"]+)"', o2.text).group(1)
o3 = oertlich_web.post("/login",
                       data={"email": "zwei@ag.local", "passwort": PASSWORT,
                             "csrf": o_csrf}, follow_redirects=False)
ergebnis["ortlich_login_antwort"] = o3.status_code
ergebnis["ortlich_login_ziel"] = o3.headers.get("location", "")

print("---ERGEBNIS---")
print(json.dumps(ergebnis, ensure_ascii=False))
'''


class TestZweiAdressen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lauf = subprocess.run([sys.executable, "-c", KIND, WURZEL],
                              capture_output=True, text=True, cwd=WURZEL,
                              encoding="utf-8", errors="replace", timeout=180)
        if "---ERGEBNIS---" not in (lauf.stdout or ""):
            raise AssertionError("Kindprozess ohne Ergebnis:\n"
                                 + (lauf.stdout or "") + "\n" + (lauf.stderr or ""))
        cls.e = json.loads(lauf.stdout.split("---ERGEBNIS---")[1].strip())

    def test_erkennt_zwei_adressen(self):
        self.assertFalse(self.e["gleicher_ursprung"])
        self.assertEqual(self.e["cookie_domain"], ".mvlg-wag.de")

    def test_sitzungscookie_gilt_fuer_die_ganze_domain(self):
        self.assertIn("wag_sitzung", self.e["cookie_kopf"])
        self.assertIn("domain=.mvlg-wag.de", self.e["cookie_kopf"].lower(),
                      "ohne Domain gilt die Anmeldung nur für einen Namen")
        self.assertTrue(self.e["cookie_geht_ans_dashboard"],
                        "der Browser schickte das Cookie nicht an app.mvlg-wag.de")

    def test_anmeldung_fuehrt_zum_dashboard(self):
        self.assertEqual(self.e["login_status"], 303)
        self.assertTrue(self.e["login_ziel"].startswith("https://app.mvlg-wag.de"),
                        self.e["login_ziel"])

    def test_dashboard_erkennt_die_anmeldung(self):
        self.assertEqual(self.e["dashboard_status"], 200,
                         "Dashboard schickt trotz Anmeldung zur Anmeldeseite")
        self.assertTrue(self.e["dashboard_zeigt_namen"])
        self.assertEqual(self.e["bereich_status"], 200)

    def test_richtlinie_erlaubt_beide_namen(self):
        self.assertTrue(self.e["csp_erlaubt_beide"])
        self.assertTrue(self.e["csp_ohne_fremde_schriften"])

    def test_push_nur_noch_im_dashboard(self):
        """Zwei Knöpfe für dieselbe Sache haben mehr verwirrt als genützt."""
        self.assertEqual(self.e["push_dashboard"], 200)
        self.assertEqual(self.e["website_seite"], 404)
        self.assertEqual(self.e["push_website"], 404)
        self.assertTrue(self.e["dashboard_kann_push"])
        arten = sorted(a for a, _ in self.e["anmeldungen"])
        self.assertEqual(arten, ["dashboard"])

    def test_die_geraetekennung_gilt_trotzdem_fuer_beide_namen(self):
        """Sie hängt nicht an Push: An ihr erkennt die Anlage dasselbe Gerät
        über beide Adressen hinweg, auch für Sitzungen."""
        self.assertIn("domain=.mvlg-wag.de", self.e["geraete_cookie"].lower(),
                      "die Gerätekennung gilt nur für einen Namen")
        self.assertTrue(self.e["kennung_geht_an_website"])
        self.assertEqual(self.e["empfaenger_anzahl"], 1)

    def test_das_dashboard_erklaert_die_zweite_anmeldung_nicht_mehr(self):
        self.assertFalse(self.e["hinweis_im_dashboard"])
        self.assertFalse(self.e["verweist_auf_website"])

    def test_abmelden_wirkt_auf_beiden(self):
        self.assertEqual(self.e["logout_status"], 303)
        self.assertEqual(self.e["dashboard_nach_logout"], 303,
                         "nach dem Abmelden käme man noch ins Dashboard")

    # --- Oertlich testen -------------------------------------------------
    #  Regression: als die echten Adressen in die config.cmd kamen, leitete
    #  http://localhost:8001 sofort auf mvlg-wag.de um - die Fassung auf dem
    #  eigenen Rechner liess sich nicht mehr aufrufen.
    def test_localhost_leitet_nicht_auf_die_live_seite(self):
        self.assertEqual(self.e["ortlich_dash_status"], 303)
        self.assertEqual(self.e["ortlich_dash_ziel"],
                         "http://localhost:8000/login")

    def test_localhost_verweist_auf_localhost(self):
        self.assertEqual(self.e["ortlich_login_status"], 200)
        self.assertEqual(self.e["ortlich_fremde_verweise"], [],
                         "Auf der oertlichen Seite stehen Live-Verweise.")

    def test_localhost_anmeldung_bleibt_oertlich(self):
        self.assertEqual(self.e["ortlich_login_antwort"], 303)
        self.assertEqual(self.e["ortlich_login_ziel"], "http://localhost:8001/")

    def test_localhost_darf_formulare_abschicken(self):
        csp = self.e["ortlich_login_csp"]
        self.assertIn("http://localhost:8000", csp)
        self.assertIn("http://localhost:8001", csp)


if __name__ == "__main__":
    unittest.main()
