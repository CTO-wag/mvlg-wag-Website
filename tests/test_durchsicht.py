"""Die Funde der Durchsicht vor dem Ausrollen - damit sie es bleiben.

Jeder Test hier steht für einen Fehler, der beim gründlichen Durchsehen am
14.08.2026 aufgefallen ist, bevor er jemandem im Betrieb begegnen konnte.
"""

import unittest
from datetime import timedelta

from tests import hilfe                                      # noqa: F401

from kern import umzug
from kern.datenbank import SessionLocal
from kern.modelle import DeliveryLog, NotificationPreference, PushSubscription, User
from kern.sicherheit import passwort_hashen
from tests.hilfe import angemeldeter_client


def _person(db, email="durchsicht@ag.local"):
    p = db.query(User).filter(User.email == email).first()
    if not p:
        p = User(vorname="Durch", nachname="Sicht", email=email,
                 password_hash=passwort_hashen("DurchSicht2026x"), role="member",
                 department="tech", status="aktiv")
        db.add(p)
        db.commit()
    return p


class TestHinterEinemProxy(unittest.TestCase):
    """Reicht der Tunnel den Host nicht durch, sieht die Anwendung einen
    Aufruf von 127.0.0.1. Sie darf daraus NICHT schliessen, dass jemand
    örtlich testet - sonst zeigen alle Verweise der öffentlichen Seite auf
    den Rechner des Besuchers und das Sitzungs-Cookie verliert seine Domain.
    """

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def _adressen(self, host, kopf=None):
        from fastapi.testclient import TestClient
        from website.app import app as web
        import re
        with TestClient(web, base_url=f"http://{host}") as k:
            antwort = k.get("/login", headers=kopf or {})
        return sorted({v for v in re.findall(
            r'<a [^>]*href="(https?://[^"]+)"', antwort.text)})

    def test_ohne_proxy_bleibt_alles_oertlich(self):
        # Der Verweis auf die Schulseite ist ein fremder und bleibt fremd -
        # geprüft werden nur unsere eigenen Adressen.
        verweise = self._adressen("localhost:8000")
        self.assertTrue(verweise, "keine Verweise gefunden")
        eigene = [v for v in verweise if "mvlg-wag.de" in v or "localhost" in v]
        self.assertTrue(eigene, "keine eigenen Verweise gefunden")
        for v in eigene:
            self.assertIn("localhost", v)

    def test_mit_proxy_spur_gelten_die_eingestellten_adressen(self):
        from kern import einstellungen as cfg
        for spur in ({"X-Forwarded-For": "203.0.113.7"},
                     {"X-Forwarded-Proto": "https"},
                     {"CF-Connecting-IP": "203.0.113.7"}):
            with self.subTest(spur=list(spur)[0]):
                verweise = self._adressen("127.0.0.1:8000", spur)
                for v in verweise:
                    self.assertFalse(
                        v.startswith("http://127.0.0.1"),
                        f"{list(spur)[0]}: öffentliche Seite verweist auf "
                        f"{v} statt auf {cfg.WEBSITE_URL}")

    def test_cookie_behaelt_hinter_dem_proxy_seine_domain(self):
        """Ohne Domain gilt die Anmeldung nur für einen der beiden Namen."""
        from kern.webbasis import _wirt_aus, OertlicheCookies
        scope_oertlich = {"type": "http", "headers": [(b"host", b"127.0.0.1:8000")]}
        scope_proxy = {"type": "http", "headers": [(b"host", b"127.0.0.1:8000"),
                                                   (b"x-forwarded-for", b"203.0.113.7")]}
        self.assertEqual(_wirt_aus(scope_oertlich), "127.0.0.1")

        gesehen = []

        class Weiter:
            async def __call__(self, scope, receive, send):
                gesehen.append(scope)

        import asyncio
        mittel = OertlicheCookies(Weiter())
        gesendet = []

        async def send(ereignis):
            gesendet.append(ereignis)

        async def lauf(scope):
            del gesendet[:]

            async def app(scope_, receive_, send_):
                await send_({"type": "http.response.start", "status": 200,
                             "headers": [(b"set-cookie",
                                          b"wag_sitzung=x; Domain=.mvlg-wag.de; Path=/")]})
            mittel.app = app
            await mittel(scope, None, send)
            return gesendet[0]["headers"][0][1].decode()

        oertlich = asyncio.run(lauf(scope_oertlich))
        hinter_proxy = asyncio.run(lauf(scope_proxy))
        self.assertNotIn("Domain", oertlich, "auf localhost muss die Domain weg")
        self.assertIn("Domain=.mvlg-wag.de", hinter_proxy,
                      "hinter dem Proxy muss die Domain bleiben")


class TestPushAnmeldungOhneDatum(unittest.TestCase):
    """Eine Zeile ohne created_at stammt aus V1 - sie gilt als alt.

    Andersherum wäre der Fehler teurer: Die Person bekäme den Hinweis nie
    und wüsste nicht, warum nichts mehr ankommt.
    """

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_ohne_datum_gilt_als_alt(self):
        db = SessionLocal()
        p = _person(db, "ohnedatum@ag.local")
        db.query(PushSubscription).filter(
            PushSubscription.user_id == p.id).delete()
        # Über rohes SQL: Der ORM-Standard würde created_at sonst selbst
        # füllen - eine echte Leerstelle gibt es nur bei Zeilen, die aus V1
        # stammen oder von Hand eingesetzt wurden.
        from sqlalchemy import text as sql
        db.execute(sql("insert into push_subscriptions "
                       "(user_id, endpoint, p256dh, auth, ursprung, created_at) "
                       "values (:u, :e, 'k', 'a', 'dashboard', NULL)"),
                   {"u": p.id, "e": "https://push.test/ohne"})
        db.commit()
        stand = umzug.push_stand(db, p)
        db.query(PushSubscription).filter(
            PushSubscription.user_id == p.id).delete()
        db.commit()
        db.close()
        self.assertFalse(stand["dashboard"], "Zeile ohne Datum gilt als neu")
        self.assertEqual(len(stand["alte"]), 1)
        self.assertIn("dashboard", stand["fehlend"])


class TestZustellwege(unittest.TestCase):
    """Wer kein Gerät angemeldet hat, muss trotzdem erreicht werden."""

    @classmethod
    def setUpClass(cls):
        cls.web, cls.dash = angemeldeter_client()

    def test_kein_geraet_ist_kein_zustellfehler(self):
        """Sonst steht auf der Sicherheitsseite dauerhaft eine Warnung -
        und eine Warnung, die immer leuchtet, liest bald niemand mehr."""
        from kern import push
        db = SessionLocal()
        p = _person(db, "ohnegeraet@ag.local")
        db.query(PushSubscription).filter(
            PushSubscription.user_id == p.id).delete()
        vorher = db.query(DeliveryLog).count()
        pid = p.id
        db.commit()
        db.close()

        ok, grund = push.webpush_an_person(pid, "Test", "Text", warten=True,
                                           ziel="Ohne Gerät", anlass="test")
        self.assertFalse(ok)
        self.assertIn("kein Gerät", grund)

        db = SessionLocal()
        nachher = db.query(DeliveryLog).count()
        db.close()
        self.assertEqual(vorher, nachher,
                         "leerer Push wurde als Fehler protokolliert")

    def test_email_springt_ein_wenn_push_ins_leere_ginge(self):
        """Web-Push eingeschaltet, aber kein Gerät: dann muss die E-Mail
        kommen. Vorher galt der blosse Schalter als 'erreicht'."""
        import unittest.mock
        from kern import benachrichtigung
        db = SessionLocal()
        p = _person(db, "nurmail@ag.local")
        db.query(PushSubscription).filter(
            PushSubscription.user_id == p.id).delete()
        pref = benachrichtigung.einstellung(db, p.id)
        pref.enabled, pref.webpush, pref.ntfy, pref.email = 1, 1, 0, 1
        pref.tasks = 1
        db.commit()
        pid = p.id

        with unittest.mock.patch("kern.mail.versand_moeglich", return_value=True), \
             unittest.mock.patch("kern.mail.sende_vordruck") as versand, \
             unittest.mock.patch("kern.push.webpush_an_person",
                                 return_value=(False, "kein Gerät angemeldet")):
            benachrichtigung.melde(db, pid, "tasks", "Titel", "Text")
        db.close()
        self.assertTrue(versand.called,
                        "ohne angemeldetes Gerät kam gar nichts an")


if __name__ == "__main__":
    unittest.main()
