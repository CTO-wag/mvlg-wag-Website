"""Passwoerter, Token, zweiter Faktor, Anmeldebremse.

Was gegenueber V1 dazugekommen ist:

  * **Zweiter Faktor (TOTP)** - freiwillig je Konto, ohne zusaetzliches Paket.
    Der Algorithmus ist RFC 6238 und besteht aus HMAC-SHA1 plus Base32; beides
    bringt Python mit. Eine Abhaengigkeit weniger, die jemand installieren muss.
  * **Passwortpruefung gegen die haeufigsten Muster** - "Passwort2024!" erfuellt
    jede Laengenregel und ist trotzdem geraten, bevor man die Zeile zu Ende
    gelesen hat.
  * **Anmeldeprotokoll** - auch die Fehlversuche, mit IP und Zeitpunkt.
  * **Sitzungen an den Browser gebunden** - eine gestohlene Sitzungs-ID nuetzt
    in einem anderen Browser nichts mehr.
  * **CSRF-Token mit Ablauf** statt eines Tokens fuer die ganze Sitzung.
"""

import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
import unicodedata
from urllib.parse import quote

import bcrypt

from kern.text import sauber, utcnow

#  Passwoerter
#  bcrypt bleibt: die vorhandenen Hashes sind bcrypt, und ein Wechsel des
#  Verfahrens haette bedeutet, dass sich alle neu anmelden muessen. Die Kosten
#  steigen aber von den frueheren 12 auf 13 Runden - jede Anmeldung rechnet
#  danach automatisch auf den neuen Wert um (siehe passwort_pruefen).
BCRYPT_RUNDEN = 13

PASSWORT_REGEL = ("Mindestens 12 Zeichen, dazu Groß- und Kleinbuchstaben "
                  "sowie eine Ziffer.")

# Keine Wortliste mit Millionen Eintraegen - nur die Muster, die in einer
# Schul-AG tatsaechlich vorkommen. Verglichen wird kleingeschrieben und ohne
# die uebliche Zeichenersetzung (a->@, o->0, ...).
_SCHWACHE_MUSTER = (
    "passwort", "password", "123456", "qwertz", "qwerty", "wirtschaft",
    "investment", "mvlg", "schule", "gymnasium", "koblenz", "admin",
    "willkommen", "sommer", "winter", "geheim", "letmein", "iloveyou",
    "aktien", "boerse", "borse", "money", "startup",
)
_ERSETZUNGEN = str.maketrans({"@": "a", "0": "o", "1": "i", "3": "e",
                              "4": "a", "5": "s", "7": "t", "$": "s", "!": "i"})


def passwort_hashen(passwort: str) -> str:
    return bcrypt.hashpw(passwort.encode("utf-8"),
                         bcrypt.gensalt(BCRYPT_RUNDEN)).decode("utf-8")


def passwort_pruefen(passwort: str, hash_wert: str) -> bool:
    try:
        return bcrypt.checkpw(passwort.encode("utf-8"), hash_wert.encode("utf-8"))
    except Exception:
        return False


def hash_veraltet(hash_wert: str) -> bool:
    """Wurde dieser Hash mit weniger Runden erzeugt als heute ueblich?

    Wird bei jeder gelungenen Anmeldung geprueft; passt es nicht, wird das
    Passwort still neu gehasht. So wandert der Bestand mit, ohne dass jemand
    etwas tun muss.
    """
    treffer = re.match(r"^\$2[aby]\$(\d{2})\$", hash_wert or "")
    return bool(treffer) and int(treffer.group(1)) < BCRYPT_RUNDEN


def passwort_bewerten(passwort: str, name_teile=()) -> tuple:
    """(gueltig, Meldung). Die Meldung nennt genau, was fehlt.

    In V1 gab es eine einzige Regel-Zeile, egal woran es lag. Wer ein 11
    Zeichen langes Passwort eingab, las denselben Satz wie jemand, der die
    Ziffer vergessen hatte.
    """
    passwort = passwort or ""
    fehlt = []
    if len(passwort) < 12:
        fehlt.append("mindestens 12 Zeichen")
    if not re.search(r"[a-zäöüß]", passwort):
        fehlt.append("einen Kleinbuchstaben")
    if not re.search(r"[A-ZÄÖÜ]", passwort):
        fehlt.append("einen Großbuchstaben")
    if not re.search(r"\d", passwort):
        fehlt.append("eine Ziffer")
    if fehlt:
        if len(fehlt) == 1:
            return False, f"Dem Passwort fehlt noch {fehlt[0]}."
        return False, ("Dem Passwort fehlen noch: " + ", ".join(fehlt[:-1])
                       + " und " + fehlt[-1] + ".")

    vereinfacht = unicodedata.normalize("NFKD", passwort.lower()).translate(_ERSETZUNGEN)
    for muster in _SCHWACHE_MUSTER:
        if muster in vereinfacht:
            return False, (f"Das Passwort enthält „{muster}“ und ist damit leicht "
                           "zu erraten. Bitte etwas wählen, das nichts mit der AG "
                           "oder der Schule zu tun hat.")
    for teil in name_teile:
        teil = sauber(teil).lower()
        if len(teil) >= 4 and teil in vereinfacht:
            return False, ("Der eigene Name darf nicht im Passwort stehen.")
    if len(set(passwort)) <= 4:
        return False, "Das Passwort besteht aus zu wenigen verschiedenen Zeichen."
    if re.search(r"(.)\1{3,}", passwort):
        return False, "Vier gleiche Zeichen hintereinander sind zu wenig."
    return True, ""


def passwort_gueltig(passwort: str) -> bool:
    return passwort_bewerten(passwort)[0]


def passwort_vorschlag() -> str:
    """Ein leicht abzutippendes, trotzdem starkes Startpasswort.

    Silben statt Zufallszeichen: ein Passwort, das der Vorstand jemandem
    vorlesen muss, wird sonst falsch abgetippt und landet als Support-Anfrage.
    """
    silben = ("ka", "re", "mo", "lu", "ta", "vi", "no", "sa", "de", "pi",
              "gu", "fer", "lin", "bor", "mal", "ton", "wes", "rik")
    wort = "".join(secrets.choice(silben) for _ in range(3))
    return (wort.capitalize() + "-"
            + "".join(secrets.choice(silben) for _ in range(2)).capitalize()
            + str(secrets.randbelow(90) + 10))


#  Token
def token_erzeugen(laenge: int = 32) -> str:
    return secrets.token_urlsafe(laenge)


def token_hashen(roh: str) -> str:
    """Nur der Hash landet in der Datenbank - aus ihm laesst sich das Token
    nicht zurueckrechnen."""
    return hashlib.sha256((roh or "").encode("utf-8")).hexdigest()


def gleich(a: str, b: str) -> bool:
    """Zeitunabhaengiger Vergleich - verhindert, dass sich ein Token ueber die
    Antwortzeit Zeichen fuer Zeichen erraten laesst."""
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


#  Zweiter Faktor (TOTP, RFC 6238)
TOTP_SCHRITT = 30
TOTP_STELLEN = 6
# Ein Schritt Toleranz in beide Richtungen: Handys gehen selten sekundengenau.
TOTP_TOLERANZ = 1


def totp_geheimnis() -> str:
    """20 Byte Zufall als Base32 - das Format, das jede Authenticator-App liest."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp_code(geheimnis: str, zeitpunkt: float = None) -> str:
    schluessel = base64.b32decode(geheimnis + "=" * (-len(geheimnis) % 8), casefold=True)
    zaehler = int((zeitpunkt if zeitpunkt is not None else time.time()) // TOTP_SCHRITT)
    roh = hmac.new(schluessel, struct.pack(">Q", zaehler), hashlib.sha1).digest()
    versatz = roh[-1] & 0x0F
    zahl = struct.unpack(">I", roh[versatz:versatz + 4])[0] & 0x7FFFFFFF
    return str(zahl % (10 ** TOTP_STELLEN)).zfill(TOTP_STELLEN)


def totp_pruefen(geheimnis: str, eingabe: str) -> bool:
    eingabe = re.sub(r"\s", "", eingabe or "")
    if not geheimnis or not eingabe.isdigit() or len(eingabe) != TOTP_STELLEN:
        return False
    jetzt = time.time()
    for versatz in range(-TOTP_TOLERANZ, TOTP_TOLERANZ + 1):
        if gleich(totp_code(geheimnis, jetzt + versatz * TOTP_SCHRITT), eingabe):
            return True
    return False


#  Ersatzcodes fuer den zweiten Faktor
#  Ein zweiter Faktor ohne Rueckweg ist eine Falle: Wer sein Handy verliert,
#  verliert sein Konto. Deshalb bekommt jeder beim Einschalten acht Codes, die
#  je einmal statt des Zahlencodes gelten. Gespeichert werden nur Pruefwerte -
#  aus der Datenbank laesst sich kein Code zurueckrechnen.
ERSATZCODES_ANZAHL = 8


def ersatzcodes_erzeugen(anzahl: int = ERSATZCODES_ANZAHL) -> tuple:
    """(Klartext-Liste zum Anzeigen, JSON-Text fuer die Datenbank).

    Die Codes sind bewusst kurz und in zwei Haelften geteilt: Man schreibt sie
    ab oder druckt sie aus, und dabei ist "3f9a-c072" weniger fehleranfaellig
    als eine lange Zeichenkette. Vier Bytes je Haelfte reichen: Ein Code gilt
    nur einmal, und die Anmeldung ist ohnehin gebremst.
    """
    import json
    klartext = []
    for _ in range(anzahl):
        klartext.append(f"{secrets.token_hex(2)}-{secrets.token_hex(2)}")
    gespeichert = json.dumps([token_hashen(c) for c in klartext])
    return klartext, gespeichert


def ersatzcode_einloesen(gespeichert: str, eingabe: str):
    """Prueft einen Ersatzcode und verbraucht ihn.

    Gibt (erfolg, neuer_gespeicherter_stand) zurueck. Ein eingeloester Code
    verschwindet - sonst waere er ein zweites Passwort statt einer Notluke.
    """
    import json
    if not gespeichert or not eingabe:
        return False, gespeichert
    sauber = eingabe.strip().lower().replace(" ", "")
    if not sauber:
        return False, gespeichert
    try:
        offen = json.loads(gespeichert)
    except (ValueError, TypeError):
        return False, gespeichert
    wert = token_hashen(sauber)
    # Vergleich in konstanter Zeit ueber alle Eintraege: kein frueher Ausstieg,
    # der die Zahl der verbleibenden Codes verraten koennte.
    treffer = False
    uebrig = []
    for eintrag in offen:
        if gleich(eintrag, wert) and not treffer:
            treffer = True
            continue
        uebrig.append(eintrag)
    return treffer, json.dumps(uebrig)


def ersatzcodes_offen(gespeichert: str) -> int:
    """Wie viele Ersatzcodes noch gelten."""
    import json
    try:
        return len(json.loads(gespeichert or "[]"))
    except (ValueError, TypeError):
        return 0


def totp_url(geheimnis: str, email: str, herausgeber: str = "Wirtschafts-AG") -> str:
    """otpauth-Adresse fuer den QR-Code der Authenticator-App."""
    kennung = quote(f"{herausgeber}:{email}")
    return (f"otpauth://totp/{kennung}?secret={geheimnis}"
            f"&issuer={quote(herausgeber)}&digits={TOTP_STELLEN}&period={TOTP_SCHRITT}")


#  Sitzungen an den Browser binden
def geraete_fingerabdruck(user_agent: str, geheim: str) -> str:
    """Ein kurzer Hash aus Browserfamilie und Betriebssystem.

    Zwei Dinge, die hier bewusst NICHT eingehen:

    Die IP-Adresse - sie wechselt beim Gang vom Schul-WLAN ins Mobilnetz, und
    jede Sitzung waere staendig ungueltig.

    Die Fassungsnummer des Browsers - Chrome aktualisiert sich alle paar
    Wochen und aendert dabei seine Kennung. Wuerde die mitzaehlen, flogen nach
    jedem Update alle raus, ohne dass irgendetwas passiert waere. Uebrig
    bleibt "Chrome auf Android": stabil ueber Monate, aber verschieden genug,
    dass ein gestohlenes Sitzungs-Cookie in einem anderen Browser auffaellt.
    """
    roh = geraet_beschreiben(user_agent)
    return hmac.new(geheim.encode(), roh.encode(), hashlib.sha256).hexdigest()[:32]


def geraet_beschreiben(user_agent: str) -> str:
    """"Chrome auf Android" statt der vollen Kennung - fuer die Geraeteliste."""
    ua = user_agent or ""
    system = ("iPhone" if "iPhone" in ua else
              "iPad" if "iPad" in ua else
              "Android" if "Android" in ua else
              "Mac" if "Macintosh" in ua or "Mac OS" in ua else
              "Windows" if "Windows" in ua else
              "Linux" if "Linux" in ua else "")
    browser = ("Edge" if "Edg/" in ua else
               "Samsung Internet" if "SamsungBrowser" in ua else
               "Opera" if "OPR/" in ua else
               "Chrome" if "Chrome" in ua else
               "Firefox" if "Firefox" in ua else
               "Safari" if "Safari" in ua else "Browser")
    if system and browser:
        return f"{browser} auf {system}"
    return browser or system or "Unbekanntes Gerät"


#  Anmeldebremse (je IP, im Speicher)
#  Gezaehlt wird je IP - und genau daran waere die Bremse im Schul-WLAN fast
#  gescheitert: dort haengen alle hinter einer Adresse. Meldet sich beim
#  AG-Treffen die halbe Gruppe gleichzeitig an, sieht das aus wie ein Angriff.
#  Deshalb zaehlen bei /login nur FEHLversuche; eine gelungene Anmeldung wird
#  wieder gutgeschrieben. Formular-Endpunkte zaehlen jeden Aufruf - dort ist
#  das erfolgreiche Absenden genau das, wovor die Bremse schuetzt (Spam).

class Bremse:
    """Zaehlt Zugriffe je (Pfad, IP) in einem gleitenden Zeitfenster."""

    def __init__(self):
        from collections import defaultdict, deque
        self._eintraege = defaultdict(deque)
        self._deque = deque

    def pruefen(self, pfad: str, ip: str, maximum: int, fenster: int):
        """(erlaubt, Wartezeit in Sekunden, Merker zum Gutschreiben)."""
        schlange = self._eintraege[(pfad, ip)]
        jetzt = time.monotonic()
        while schlange and jetzt - schlange[0] > fenster:
            schlange.popleft()
        if len(schlange) >= maximum:
            return False, max(1, int(fenster - (jetzt - schlange[0])) + 1), None
        schlange.append(jetzt)
        return True, 0, (schlange, jetzt)

    def gutschreiben(self, merker) -> None:
        if not merker:
            return
        schlange, zeitpunkt = merker
        try:
            schlange.remove(zeitpunkt)
        except ValueError:                                   # pragma: no cover
            pass

    def aufraeumen(self, hoechstes_fenster: int = 3600) -> None:
        """Tote Eintraege entfernen - sonst waechst die Tabelle mit jeder
        neuen IP unbegrenzt weiter."""
        jetzt = time.monotonic()
        tot = []
        for schluessel, schlange in list(self._eintraege.items()):
            while schlange and jetzt - schlange[0] > hoechstes_fenster:
                schlange.popleft()
            if not schlange:
                tot.append(schluessel)
        for schluessel in tot:
            self._eintraege.pop(schluessel, None)


bremse = Bremse()

# Pfad: (Anzahl, Fenster in Sekunden, nur Fehlversuche zaehlen)
RATE_LIMITS = {
    "/login": (60, 15 * 60, True),
    "/login/zweiter-faktor": (30, 15 * 60, True),
    "/passwort-vergessen": (12, 60 * 60, False),
    "/passwort-neu": (20, 60 * 60, True),
    "/bewerbung": (40, 60 * 60, False),
    "/kontakt": (25, 60 * 60, False),
}

LOGIN_MAX_VERSUCHE = 5
LOGIN_SPERRE_MINUTEN = 15


def konto_gesperrt_bis(user):
    """None, wenn das Konto offen ist - sonst der Zeitpunkt der Freigabe."""
    if user and user.locked_until and user.locked_until > utcnow():
        return user.locked_until
    return None
