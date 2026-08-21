"""Einstellungen, die sich im Betrieb umschalten lassen.

Alles, was nicht in config.cmd gehoert, weil es zur Laufzeit aenderbar sein
soll: Testmodi, Texte, Schaltzustaende. Ein Schluessel-Wert-Speicher in der
Datenbank, damit beide Serverprozesse denselben Stand sehen.

Der kleine Zwischenspeicher ist noetig, weil manche Werte bei jedem
Seitenaufbau gelesen werden. Er haelt sie nur wenige Sekunden - lange genug,
um die Abfragen zu sparen, kurz genug, dass eine Aenderung im Dashboard
sofort auch im anderen Prozess ankommt.
"""

import threading
import time

from kern.datenbank import sitzung
from kern.modelle import AppSetting

_CACHE_SEKUNDEN = 5
_cache = {}
_sperre = threading.Lock()

# --- Bekannte Schluessel ----------------------------------------------------
EMAIL_TESTMODUS = "email_test_mode"          # Name aus V1 - Wert bleibt erhalten
PUSH_TESTMODUS = "push_test_mode"
WHATSAPP_TESTMODUS = "whatsapp_test_mode"
WHATSAPP_WILLKOMMEN = "whatsapp_willkommen"
WHATSAPP_AUTOMATIK = "whatsapp_automatik"
VAPID_PRIVAT = "vapid_private_key"
VAPID_OEFFENTLICH = "vapid_public_key"
STARTSEITE_ZAHLEN = "startseite_zahlen"      # Kennzahlen unter dem Aufmacher


def hole(schluessel: str, standard: str = "") -> str:
    with _sperre:
        eintrag = _cache.get(schluessel)
        if eintrag and time.monotonic() - eintrag[1] < _CACHE_SEKUNDEN:
            return eintrag[0]
    with sitzung() as db:
        zeile = db.get(AppSetting, schluessel)
        wert = zeile.value if zeile else standard
    with _sperre:
        _cache[schluessel] = (wert, time.monotonic())
    return wert


def hole_db(db, schluessel: str, standard: str = "") -> str:
    """Wie hole(), aber mit vorhandener Sitzung - spart eine Verbindung."""
    zeile = db.get(AppSetting, schluessel)
    return zeile.value if zeile else standard


def setze(db, schluessel: str, wert: str) -> None:
    zeile = db.get(AppSetting, schluessel)
    if zeile:
        zeile.value = wert
    else:
        db.add(AppSetting(key=schluessel, value=wert))
    db.commit()
    with _sperre:
        _cache.pop(schluessel, None)


def an(schluessel: str, standard: bool = False) -> bool:
    return hole(schluessel, "1" if standard else "0") == "1"


def an_db(db, schluessel: str, standard: bool = False) -> bool:
    return hole_db(db, schluessel, "1" if standard else "0") == "1"


def schalte(db, schluessel: str, zustand: bool) -> None:
    setze(db, schluessel, "1" if zustand else "0")


def verwerfen() -> None:
    with _sperre:
        _cache.clear()
