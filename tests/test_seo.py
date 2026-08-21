"""Was Suchmaschinen und Chat-Apps von der Seite sehen.

Das ist der erste Eindruck: Wer den Link in WhatsApp einfügt, sieht ein Bild
und zwei Zeilen Text – nicht die Seite. Und was Google indiziert, entscheidet
darüber, ob die AG überhaupt gefunden wird. Beides fällt nicht auf, wenn es
kaputt ist, weil es niemand im Alltag benutzt. Deshalb hier festgehalten.
"""

import os
import re
import struct
import unittest
import xml.etree.ElementTree as ET
from datetime import date

from tests import hilfe                                      # noqa: F401

from fastapi.testclient import TestClient

from kern import einstellungen as cfg
from website.app import app as web_app

BILDER = os.path.join(cfg.STATISCH_DIR, "bilder")


def png_masse(pfad):
    with open(pfad, "rb") as datei:
        kopf = datei.read(24)
    return struct.unpack(">II", kopf[16:24])


class TestRobots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hilfe.frische_datenbank()
        cls.c = TestClient(web_app)
        cls.text = cls.c.get("/robots.txt").text

    def test_erreichbar_und_lesbar(self):
        antwort = self.c.get("/robots.txt")
        self.assertEqual(antwort.status_code, 200)
        self.assertTrue(antwort.headers["content-type"].startswith("text/plain"))
        self.assertTrue(self.text.startswith("User-agent:"))

    def test_nennt_die_sitemap_absolut(self):
        self.assertIn(f"Sitemap: {cfg.SITE_URL}/sitemap.xml", self.text)

    def test_sperrt_alles_mit_geheimnis_in_der_adresse(self):
        """Eine indizierte Adresse ist eine öffentliche Adresse."""
        for pfad in ("/dashboard", "/login", "/passwort-neu", "/kalender/",
                     "/benachrichtigungen"):
            self.assertIn(f"Disallow: {pfad}", self.text, pfad)

    def test_startseite_bleibt_erlaubt(self):
        self.assertIn("Allow: /", self.text)
        self.assertNotIn("Disallow: /\n", self.text,
                         "die ganze Seite ist gesperrt")


class TestSitemap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hilfe.frische_datenbank()
        cls.c = TestClient(web_app)
        cls.antwort = cls.c.get("/sitemap.xml")
        cls.baum = ET.fromstring(cls.antwort.text)

    def test_gueltiges_xml(self):
        self.assertEqual(self.antwort.status_code, 200)
        self.assertIn("xml", self.antwort.headers["content-type"])
        self.assertTrue(self.baum.tag.endswith("urlset"))

    def test_alle_adressen_absolut_und_erreichbar(self):
        raum = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        adressen = [u.findtext(raum + "loc") for u in self.baum.findall(raum + "url")]
        self.assertGreaterEqual(len(adressen), 4)
        for adresse in adressen:
            self.assertTrue(adresse.startswith(cfg.SITE_URL), adresse)
            pfad = adresse[len(cfg.SITE_URL):] or "/"
            self.assertEqual(self.c.get(pfad).status_code, 200,
                             f"{pfad} steht in der Sitemap, antwortet aber nicht")

    def test_kein_datum_aus_der_zukunft(self):
        """Ein lastmod von morgen macht die ganze Angabe unglaubwürdig."""
        raum = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        heute = date.today()
        for eintrag in self.baum.findall(raum + "url"):
            stand = date.fromisoformat(eintrag.findtext(raum + "lastmod"))
            self.assertLessEqual(stand, heute)

    def test_nichts_gesperrtes_in_der_sitemap(self):
        """Was robots.txt verbietet, darf man nicht gleichzeitig anbieten."""
        from website.routen.oeffentlich import GESPERRT
        for eintrag in self.baum.iter():
            if not eintrag.tag.endswith("loc"):
                continue
            pfad = eintrag.text[len(cfg.SITE_URL):] or "/"
            for verboten in GESPERRT:
                self.assertFalse(pfad.startswith(verboten),
                                 f"{pfad} ist gesperrt und steht doch drin")


class TestVorschaubild(unittest.TestCase):
    """Das Bild, das beim Verschicken des Links erscheint."""

    @classmethod
    def setUpClass(cls):
        hilfe.frische_datenbank()
        cls.c = TestClient(web_app)

    def _og(self, pfad, name):
        text = self.c.get(pfad).text
        treffer = re.search(rf'<meta property="og:{name}" content="([^"]+)"', text)
        self.assertIsNotNone(treffer, f"{pfad}: og:{name} fehlt")
        return treffer.group(1)

    def test_jede_oeffentliche_seite_hat_titel_text_und_bild(self):
        for pfad in ("/", "/bewerbung", "/quiz", "/impressum", "/datenschutz"):
            with self.subTest(pfad=pfad):
                self.assertTrue(self._og(pfad, "title"))
                self.assertTrue(self._og(pfad, "description"))
                self.assertTrue(self._og(pfad, "image").startswith("http"))

    def test_bild_ist_absolut_und_traegt_eine_pruefsumme(self):
        """Ohne Prüfsumme in der Adresse zeigen die Chat-Apps nach einer
        Änderung wochenlang das alte Bild - sie merken sich es je Adresse."""
        adresse = self._og("/", "image")
        self.assertTrue(adresse.startswith(cfg.SITE_URL), adresse)
        self.assertRegex(adresse, r"\?v=[0-9a-f]{6,}$")

    def test_bild_wird_auch_ausgeliefert(self):
        adresse = self._og("/", "image")
        antwort = self.c.get(adresse[len(cfg.SITE_URL):])
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.headers["content-type"], "image/png")

    def test_masse_und_gewicht_stimmen(self):
        """1200x630 erwarten die Dienste; über rund 300 KB lädt WhatsApp nicht."""
        for name in ("vorschaubild.png", "vorschaubild-bewerbung.png"):
            with self.subTest(bild=name):
                pfad = os.path.join(BILDER, name)
                self.assertTrue(os.path.exists(pfad), f"{name} fehlt")
                self.assertEqual(png_masse(pfad), (1200, 630))
                self.assertLess(os.path.getsize(pfad), 300_000)

    def test_angegebene_masse_stimmen_mit_dem_bild_ueberein(self):
        text = self.c.get("/").text
        breite = re.search(r'og:image:width" content="(\d+)"', text).group(1)
        hoehe = re.search(r'og:image:height" content="(\d+)"', text).group(1)
        self.assertEqual((int(breite), int(hoehe)),
                         png_masse(os.path.join(BILDER, "vorschaubild.png")))

    def test_bewerbung_hat_ein_eigenes_bild(self):
        """Der Link wird verschickt, um Leute zu werben - dann soll im Chat
        auch "Bewirb dich" stehen."""
        self.assertIn("vorschaubild-bewerbung",
                      self._og("/bewerbung", "image"))
        self.assertNotIn("vorschaubild-bewerbung", self._og("/", "image"))

    def test_twitter_karte_passt_zum_bild(self):
        text = self.c.get("/").text
        self.assertIn('name="twitter:card" content="summary_large_image"', text)
        self.assertIn("vorschaubild.png", re.search(
            r'name="twitter:image" content="([^"]+)"', text).group(1))


class TestSecurityTxt(unittest.TestCase):
    """RFC 9116: wohin man sich wendet, wenn man eine Lücke findet."""

    @classmethod
    def setUpClass(cls):
        hilfe.frische_datenbank()
        cls.c = TestClient(web_app)

    def test_vorhanden_und_vollstaendig(self):
        antwort = self.c.get("/.well-known/security.txt")
        self.assertEqual(antwort.status_code, 200)
        for pflicht in ("Contact:", "Expires:"):
            self.assertIn(pflicht, antwort.text)

    def test_ablauf_liegt_in_der_zukunft(self):
        """Ein abgelaufenes security.txt ist schlechter als keines."""
        from datetime import datetime, timezone
        antwort = self.c.get("/.well-known/security.txt")
        zeile = [z for z in antwort.text.splitlines() if z.startswith("Expires:")][0]
        stand = datetime.fromisoformat(zeile.split(" ", 1)[1].replace("Z", "+00:00"))
        self.assertGreater(stand, datetime.now(timezone.utc))


class TestMailLogo(unittest.TestCase):
    """Das Logo in der E-Mail hatte einen weissen Hintergrund eingebrannt.

    In der Mail sitzt es auf der navyblauen Kopfleiste - also klebte dort ein
    weisser Kasten, im hellen wie im dunklen Modus.
    """

    def test_hintergrund_ist_navy_und_nicht_weiss(self):
        from PIL import Image
        from kern.mail import LOGO_DATEI
        bild = Image.open(LOGO_DATEI).convert("RGB")
        for ecke in ((0, 0), (bild.width - 1, 0), (0, bild.height - 1),
                     (bild.width - 1, bild.height - 1)):
            with self.subTest(ecke=ecke):
                self.assertEqual(bild.getpixel(ecke), (14, 38, 71),
                                 "Ecke ist nicht #0E2647 - in der Mail wäre "
                                 "das ein Kasten auf der blauen Leiste")

    def test_kopfleiste_hat_denselben_farbwert(self):
        """Bild und Leiste müssen exakt denselben Ton haben, sonst sieht man
        die Kante."""
        from kern.mail import als_html
        html = als_html("Betreff", "Text")
        self.assertIn("background:#0E2647;padding:18px 24px", html)
        self.assertIn("background:#0E2647;", html.split("<img")[1][:400],
                      "das Bild selbst trägt keinen Rückfall-Hintergrund")

    def test_name_steht_als_text_in_der_kopfleiste(self):
        """Wer Bilder abgeschaltet hat, soll trotzdem sehen, von wem es kommt."""
        from kern.mail import als_html
        html = als_html("Betreff", "Text")
        self.assertIn("Wirtschafts- &amp; Investment-AG", html)
        self.assertIn("Max-von-Laue-Gymnasium Koblenz", html)

    def test_logo_bleibt_klein(self):
        """Das Bild hängt an jeder Mail."""
        import os
        from kern.mail import LOGO_DATEI
        self.assertLess(os.path.getsize(LOGO_DATEI), 60_000)


if __name__ == "__main__":
    unittest.main()
