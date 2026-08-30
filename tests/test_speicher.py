"""Hochgeladene Dateien im Supabase-Storage.

Der teuerste Fehler waere hier nicht, dass etwas nicht hochgeht - das faellt
sofort auf. Teuer ist die Zwischenform: Ein Ticket, das mit einem Dateinamen
in der Datenbank steht, hinter dem nichts liegt. Deshalb pruefen die Tests vor
allem, was bei einem Fehlschlag passiert.

Der Storage selbst wird nicht angesprochen. Ein Test, der ein Bild in den
echten Bucket legt, braucht Netz, einen gueltigen Schluessel und laesst
Dateien zurueck - stattdessen tritt hier ein Bucket im Arbeitsspeicher an
seine Stelle.
"""

import json
import os
import unittest

from tests import hilfe                                      # noqa: F401

from kern import einstellungen as cfg
from kern import speicher
from tests.hilfe import angemeldeter_client, csrf_aus


class Bucketattrappe:
    """Steht anstelle von speicher._anfrage und merkt sich alles."""

    def __init__(self):
        self.dateien = {}
        self.aufrufe = []
        self.faellt_aus = False

    def __call__(self, methode, pfad, daten=None, inhaltstyp="", kopf=None,
                 fehlt_ist_leer=False):
        self.aufrufe.append((methode, pfad))
        if self.faellt_aus:
            raise speicher.SpeicherFehler("Supabase Storage nicht erreichbar: Test")
        teile = pfad.strip("/").split("/")
        if teile[:2] == ["object", "list"]:
            wunsch = json.loads(daten.decode("utf-8"))
            passend = sorted(k for k in self.dateien
                             if k.startswith(wunsch["prefix"]))
            ausschnitt = passend[wunsch["offset"]:wunsch["offset"] + wunsch["limit"]]
            return json.dumps([{"name": k.split("/", 1)[1]}
                               for k in ausschnitt]).encode("utf-8")
        if teile[0] == "bucket":
            if methode == "GET":
                return None if fehlt_ist_leer else b"{}"
            return b"{}"
        schluessel = "/".join(teile[2:])                      # bereich/name
        if methode == "POST":
            self.dateien[schluessel] = daten
            return b"{}"
        if methode == "GET":
            inhalt = self.dateien.get(schluessel)
            if inhalt is None and fehlt_ist_leer:
                return None
            if inhalt is None:
                raise speicher.SpeicherFehler("Supabase Storage 404: not found")
            return inhalt
        if methode == "DELETE":
            self.dateien.pop(schluessel, None)
            return b"{}"
        raise AssertionError(f"unerwartet: {methode} {pfad}")


class MitStorage(unittest.TestCase):
    """Basis: Storage eingerichtet, aber ohne Netz."""

    def setUp(self):
        self.vorher = (cfg.SUPABASE_URL, cfg.SUPABASE_SERVICE_KEY,
                       speicher._anfrage)
        cfg.SUPABASE_URL = "https://beispiel.supabase.co"
        cfg.SUPABASE_SERVICE_KEY = "dienst-schluessel"
        self.bucket = Bucketattrappe()
        speicher._anfrage = self.bucket

    def tearDown(self):
        (cfg.SUPABASE_URL, cfg.SUPABASE_SERVICE_KEY,
         speicher._anfrage) = self.vorher
        for bereich in (speicher.SUPPORT, speicher.REDAKTION):
            for name in speicher.auf_platte(bereich):
                os.remove(os.path.join(speicher.ORDNER[bereich], name))


class TestOhneSchluessel(unittest.TestCase):
    """Ohne Schluessel bleibt alles beim Datenordner - sonst stuende die
    Entwicklung ohne Netz still."""

    def tearDown(self):
        for name in speicher.auf_platte(speicher.SUPPORT):
            os.remove(os.path.join(speicher.ORDNER[speicher.SUPPORT], name))

    def test_ablegen_holen_entfernen(self):
        self.assertFalse(speicher.in_supabase())
        speicher.ablegen(speicher.SUPPORT, "a1.png", b"bilddaten")
        pfad = os.path.join(cfg.SUPPORT_UPLOAD_DIR, "a1.png")
        self.assertTrue(os.path.exists(pfad))
        self.assertEqual(speicher.holen(speicher.SUPPORT, "a1.png"), b"bilddaten")
        speicher.entfernen(speicher.SUPPORT, "a1.png")
        self.assertFalse(os.path.exists(pfad))

    def test_unbekannte_datei(self):
        self.assertIsNone(speicher.holen(speicher.SUPPORT, "gibtsnicht.png"))


class TestNamenspruefung(unittest.TestCase):
    """Die Namen kommen aus der Datenbank und sind Zufallswerte. Trotzdem:
    Wer hier einmal einen Pfad durchliesse, oeffnete den ganzen Datenordner."""

    def test_pfadangaben_werden_abgewiesen(self):
        for name in ("../geheim.db", "unter/ordner.png", "a\\b.png", "", ".."):
            with self.assertRaises(speicher.SpeicherFehler):
                speicher.holen(speicher.SUPPORT, name)

    def test_unbekannter_bereich(self):
        with self.assertRaises(speicher.SpeicherFehler):
            speicher.ablegen("erfunden", "a.png", b"x")


class TestMitStorage(MitStorage):
    def test_nichts_landet_auf_der_platte(self):
        speicher.ablegen(speicher.SUPPORT, "b2.png", b"daten", "image/png")
        self.assertFalse(os.path.exists(
            os.path.join(cfg.SUPPORT_UPLOAD_DIR, "b2.png")))
        self.assertEqual(self.bucket.dateien["support/b2.png"], b"daten")

    def test_bereich_wird_zum_unterordner(self):
        speicher.ablegen(speicher.REDAKTION, "c3.pdf", b"pdf")
        self.assertIn("redaktion/c3.pdf", self.bucket.dateien)

    def test_holen_kommt_aus_dem_bucket(self):
        speicher.ablegen(speicher.SUPPORT, "d4.png", b"oben")
        self.assertEqual(speicher.holen(speicher.SUPPORT, "d4.png"), b"oben")

    def test_alte_dateien_auf_der_platte_bleiben_lesbar(self):
        """Der Grund, warum holen() zuerst den Datenordner ansieht: Was vor
        dem Umzug hochgeladen wurde, liegt nur dort."""
        os.makedirs(cfg.SUPPORT_UPLOAD_DIR, exist_ok=True)
        with open(os.path.join(cfg.SUPPORT_UPLOAD_DIR, "alt.png"), "wb") as ziel:
            ziel.write(b"von frueher")
        self.assertEqual(speicher.holen(speicher.SUPPORT, "alt.png"),
                         b"von frueher")
        self.assertNotIn("support/alt.png", self.bucket.dateien)

    def test_entfernen_raeumt_beide_seiten(self):
        os.makedirs(cfg.SUPPORT_UPLOAD_DIR, exist_ok=True)
        with open(os.path.join(cfg.SUPPORT_UPLOAD_DIR, "e5.png"), "wb") as ziel:
            ziel.write(b"beides")
        self.bucket.dateien["support/e5.png"] = b"beides"
        speicher.entfernen(speicher.SUPPORT, "e5.png")
        self.assertFalse(os.path.exists(
            os.path.join(cfg.SUPPORT_UPLOAD_DIR, "e5.png")))
        self.assertNotIn("support/e5.png", self.bucket.dateien)

    def test_stoerung_beim_ablegen_wird_gemeldet(self):
        self.bucket.faellt_aus = True
        with self.assertRaises(speicher.SpeicherFehler):
            speicher.ablegen(speicher.SUPPORT, "f6.png", b"x")
        # Und schreibt gerade NICHT ersatzweise auf die Platte.
        self.assertFalse(os.path.exists(
            os.path.join(cfg.SUPPORT_UPLOAD_DIR, "f6.png")))

    def test_liste_blaettert_durch(self):
        for i in range(120):
            speicher.ablegen(speicher.SUPPORT, f"g{i:03}.png", b"x")
        self.assertEqual(len(speicher.liste(speicher.SUPPORT)), 120)


class TestAntwort(MitStorage):
    def test_bild_aus_dem_bucket(self):
        speicher.ablegen(speicher.SUPPORT, "h7.png", b"PNGDATEN")
        antwort = speicher.antwort(speicher.SUPPORT, "h7.png")
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.media_type, "image/png")
        self.assertEqual(antwort.body, b"PNGDATEN")
        self.assertNotIn("content-disposition", antwort.headers)

    def test_anhang_behaelt_seinen_namen(self):
        speicher.ablegen(speicher.REDAKTION, "i8.pdf", b"%PDF")
        antwort = speicher.antwort(speicher.REDAKTION, "i8.pdf",
                                   dateiname="Plakat Herbst.pdf")
        self.assertIn("Plakat Herbst.pdf", antwort.headers["content-disposition"])

    def test_umlaute_im_dateinamen(self):
        """Ohne den utf-8-Zweig hiesse die Datei beim Herunterladen anders."""
        speicher.ablegen(speicher.REDAKTION, "j9.pdf", b"%PDF")
        antwort = speicher.antwort(speicher.REDAKTION, "j9.pdf",
                                   dateiname="Präsentation.pdf")
        self.assertIn("utf-8''", antwort.headers["content-disposition"])

    def test_fehlende_datei_ist_ein_404(self):
        self.assertEqual(
            speicher.antwort(speicher.SUPPORT, "weg.png").status_code, 404)

    def test_stoerung_ist_kein_404(self):
        """502 statt 404: „gerade nicht erreichbar“ und „gibt es nicht“ sind
        zwei verschiedene Nachrichten - und nur eine davon heisst warten."""
        self.bucket.faellt_aus = True
        self.assertEqual(
            speicher.antwort(speicher.SUPPORT, "k10.png").status_code, 502)


class TestSupportUpload(MitStorage):
    """Der ganze Weg: hochladen, in der Datenbank landen, wieder abrufen."""

    def setUp(self):
        super().setUp()
        self.web, self.dash = angemeldeter_client()

    def _anlegen(self, bild=b"\x89PNG-daten"):
        seite = self.dash.get("/dashboard/support").text
        return self.dash.post("/dashboard/support", data={
            "csrf": csrf_aus(seite), "betreff": "Bildschirm bleibt weiss",
            "text": "Seit heute Morgen laedt das Dashboard nicht."},
            files={"bild": ("schirm.png", bild, "image/png")})

    def test_bild_geht_in_den_bucket(self):
        antwort = self._anlegen()
        self.assertEqual(antwort.status_code, 200)
        self.assertIn("angekommen", antwort.text)
        namen = list(self.bucket.dateien)
        self.assertEqual(len(namen), 1)
        self.assertTrue(namen[0].startswith("support/"))
        self.assertEqual(self.bucket.dateien[namen[0]], b"\x89PNG-daten")

    def test_bild_kommt_wieder_heraus(self):
        self._anlegen()
        name = list(self.bucket.dateien)[0].split("/", 1)[1]
        antwort = self.dash.get(f"/dashboard/support/bild/{name}")
        self.assertEqual(antwort.status_code, 200)
        self.assertEqual(antwort.content, b"\x89PNG-daten")

    def test_ohne_bucket_kein_ticket(self):
        """Sonst stuende in der Datenbank ein Dateiname ohne Datei - und
        niemand wuesste, dass der Screenshot fehlt."""
        from kern.datenbank import SessionLocal
        from kern.modelle import SupportTicket

        def tickets():
            db = SessionLocal()
            try:
                return db.query(SupportTicket).count()
            finally:
                db.close()

        vorher = tickets()
        self.bucket.faellt_aus = True
        antwort = self._anlegen()
        self.assertIn("nicht gespeichert werden", antwort.text)
        self.assertEqual(tickets(), vorher)


if __name__ == "__main__":
    unittest.main()
