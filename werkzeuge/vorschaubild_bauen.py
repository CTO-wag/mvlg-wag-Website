"""Baut die Vorschaubilder, die beim Verschicken eines Links erscheinen.

Wer die Adresse in WhatsApp, Discord, Signal oder Teams einfügt, sieht nicht
den Text der Seite, sondern dieses Bild plus Titel und Beschreibung. Es ist
damit oft der erste Eindruck der AG - und ein schiefes Bild wirkt dort
genauso wie ein Rechtschreibfehler im Anschreiben.

Erzeugt zwei Dateien in statisch/bilder/:

  vorschaubild.png            fuer die Startseite und alles Uebrige
  vorschaubild-bewerbung.png  fuer /bewerbung, mit Aufforderung

Aufruf:
    python werkzeuge/vorschaubild_bauen.py

Warum ein Skript und kein von Hand gebautes Bild: Motto, Schulname oder
Farben aendern sich; dann laeuft das hier einmal durch, statt dass jemand
Photoshop sucht. Die Groesse 1200x630 ist die, die alle Dienste erwarten
(Seitenverhaeltnis 1,91:1).

Der weisse Saum um das Wappen war ein echtes Problem der alten Fassung: Das
Logo hat halbdurchsichtige Randpunkte, deren Farbe noch die des weissen
Hintergrunds von damals traegt. Auf dunklem Grund leuchtet das als heller
Rahmen. `_saum_entfernen` rechnet ihn heraus.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

ORDNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BILDER = os.path.join(ORDNER, "statisch", "bilder")

BREITE, HOEHE = 1200, 630
NAVY_OBEN = (16, 42, 79)
NAVY_UNTEN = (8, 18, 35)
AMBER = (217, 164, 65)
AMBER_TIEF = (183, 121, 31)
WEISS = (255, 255, 255)
GEDAEMPFT = (176, 192, 214)

# Segoe UI liegt auf jedem Windows und kommt der Hausschrift am naechsten.
# Faellt auf DejaVu zurueck, damit das Skript auch anderswo laeuft.
SCHRIFTEN = {
    "fett": ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "halbfett": ["C:/Windows/Fonts/seguisb.ttf", "C:/Windows/Fonts/segoeuib.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "normal": ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}


def schrift(art: str, groesse: int):
    for pfad in SCHRIFTEN[art]:
        if os.path.exists(pfad):
            return ImageFont.truetype(pfad, groesse)
    return ImageFont.load_default()


def _hintergrund() -> Image.Image:
    """Navy-Verlauf mit einem warmen Schimmer hinter dem Wappen."""
    bild = Image.new("RGB", (BREITE, HOEHE))
    zeichner = ImageDraw.Draw(bild)
    for y in range(HOEHE):
        anteil = y / HOEHE
        farbe = tuple(int(NAVY_OBEN[i] + (NAVY_UNTEN[i] - NAVY_OBEN[i]) * anteil)
                      for i in range(3))
        zeichner.line([(0, y), (BREITE, y)], fill=farbe)

    # Weicher Lichtkegel oben in der Mitte - nimmt der Flaeche das Flache.
    schimmer = Image.new("RGBA", (BREITE, HOEHE), (0, 0, 0, 0))
    s = ImageDraw.Draw(schimmer)
    for r in range(320, 0, -8):
        deckung = int(16 * (1 - r / 320))
        s.ellipse([BREITE // 2 - r, 150 - r // 2, BREITE // 2 + r, 150 + r // 2],
                  fill=(90, 130, 200, deckung))
    bild = Image.alpha_composite(bild.convert("RGBA"), schimmer)

    # Amber-Kante oben: dasselbe Zeichen wie die Kopfzeile der Seite.
    zeichner = ImageDraw.Draw(bild)
    for y in range(8):
        anteil = y / 8
        farbe = tuple(int(AMBER[i] + (AMBER_TIEF[i] - AMBER[i]) * anteil)
                      for i in range(3))
        zeichner.line([(0, y), (BREITE, y)], fill=farbe + (255,))
    return bild


def _saum_entfernen(logo: Image.Image) -> Image.Image:
    """Rechnet den weissen Hintergrund aus den halbdurchsichtigen Raendern.

    Ein Randpunkt mit Deckung a wurde einmal ueber Weiss gerechnet:
        gesehen = echt * a + 255 * (1 - a)
    Also zurueck:
        echt = (gesehen - 255 * (1 - a)) / a
    Ohne diesen Schritt liegt auf dunklem Grund ein heller Rahmen um das
    Wappen - genau der Fehler im bisherigen Vorschaubild.
    """
    logo = logo.convert("RGBA")
    punkte = logo.load()
    for x in range(logo.width):
        for y in range(logo.height):
            r, g, b, a = punkte[x, y]
            if 0 < a < 255:
                anteil = a / 255
                punkte[x, y] = (
                    max(0, min(255, int((r - 255 * (1 - anteil)) / anteil))),
                    max(0, min(255, int((g - 255 * (1 - anteil)) / anteil))),
                    max(0, min(255, int((b - 255 * (1 - anteil)) / anteil))),
                    a)
    return logo


def _mittig(zeichner, text, y, font, farbe, abstand=0):
    kasten = zeichner.textbbox((0, 0), text, font=font)
    breite = kasten[2] - kasten[0]
    if abstand:
        breite += abstand * (len(text) - 1)
        x = (BREITE - breite) // 2
        for zeichen in text:
            zeichner.text((x, y), zeichen, font=font, fill=farbe)
            x += zeichner.textbbox((0, 0), zeichen, font=font)[2] + abstand
        return
    zeichner.text(((BREITE - breite) // 2 - kasten[0], y), text, font=font,
                  fill=farbe)


def banner(dateiname: str, titel: str, unterzeile: str, satz: str,
           fusszeile: str, logo_hoehe: int = 230) -> str:
    bild = _hintergrund()
    zeichner = ImageDraw.Draw(bild)

    logo = _saum_entfernen(Image.open(os.path.join(BILDER, "logo.png")))
    breite = int(logo.width * logo_hoehe / logo.height)
    logo = logo.resize((breite, logo_hoehe), Image.LANCZOS)
    # Derselbe weisse Saum wie in der Mail: der Grund dieses Banners ist
    # dunkelblau, und das Wappen ist es auch. Ohne Kante verschwimmt es -
    # ausgerechnet in dem Bild, das bei jedem geteilten Link erscheint.
    saum = _saum_zeichnen(logo, max(2.0, logo_hoehe / 70))
    bild.alpha_composite(saum, ((BREITE - breite) // 2, 46))
    bild.alpha_composite(logo, ((BREITE - breite) // 2, 46))

    y = 46 + logo_hoehe + 26
    _mittig(zeichner, titel, y, schrift("fett", 58), WEISS)
    y += 76
    _mittig(zeichner, unterzeile, y, schrift("normal", 30), GEDAEMPFT)
    y += 56

    zeichner.line([(BREITE // 2 - 80, y + 8), (BREITE // 2 + 80, y + 8)],
                  fill=AMBER, width=3)
    y += 34
    _mittig(zeichner, satz, y, schrift("halbfett", 32), AMBER)

    # Fusszeile: die Adresse, damit auch ohne Klick klar ist, wohin es geht.
    # Der Rahmen wird auf einer eigenen Ebene gezeichnet und dann eingemischt:
    # ImageDraw ersetzt Punkte, statt sie zu ueberblenden - eine Fuellung mit
    # Deckung 18 waere sonst ein weisser Balken statt eines Hauchs.
    fuss = schrift("normal", 24)
    kasten = zeichner.textbbox((0, 0), fusszeile, font=fuss)
    b, h = kasten[2] - kasten[0], kasten[3] - kasten[1]
    x0 = (BREITE - b) // 2 - 20
    y0 = HOEHE - 66
    ebene = Image.new("RGBA", bild.size, (0, 0, 0, 0))
    ImageDraw.Draw(ebene).rounded_rectangle(
        [x0, y0, x0 + b + 40, y0 + h + 20], radius=999,
        fill=(255, 255, 255, 16), outline=(255, 255, 255, 46), width=1)
    bild.alpha_composite(ebene)
    ImageDraw.Draw(bild).text((x0 + 20 - kasten[0], y0 + 10 - kasten[1]),
                              fusszeile, font=fuss, fill=GEDAEMPFT)

    ziel = os.path.join(BILDER, dateiname)
    bild.convert("RGB").save(ziel, "PNG", optimize=True)
    return f"{dateiname}: {os.path.getsize(ziel) / 1024:.0f} KB"


def _saum_zeichnen(logo: Image.Image, staerke: float) -> Image.Image:
    """Ein weisser Umriss in der Form des Bildes.

    Entspricht dem, was im Browser zwei gestapelte drop-shadow ohne Versatz
    machen: die Alphamaske weichzeichnen und aufhellen, bis eine Kante steht.
    """
    from PIL import ImageFilter
    maske = logo.getchannel("A").filter(ImageFilter.GaussianBlur(staerke))
    # Aufhellen, sonst bliebe ein grauer Hauch statt einer Kante.
    maske = maske.point(lambda w: min(255, int(w * 2.6)))
    umriss = Image.new("RGBA", logo.size, (255, 255, 255, 0))
    umriss.putalpha(maske)
    return umriss


def mail_logo() -> str:
    """Das Wappen fuer die E-Mail-Kopfleiste - freistehend, mit hellem Saum.

    Die Geschichte dieser Funktion in drei Schritten, weil jeder davon einen
    Fehler behoben und den naechsten aufgedeckt hat:

    1. Ganz frueher lag ein weisser Hintergrund fest im Bild. Auf der
       navyblauen Kopfleiste klebte damit ein weisser Kasten.
    2. Also bekam das Bild denselben Navy-Ton wie die Leiste. Auf dem
       Bildschirm war der Uebergang unsichtbar - bis eine Mail auf einem
       iPhone im Dunkelmodus ankam. Apple Mail rechnet die Farben solcher
       Nachrichten selbst um: Die Leiste wurde hellblau, die weisse Schrift
       dunkel. Nur das Bild konnte es nicht umfaerben, und so sass ein
       dunkelblauer Klotz auf hellblauem Grund.
    3. Jetzt traegt das Bild gar keinen Hintergrund mehr.

    Das Gegenargument gegen Transparenz war bisher, ein dunkles Wappen
    verschwaende auf dunklem Grund. Das stimmt - aber genau dagegen gibt es
    den Saum, den diese Datei ohnehin schon zeichnet. Mit ihm steht das
    Wappen auf Navy, auf Hellblau und auf Fast-Schwarz gleich gut da, und
    ein Kasten kann gar nicht erst entstehen, egal was ein Mailprogramm mit
    dem Hintergrund anstellt.

    Der zweite Teil der Behebung steht in kern/mail.py: Die Nachricht meldet
    jetzt beide Farbschemata an, damit Apple Mail die Farben ueberhaupt in
    Ruhe laesst. Diese Datei ist die Absicherung fuer alle Programme, die es
    trotzdem tun.
    """
    logo = _saum_entfernen(Image.open(os.path.join(BILDER, "logo.png")))
    breite = 300                             # angezeigt mit 72 - fuer scharfe Schirme
    hoehe = round(logo.height * breite / logo.width)
    logo = logo.resize((breite, hoehe), Image.LANCZOS)

    # Der helle Saum. Das Wappen ist selbst dunkelblau; auf der navyblauen
    # Leiste verschwaemme es sonst zu einem Fleck. Auf der Website macht das
    # eine CSS-Regel (img.wappen), in einer E-Mail gibt es die nicht - dort
    # muss der Saum ins Bild.
    # 6.0 bezogen auf die 300 Pixel Breite dieser Datei. Bei 3.5 - dem Wert
    # von frueher, als noch ein Navy-Grund darunter lag - traegt er auf einem
    # dunklen Grund nicht mehr; ab etwa 9 faengt er auf hellem Grund an zu
    # leuchten. Dazwischen sieht es auf jedem Grund richtig aus.
    rand = 12                                # Platz, damit der Saum nicht anstoesst
    bild = Image.new("RGBA", (breite + rand * 2, hoehe + rand * 2), (0, 0, 0, 0))
    saum = _saum_zeichnen(logo, 6.0)
    bild.paste(saum, (rand, rand), saum)
    # alpha_composite statt paste: Auf durchsichtigem Grund wuerde paste die
    # Deckung des Wappens einfach ueberschreiben und die weichen Kanten des
    # Saums darunter wegschneiden.
    bild.alpha_composite(logo, (rand, rand))

    # Das Wappen hat wenige Farben - eine Palette spart drei Viertel der
    # Groesse. Das Bild haengt an jeder einzelnen Mail, das zaehlt.
    # FASTOCTREE statt MEDIANCUT: Nur dieses Verfahren nimmt den Alphakanal
    # mit. Mit MEDIANCUT waere die Durchsichtigkeit weg und der Kasten
    # zurueck - der Fehler, um den es hier ueberhaupt geht.
    sparsam = bild.quantize(colors=128, method=Image.FASTOCTREE,
                            dither=Image.NONE)
    ziel = os.path.join(BILDER, "logo-mail.png")
    sparsam.save(ziel, "PNG", optimize=True)
    return (f"logo-mail.png: {bild.size[0]}x{bild.size[1]}, "
            f"{os.path.getsize(ziel) / 1024:.0f} KB, durchsichtig mit Saum")


if __name__ == "__main__":
    print(mail_logo())
    print(banner("vorschaubild.png",
                 "Wirtschafts- & Investment-AG",
                 "Max-von-Laue-Gymnasium Koblenz",
                 "An alle, die größer denken.",
                 "mvlg-wag.de"))
    print(banner("vorschaubild-bewerbung.png",
                 "Bewirb dich für die AG",
                 "Wirtschafts- & Investment-AG am MvLG Koblenz",
                 "Kein Vorwissen nötig. Nur Interesse.",
                 "mvlg-wag.de/bewerbung",
                 logo_hoehe=200))
    sys.exit(0)
