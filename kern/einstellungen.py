"""Alle Konfigurationswerte an einem Ort.

Gelesen wird ausschliesslich aus der Umgebung - gesetzt wird die von
config.cmd, die start.bat vor dem Start einliest. Damit gibt es genau eine
Stelle, an der ein Wert herkommt, und keine zweite Wahrheit im Quelltext.

Wichtig fuer den Umstieg von V1: Es wird DIESELBE config.cmd und DERSELBE
Datenordner benutzt. Gleicher SECRET_KEY heisst, dass angemeldete Personen
angemeldet bleiben; gleicher Datenordner heisst, dass Datenbank, Sicherungen
und hochgeladene Dateien unveraendert weiterlaufen.
"""

import os
import re
import secrets

#  Ordner
#  Der Programmordner ist Management-System-V2, der Projektordner darueber
#  ("Websites"). Der Datenordner liegt bewusst ausserhalb des Programmordners:
#  Programmstand wird ersetzt, Datenstand niemals.
PROGRAMM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJEKT_DIR = os.path.dirname(PROGRAMM_DIR)
VORLAGEN_DIR = os.path.join(PROGRAMM_DIR, "vorlagen")
STATISCH_DIR = os.path.join(PROGRAMM_DIR, "statisch")


def _ordner_aus_umgebung(name: str, standard: str) -> str:
    """Liest einen Pfad aus der Umgebung - nachsichtig gegenueber cmd.

    cmd reicht Anfuehrungszeichen durch, wenn jemand  set DATEN_DIR="D:\\X"
    schreibt statt  set "DATEN_DIR=D:\\X". Beides sieht richtig aus, das erste
    ergaebe einen Ordner, dessen Name mit " beginnt. Relative Angaben zaehlen
    ab dem Programmordner, nicht ab dem Arbeitsverzeichnis - sonst haengt der
    Ort davon ab, aus welchem Fenster gestartet wurde.
    """
    wert = os.environ.get(name, "").replace('"', "").strip()
    if not wert:
        return standard
    return os.path.abspath(os.path.join(PROGRAMM_DIR, os.path.expandvars(wert)))


DATEN_DIR = _ordner_aus_umgebung("DATEN_DIR", os.path.join(PROJEKT_DIR, "daten"))
os.makedirs(DATEN_DIR, exist_ok=True)

BACKUP_DIR = _ordner_aus_umgebung("BACKUP_DIR", os.path.join(DATEN_DIR, "backups"))
REDAKTION_UPLOAD_DIR = _ordner_aus_umgebung(
    "UPLOAD_DIR", os.path.join(DATEN_DIR, "redaktion_uploads"))
SUPPORT_UPLOAD_DIR = _ordner_aus_umgebung(
    "SUPPORT_UPLOAD_DIR", os.path.join(DATEN_DIR, "support_uploads"))
for _ordner in (BACKUP_DIR, REDAKTION_UPLOAD_DIR, SUPPORT_UPLOAD_DIR):
    os.makedirs(_ordner, exist_ok=True)

DATENBANK_DATEI = os.path.join(DATEN_DIR, "ag_plattform.db")
# .strip() or ... statt eines blossen get(): In der config.cmd steht ein Wert
# oft als  set "DATABASE_URL="  da, um zu zeigen, dass es ihn gibt. get() gibt
# dann eine leere Zeichenkette zurueck - der Schluessel existiert ja - und die
# Anwendung braeche beim Start mit einer unverstaendlichen Meldung ab.
DATABASE_URL = (os.environ.get("DATABASE_URL", "").strip()
                or "sqlite:///" + DATENBANK_DATEI.replace("\\", "/"))

def _text(name: str, standard: str = "") -> str:
    """Eine Zeichenkette aus der Umgebung - leer zaehlt als "nicht gesetzt".

    Der Unterschied ist wichtiger, als er aussieht: In config.cmd steht
        set "DASHBOARD_URL="
    als Hinweis, dass es den Wert gibt. os.environ.get() liefert dann aber
    eine leere Zeichenkette statt der Vorgabe - der Schluessel existiert ja.
    Genau daran hing, dass Website- und Dashboard-Adresse im Startbericht
    leer standen und alle Verweise zwischen beiden Servern ins Nichts liefen.
    """
    wert = os.environ.get(name, "")
    return wert.strip() or standard


def _ja(name: str, standard: str = "false") -> bool:
    return _text(name, standard).lower() in ("true", "1", "ja", "yes")


def _zahl(name: str, standard: int) -> int:
    try:
        return int(_text(name, str(standard)))
    except ValueError:
        return standard


#  Support-Automatik
GROQ_API_KEY = _text("GROQ_API_KEY")
GROQ_MODEL = _text("GROQ_MODEL", "openai/gpt-oss-120b")
SUPPORT_KI_ENABLED = _ja("SUPPORT_KI_ENABLED", "true")


#  Betrieb
APP_ENV = _text("APP_ENV", "development").lower()
IST_PRODUKTION = APP_ENV == "production"

SECRET_KEY = _text("SECRET_KEY", "")
if not SECRET_KEY:
    if IST_PRODUKTION:
        raise RuntimeError("SECRET_KEY muss im Produktivbetrieb gesetzt sein.")
    # Nur fuer Testlaeufe: bei jedem Start neu, alle Anmeldungen laufen ab.
    SECRET_KEY = secrets.token_hex(32)

SITE_URL = _text("SITE_URL", "https://mvlg-wag.de").rstrip("/")
# Das Dashboard laeuft als eigener Prozess auf einem eigenen Port. Oeffentliche
# Seite und Dashboard verweisen ueber diese beiden Adressen aufeinander.
WEBSITE_PORT = _zahl("WEBSITE_PORT", 8000)
DASHBOARD_PORT = _zahl("DASHBOARD_PORT", 8001)

# Im Produktivbetrieb laufen beide hinter derselben oeffentlichen Adresse:
# der Tunnel schickt /dashboard an Port 8001 und alles andere an Port 8000.
# Das ist nicht nur bequem, sondern noetig - Push-Benachrichtigungen haengen
# am Ursprung (Schema + Host). Zwei verschiedene Hosts hiessen: zwei
# Hintergrundskripte, zwei Anmeldungen, und wer die Startseite auf den
# Startbildschirm legt, bekommt die Meldungen des Dashboards nicht.
WEBSITE_URL = _text("WEBSITE_URL",
                    SITE_URL if IST_PRODUKTION else f"http://localhost:{WEBSITE_PORT}"
                    ).rstrip("/")
DASHBOARD_URL = _text("DASHBOARD_URL",
                      f"{SITE_URL}/dashboard" if IST_PRODUKTION
                      else f"http://localhost:{DASHBOARD_PORT}").rstrip("/")

# Laufen beide unter demselben Ursprung? Davon haengt ab, ob ein einziges
# Hintergrundskript fuer Push genuegt.
def _ursprung(adresse: str) -> str:
    from urllib.parse import urlsplit
    teile = urlsplit(adresse)
    return f"{teile.scheme}://{teile.netloc}"


GLEICHER_URSPRUNG = _ursprung(WEBSITE_URL) == _ursprung(DASHBOARD_URL)


def _gemeinsame_domain(a: str, b: str) -> str:
    """Der gemeinsame Namensteil zweier Adressen - oder leer.

    Liegen Website und Dashboard auf verschiedenen Namen derselben Domain
    (mvlg-wag.de und app.mvlg-wag.de), muss das Sitzungs-Cookie ausdruecklich
    fuer ".mvlg-wag.de" gesetzt werden. Ohne das gilt es nur fuer den Namen,
    unter dem man sich angemeldet hat - man landet im Dashboard sofort wieder
    auf der Anmeldeseite.

    Leer bleibt es bei gleichem Namen (dann ist nichts zu tun), bei localhost
    und bei IP-Adressen: dort sind Domain-Cookies nicht erlaubt.
    """
    from urllib.parse import urlsplit
    eins = urlsplit(a).hostname or ""
    zwei = urlsplit(b).hostname or ""
    if not eins or eins == zwei:
        return ""
    if any(t.replace(".", "").isdigit() or "." not in t for t in (eins, zwei)):
        return ""                      # localhost, 127.0.0.1, blosser Rechnername
    teile_a, teile_b = eins.split("."), zwei.split(".")
    gemeinsam = []
    while teile_a and teile_b and teile_a[-1] == teile_b[-1]:
        gemeinsam.insert(0, teile_a.pop())
        teile_b.pop()
    # Mindestens "etwas.de" - ein Cookie fuer ".de" nimmt kein Browser an.
    return "." + ".".join(gemeinsam) if len(gemeinsam) >= 2 else ""


# Fuer welchen Namensbereich Cookies gelten sollen. Leer = nur fuer den
# aufgerufenen Namen.
COOKIE_DOMAIN = _text("COOKIE_DOMAIN") or _gemeinsame_domain(WEBSITE_URL,
                                                             DASHBOARD_URL)

# Namen, unter denen die Anwendung "auf diesem Rechner" laeuft.
LOKALE_NAMEN = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", ""})

# Kopfzeilen, die nur ein vorgelagerter Dienst setzt (Tunnel, Reverse Proxy).
# Steht eine davon drin, kommt der Aufruf von aussen - egal, welcher Name im
# Host steht.
PROXY_SPUREN = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
                "forwarded", "cf-connecting-ip", "cf-ray")


def ueber_proxy(request) -> bool:
    """Kam der Aufruf ueber einen vorgelagerten Dienst?

    Wichtig fuer alles, was am Namen der Seite haengt. Reicht der Tunnel den
    urspruenglichen Host nicht durch, sondern seinen eigenen (127.0.0.1),
    dann saehe die Anwendung einen oertlichen Aufruf - und wuerde jeden
    Verweis der oeffentlichen Seite auf 127.0.0.1 umbiegen und dem
    Sitzungs-Cookie die Domain nehmen. Fuer Besucher waere die Seite kaputt.
    Deshalb: Sobald eine Proxy-Spur da ist, gelten die eingestellten Adressen.
    """
    try:
        kopf = request.headers
    except Exception:                                        # pragma: no cover
        return False
    return any(name in kopf for name in PROXY_SPUREN)

# Kopfzeilen, die nur ein vorgelagerter Dienst setzt (Tunnel, Reverse Proxy).
# Steht eine davon drin, kommt der Aufruf von aussen - egal, welcher Name im
# Host steht.
PROXY_SPUREN = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
                "forwarded", "cf-connecting-ip", "cf-ray")


def ueber_proxy(request) -> bool:
    """Kam der Aufruf ueber einen vorgelagerten Dienst?

    Wichtig fuer alles, was am Namen der Seite haengt. Reicht der Tunnel den
    urspruenglichen Host nicht durch, sondern seinen eigenen (127.0.0.1),
    dann saehe die Anwendung einen oertlichen Aufruf - und wuerde jeden
    Verweis der oeffentlichen Seite auf 127.0.0.1 umbiegen und dem
    Sitzungs-Cookie die Domain nehmen. Fuer Besucher waere die Seite kaputt.
    Deshalb: Sobald eine Proxy-Spur da ist, gelten die eingestellten Adressen.
    """
    try:
        kopf = request.headers
    except Exception:                                        # pragma: no cover
        return False
    return any(name in kopf for name in PROXY_SPUREN)


def adressen_fuer(request) -> tuple:
    """(Website-Adresse, Dashboard-Adresse) - passend zum Aufruf.

    Wer http://localhost:8001 oeffnet, will die oertliche Fassung testen und
    nicht auf mvlg-wag.de landen. Frueher standen hier feste Werte aus der
    config.cmd; seit dort die echten Adressen stehen, verwies das lokale
    Dashboard bei jeder Weiterleitung und in jedem Verweis auf den
    Live-Betrieb - Testen war damit nicht mehr moeglich.

    Kommt der Aufruf also ueber localhost herein, bleiben wir auf localhost.
    In jedem anderen Fall gelten die eingestellten Adressen.
    """
    host = ""
    try:
        host = (request.url.hostname or "") if request is not None else ""
    except Exception:                                        # pragma: no cover
        host = ""
    if host not in LOKALE_NAMEN or not host or ueber_proxy(request):
        return WEBSITE_URL, DASHBOARD_URL

    schema = request.url.scheme or "http"
    website = f"{schema}://{host}:{WEBSITE_PORT}"
    dashboard = f"{schema}://{host}:{DASHBOARD_PORT}"
    # Auf welchem Port die Seite gerade WIRKLICH antwortet, weiss nur der
    # Aufruf selbst. Bei einem Testlauf auf 8010/8011 stuenden sonst die
    # eingestellten 8000/8001 in den eigenen Verweisen - und die zeigen ins
    # Leere. Fuer die eigene Haelfte gilt deshalb immer die Adresse, unter
    # der man angesprochen wurde.
    eigene = f"{schema}://{request.url.netloc}"
    anwendung = getattr(request, "app", None)
    zustand = getattr(anwendung, "state", None)
    if zustand is not None and getattr(zustand, "ist_dashboard", False):
        dashboard = eigene
    else:
        website = eigene
    return website, dashboard


def form_action_ziele(request) -> tuple:
    """Adressen, an die ein Formular abgeschickt werden darf.

    Das Anmeldeformular steht auf der Website und schickt an die Website;
    danach geht es weiter ins Dashboard. Beide Adressen muessen deshalb in der
    Richtlinie stehen - beim oertlichen Testen eben die localhost-Adressen.
    """
    website, dashboard = adressen_fuer(request)
    ziele = [website, dashboard]
    for adresse in (WEBSITE_URL, DASHBOARD_URL):
        if adresse not in ziele:
            ziele.append(adresse)
    return tuple(ziele)

HTTPS_ONLY_COOKIES = _ja("HTTPS_ONLY_COOKIES", "true")
TRUST_PROXY_HEADERS = _ja("TRUST_PROXY_HEADERS", "false")
HSTS_ENABLED = _ja("HSTS_ENABLED", "false")
HSTS_MAX_AGE = _zahl("HSTS_MAX_AGE", 86400)

if IST_PRODUKTION and not HTTPS_ONLY_COOKIES:
    raise RuntimeError("HTTPS_ONLY_COOKIES muss im Produktivbetrieb aktiviert sein.")

# Wie lange eine Anmeldung ohne Aktivitaet gilt und wie lange sie hoechstens
# gilt. V1 kannte nur die acht Stunden des Cookies; eine vergessene Sitzung an
# einem Schulrechner blieb damit den ganzen Schultag offen.
# Zwei Betriebsarten. Wer beim Anmelden "eingeloggt bleiben" stehen laesst
# (Standardfall), bekommt die langen Fristen; wer den Haken entfernt, die
# kurzen. Frueher galten fuer alle die kurzen: acht Stunden Leerlauf. Wer
# nachmittags arbeitete und am naechsten Tag wiederkam, musste sich neu
# anmelden - bei einer AG, die sich alle zwei Wochen trifft, also praktisch
# jedes Mal.
SITZUNG_LEERLAUF_MINUTEN = _zahl("SITZUNG_LEERLAUF_MINUTEN", 8 * 60)
SITZUNG_HOECHSTDAUER_STUNDEN = _zahl("SITZUNG_HOECHSTDAUER_STUNDEN", 24)

# "Eingeloggt bleiben": Erst nach drei Monaten ohne jeden Aufruf ist Schluss,
# spaetestens nach einem halben Jahr. Das ist bewusst lang - die Sitzung
# haengt an einem Geraet, laesst sich unter "Mein Konto" einzeln beenden, und
# ein Passwortwechsel wirft alle anderen ohnehin hinaus.
SITZUNG_DAUERHAFT_LEERLAUF_TAGE = _zahl("SITZUNG_DAUERHAFT_LEERLAUF_TAGE", 90)
SITZUNG_DAUERHAFT_TAGE = _zahl("SITZUNG_DAUERHAFT_TAGE", 180)

DEFAULT_ADMIN_EMAIL = _text("DEFAULT_ADMIN_EMAIL", "vorstand@ag.local")
DEFAULT_ADMIN_PASSWORD = os.environ.get("DEFAULT_ADMIN_PASSWORD")

#  E-Mail
SMTP_HOST = _text("SMTP_HOST", "")
SMTP_PORT = _zahl("SMTP_PORT", 587)
SMTP_USER = _text("SMTP_USER", "")
SMTP_PASSWORD = _text("SMTP_PASSWORD", "")
SMTP_SECURITY = _text("SMTP_SECURITY", "starttls").lower()
SMTP_FROM = _text("SMTP_FROM", "") or SMTP_USER
SMTP_FROM_NAME = os.environ.get(
    "SMTP_FROM_NAME", "Wirtschafts- & Investment-AG").strip()
MAIL_REPLY_TO = _text("MAIL_REPLY_TO", "cto@tech.mvlg-wag.de")

#  Cloudflare Email Routing (ausschließlich serverseitig)
CLOUDFLARE_API_TOKEN = _text("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ACCOUNT_ID = _text("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_ZONE_ID = _text("CLOUDFLARE_ZONE_ID", "")

#  Nutzer-Analyse (Support)
#  Was ueber die Geraete der Mitglieder festgehalten wird, damit der Support
#  bei "geht bei mir nicht" nachsehen kann statt nachzufragen. Aus. Ein.
#  Die Frist ist kein Beiwerk: ohne sie waechst die Tabelle unbegrenzt, und
#  Diagnosedaten von vorletztem Jahr helfen niemandem mehr.
DIAGNOSE_AKTIV = _ja("DIAGNOSE_AKTIV", "true")
DIAGNOSE_TAGE = _zahl("DIAGNOSE_TAGE", 90)

#  Herkunft einer IP-Adresse (Land, Anbieter, VPN-Verdacht).
#  Dafuer geht die IP an einen fremden Dienst - deshalb getrennt schaltbar.
#  Steht sie auf false, bleibt die Analyse vollstaendig im Haus; VPN wird
#  dann nur noch aus Zeitzone und Sprache geschaetzt.
#  Die Adresse traegt {ip} als Platzhalter. Voreingestellt ist ipwho.is:
#  ueber HTTPS, ohne Anmeldung, ohne Schluessel. Wer einen Dienst mit
#  ausdruecklicher VPN-Erkennung hat (ip-api.com Pro, proxycheck.io),
#  traegt dessen Adresse hier ein - kern/diagnose.py versteht beide Formate.
IP_INFO_AKTIV = _ja("IP_INFO_AKTIV", "true")
IP_INFO_URL = _text("IP_INFO_URL", "https://ipwho.is/{ip}")

#  Benachrichtigungen
NTFY_BASE_URL = _text("NTFY_BASE_URL", "https://ntfy.sh").rstrip("/")
DELIVERY_LOG_TAGE = _zahl("DELIVERY_LOG_TAGE", 30)

# Aufbewahrung von Bewerbungen. 0 schaltet das Loeschen ab - dann bleiben die
# Daten liegen, was nur fuer eine Uebergangszeit zu verantworten ist.
BEWERBUNG_ABGELEHNT_TAGE = _zahl("BEWERBUNG_ABGELEHNT_TAGE", 180)
BEWERBUNG_ANGENOMMEN_TAGE = _zahl("BEWERBUNG_ANGENOMMEN_TAGE", 365)

#  Auffangnetz bei Cloudflare
#  Ein kleiner Worker steht vor der Plattform und zeigt eine eigene Seite,
#  wenn hier nichts antwortet (cloudflare/worker.js). Wer dort eine Meldung
#  hinterlaesst, kann das nicht angemeldet tun - die Anmeldung waere ja auch
#  gerade nicht erreichbar. Die Meldungen liegen deshalb beim Worker und werden
#  abgeholt, sobald die Plattform wieder laeuft.
#
#  Beide Werte leer = kein Auffangnetz. Dann tut kern/ausfallmeldungen.py
#  nichts, und es fehlt auch nichts: Der Worker kann seine Fehlerseite ohne
#  diese Seite hier zeigen, nur die Tickets entstehen dann nicht.
AUSFALL_WORKER_URL = _text("AUSFALL_WORKER_URL", "").rstrip("/")
AUSFALL_SCHLUESSEL = _text("AUSFALL_SCHLUESSEL", "")
# Wie oft nachgesehen wird. Fuenf Minuten: Nach einem Neustart soll das Ticket
# da sein, bevor jemand nachfragt, warum niemand reagiert.
AUSFALL_ABHOLUNG_MINUTEN = _zahl("AUSFALL_ABHOLUNG_MINUTEN", 5)

#  WhatsApp-Bot
#  Drei Betriebsarten, damit der Bot auch ohne Meta-Konto nuetzlich ist:
#    cloud     - offizielle WhatsApp Cloud API von Meta (Token + Nummer-ID)
#    callmebot - kostenloser Weg ueber callmebot.com (ein Schluessel je Nummer)
#    manuell   - nichts wird verschickt, das Dashboard bietet einen fertigen
#                wa.me-Link zum Antippen an (Vorgabe, funktioniert immer)
WHATSAPP_MODUS = _text("WHATSAPP_MODUS", "manuell").lower()
# --- Betriebsart "web": eigener Node-Dienst mit whatsapp-web.js -------------
#  Er haelt eine WhatsApp-Web-Sitzung offen (Kopplung per QR-Code) und nimmt
#  Sendeauftraege ueber 127.0.0.1 entgegen. Kein Business-Konto, keine
#  genehmigten Vorlagen - dafuer ist es nicht die offizielle Schnittstelle.
WHATSAPP_WEB_PORT = _zahl("WHATSAPP_WEB_PORT", 8099)
WHATSAPP_WEB_URL = _text("WHATSAPP_WEB_URL",
                         f"http://127.0.0.1:{WHATSAPP_WEB_PORT}").rstrip("/")
# Ohne Token startet der Dienst nicht - sonst koennte jedes Programm auf
# diesem Rechner im Namen der AG Nachrichten verschicken.
WHATSAPP_WEB_TOKEN = _text("WHATSAPP_WEB_TOKEN", "")
WHATSAPP_WEB_SITZUNG = _ordner_aus_umgebung(
    "WHATSAPP_WEB_SITZUNG", os.path.join(DATEN_DIR, "whatsapp-sitzung"))
WHATSAPP_TOKEN = _text("WHATSAPP_TOKEN", "")
WHATSAPP_NUMMER_ID = _text("WHATSAPP_NUMMER_ID", "")
WHATSAPP_API_VERSION = _text("WHATSAPP_API_VERSION", "v21.0")
WHATSAPP_VORLAGE_NAME = _text("WHATSAPP_VORLAGE_NAME", "")
WHATSAPP_LANDESVORWAHL = _text("WHATSAPP_LANDESVORWAHL", "49")
WHATSAPP_GRUPPE = os.environ.get(
    "WHATSAPP_GRUPPE", "https://chat.whatsapp.com/CvMbVpu81rF0QhsLLjz1Ms").strip()
DISCORD_EINLADUNG = os.environ.get(
    "DISCORD_EINLADUNG", "https://discord.gg/Y3zEEsD8Ec").strip()

#  Erinnerungen, Sicherungen, Papierkorb
REMINDER_HOUR_LOCAL = max(0, min(23, _zahl("REMINDER_HOUR", 7)))
REMINDERS_ENABLED = _ja("REMINDERS_ENABLED", "true")
BACKUPS_ENABLED = _ja("BACKUPS_ENABLED", "true")
BACKUP_INTERVAL_HOURS = max(1, _zahl("BACKUP_INTERVAL_HOURS", 12))
BACKUP_KEEP = max(1, _zahl("BACKUP_KEEP", 2))
TRASH_RETENTION_DAYS = max(1, _zahl("TRASH_RETENTION_DAYS", 30))
# Neu in V2: das Leistungs-Scoring laeuft von selbst. Hier steht nur, wann der
# naechtliche Vollabgleich stattfindet - im Betrieb rechnet es bei jedem
# Ereignis sofort nach.
SCORING_HOUR_LOCAL = max(0, min(23, _zahl("SCORING_HOUR", 3)))

#  Grenzen fuer Uploads
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
MAX_REDAKTION_BYTES = 10 * 1024 * 1024
ERLAUBTE_BILDTYPEN = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
ERLAUBTE_ANHANGTYPEN = dict(ERLAUBTE_BILDTYPEN, **{
    "image/gif": ".gif",
    "application/pdf": ".pdf",
})


#  Wo hochgeladene Dateien liegen: Supabase Storage
#  Die Datenbank liegt laengst bei Supabase, die Bilder lagen bis hierher auf
#  der Platte des Rechners, auf dem der Server gerade lief. Beides zusammen
#  geht nur so lange gut, wie es genau einen Rechner gibt: Zieht die Anwendung
#  um, steht in der Datenbank der Dateiname und im Ordner liegt nichts.
#
#  Ist ein Schluessel eingetragen, wandert jede hochgeladene Datei in den
#  Bucket. Ist keiner da (Entwicklung, Testlauf), bleibt alles im Datenordner -
#  ohne Netz und ohne Zugang laeuft die Anwendung dann genau wie vorher.
def _supabase_projekt() -> str:
    """Die Projekt-Kennung aus der DATABASE_URL - oder leer.

    Damit die Adresse des Storage nicht ein zweites Mal eingetragen werden
    muss: Sie steht schon in der Datenbankadresse. Beim Pooler steckt die
    Kennung im Benutzernamen (postgres.abcdef...), bei der direkten
    Verbindung im Rechnernamen (db.abcdef....supabase.co). Zwei Eintraege
    fuer dasselbe Projekt gehen irgendwann auseinander - und dann laegen die
    Dateien in einem anderen Projekt als die Datenbank.
    """
    if "supabase" not in DATABASE_URL:
        return ""
    for muster in (r"postgres\.([a-z0-9]{16,})", r"db\.([a-z0-9]{16,})\.supabase\."):
        treffer = re.search(muster, DATABASE_URL)
        if treffer:
            return treffer.group(1)
    return ""


_projekt = _supabase_projekt()
SUPABASE_URL = (_text("SUPABASE_URL").rstrip("/")
                or (f"https://{_projekt}.supabase.co" if _projekt else ""))
# Der Service-Role-Key aus dem Supabase-Dashboard (Project Settings -> API).
# Er darf am Bucket alles und gehoert deshalb ausschliesslich in die
# config.cmd - niemals in den Quelltext und niemals in den Browser.
SUPABASE_SERVICE_KEY = _text("SUPABASE_SERVICE_KEY")
SUPABASE_BUCKET = _text("SUPABASE_BUCKET", "dateien")
# Erst beides zusammen schaltet den Storage ein.
DATEIEN_IN_SUPABASE = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def _datenbank_kurz() -> str:
    """Woher die Daten kommen - ohne Passwort im Klartext."""
    if DATABASE_URL.startswith("sqlite"):
        return "SQLite-Datei im Datenordner"
    ort = DATABASE_URL.split("@")[-1].split("/")[0] if "@" in DATABASE_URL else "?"
    art = "Supabase" if "supabase" in DATABASE_URL else "Postgres"
    return f"{art} ({ort})"


def _dateien_kurz() -> str:
    """Wohin hochgeladene Bilder und Anhaenge gehen."""
    if DATEIEN_IN_SUPABASE:
        return f"Supabase Storage (Bucket {SUPABASE_BUCKET})"
    if SUPABASE_URL:
        return "Datenordner (SUPABASE_SERVICE_KEY fehlt)"
    return "Datenordner"


def zusammenfassung() -> list:
    """Kurzer Startbericht - was aktiv ist und was nicht."""
    cloudflare_status = (
        "Email Routing konfiguriert"
        if CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_ZONE_ID
        else "nicht konfiguriert"
    )
    zeilen = [
        f"Umgebung     : {APP_ENV}",
        f"Datenbank    : {_datenbank_kurz()}",
        f"Datenordner  : {DATEN_DIR}",
        f"Dateien      : {_dateien_kurz()}",
        f"Website      : {WEBSITE_URL}",
        f"Dashboard    : {DASHBOARD_URL}",
        f"E-Mail       : {'aktiv über ' + SMTP_HOST if SMTP_HOST else 'nicht konfiguriert'}",
        f"Cloudflare   : {cloudflare_status}",
        f"WhatsApp-Bot : {WHATSAPP_MODUS}",
        f"Cookies      : {'nur HTTPS' if HTTPS_ONLY_COOKIES else 'auch HTTP (nur zum Testen!)'}",
    ]
    # Nur erwaehnen, wenn es etwas zu erwaehnen gibt: bei zwei Namen haengt
    # daran, ob die Anmeldung fuer beide gilt.
    if not GLEICHER_URSPRUNG:
        zeilen.append(f"Zwei Adressen: Cookies gelten für "
                      f"{COOKIE_DOMAIN or 'nur den jeweiligen Namen (!)'}")
        zeilen.append("               Push muss auf beiden Seiten angemeldet "
                      "werden - Hinweis steht im Dashboard.")
    zeilen.append(f"HSTS         : {'an' if HSTS_ENABLED else 'aus'}")
    return zeilen
