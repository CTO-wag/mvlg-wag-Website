"""Push-Meldungen auf zwei Wegen: Web Push und ntfy.

Beide bleiben unveraendert aus V1 erhalten - das ist die Bedingung dafuer,
dass niemand seine Benachrichtigungen neu einrichten muss:

  * Die VAPID-Schluessel stehen in app_settings und werden weiterverwendet.
    Ein neues Paar wuerde alle angemeldeten Geraete ungueltig machen.
  * Das persoenliche ntfy-Thema steht in notification_preferences und aendert
    sich nicht. Wer die ntfy-App abonniert hat, bekommt weiter Meldungen.
  * Die Tabelle push_subscriptions wird weiterbenutzt.

Web Push ist der Weg ueber den Browser bzw. die auf dem Startbildschirm
abgelegte App - ohne Fremd-App und ohne geheimes Thema. ntfy bleibt als
zweiter Weg: er funktioniert auch dort, wo Web Push nicht geht.
"""

import base64
import json
import os
import threading
import urllib.error
import urllib.request

from kern import einstellungen as cfg
from kern import werte
from kern.datenbank import sitzung
from kern.modelle import PushSubscription
from kern.protokoll import zustellung
from kern.text import utcnow


def _b64(rohdaten: bytes) -> str:
    """URL-sichere Base64 ohne Fuellzeichen - so erwarten es Browser und Dienste."""
    return base64.urlsafe_b64encode(rohdaten).decode("ascii").rstrip("=")


def vapid_schluessel(db) -> tuple:
    """(privat, oeffentlich). Wird beim allerersten Aufruf erzeugt.

    Umgebungsvariablen haben Vorrang - wer die Schluessel selbst verwaltet
    oder zwei Server damit betreiben will, setzt sie dort.
    """
    aus_umgebung = (os.environ.get("VAPID_PRIVATE_KEY", "").strip(),
                    os.environ.get("VAPID_PUBLIC_KEY", "").strip())
    if all(aus_umgebung):
        return aus_umgebung
    privat = werte.hole_db(db, werte.VAPID_PRIVAT)
    oeffentlich = werte.hole_db(db, werte.VAPID_OEFFENTLICH)
    if privat and oeffentlich:
        return privat, oeffentlich

    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid01
    paar = Vapid01()
    paar.generate_keys()
    privat = _b64(paar.private_key.private_numbers()
                  .private_value.to_bytes(32, "big"))
    oeffentlich = _b64(paar.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    werte.setze(db, werte.VAPID_PRIVAT, privat)
    werte.setze(db, werte.VAPID_OEFFENTLICH, oeffentlich)
    print("[Push] Neues VAPID-Schlüsselpaar erzeugt und gespeichert.")
    return privat, oeffentlich


def vapid_kontakt() -> str:
    if cfg.MAIL_REPLY_TO:
        return f"mailto:{cfg.MAIL_REPLY_TO}"
    if cfg.SMTP_FROM:
        return f"mailto:{cfg.SMTP_FROM}"
    return cfg.SITE_URL


def geraete(db, user_id: int) -> list:
    return (db.query(PushSubscription)
            .filter(PushSubscription.user_id == user_id)
            .order_by(PushSubscription.id).all())


def empfaenger(db, user_id: int) -> list:
    """Die Anmeldungen, an die tatsaechlich geschickt wird - eine je Geraet.

    Website und Dashboard duerfen sich beide anmelden, damit es keine Rolle
    spielt, welche der beiden Seiten jemand auf dem Startbildschirm hat. Auf
    demselben Handy sind das dann zwei Anmeldungen - und ohne diese Auswahl
    zwei Meldungen fuer dasselbe Ereignis.

    Beide tragen dieselbe Geraetekennung (Cookie auf der gemeinsamen Domain).
    Je Kennung wird die neueste genommen; die ist die zuletzt bestaetigte.
    Anmeldungen ohne Kennung stammen aus V1 - sie bekommen weiter alle
    einzeln, denn ohne Kennung laesst sich nicht sagen, ob es dasselbe Geraet
    ist, und eine Meldung zu viel ist besser als keine.
    """
    je_geraet, ohne_kennung = {}, []
    for abo in geraete(db, user_id):
        if abo.geraete_id:
            fruehere = je_geraet.get(abo.geraete_id)
            if not fruehere or (abo.id or 0) > (fruehere.id or 0):
                je_geraet[abo.geraete_id] = abo
        else:
            ohne_kennung.append(abo)
    return list(je_geraet.values()) + ohne_kennung


#  Web Push
def _an_geraet(db, abo, titel: str, text: str, ziel_url: str) -> tuple:
    """(geklappt, Fehlertext, Geraet ist tot).

    Das dritte Feld zaehlt: meldet der Dienst 404 oder 410, gibt es das
    Geraet nicht mehr (App geloescht, Berechtigung entzogen). Solche
    Eintraege werden entfernt, statt bei jeder Meldung erneut zu scheitern.
    """
    from pywebpush import WebPushException, webpush
    privat, _ = vapid_schluessel(db)
    inhalt = json.dumps({"titel": titel[:120], "text": text[:400],
                         "url": ziel_url}, ensure_ascii=False)
    try:
        webpush(
            subscription_info={"endpoint": abo.endpoint,
                               "keys": {"p256dh": abo.p256dh, "auth": abo.auth}},
            data=inhalt,
            vapid_private_key=privat,
            vapid_claims={"sub": vapid_kontakt()},
            # Ohne Angabe waere die Lebensdauer 0: der Dienst wirft die Meldung
            # weg, wenn das Handy in genau dem Moment kein Netz hat. Einen Tag
            # aufheben passt - eine Fristerinnerung ist auch spaeter nuetzlich.
            ttl=24 * 60 * 60,
            timeout=10,
        )
        return True, "", False
    except WebPushException as fehler:
        code = getattr(getattr(fehler, "response", None), "status_code", None)
        if code in (404, 410):
            return False, "Gerät ist abgemeldet", True
        if code == 413:
            return False, "Meldung zu lang für den Push-Dienst", False
        if code == 429:
            return False, "Push-Dienst bremst gerade", False
        return False, f"Push-Dienst antwortet {code or type(fehler).__name__}", False
    except Exception as fehler:                              # pragma: no cover
        return False, f"Push fehlgeschlagen ({type(fehler).__name__})", False


def webpush_an_person(user_id: int, titel: str, text: str, warten: bool = False,
                      ziel: str = "", anlass: str = "") -> tuple:
    """An alle Geraete einer Person."""
    ziel_url = f"{cfg.DASHBOARD_URL}/"

    def erledigen():
        with sitzung() as db:
            abos = empfaenger(db, user_id)
            if not abos:
                # Bewusst KEIN Protokolleintrag: Es ist nichts schiefgegangen,
                # es gab auf diesem Weg nichts zuzustellen. Als Fehler gebucht
                # stand auf der Sicherheitsseite dauerhaft "5 von 16 nicht
                # zugestellt" - eine Warnung, die immer leuchtet, liest bald
                # niemand mehr, auch die naechste nicht. Dass jemand kein
                # Geraet angemeldet hat, steht dort, wo man es beheben kann:
                # in seiner eigenen Liste auf der Uebersicht (kern/umzug.py).
                return False, "kein Gerät angemeldet"
            erfolge, entfernt, fehler = 0, 0, []
            for abo in abos:
                geklappt, meldung, tot = _an_geraet(db, abo, titel, text, ziel_url)
                if geklappt:
                    erfolge += 1
                    abo.last_ok_at = utcnow()
                elif tot:
                    db.delete(abo)
                    entfernt += 1
                else:
                    fehler.append(meldung)
            db.commit()
            beschriftung = ziel or f"Konto #{user_id}"
            if erfolge:
                zustellung("webpush", beschriftung, titel, True, "", anlass)
                return True, ""
            if entfernt and not fehler:
                fehler.append(f"{entfernt} Gerät(e) hatten die Berechtigung "
                              "entzogen und wurden entfernt")
            grund = "; ".join(dict.fromkeys(fehler)) or "kein Gerät angemeldet"
            zustellung("webpush", beschriftung, titel, False, grund, anlass)
            return False, grund

    if warten:
        return erledigen()
    threading.Thread(target=erledigen, daemon=True, name="webpush").start()
    return True, ""


#  ntfy
def _an_ntfy(thema: str, titel: str, text: str) -> tuple:
    try:
        anfrage = urllib.request.Request(
            f"{cfg.NTFY_BASE_URL}/{thema}",
            data=text[:1000].encode("utf-8"), method="POST",
            headers={"Title": titel[:120].encode("utf-8").decode("latin-1", "ignore"),
                     "Priority": "default", "Tags": "bell"})
        with urllib.request.urlopen(anfrage, timeout=8):
            return True, ""
    except urllib.error.HTTPError as fehler:
        text_ = ""
        try:
            text_ = json.loads(fehler.read().decode("utf-8", "replace")).get("error", "")
        except Exception:
            pass
        if fehler.code == 429:
            # Der haeufigste Fall im Alltag und der einzige, gegen den man
            # nichts programmieren kann - deshalb im Klartext benennen.
            return False, "ntfy-Tageskontingent aufgebraucht (kostenloser Dienst)"
        return False, f"ntfy antwortet {fehler.code}{': ' + text_ if text_ else ''}"
    except Exception as fehler:
        return False, f"ntfy nicht erreichbar ({type(fehler).__name__})"


def ntfy_an_thema(thema: str, titel: str, text: str, warten: bool = False,
                  ziel: str = "", anlass: str = "") -> tuple:
    # Das Thema ist geheimzuhalten - im Protokoll steht deshalb der Name und
    # ersatzweise nur ein kurzes Stueck zur Wiedererkennung.
    beschriftung = ziel or f"Thema …{(thema or '')[-6:]}"

    def erledigen():
        geklappt, fehler = _an_ntfy(thema, titel, text)
        zustellung("push", beschriftung, titel, geklappt, fehler, anlass)
        return geklappt, fehler

    if warten:
        return erledigen()
    threading.Thread(target=erledigen, daemon=True, name="ntfy").start()
    return True, ""


def pruefe_ntfy() -> tuple:
    """(gut, Meldung) - fuer die Systemuebersicht."""
    try:
        anfrage = urllib.request.Request(f"{cfg.NTFY_BASE_URL}/v1/health",
                                         method="GET")
        with urllib.request.urlopen(anfrage, timeout=6) as antwort:
            daten = json.loads(antwort.read().decode("utf-8", "replace"))
        if daten.get("healthy"):
            return True, f"{cfg.NTFY_BASE_URL} antwortet."
        return False, "Dienst meldet sich als nicht bereit."
    except Exception as fehler:
        return False, f"{type(fehler).__name__}: nicht erreichbar"
