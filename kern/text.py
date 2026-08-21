"""Kleine Helfer fuer Text, Zeit und Zahlen.

Bewusst ein eigenes Modul: diese Funktionen werden ueberall gebraucht und
duerfen deshalb nichts aus dem Rest der Anwendung importieren. So kann jedes
andere Modul sie holen, ohne einen Ringschluss zu bauen.
"""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from markupsafe import escape as html_escape

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WOCHENTAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag",
              "Freitag", "Samstag", "Sonntag")
MONATE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember")


def _berliner_zeitzone():
    """Deutsche Zeit - mit Rueckfall, falls die Zeitzonendaten fehlen.

    Auf einem frisch aufgesetzten Windows ohne das Paket tzdata wirft
    ZoneInfo einen Fehler. Ein fester Offset ist dann zwar im Winter eine
    Stunde daneben, aber die Anwendung startet.
    """
    try:
        return ZoneInfo("Europe/Berlin")
    except Exception:                                        # pragma: no cover
        return timezone(timedelta(hours=1))


BERLIN_TZ = _berliner_zeitzone()


def utcnow() -> datetime:
    """UTC-Zeitstempel ohne Zeitzoneninfo.

    Alle Zeitspalten der Datenbank enthalten seit V1 naive UTC-Werte.
    Wuerden wir ab jetzt zeitzonenbewusste Werte schreiben, liefe jeder
    Vergleich zwischen altem und neuem Wert in einen TypeError.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def nach_berlin(dt, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Naiven UTC-Zeitstempel als deutsche Ortszeit ausgeben."""
    if not dt:
        return ""
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt.strftime("%d.%m.%Y")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BERLIN_TZ).strftime(fmt)


def heute_berlin() -> date:
    return datetime.now(BERLIN_TZ).date()


def datum_lang(d) -> str:
    """"Montag, 3. März 2026" - fuer Ueberschriften und Erinnerungen."""
    if not d:
        return ""
    return f"{WOCHENTAGE[d.weekday()]}, {d.day}. {MONATE[d.month - 1]} {d.year}"


def relativ(dt) -> str:
    """"vor 3 Minuten" statt eines Zeitstempels - fuer Listen und Verlaeufe."""
    if not dt:
        return ""
    sekunden = (utcnow() - dt).total_seconds()
    if sekunden < 0:
        return "gerade eben"
    if sekunden < 60:
        return "gerade eben"
    if sekunden < 3600:
        n = int(sekunden // 60)
        return f"vor {n} Minute{'n' if n != 1 else ''}"
    if sekunden < 86400:
        n = int(sekunden // 3600)
        return f"vor {n} Stunde{'n' if n != 1 else ''}"
    if sekunden < 30 * 86400:
        n = int(sekunden // 86400)
        return f"vor {n} Tag{'en' if n != 1 else ''}"
    return nach_berlin(dt, "%d.%m.%Y")


def sauber(wert) -> str:
    return (wert or "").strip()


def kuerzen(wert, laenge: int) -> str:
    """Text auf eine Hoechstlaenge bringen - mit sichtbarer Auslassung."""
    t = sauber(wert)
    return t if len(t) <= laenge else t[: max(1, laenge - 1)].rstrip() + "…"


def esc(wert) -> str:
    """HTML-Maskierung fuer Werte, die von Hand in HTML eingesetzt werden.

    Rueckgabe ist bewusst ein einfaches str und kein Markup-Objekt: Markup
    maskiert beim Verketten mit + auch die andere Seite mit, wodurch aus
    "<td>" + esc(name) sichtbarer Quelltext wuerde.
    """
    return str(html_escape("" if wert is None else str(wert)))


def csv_sicher(wert) -> str:
    """Schuetzt CSV-Exporte vor Formel-Injektion.

    Tabellenkalkulationen deuten Zellen, die mit = + - @ oder Tab/CR beginnen,
    als Formel. Ein vorangestelltes Apostroph zwingt sie zu Text.
    """
    t = "" if wert is None else str(wert)
    if t and t[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + t
    return t


def email_normal(wert: str) -> str:
    return sauber(wert).lower()


def email_gueltig(wert: str) -> bool:
    return bool(wert and len(wert) <= 160 and EMAIL_RE.match(wert))


def schluessel_normal(wert: str) -> str:
    """Aus einer Eingabe einen technischen Schluessel machen (a-z, 0-9, _, -)."""
    return re.sub(r"[^a-z0-9_-]", "", sauber(wert).lower())


def telefon_normal(wert: str, landesvorwahl: str = "49") -> str:
    """Telefonnummer auf reine Ziffern in internationaler Form bringen.

    In der Datenbank stehen Nummern in allen Schreibweisen nebeneinander:
    "+4915112209314", "+49 1525 7168299", "0163 6177263". Fuer WhatsApp und
    fuer Vergleiche braucht es genau eine Form: Landesvorwahl ohne Plus.

    Der haeufigste Fall aus der Bewerbung ist eine Nummer ganz ohne Vorsatz -
    "1516 1234567", so wie man sie jemandem zuruft. Frueher blieb die genau so
    stehen und ging als Auslandsnummer ins Leere; die Willkommensnachricht kam
    dann nie an, ohne dass es jemand merkte. Solche Nummern bekommen die
    Landesvorwahl vorgesetzt.
    """
    roh = re.sub(r"[^\d+]", "", wert or "")
    if not roh:
        return ""
    if roh.startswith("00"):
        roh = "+" + roh[2:]
    if roh.startswith("+"):
        return roh[1:]
    if roh.startswith("0"):
        return landesvorwahl + roh[1:]
    # Kein Vorsatz. Steht die Landesvorwahl schon davor (jemand hat das Plus
    # weggelassen), bleibt sie stehen - sonst waere aus 49163... plötzlich
    # 4949163...
    if roh.startswith(landesvorwahl) and len(roh) >= len(landesvorwahl) + 9:
        return roh
    return landesvorwahl + roh


# Eine deutsche Rufnummer hat mit Landesvorwahl 11 bis 14 Ziffern
# (49 + 9 bis 12). Kuerzer ist ein Zahlendreher, laenger ein Versehen.
TELEFON_MIN, TELEFON_MAX = 10, 15


def telefon_gueltig(wert: str, landesvorwahl: str = "49") -> bool:
    """Sieht das nach einer Rufnummer aus, mit der man jemanden erreicht?"""
    ziffern = telefon_normal(wert, landesvorwahl)
    return bool(ziffern) and TELEFON_MIN <= len(ziffern) <= TELEFON_MAX


def telefon_anzeige(wert: str, landesvorwahl: str = "49") -> str:
    """Lesbare Schreibweise: "+49 163 6177263".

    Gespeichert wird diese Form, nicht die nackten Ziffern: Sie ist eindeutig
    (das Plus sagt "international"), laesst sich vorlesen und man erkennt
    einen Zahlendreher eher als in einem 13-stelligen Block.
    """
    ziffern = telefon_normal(wert, landesvorwahl)
    if not ziffern:
        return ""
    if ziffern.startswith(landesvorwahl):
        vorwahl, rest = landesvorwahl, ziffern[len(landesvorwahl):]
    else:
        # Auslaendische Nummer: die meisten europaeischen Laender haben eine
        # zweistellige Vorwahl (43, 41, 31, 33 ...). Zur Not steht die Trennung
        # eine Stelle daneben - die Ziffern bleiben in jedem Fall richtig.
        vorwahl, rest = ziffern[:2], ziffern[2:]
    if not rest:
        return "+" + ziffern
    # Mobilnummern beginnen mit 15/16/17 - danach trennt man nach drei Ziffern.
    if rest.startswith("1") and len(rest) > 4:
        return f"+{vorwahl} {rest[:3]} {rest[3:]}"
    return f"+{vorwahl} {rest}"


def initialen(vorname: str, nachname: str) -> str:
    a = (sauber(vorname) or "?")[0]
    b = (sauber(nachname) or "?")[0]
    return (a + b).upper()


#  Geld
#  Betraege stehen ueberall als ganze Cent. Fliesskommazahlen koennen 0,10 Euro
#  nicht exakt darstellen; addiert man genug davon, fehlen am Ende Cent, die
#  niemand erklaeren kann.

def betrag_in_cent(eingabe: str):
    """"12,50", "12.50", "1.234,56" oder "-8" zu Cent. None bei Unsinn.

    Absichtlich streng bei Leerzeichen zwischen Ziffern: "12 50" ergab frueher
    1250,00 Euro, weil das Leerzeichen einfach entfernt wurde. Wer so tippt,
    meint aber 12,50 - und eine Buchung, die um den Faktor hundert daneben
    liegt, faellt in einer Kasse erst beim Abrechnen auf. Lieber nachfragen.
    Als Tausendertrenner bleibt das Leerzeichen erlaubt, wenn danach genau
    drei Ziffern stehen ("1 234,56").
    """
    text = sauber(eingabe).replace("€", "").replace("EUR", "")
    text = text.replace(" ", " ").replace(" ", " ").strip()
    if not text:
        return None
    # "12,-" ist im Deutschen ueblich fuer "12 Euro genau".
    if text.endswith(",-") or text.endswith(".-"):
        text = text[:-2]
    if re.search(r"\d\s+\d", text) and not re.fullmatch(
            r"-?\d{1,3}( \d{3})+([.,]\d+)?", text):
        return None
    text = text.replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        wert = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if abs(wert) > Decimal("10000000"):
        return None
    return int((wert * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def euro(cent) -> str:
    """Cent als deutsche Betragsangabe: 123456 -> "1.234,56 €"."""
    if cent is None:
        return "–"
    minus = cent < 0
    ganz, rest = divmod(abs(int(cent)), 100)
    text = f"{ganz:,}".replace(",", ".") + f",{rest:02d} €"
    return ("−" + text) if minus else text


def prozent(teil, ganzes) -> int:
    if not ganzes:
        return 0
    return max(0, min(100, round(teil / ganzes * 100)))
