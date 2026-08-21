"""Willkommensnachrichten per WhatsApp.

Vier Betriebsarten: cloud (Meta-API), callmebot, web (eigener Node-Dienst
mit offener WhatsApp-Web-Sitzung) und manuell. Manuell ist die Vorgabe -
dann legt das Dashboard einen fertigen wa.me-Link zum Antippen bereit.
"""

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from kern import einstellungen as cfg
from kern import werte
from kern.datenbank import sitzung
from kern.modelle import User, WhatsAppNachricht
from kern.protokoll import zustellung
from kern.text import sauber, telefon_normal, utcnow

HOECHSTVERSUCHE = 4

# Einstellungen, die nur den Cloud-Betrieb betreffen und im Dashboard stehen.
WERTE_VORLAGE_PARAMETER = "whatsapp_vorlage_parameter"
WERTE_VORLAGE_SPRACHE = "whatsapp_vorlage_sprache"

# Der Standardtext. Aenderbar im Dashboard unter "WhatsApp-Bot" - dieser hier
# greift nur, solange nichts eigenes hinterlegt ist.
WILLKOMMEN_STANDARD = (
    "Hallo {vorname},\n\n"
    "willkommen in der Wirtschafts- & Investment-AG am MvLG. "
    "Schön, dass du dabei bist.\n\n"
    "Dein Zugang zum Dashboard ist eingerichtet – dort findest du deine "
    "Aufgaben, die nächsten Termine und alles Weitere:\n{dashboard}\n\n"
    "Unsere Gruppe:\n{gruppe}\n\n"
    "Bei Fragen einfach hier melden.\n"
    "– Der Vorstand"
)

PLATZHALTER = {
    "{vorname}": "Vorname der Person",
    "{nachname}": "Nachname",
    "{name}": "Vor- und Nachname",
    "{abteilung}": "Abteilung, in der die Person ist",
    "{rolle}": "Rolle der Person",
    "{dashboard}": "Adresse des Dashboards",
    "{gruppe}": "Einladungslink der WhatsApp-Gruppe",
    "{discord}": "Einladungslink zum Discord",
}


MODI = ("manuell", "web", "cloud", "callmebot")


def modus() -> str:
    return cfg.WHATSAPP_MODUS if cfg.WHATSAPP_MODUS in MODI else "manuell"


#  Betriebsart "web": der Node-Beiwagen mit whatsapp-web.js
def _web_aufruf(pfad: str, nutzlast: dict = None, frist: int = 30) -> tuple:
    """Ruft den Beiwagen auf. (erfolg, Daten-oder-Fehlertext)."""
    if not cfg.WHATSAPP_WEB_TOKEN:
        return False, ("WHATSAPP_WEB_TOKEN fehlt in config.cmd – ohne Token "
                       "startet der Dienst nicht.")
    ziel = f"{cfg.WHATSAPP_WEB_URL}{pfad}"
    daten = json.dumps(nutzlast).encode("utf-8") if nutzlast is not None else None
    anfrage = urllib.request.Request(
        ziel, data=daten, method="POST" if nutzlast is not None else "GET",
        headers={"X-Token": cfg.WHATSAPP_WEB_TOKEN,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(anfrage, timeout=frist) as antwort:
            return True, json.loads(antwort.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as fehler:
        try:
            koerper = json.loads(fehler.read().decode("utf-8", "replace"))
            return False, koerper.get("fehler") or f"Dienst antwortet {fehler.code}"
        except Exception:
            return False, f"Dienst antwortet {fehler.code}"
    except urllib.error.URLError:
        return False, ("Der WhatsApp-Dienst läuft nicht. Er wird von start.bat "
                       "mitgestartet, sobald WHATSAPP_MODUS=web gesetzt ist.")
    except Exception as fehler:
        return False, f"WhatsApp-Dienst nicht erreichbar ({type(fehler).__name__})"


_WEB_FRISCHE = 5.0          # Sekunden, so lange gilt der gespeicherte Zustand
_web_stand = {"wert": None, "zeit": 0.0}
_web_holt = False
_web_sperre = threading.Lock()


def _web_zustand_holen() -> dict:
    erfolg, daten = _web_aufruf("/zustand", frist=8)
    if not erfolg:
        return {"zustand": "aus", "meldung": daten, "qr": "", "nummer": None}
    return daten


def _web_auffrischen() -> None:
    global _web_holt
    try:
        stand = _web_zustand_holen()
    except Exception as problem:                             # pragma: no cover
        stand = {"zustand": "aus", "qr": "", "nummer": None,
                 "meldung": f"Abfrage fehlgeschlagen ({type(problem).__name__})"}
    with _web_sperre:
        _web_stand["wert"] = stand
        _web_stand["zeit"] = time.monotonic()
        _web_holt = False


def web_zustand(warten: bool = False) -> dict:
    """Was der Beiwagen gerade macht - aus dem Zwischenspeicher.

    Warum nicht einfach fragen? Weil die Antwort ueber eine Steckverbindung
    kommt und das Rendern einer Seite daran haengen wuerde. Laeuft der Dienst
    nicht, wartet Windows sekundenlang auf den abgelehnten Verbindungsversuch:
    die WhatsApp-Seite brauchte dadurch vier Sekunden, Sicherheit und
    Datenbank je zwei - obwohl dort nur eine Statuszeile davon abhaengt.

    Also: gespeicherten Wert sofort zurueckgeben und im Hintergrund
    auffrischen. `warten=True` erzwingt die Abfrage - fuer den Knopf
    "Verbindung prüfen", wo genau das der Zweck ist.
    """
    global _web_holt
    if modus() != "web":
        return {"zustand": "aus", "qr": "", "nummer": None,
                "meldung": "Die Betriebsart ist nicht „web“."}

    if warten:
        stand = _web_zustand_holen()
        with _web_sperre:
            _web_stand["wert"] = stand
            _web_stand["zeit"] = time.monotonic()
        return stand

    with _web_sperre:
        wert = _web_stand["wert"]
        frisch = wert is not None and time.monotonic() - _web_stand["zeit"] < _WEB_FRISCHE
        starten = not frisch and not _web_holt
        if starten:
            _web_holt = True

    if starten:
        threading.Thread(target=_web_auffrischen, daemon=True,
                         name="whatsapp-zustand").start()
    if wert is not None:
        return wert
    return {"zustand": "pruefung", "qr": "", "nummer": None,
            "meldung": "Verbindung wird geprüft …"}


def web_abmelden() -> tuple:
    erfolg, daten = _web_aufruf("/abmelden", {}, frist=20)
    return erfolg, "" if erfolg else str(daten)


def _ueber_web(nummer: str, text: str) -> tuple:
    erfolg, daten = _web_aufruf("/senden", {"nummer": nummer, "text": text},
                                frist=45)
    if erfolg and isinstance(daten, dict) and daten.get("ok"):
        return True, ""
    if isinstance(daten, dict):
        return False, str(daten.get("fehler") or "Versand fehlgeschlagen.")
    return False, str(daten)


def einsatzbereit(warten: bool = False) -> tuple:
    """(bereit, Meldung) - was der Bot gerade kann."""
    art = modus()
    if art == "web":
        stand = web_zustand(warten=warten)
        zustand = stand.get("zustand")
        if zustand == "pruefung":
            return False, stand.get("meldung", "Verbindung wird geprüft …")
        if zustand == "bereit":
            nummer = stand.get("nummer")
            return True, ("Verbunden über WhatsApp Web"
                          + (f" als +{nummer}" if nummer else "")
                          + ". Neue Mitglieder werden automatisch begrüßt.")
        if zustand == "qr":
            return False, ("Noch nicht gekoppelt – unten den QR-Code mit "
                           "WhatsApp scannen (Einstellungen → Verknüpfte "
                           "Geräte → Gerät verknüpfen).")
        if zustand == "aus":
            return False, stand.get("meldung", "Der Dienst läuft nicht.")
        return False, stand.get("meldung", "Der Dienst startet gerade.")
    if art == "cloud":
        if not (cfg.WHATSAPP_TOKEN and cfg.WHATSAPP_NUMMER_ID):
            return False, ("Cloud-API gewählt, aber WHATSAPP_TOKEN oder "
                           "WHATSAPP_NUMMER_ID fehlt in config.cmd.")
        if not cfg.WHATSAPP_VORLAGE_NAME:
            # Der haeufigste Stolperstein beim Anschluss eines Business-Kontos.
            # Ohne Vorlage laesst Meta nur Antworten innerhalb von 24 Stunden
            # zu - eine Begruessung geht damit nie raus.
            return False, ("Vollautomatisch verschickt wird erst mit einer von "
                           "Meta genehmigten Vorlage. Ohne sie lässt WhatsApp "
                           "nur Nachrichten an Personen zu, die in den letzten "
                           "24 Stunden selbst geschrieben haben – ein neues "
                           "Mitglied hat das nie. Vorlagenname in config.cmd "
                           "unter WHATSAPP_VORLAGE_NAME eintragen.")
        return True, (f"Versand über die WhatsApp Cloud API mit der Vorlage "
                      f"„{cfg.WHATSAPP_VORLAGE_NAME}“. Neue Mitglieder werden "
                      "automatisch begrüßt.")
    if art == "callmebot":
        return True, ("Versand über CallMeBot. Jede Nummer braucht dort einen "
                      "eigenen Schlüssel.")
    return True, ("Nachrichten werden vorbereitet und per Klick in WhatsApp "
                  "geöffnet – es wird nichts automatisch verschickt.")


def automatik_an(db=None) -> bool:
    """Soll der Bot bei neuen Mitgliedern von selbst tätig werden?"""
    if db is not None:
        return werte.an_db(db, werte.WHATSAPP_AUTOMATIK, True)
    return werte.an(werte.WHATSAPP_AUTOMATIK, True)


def vorlage(db) -> str:
    gespeichert = werte.hole_db(db, werte.WHATSAPP_WILLKOMMEN)
    return gespeichert or WILLKOMMEN_STANDARD


def fuelle_vorlage(text: str, person: User) -> str:
    from kern.rechte import abteilung_label, label
    ersetzungen = {
        "{vorname}": person.vorname or "",
        "{nachname}": person.nachname or "",
        "{name}": person.name,
        "{abteilung}": abteilung_label(person.department),
        "{rolle}": label(person.role),
        "{dashboard}": cfg.DASHBOARD_URL,
        "{gruppe}": cfg.WHATSAPP_GRUPPE,
        "{discord}": cfg.DISCORD_EINLADUNG,
    }
    for platzhalter, wert in ersetzungen.items():
        text = text.replace(platzhalter, wert)
    return text


def wa_link(nummer: str, text: str) -> str:
    """Der Klick-Link fuer die Betriebsart „manuell“.

    wa.me oeffnet WhatsApp (App oder Web) mit fertig vorgeschriebenem Text -
    abgeschickt wird erst durch einen zweiten Tipp. Das ist gewollt: eine
    Nachricht im Namen der AG soll jemand gesehen haben, bevor sie rausgeht.
    """
    return (f"https://wa.me/{telefon_normal(nummer, cfg.WHATSAPP_LANDESVORWAHL)}"
            f"?text={urllib.parse.quote(text)}")


#  Ausgangskorb
def einreihen(db, person: User, text: str = None, anlass: str = "willkommen") -> WhatsAppNachricht:
    """Eine Nachricht in den Korb legen. Ohne commit."""
    nummer = telefon_normal(getattr(person, "telefonnummer", ""),
                            cfg.WHATSAPP_LANDESVORWAHL)
    inhalt = text if text is not None else fuelle_vorlage(vorlage(db), person)
    eintrag = WhatsAppNachricht(
        user_id=person.id, nummer=nummer, name=person.name,
        text=inhalt, anlass=anlass,
        # Ohne Nummer braucht es keinen Versuch - das waere nur eine
        # Fehlermeldung, die sich viermal wiederholt.
        status="offen" if nummer else "keine_nummer",
        fehler=None if nummer else "Für dieses Konto ist keine Telefonnummer hinterlegt.")
    db.add(eintrag)
    return eintrag


def willkommen_ausloesen(db, person: User, erzwingen: bool = False) -> WhatsAppNachricht:
    """Der uebliche Einstiegspunkt: neues Mitglied begruessen.

    Wird nur einmal je Person getan - der Zeitpunkt steht am Konto. Ohne
    diese Sperre bekaeme jemand bei jeder Rollenaenderung erneut eine
    Begruessung.
    """
    if not erzwingen:
        if person.willkommen_gesendet_am:
            return None
        if not automatik_an(db):
            return None
    eintrag = einreihen(db, person, anlass="willkommen")
    person.willkommen_gesendet_am = utcnow()
    return eintrag


def offene(db, grenze: int = 50) -> list:
    return (db.query(WhatsAppNachricht)
            .filter(WhatsAppNachricht.status == "offen",
                    WhatsAppNachricht.versuche < HOECHSTVERSUCHE)
            .order_by(WhatsAppNachricht.created_at).limit(grenze).all())


#  Versandwege
def _parameter_saeubern(wert: str) -> str:
    """Bringt einen Wert in die Form, die Meta fuer Vorlagen zulaesst.

    Die Cloud API weist Vorlagen-Parameter zurueck, die einen Zeilenumbruch,
    einen Tabulator oder mehr als vier Leerzeichen hintereinander enthalten -
    mit Fehler 132000, dessen Text nicht verraet, woran es lag. Deshalb hier
    einmal sauber machen, statt sich das spaeter am Ausgangskorb anzusehen.
    """
    text = re.sub(r"[\r\n\t]+", " ", str(wert or ""))
    text = re.sub(r" {4,}", "   ", text)
    return text.strip()[:1000]


def vorlagen_parameter(db, person: User) -> list:
    """Die Werte, die in die genehmigte Meta-Vorlage eingesetzt werden.

    Welche und in welcher Reihenfolge, steht in der Einstellung
    ``whatsapp_vorlage_parameter`` - eine Liste von Platzhalternamen, getrennt
    durch Komma. Sie muss zu {{1}}, {{2}} ... der Vorlage passen, die Meta
    genehmigt hat.

    Warum nicht einfach der ganze Willkommenstext als ein Parameter? Weil ein
    Parameter keinen Zeilenumbruch enthalten darf. Die Zeilenumbrueche gehoeren
    in die Vorlage selbst; hier kommen nur kurze Werte hinein.
    """
    roh = werte.hole_db(db, WERTE_VORLAGE_PARAMETER, "vorname")
    namen = [n.strip() for n in roh.split(",") if n.strip()]
    fertig = fuelle_vorlage("", person)      # nur fuer die Ersetzungstabelle
    tabelle = {
        "vorname": person.vorname or "",
        "nachname": person.nachname or "",
        "name": person.name,
        "dashboard": cfg.DASHBOARD_URL,
        "gruppe": cfg.WHATSAPP_GRUPPE,
        "discord": cfg.DISCORD_EINLADUNG,
    }
    from kern.rechte import abteilung_label, label
    tabelle["abteilung"] = abteilung_label(person.department)
    tabelle["rolle"] = label(person.role)
    del fertig
    return [_parameter_saeubern(tabelle.get(n, n)) for n in namen]


def _cloud_aufrufen(nutzlast: dict) -> tuple:
    """Ein Aufruf an die Graph-API. (erfolg, Meldung)."""
    ziel = (f"https://graph.facebook.com/{cfg.WHATSAPP_API_VERSION}/"
            f"{cfg.WHATSAPP_NUMMER_ID}/messages")
    anfrage = urllib.request.Request(
        ziel, data=json.dumps(nutzlast).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {cfg.WHATSAPP_TOKEN}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(anfrage, timeout=15) as antwort:
            json.loads(antwort.read().decode("utf-8", "replace"))
        return True, ""
    except urllib.error.HTTPError as fehler:
        code, meldung = None, ""
        try:
            koerper = json.loads(fehler.read().decode("utf-8", "replace"))
            angaben = koerper.get("error", {})
            meldung = angaben.get("message", "")
            code = angaben.get("code")
            if angaben.get("error_data", {}).get("details"):
                meldung += " – " + angaben["error_data"]["details"]
        except Exception:
            pass
        return False, _cloud_fehler_erklaeren(fehler.code, code, meldung)
    except Exception as fehler:
        return False, f"WhatsApp nicht erreichbar ({type(fehler).__name__})"


# Die Fehler, die beim Anschluss eines Business-Kontos wirklich vorkommen.
# Metas eigene Texte nennen die Ursache oft nicht - hier steht, was zu tun ist.
_CLOUD_HINWEISE = {
    131026: "Die Nummer hat kein WhatsApp oder kann keine Nachrichten empfangen.",
    131047: "Außerhalb des 24-Stunden-Fensters – dafür braucht es eine von "
            "Meta genehmigte Vorlage (WHATSAPP_VORLAGE_NAME setzen).",
    131051: "Dieser Nachrichtentyp ist für die Nummer nicht freigegeben.",
    132000: "Die Vorlage erwartet eine andere Anzahl Parameter, oder ein "
            "Parameter enthält einen Zeilenumbruch.",
    132001: "Diese Vorlage gibt es unter dem Namen oder in der Sprache nicht.",
    132005: "Der Vorlagentext wurde nach der Genehmigung geändert.",
    132015: "Die Vorlage ist pausiert, weil zu viele Empfänger sie gemeldet haben.",
    132016: "Die Vorlage wurde von Meta deaktiviert.",
    133010: "Die Absendernummer ist nicht registriert.",
    190: "Das Zugriffstoken ist abgelaufen oder ungültig – in der Meta-Konsole "
         "ein neues (am besten dauerhaftes) erzeugen.",
    100: "Meta hat die Anfrage abgelehnt – meist stimmt die Nummern-ID nicht.",
    80007: "Zu viele Nachrichten in kurzer Zeit – der Korb versucht es später erneut.",
}


def _cloud_fehler_erklaeren(http_code: int, meta_code, meldung: str) -> str:
    hinweis = _CLOUD_HINWEISE.get(meta_code)
    grund = meldung or "ohne Angabe"
    if hinweis:
        return f"{hinweis} (Meta {meta_code}: {grund})"[:300]
    return f"WhatsApp antwortet {http_code}"f" (Code {meta_code}): {grund}"[:300]


def _ueber_cloud(db, nummer: str, text: str, person=None) -> tuple:
    """Versand ueber die offizielle Cloud API.

    Zwei Wege, und der Unterschied ist der wichtigste Punkt beim Anschluss
    eines Business-Kontos:

    * **Mit Vorlage** (WHATSAPP_VORLAGE_NAME gesetzt): funktioniert immer,
      auch wenn die Person noch nie geschrieben hat. Genau der Fall bei einem
      neuen Mitglied. Der Text steht in der von Meta genehmigten Vorlage, hier
      gehen nur die Platzhalterwerte mit.
    * **Ohne Vorlage**: freier Text. Meta laesst das nur innerhalb von 24
      Stunden zu, nachdem die Person selbst geschrieben hat. Fuer eine
      Begruessung also in aller Regel nicht.
    """
    if cfg.WHATSAPP_VORLAGE_NAME and person is not None:
        parameter = vorlagen_parameter(db, person)
        vorlage_teile = []
        if parameter:
            vorlage_teile.append({
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in parameter],
            })
        nutzlast = {
            "messaging_product": "whatsapp", "to": nummer, "type": "template",
            "template": {
                "name": cfg.WHATSAPP_VORLAGE_NAME,
                "language": {"code": werte.hole_db(db, WERTE_VORLAGE_SPRACHE, "de")},
                "components": vorlage_teile,
            },
        }
    else:
        nutzlast = {"messaging_product": "whatsapp", "to": nummer,
                    "type": "text",
                    "text": {"body": text[:4000], "preview_url": True}}
    return _cloud_aufrufen(nutzlast)


def verbindung_pruefen() -> tuple:
    """(gut, Meldung) - fragt Meta nach der Absendernummer.

    Der Knopf, den man beim Anschliessen eines Business-Kontos braucht: Er
    sagt, ob Token und Nummern-ID zusammenpassen, ohne dass jemand eine echte
    Nachricht bekommt.
    """
    if modus() != "cloud":
        return False, "Der Bot läuft nicht im Cloud-Betrieb."
    if not (cfg.WHATSAPP_TOKEN and cfg.WHATSAPP_NUMMER_ID):
        return False, "WHATSAPP_TOKEN oder WHATSAPP_NUMMER_ID fehlt in config.cmd."
    ziel = (f"https://graph.facebook.com/{cfg.WHATSAPP_API_VERSION}/"
            f"{cfg.WHATSAPP_NUMMER_ID}?fields=display_phone_number,"
            f"verified_name,quality_rating")
    anfrage = urllib.request.Request(
        ziel, headers={"Authorization": f"Bearer {cfg.WHATSAPP_TOKEN}"})
    try:
        with urllib.request.urlopen(anfrage, timeout=12) as antwort:
            daten = json.loads(antwort.read().decode("utf-8", "replace"))
        nummer = daten.get("display_phone_number", "?")
        name = daten.get("verified_name", "?")
        güte = daten.get("quality_rating", "")
        return True, (f"Verbunden mit {name} ({nummer})"
                      + (f", Bewertung {güte}" if güte else "") + ".")
    except urllib.error.HTTPError as fehler:
        code, meldung = None, ""
        try:
            angaben = json.loads(fehler.read().decode("utf-8", "replace")).get("error", {})
            meldung, code = angaben.get("message", ""), angaben.get("code")
        except Exception:
            pass
        return False, _cloud_fehler_erklaeren(fehler.code, code, meldung)
    except Exception as fehler:
        return False, f"Meta nicht erreichbar ({type(fehler).__name__})"


def _ueber_callmebot(nummer: str, text: str, schluessel: str) -> tuple:
    if not schluessel:
        return False, ("Für diese Nummer ist kein CallMeBot-Schlüssel "
                       "hinterlegt.")
    ziel = ("https://api.callmebot.com/whatsapp.php?"
            + urllib.parse.urlencode({"phone": "+" + nummer,
                                      "text": text[:900],
                                      "apikey": schluessel}))
    try:
        with urllib.request.urlopen(ziel, timeout=15) as antwort:
            inhalt = antwort.read().decode("utf-8", "replace")
        if "queued" in inhalt.lower() or "sent" in inhalt.lower():
            return True, ""
        return False, inhalt[:160].strip() or "Unklare Antwort von CallMeBot."
    except Exception as fehler:
        return False, f"CallMeBot nicht erreichbar ({type(fehler).__name__})"


def _schluessel_fuer(db, nummer: str) -> str:
    """CallMeBot-Schluessel je Nummer, hinterlegt im Dashboard."""
    roh = werte.hole_db(db, "whatsapp_callmebot_schluessel", "")
    for zeile in roh.splitlines():
        if "=" not in zeile:
            continue
        wessen, _, schluessel = zeile.partition("=")
        if telefon_normal(wessen, cfg.WHATSAPP_LANDESVORWAHL) == nummer:
            return sauber(schluessel)
    return ""


def sende_eintrag(db, eintrag: WhatsAppNachricht) -> tuple:
    """Einen Korbeintrag zustellen. Gibt (erfolg, Meldung) zurueck."""
    art = modus()
    eintrag.versuche = (eintrag.versuche or 0) + 1

    if not eintrag.nummer:
        eintrag.status = "keine_nummer"
        eintrag.fehler = "Keine Telefonnummer hinterlegt."
        return False, eintrag.fehler

    if werte.an_db(db, werte.WHATSAPP_TESTMODUS):
        eintrag.status = "test"
        eintrag.fehler = "Testmodus - nicht wirklich verschickt."
        zustellung("whatsapp", eintrag.name or eintrag.nummer, eintrag.anlass,
                   False, eintrag.fehler, "whatsapp")
        return False, eintrag.fehler

    if art == "manuell":
        # Kein Versand - der Eintrag wartet auf den Klick im Dashboard.
        eintrag.status = "bereit"
        eintrag.fehler = None
        return False, "Bereit zum Absenden per Klick."

    if art == "web":
        erfolg, meldung = _ueber_web(eintrag.nummer, eintrag.text)
    elif art == "cloud":
        person = db.get(User, eintrag.user_id) if eintrag.user_id else None
        erfolg, meldung = _ueber_cloud(db, eintrag.nummer, eintrag.text, person)
    else:
        erfolg, meldung = _ueber_callmebot(
            eintrag.nummer, eintrag.text, _schluessel_fuer(db, eintrag.nummer))

    if erfolg:
        eintrag.status = "gesendet"
        eintrag.gesendet_am = utcnow()
        eintrag.fehler = None
    else:
        eintrag.fehler = meldung[:300]
        # Nach genug Versuchen aufgeben und es sichtbar machen, statt es
        # ewig im Hintergrund weiterprobieren zu lassen.
        eintrag.status = ("fehler" if eintrag.versuche >= HOECHSTVERSUCHE
                          else "offen")
    zustellung("whatsapp", eintrag.name or eintrag.nummer, eintrag.anlass,
               erfolg, "" if erfolg else meldung, "whatsapp")
    return erfolg, meldung


def korb_abarbeiten() -> dict:
    """Alle offenen Nachrichten zustellen. Fuer den Hintergrundlauf."""
    bilanz = {"gesendet": 0, "fehlgeschlagen": 0, "wartend": 0}
    if modus() == "manuell":
        with sitzung() as db:
            # Auch im manuellen Betrieb einmal durchgehen: dadurch bekommen
            # neue Eintraege den Zustand "bereit" und tauchen im Dashboard
            # als abzusendend auf.
            for eintrag in offene(db):
                sende_eintrag(db, eintrag)
                bilanz["wartend"] += 1
            db.commit()
        return bilanz
    with sitzung() as db:
        for eintrag in offene(db):
            erfolg, _ = sende_eintrag(db, eintrag)
            bilanz["gesendet" if erfolg else "fehlgeschlagen"] += 1
            time.sleep(0.4)      # nicht in einem Schwall - das bremsen Dienste aus
        db.commit()
    return bilanz


def korb_anstossen() -> None:
    """Korb im Hintergrund abarbeiten - blockiert den Aufrufer nicht."""
    def arbeit():
        try:
            korb_abarbeiten()
        except Exception as problem:                         # pragma: no cover
            print(f"[WhatsApp] Korb fehlgeschlagen: {problem}")

    threading.Thread(target=arbeit, daemon=True, name="whatsapp").start()


def uebersicht(db) -> dict:
    """Zahlen fuer die Dashboard-Karte."""
    from sqlalchemy import func
    zeilen = dict(db.query(WhatsAppNachricht.status,
                           func.count(WhatsAppNachricht.id))
                  .group_by(WhatsAppNachricht.status).all())
    return {
        "offen": zeilen.get("offen", 0) + zeilen.get("bereit", 0),
        "gesendet": zeilen.get("gesendet", 0),
        "fehler": zeilen.get("fehler", 0),
        "ohne_nummer": zeilen.get("keine_nummer", 0),
        "gesamt": sum(zeilen.values()),
    }
