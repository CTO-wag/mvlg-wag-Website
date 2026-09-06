"""Was fuer den Support ueber ein Geraet feststellbar ist.

Anlass: Eine Support-Anfrage lautet "geht bei mir nicht". Bis jemand
antworten kann, sind drei Rueckfragen noetig - welches Handy, welcher
Browser, welche Fassung, WLAN oder mobil, als App oder im Browser. Bis die
Antworten da sind, ist eine Woche vergangen und das Problem hat sich
entweder von selbst erledigt oder ist zum zweiten Ticket geworden.

Dieses Modul beantwortet die Fragen im Voraus. Es sammelt aus drei Quellen:

  1. **Kopfzeilen** - was jeder Aufruf ohnehin mitbringt (User-Agent,
     Sprache, Client Hints, die Cloudflare-Angaben). Kostet nichts.
  2. **Browser** - was nur JavaScript weiss: Bildschirm, Grafikeinheit,
     Arbeitsspeicher, Leitungsgeschwindigkeit, Zeitzone, ob die Seite als
     App laeuft, ob Push erlaubt ist (statisch/js/diagnose.js).
  3. **IP-Adresse** - Land, Anbieter und der VPN-Verdacht. Dafuer geht die
     Adresse an einen fremden Dienst, deshalb einzeln abschaltbar
     (IP_INFO_AKTIV).

Was hier NICHT passiert: kein Standort, kein Verlauf, keine Tastatur- oder
Mausaufzeichnung, kein Fingerabdruck ueber Canvas oder Schriftarten. Das
waere technisch moeglich und beantwortet keine einzige Supportfrage.

Gespeichert wird je Person und Geraet EIN Datensatz, der aufgefrischt wird -
nicht einer je Aufruf. Und er verfaellt (DIAGNOSE_TAGE).
"""

import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from kern import einstellungen as cfg
from kern.datenbank import hole_db, sitzung
from kern.modelle import ClientFehler, Geraeteprofil
from kern.text import sauber, utcnow

ZEITGRENZE = 6          # Sekunden fuer den IP-Dienst
IP_CACHE_STUNDEN = 12


#  Was der Browser meldet - und wie es heisst
#  Eine Liste statt einzelner Spalten: Browser lernen staendig neue Angaben
#  dazu. Was hier steht, zeigt die Analyse an; was der Browser darueber
#  hinaus schickt, wird verworfen.
#  (Schluessel, Anzeigename, Gruppe, Einheit)
BROWSER_FELDER = (
    ("bildschirm",       "Bildschirm",              "Gerät",     ""),
    ("fenster",          "Fenstergröße",            "Gerät",     ""),
    ("pixelverhaeltnis", "Pixeldichte",             "Gerät",     "x"),
    ("gpu",              "Grafikeinheit",           "Gerät",     ""),
    ("cpu_kerne",        "Prozessorkerne",          "Gerät",     ""),
    ("speicher_gb",      "Arbeitsspeicher",         "Gerät",     " GB"),
    ("touchpunkte",      "Berührungspunkte",        "Gerät",     ""),
    ("akku",             "Akkustand",               "Gerät",     " %"),
    ("akku_laedt",       "Lädt gerade",             "Gerät",     ""),

    ("netz_art",         "Verbindungsart",          "Netz",      ""),
    ("netz_tempo",       "Geschwindigkeit",         "Netz",      " Mbit/s"),
    ("netz_rtt",         "Antwortzeit",             "Netz",      " ms"),
    ("datensparmodus",   "Datensparmodus",          "Netz",      ""),
    ("online",           "Verbindung steht",        "Netz",      ""),

    ("zeitzone",         "Zeitzone",                "Umgebung",  ""),
    ("sprachen",         "Sprachen",                "Umgebung",  ""),
    ("farbschema",       "Farbschema",              "Umgebung",  ""),
    ("kontrast",         "Erhöhter Kontrast",       "Umgebung",  ""),
    ("weniger_bewegung", "Weniger Bewegung",        "Umgebung",  ""),
    ("als_app",          "Als App gestartet",       "Umgebung",  ""),
    ("zeiger",           "Bedienung",               "Umgebung",  ""),

    ("push_erlaubnis",   "Push-Berechtigung",       "Plattform", ""),
    ("sw_status",        "Hintergrundskript",       "Plattform", ""),
    ("speicher_belegt",  "Belegter Speicher",       "Plattform", " MB"),
    ("speicher_frei",    "Verfügbarer Speicher",    "Plattform", " MB"),
    ("cookies",          "Cookies erlaubt",         "Plattform", ""),
    ("ablage",           "Lokale Ablage",           "Plattform", ""),
    ("automatisiert",    "Automatisierter Browser", "Plattform", ""),

    ("ladezeit",         "Ladezeit der Seite",      "Leistung",  " ms"),
    ("serverzeit",       "Antwort des Servers",     "Leistung",  " ms"),
    ("darstellzeit",     "Bis zum ersten Inhalt",   "Leistung",  " ms"),
)

# Nur diese Schluessel werden angenommen. Alles andere wirft der Server weg -
# sonst kann sich jeder angemeldete Browser beliebige Felder ausdenken und
# die Tabelle vollschreiben.
ERLAUBTE_FELDER = frozenset(k for k, _, _, _ in BROWSER_FELDER)

# Reihenfolge der Gruppen in der Anzeige.
BROWSER_GRUPPEN = ("Gerät", "Netz", "Umgebung", "Plattform", "Leistung")

KOPF_FELDER = (
    ("ch_plattform", "Betriebssystem"),
    ("ch_version",   "Systemfassung"),
    ("ch_modell",    "Gerätemodell"),
    ("ch_marken",    "Browser laut Client Hints"),
    ("ch_arch",      "Architektur"),
    ("ch_bitness",   "Wortbreite"),
    ("ch_mobil",     "Mobilgerät"),
    ("sprache",      "Bevorzugte Sprache"),
    ("cf_land",      "Land laut Cloudflare"),
    ("cf_ray",       "Cloudflare-Kennung"),
    ("protokoll",    "Übertragungsart"),
    ("dnt",          "Tracking-Widerspruch"),
)


#  Kopfzeilen auswerten
def _ch(request: Request, name: str) -> str:
    """Ein Client Hint, ohne die Anfuehrungszeichen, die Chrome mitschickt."""
    return sauber(request.headers.get(name, "")).strip('"')[:120]


def kopf_daten(request: Request) -> dict:
    """Alles, was ohne Zutun des Browsers in jedem Aufruf steht.

    Die Sec-CH-*-Angaben schickt der Browser nur, wenn der Server vorher
    danach gefragt hat - das tut die Accept-CH-Kopfzeile in
    kern/webbasis.py. Ohne sie bleibt das Feld leer, und das ist kein
    Fehler, sondern der Normalfall bei Firefox und Safari.
    """
    kopf = request.headers
    daten = {
        "user_agent": sauber(kopf.get("user-agent", ""))[:400],
        "sprache": sauber(kopf.get("accept-language", ""))[:120],
        "ch_plattform": _ch(request, "sec-ch-ua-platform"),
        "ch_version": _ch(request, "sec-ch-ua-platform-version"),
        "ch_modell": _ch(request, "sec-ch-ua-model"),
        "ch_marken": sauber(kopf.get("sec-ch-ua-full-version-list")
                            or kopf.get("sec-ch-ua", ""))[:300],
        "ch_arch": _ch(request, "sec-ch-ua-arch"),
        "ch_bitness": _ch(request, "sec-ch-ua-bitness"),
        "ch_mobil": {"?1": "ja", "?0": "nein"}.get(
            sauber(kopf.get("sec-ch-ua-mobile", "")), ""),
        "cf_land": sauber(kopf.get("cf-ipcountry", ""))[:8],
        "cf_ray": sauber(kopf.get("cf-ray", ""))[:32],
        "protokoll": "HTTP/" + str(request.scope.get("http_version", "")),
        "dnt": "ja" if kopf.get("dnt") == "1" or kopf.get("sec-gpc") == "1" else "",
    }
    return {k: v for k, v in daten.items() if v and v != "HTTP/"}


#  User-Agent zerlegen
#  kern/sicherheit.geraet_beschreiben() macht dasselbe in kurz ("Chrome auf
#  Android") - das genuegt fuer die Geraeteliste im eigenen Konto. Hier wird
#  die Fassung gebraucht: "Chrome 118" gegen "Chrome 131" ist bei einem
#  Darstellungsfehler die halbe Antwort.
_BROWSER_MUSTER = (
    ("Edge",             r"Edg/(\d+)"),
    ("Samsung Internet", r"SamsungBrowser/(\d+)"),
    ("Opera",            r"OPR/(\d+)"),
    ("Firefox",          r"Firefox/(\d+)"),
    ("Chrome",           r"Chrome/(\d+)"),
    ("Safari",           r"Version/(\d+).*Safari"),
)
_SYSTEM_MUSTER = (
    ("iOS",     r"(?:iPhone|iPad).*?OS (\d+[_\d]*)"),
    ("Android", r"Android (\d+(?:\.\d+)?)"),
    ("Windows", r"Windows NT (\d+\.\d+)"),
    ("macOS",   r"Mac OS X (\d+[_.\d]*)"),
)
_WINDOWS_NAMEN = {"10.0": "10/11", "6.3": "8.1", "6.2": "8", "6.1": "7"}


def zerlegen(user_agent: str, kopf: dict = None) -> dict:
    """Browser, System, Modell und "ist ein Handy" aus Kennung und Hints.

    Die Client Hints haben Vorrang, wo sie da sind: Sie nennen das echte
    Geraetemodell und die echte Systemfassung, waehrend der User-Agent von
    Chrome seit der "User-Agent Reduction" beides einfriert - dort steht
    bei jedem Android-Handy "Android 10; K", egal was wirklich laeuft.
    """
    ua = user_agent or ""
    kopf = kopf or {}

    browser = ""
    for name, muster in _BROWSER_MUSTER:
        treffer = re.search(muster, ua)
        if treffer:
            browser = f"{name} {treffer.group(1)}"
            break
    if not browser:
        browser = "Unbekannter Browser"

    plattform = ""
    for name, muster in _SYSTEM_MUSTER:
        treffer = re.search(muster, ua)
        if treffer:
            fassung = treffer.group(1).replace("_", ".")
            if name == "Windows":
                fassung = _WINDOWS_NAMEN.get(fassung, fassung)
            plattform = f"{name} {fassung}"
            break
    if kopf.get("ch_plattform") and kopf.get("ch_version"):
        plattform = f"{kopf['ch_plattform']} {kopf['ch_version'].split('.')[0]}"
    elif not plattform:
        plattform = kopf.get("ch_plattform") or "Unbekanntes System"

    modell = kopf.get("ch_modell", "")
    ist_mobil = bool(kopf.get("ch_mobil") == "ja"
                     or re.search(r"Mobi|Android|iPhone|iPad", ua))
    return {"browser": browser, "plattform": plattform, "modell": modell,
            "ist_mobil": ist_mobil}


def beschreiben(teile: dict) -> str:
    """Die eine Zeile, die in der Geraeteliste steht."""
    text = f"{teile.get('browser', '?')} auf {teile.get('plattform', '?')}"
    if teile.get("modell"):
        text += f" · {teile['modell']}"
    return text[:200]


#  Herkunft der IP-Adresse
#  Zwei Dienste, ein Parser: ipwho.is antwortet mit "connection", die von
#  ip-api.com kommt mit "isp"/"as"/"proxy". Wer den einen gegen den anderen
#  tauscht, aendert eine Zeile in config.cmd und sonst nichts.
_IP_CACHE = {}          # ip -> (zeitpunkt, daten)
_IP_SPERRE = threading.Lock()

# Namensbestandteile, die auf ein Rechenzentrum statt auf einen Haushalt
# deuten. Ein Handy haengt bei Telekom oder Vodafone, nicht bei Hetzner.
_HOSTER = ("hetzner", "ovh", "digitalocean", "linode", "vultr", "contabo",
           "m247", "datacamp", "leaseweb", "choopa", "amazon", "aws",
           "google cloud", "azure", "oracle cloud", "nordvpn", "mullvad",
           "surfshark", "expressvpn", "cyberghost", "private internet",
           "protonvpn", "ipvanish", "hosting", "datacenter", "data center",
           "vpn", "proxy", "tor-exit", "torexit")

_PRIVAT = re.compile(
    r"^(10\.|127\.|169\.254\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1$|f[cd])")


def ist_privat(ip: str) -> bool:
    """Adressen aus dem eigenen Netz - dazu weiss kein Dienst etwas."""
    return bool(_PRIVAT.match((ip or "").lower()))


def _rueckwaerts(ip: str) -> str:
    """Der Rechnername zur Adresse. Verraet oft mehr als der Anbietername."""
    try:
        return socket.gethostbyaddr(ip)[0][:160]
    except Exception:
        return ""


def ip_infos(ip: str) -> dict:
    """Land, Anbieter und Art der Adresse. Leer, wenn nichts zu holen ist.

    Ergebnisse werden gemerkt: In einer Schul-AG kommen alle aus wenigen
    Netzen, und der Dienst hat ein Anfragelimit. Ohne den Zwischenspeicher
    waere es beim AG-Treffen nach dem dritten Handy aufgebraucht.
    """
    ip = sauber(ip)
    if not ip or ip == "unbekannt" or ist_privat(ip):
        return {}

    with _IP_SPERRE:
        gemerkt = _IP_CACHE.get(ip)
        if gemerkt and time.time() - gemerkt[0] < IP_CACHE_STUNDEN * 3600:
            return dict(gemerkt[1])

    daten = {}
    if cfg.IP_INFO_AKTIV and cfg.IP_INFO_URL:
        try:
            adresse = cfg.IP_INFO_URL.replace("{ip}", urllib.parse.quote(ip))
            anfrage = urllib.request.Request(
                adresse, headers={"User-Agent": "AG-Plattform/2 (Support)",
                                  "Accept": "application/json"})
            with urllib.request.urlopen(anfrage, timeout=ZEITGRENZE) as antwort:
                roh = json.loads(antwort.read().decode("utf-8", "replace"))
            daten = _ip_antwort_lesen(roh)
        except (urllib.error.URLError, ValueError, OSError) as problem:
            # Kein Grund fuer eine Fehlermeldung: Die Analyse laeuft ohne den
            # Dienst weiter, nur ohne Landesangabe.
            daten = {"fehler": type(problem).__name__}

    name = _rueckwaerts(ip)
    if name:
        daten["rueckwaerts"] = name

    with _IP_SPERRE:
        _IP_CACHE[ip] = (time.time(), dict(daten))
        # Nicht unbegrenzt wachsen lassen.
        if len(_IP_CACHE) > 500:
            aeltester = min(_IP_CACHE.items(), key=lambda p: p[1][0])[0]
            _IP_CACHE.pop(aeltester, None)
    return daten


def _ip_antwort_lesen(roh) -> dict:
    """Die Antwort beider gaengiger Dienste auf dieselben Schluessel bringen."""
    if not isinstance(roh, dict):
        return {}
    verbindung = roh.get("connection") or {}
    sicherheit = roh.get("security") or {}
    if not isinstance(verbindung, dict):
        verbindung = {}
    if not isinstance(sicherheit, dict):
        sicherheit = {}

    anbieter = (verbindung.get("isp") or verbindung.get("org")
                or roh.get("isp") or roh.get("org") or "")
    asn = verbindung.get("asn") or roh.get("as") or roh.get("asn") or ""
    if isinstance(asn, int):
        asn = f"AS{asn}"

    daten = {
        "land": roh.get("country") or roh.get("country_name") or "",
        "land_code": roh.get("country_code") or roh.get("countryCode") or "",
        "region": roh.get("region") or roh.get("regionName") or "",
        "stadt": roh.get("city") or "",
        "anbieter": str(anbieter)[:120],
        "asn": str(asn)[:40],
    }
    # Ausdrueckliche Angaben des Dienstes, wo es sie gibt.
    for schluessel, ziel in (("proxy", "proxy"), ("vpn", "vpn"),
                             ("tor", "tor"), ("hosting", "hosting"),
                             ("mobile", "mobil")):
        wert = sicherheit.get(schluessel)
        if wert is None:
            wert = roh.get(schluessel)
        if isinstance(wert, bool):
            daten[ziel] = wert
    return {k: v for k, v in daten.items() if v not in ("", None)}


#  VPN-Verdacht
#  Ein VPN laesst sich von aussen nicht beweisen. Was geht, ist ein Verdacht
#  aus mehreren unabhaengigen Anzeichen - und der wird ausgeschrieben, damit
#  niemand einer Zahl glaubt, die er nicht nachvollziehen kann.
#  Bewusst KEINE Sperre und kein Alarm: Ein VPN zu benutzen ist erlaubt. Die
#  Angabe steht hier, weil sie Fehler erklaert - blockierte Push-Zustellung,
#  fremdsprachige Inhalte, Zeitangaben in der falschen Zone.
_ZONE_LAND = {
    "Europe/Berlin": "DE", "Europe/Busingen": "DE", "Europe/Vienna": "AT",
    "Europe/Zurich": "CH", "Europe/Amsterdam": "NL", "Europe/Brussels": "BE",
    "Europe/Paris": "FR", "Europe/Madrid": "ES", "Europe/Lisbon": "PT",
    "Europe/Rome": "IT", "Europe/London": "GB", "Europe/Dublin": "IE",
    "Europe/Warsaw": "PL", "Europe/Prague": "CZ", "Europe/Bratislava": "SK",
    "Europe/Budapest": "HU", "Europe/Bucharest": "RO", "Europe/Sofia": "BG",
    "Europe/Athens": "GR", "Europe/Istanbul": "TR", "Europe/Kiev": "UA",
    "Europe/Kyiv": "UA", "Europe/Moscow": "RU", "Europe/Stockholm": "SE",
    "Europe/Oslo": "NO", "Europe/Copenhagen": "DK", "Europe/Helsinki": "FI",
    "Europe/Zagreb": "HR", "Europe/Belgrade": "RS", "Europe/Ljubljana": "SI",
    "Europe/Luxembourg": "LU", "Europe/Tirane": "AL", "Europe/Skopje": "MK",
    "America/New_York": "US", "America/Chicago": "US", "America/Denver": "US",
    "America/Los_Angeles": "US", "America/Toronto": "CA",
    "Asia/Tokyo": "JP", "Asia/Singapore": "SG", "Asia/Shanghai": "CN",
    "Asia/Dubai": "AE", "Australia/Sydney": "AU",
}


def vpn_bewerten(ip_daten: dict, browser: dict, kopf: dict) -> tuple:
    """(Verdacht 0-100, Begruendung). Keine Anhaltspunkte = 0 und leer."""
    punkte, gruende = 0, []
    ip_daten = ip_daten or {}
    browser = browser or {}
    kopf = kopf or {}

    if ip_daten.get("vpn"):
        punkte += 60
        gruende.append("Der Dienst meldet die Adresse ausdrücklich als VPN")
    if ip_daten.get("proxy"):
        punkte += 45
        gruende.append("Die Adresse ist als Proxy bekannt")
    if ip_daten.get("tor"):
        punkte += 70
        gruende.append("Die Adresse ist ein Tor-Ausgangsknoten")

    anbieter = (str(ip_daten.get("anbieter", "")) + " "
                + str(ip_daten.get("rueckwaerts", ""))).lower()
    if ip_daten.get("hosting") or any(h in anbieter for h in _HOSTER):
        punkte += 40
        gruende.append("Die Adresse gehört zu einem Rechenzentrum, nicht "
                       "zu einem Privatanschluss")

    # Das staerkste Anzeichen, das ohne fremden Dienst auskommt: Die Uhr des
    # Geraets steht in einer anderen Zeitzone als das Land der Adresse.
    zone = browser.get("zeitzone", "")
    zonen_land = _ZONE_LAND.get(zone, "")
    ip_land = str(ip_daten.get("land_code") or kopf.get("cf_land") or "").upper()
    if zone and zonen_land and ip_land and zonen_land != ip_land:
        punkte += 45
        gruende.append(f"Die Zeitzone des Geräts ({zone}) passt nicht zum "
                       f"Land der Adresse ({ip_land})")

    # Schwaecheres Anzeichen, deshalb wenig Gewicht: Ein Austauschschüler hat
    # einen deutschen Browser an einer ausländischen Leitung, und das ist
    # kein VPN.
    sprachen = str(browser.get("sprachen") or kopf.get("sprache") or "").lower()
    if ip_land and ip_land != "DE" and sprachen.startswith("de"):
        punkte += 15
        gruende.append("Deutsche Spracheinstellung an einer ausländischen "
                       "Adresse")

    return max(0, min(100, punkte)), " · ".join(gruende)[:400]


#  Festhalten
def geraete_kennung(request: Request) -> str:
    """Woran dasselbe Geraet wiedererkannt wird.

    Erste Wahl ist die Geraetekennung aus dem Cookie, die schon fuer Push
    vergeben wird (kern/push_anmeldung.py) - sie haelt ueber Jahre und ueber
    beide Adressen hinweg.

    Nur: Dieses Cookie bekommt erst, wer sich einmal fuer Push angemeldet
    hat. Bei allen anderen fehlt es, und geraete_id() wuerfelt dann bei jedem
    Aufruf eine neue Kennung aus. Genau so war es hier zuerst gebaut - mit
    der Folge, dass fuer JEDEN Seitenaufruf ein eigenes Geraeteprofil
    entstand. Das Dossier waere eine endlose Liste desselben Handys gewesen
    und die Tabelle in einer Woche groesser als der Rest der Datenbank.

    Deshalb der Rueckfall auf den Fingerabdruck, den kern/sitzung.py ohnehin
    fuer jede Sitzung bildet: "Chrome auf Android" plus SECRET_KEY. Er ist
    grob - zwei gleiche Handys derselben Person fielen zusammen -, aber er
    ist stabil, und stabil ist hier das, worauf es ankommt.
    """
    from kern.einstellungen import SECRET_KEY
    from kern.push_anmeldung import GERAETE_COOKIE
    from kern.sicherheit import geraete_fingerabdruck

    aus_cookie = sauber(request.cookies.get(GERAETE_COOKIE, ""))[:40]
    if aus_cookie and all(c in "0123456789abcdef" for c in aus_cookie):
        return aus_cookie
    return geraete_fingerabdruck(
        request.headers.get("user-agent") or "", SECRET_KEY)[:40]


def _bereinigen(roh) -> dict:
    """Nur bekannte Felder, nur harmlose Werte, nur begrenzte Laenge.

    Was hier ankommt, hat ein fremder Browser geschickt. Es wird angezeigt,
    gilt also als Behauptung und nicht als Wahrheit - und es darf die
    Tabelle nicht sprengen.
    """
    if not isinstance(roh, dict):
        return {}
    ergebnis = {}
    for schluessel, wert in roh.items():
        if schluessel not in ERLAUBTE_FELDER:
            continue
        if isinstance(wert, bool):
            ergebnis[schluessel] = "ja" if wert else "nein"
        elif isinstance(wert, int):
            ergebnis[schluessel] = wert
        elif isinstance(wert, float):
            ergebnis[schluessel] = round(wert, 2)
        elif isinstance(wert, str):
            gekuerzt = sauber(wert)[:200]
            if gekuerzt:
                ergebnis[schluessel] = gekuerzt
    return ergebnis


def _json_lesen(text) -> dict:
    try:
        wert = json.loads(text or "{}")
        return wert if isinstance(wert, dict) else {}
    except (ValueError, TypeError):
        return {}


def merken(db: Session, request: Request, user, browserdaten=None) -> None:
    """Das Profil dieses Geraets anlegen oder auffrischen.

    Wird bei jedem Bereichswechsel gerufen, macht aber fast immer nichts:
    Der Zeitpunkt der letzten Auffrischung steht in der Sitzung, und
    innerhalb einer Minute wird die Datenbank gar nicht erst gefragt. Ein
    Schreibzugriff je Klick waere genau der Fehler, den kern/sitzung.py an
    derselben Stelle vermeidet - dort ist es dieselbe Minute.
    """
    if not cfg.DIAGNOSE_AKTIV or not user:
        return
    try:
        from kern.sitzung import client_ip

        # Kommen frische Browserdaten, wird immer geschrieben - die sind der
        # eigentliche Zweck der Uebung und kommen nur einmal je Sitzung.
        jetzt = utcnow()
        if not browserdaten:
            zuletzt = request.session.get("diag_stand", 0)
            if zuletzt and time.time() - zuletzt < 60:
                return
            request.session["diag_stand"] = time.time()

        kennung = geraete_kennung(request)
        profil = (db.query(Geraeteprofil)
                  .filter(Geraeteprofil.user_id == user.id,
                          Geraeteprofil.geraete_id == kennung)
                  .first())

        kopf = kopf_daten(request)
        teile = zerlegen(kopf.get("user_agent", ""), kopf)
        ip = client_ip(request, cfg.TRUST_PROXY_HEADERS)

        if not profil:
            profil = Geraeteprofil(user_id=user.id, geraete_id=kennung,
                                   erstmals=jetzt, aufrufe=0)
            db.add(profil)

        profil.sitzung_id = request.session.get("sid")
        profil.ip_address = ip
        profil.user_agent = kopf.get("user_agent", "")
        profil.kopfdaten = json.dumps(kopf, ensure_ascii=False)
        profil.browser = teile["browser"]
        profil.plattform = teile["plattform"]
        profil.modell = teile["modell"] or None
        profil.ist_mobil = 1 if teile["ist_mobil"] else 0
        profil.beschreibung = beschreiben(teile)
        profil.zuletzt = jetzt
        profil.aufrufe = (profil.aufrufe or 0) + 1

        if browserdaten:
            vorhanden = _json_lesen(profil.browserdaten)
            vorhanden.update(_bereinigen(browserdaten))
            profil.browserdaten = json.dumps(vorhanden, ensure_ascii=False)

        db.commit()

        # Die Herkunft der Adresse nur, wenn sie fehlt oder alt ist - und
        # immer nebenher: Ein fremder Dienst darf keinen Seitenaufbau
        # aufhalten, auch dann nicht, wenn er gerade nicht antwortet.
        veraltet = (not profil.ip_geprueft_am
                    or (jetzt - profil.ip_geprueft_am) > timedelta(days=1))
        if ip and veraltet and not ist_privat(ip):
            threading.Thread(target=_herkunft_nachtragen,
                             args=(profil.id, ip), daemon=True,
                             name="ip-herkunft").start()
    except Exception as problem:                             # pragma: no cover
        # Diagnose ist Beiwerk. Sie darf keinen Seitenaufruf scheitern
        # lassen - sonst waere ausgerechnet das Werkzeug fuer Stoerungen die
        # Ursache der naechsten.
        db.rollback()
        print(f"[Diagnose] Profil nicht gespeichert: {problem!r}")


def _herkunft_nachtragen(profil_id: int, ip: str) -> None:
    """Laeuft im Hintergrund, mit eigener Datenbanksitzung."""
    daten = ip_infos(ip)
    if not daten:
        return
    try:
        with sitzung() as db:
            profil = db.get(Geraeteprofil, profil_id)
            if not profil:
                return
            if daten.get("land"):
                code = daten.get("land_code", "")
                profil.ip_land = (f"{daten['land']} ({code})" if code
                                  else daten["land"])[:60]
            profil.ip_region = (daten.get("region") or None)
            profil.ip_stadt = (daten.get("stadt") or None)
            profil.ip_provider = (daten.get("anbieter") or None)
            profil.ip_asn = (daten.get("asn") or None)
            profil.ip_art = ("Rechenzentrum" if daten.get("hosting") else
                             "Mobilfunk" if daten.get("mobil") else
                             "Privatanschluss" if daten.get("anbieter") else None)
            profil.ip_geprueft_am = utcnow()

            verdacht, gruende = vpn_bewerten(
                daten, _json_lesen(profil.browserdaten),
                _json_lesen(profil.kopfdaten))
            profil.vpn_verdacht = verdacht
            profil.vpn_gruende = gruende or None
            db.commit()
    except Exception as problem:                             # pragma: no cover
        print(f"[Diagnose] Herkunft nicht nachgetragen: {problem!r}")


def fehler_merken(db: Session, request: Request, user, roh: dict) -> None:
    """Einen Browserfehler festhalten.

    Mit Bremse: Eine Endlosschleife im Skript wuerde sonst tausend gleiche
    Zeilen je Minute schreiben. Derselbe Fehler derselben Person zaehlt
    innerhalb einer Stunde einmal.
    """
    if not cfg.DIAGNOSE_AKTIV or not user or not isinstance(roh, dict):
        return
    meldung = sauber(roh.get("meldung"))[:500]
    if not meldung:
        return
    try:
        seit = utcnow() - timedelta(hours=1)
        schon_da = (db.query(ClientFehler.id)
                    .filter(ClientFehler.user_id == user.id,
                            ClientFehler.meldung == meldung,
                            ClientFehler.created_at >= seit).first())
        if schon_da:
            return
        zeile = roh.get("zeile")
        db.add(ClientFehler(
            user_id=user.id, geraete_id=geraete_kennung(request),
            art=sauber(roh.get("art"))[:20] or "js",
            meldung=meldung,
            quelle=sauber(roh.get("quelle"))[:300] or None,
            zeile=zeile if isinstance(zeile, int) else None,
            stapel=sauber(roh.get("stapel"))[:4000] or None,
            adresse=sauber(roh.get("adresse"))[:300] or None))
        db.commit()
    except Exception as problem:                             # pragma: no cover
        db.rollback()
        print(f"[Diagnose] Browserfehler nicht gespeichert: {problem!r}")


#  Aufraeumen
def aufraeumen() -> dict:
    """Alte Profile und Fehler entfernen. Laeuft mit kern/protokoll.py mit."""
    if cfg.DIAGNOSE_TAGE <= 0:
        return {}
    grenze = utcnow() - timedelta(days=cfg.DIAGNOSE_TAGE)
    bilanz = {}
    with sitzung() as db:
        bilanz["geraeteprofile"] = db.query(Geraeteprofil).filter(
            Geraeteprofil.zuletzt < grenze).delete(synchronize_session=False)
        bilanz["browserfehler"] = db.query(ClientFehler).filter(
            ClientFehler.created_at < grenze).delete(synchronize_session=False)
        db.commit()
    return {k: v for k, v in bilanz.items() if v}


#  Der Endpunkt, an den der Browser meldet
#  Haengt in BEIDEN Anwendungen: Ein Fehler auf der oeffentlichen Seite ist
#  genauso eine Supportfrage wie einer im Dashboard, und die Push-Anmeldung
#  passiert sogar ueberwiegend dort.
def _vom_eigenen_haus(request: Request) -> bool:
    """Kommt der Aufruf von unserer eigenen Seite?

    Statt eines CSRF-Tokens: Der Endpunkt aendert nichts, was jemand sehen
    oder verlieren kann, und muss aus zwei Rahmen heraus erreichbar sein -
    einer davon oeffentlich und ohne Token im Markup. Die Herkunftsangabe,
    die der Browser von sich aus mitschickt, ist hier das passende Mittel.
    """
    art = request.headers.get("sec-fetch-site")
    if art in ("same-origin", "same-site"):
        return True
    if art:                       # ausdruecklich "cross-site" oder "none"
        return False
    herkunft = sauber(request.headers.get("origin"))
    if not herkunft:
        return False
    erlaubt = {cfg.WEBSITE_URL.rstrip("/"), cfg.DASHBOARD_URL.rstrip("/"),
               str(request.base_url).rstrip("/")}
    return herkunft.rstrip("/") in erlaubt


def baue_router() -> APIRouter:
    router = APIRouter()

    @router.post("/diagnose/melden")
    async def melden(request: Request, db: Session = Depends(hole_db)):
        """Nimmt entgegen, was der Browser ueber sich weiss.

        Antwortet immer mit 204 und nie mit einem Fehler: Das Skript soll
        bei einem abgewiesenen Aufruf nicht selbst einen Fehler ausloesen,
        den es dann melden will.
        """
        from kern.sitzung import angemeldete_person
        if not cfg.DIAGNOSE_AKTIV or not _vom_eigenen_haus(request):
            return Response(status_code=204)
        user = angemeldete_person(request, db)
        if not user:
            return Response(status_code=204)
        try:
            roh = await request.json()
        except Exception:
            return Response(status_code=204)
        if not isinstance(roh, dict):
            return Response(status_code=204)

        if roh.get("art") in ("js", "versprechen", "netz"):
            fehler_merken(db, request, user, roh)
        else:
            merken(db, request, user, roh)
        return Response(status_code=204)

    @router.get("/diagnose/stand")
    def stand(request: Request, db: Session = Depends(hole_db)):
        """Laeuft die Erfassung? Nur fuer den CTO, zur Fehlersuche am Skript."""
        from kern.sitzung import angemeldete_person
        user = angemeldete_person(request, db)
        if not user or user.role != "cto":
            return Response(status_code=404)
        return JSONResponse({
            "aktiv": cfg.DIAGNOSE_AKTIV,
            "ip_dienst": cfg.IP_INFO_AKTIV,
            "aufbewahrung_tage": cfg.DIAGNOSE_TAGE,
            "felder": sorted(ERLAUBTE_FELDER),
        })

    return router
