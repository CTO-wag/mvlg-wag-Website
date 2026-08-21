"""Systemzustand: laeuft alles, was laufen soll?

Die Netzpruefungen (Mailserver, Push-Dienst) dauern jeweils Sekunden. Sie
laufen deshalb im Hintergrund und werden zwischengespeichert - sonst wartet
derjenige, der zufaellig als Erster hereinschaut, fuenf Sekunden auf eine
Seite, die er nur ueberfliegen wollte.
"""

import os
import threading
import time

from sqlalchemy import func

from kern import einstellungen as cfg
from kern import mail, push, werte, whatsapp
from kern.modelle import DeliveryLog, User
from kern.sicherung import vorhandene
from kern.text import utcnow

_CACHE_SEKUNDEN = 300
_cache = {}
_laeuft = set()
_sperre = threading.Lock()


def _netzpruefung(schluessel: str, funktion):
    """Ergebnis aus dem Speicher - und im Hintergrund auffrischen."""
    with _sperre:
        eintrag = _cache.get(schluessel)
        frisch = eintrag and time.monotonic() - eintrag[2] < _CACHE_SEKUNDEN
        schon_unterwegs = schluessel in _laeuft
        if not frisch and not schon_unterwegs:
            _laeuft.add(schluessel)
            starten = True
        else:
            starten = False

    if starten:
        def arbeit():
            try:
                gut, text = funktion()
            except Exception as problem:                     # pragma: no cover
                gut, text = False, f"{type(problem).__name__}"
            with _sperre:
                _cache[schluessel] = (gut, text, time.monotonic())
                _laeuft.discard(schluessel)

        threading.Thread(target=arbeit, daemon=True,
                         name=f"zustand-{schluessel}").start()

    if eintrag:
        return eintrag[0], eintrag[1]
    return None, "wird geprüft …"


def aufwaermen() -> None:
    """Beim Start einmal anstossen, damit der erste Besucher nicht wartet."""
    _netzpruefung("smtp", mail.pruefe_verbindung)
    _netzpruefung("ntfy", push.pruefe_ntfy)
    # Fuellt den Zwischenspeicher des WhatsApp-Beiwagens im Hintergrund.
    if whatsapp.modus() == "web":
        whatsapp.web_zustand()


def pruefen(db) -> list:
    """Liste von {art, titel, text} - art ist gut, warnung oder schlecht."""
    punkte = []

    def eintrag(art, titel, text):
        punkte.append({"art": art, "titel": titel, "text": text})

    # --- Datenbank ---------------------------------------------------------
    try:
        groesse = os.path.getsize(cfg.DATENBANK_DATEI)
        konten = db.query(func.count(User.id)).scalar() or 0
        eintrag("gut", "Datenbank",
                f"{groesse / 1024 / 1024:.1f} MB · {konten} Konten · "
                f"{cfg.DATEN_DIR}")
    except OSError:
        eintrag("schlecht", "Datenbank", "Datei nicht lesbar.")

    # --- Sicherungen -------------------------------------------------------
    alle = vorhandene()
    if not alle:
        eintrag("warnung", "Sicherungen",
                "Es gibt noch keine Sicherung. Eine lässt sich im Papierkorb-"
                "Bereich mit einem Klick anlegen.")
    else:
        neueste = alle[0]
        alter = (utcnow() - neueste["zeitpunkt"].replace(tzinfo=None)).total_seconds() / 3600
        art = "gut" if alter < cfg.BACKUP_INTERVAL_HOURS * 2 else "warnung"
        eintrag(art, "Sicherungen",
                f"{len(alle)} vorhanden, neueste vor {alter:.0f} Stunden "
                f"({neueste['name']}).")

    # --- E-Mail ------------------------------------------------------------
    if not mail.versand_moeglich():
        eintrag("warnung", "E-Mail",
                "Kein Postfach hinterlegt. Meldungen laufen über die App und "
                "Push; Passwort-Links lassen sich nicht verschicken.")
    else:
        gut, text = _netzpruefung("smtp", mail.pruefe_verbindung)
        eintrag("gut" if gut else ("warnung" if gut is None else "schlecht"),
                "E-Mail", text)

    # --- Push --------------------------------------------------------------
    gut, text = _netzpruefung("ntfy", push.pruefe_ntfy)
    eintrag("gut" if gut else ("warnung" if gut is None else "warnung"),
            "Push-Dienst (ntfy)", text)

    # --- Zustellungen der letzten Zeit -------------------------------------
    from datetime import timedelta
    seit = utcnow() - timedelta(days=1)
    gesamt = db.query(func.count(DeliveryLog.id)).filter(
        DeliveryLog.created_at >= seit).scalar() or 0
    schief = db.query(func.count(DeliveryLog.id)).filter(
        DeliveryLog.created_at >= seit, DeliveryLog.erfolg == 0).scalar() or 0
    if not gesamt:
        eintrag("gut", "Zustellungen (24 h)", "Nichts zu verschicken gewesen.")
    elif schief == 0:
        eintrag("gut", "Zustellungen (24 h)", f"{gesamt} verschickt, alles angekommen.")
    else:
        art = "schlecht" if schief > gesamt / 2 else "warnung"
        eintrag(art, "Zustellungen (24 h)",
                f"{schief} von {gesamt} nicht zugestellt – Einzelheiten stehen "
                "im Zustellprotokoll unter Nachrichten.")

    # --- WhatsApp ----------------------------------------------------------
    bereit, hinweis = whatsapp.einsatzbereit()
    zahlen = whatsapp.uebersicht(db)
    zusatz = ""
    if zahlen["offen"]:
        zusatz = f" {zahlen['offen']} Nachricht(en) warten."
    if zahlen["fehler"]:
        zusatz += f" {zahlen['fehler']} fehlgeschlagen."
    eintrag("gut" if bereit and not zahlen["fehler"] else "warnung",
            "WhatsApp-Bot", hinweis + zusatz)

    # --- Testmodi ----------------------------------------------------------
    testmodi = []
    if werte.an_db(db, werte.EMAIL_TESTMODUS):
        testmodi.append("E-Mail")
    if werte.an_db(db, werte.PUSH_TESTMODUS):
        testmodi.append("Push")
    if werte.an_db(db, werte.WHATSAPP_TESTMODUS):
        testmodi.append("WhatsApp")
    if testmodi:
        eintrag("warnung", "Testmodus aktiv",
                f"{', '.join(testmodi)} geht nur an Verwalter. Nicht vergessen, "
                "das wieder auszuschalten.")

    # --- Betriebseinstellungen ---------------------------------------------
    if not cfg.HTTPS_ONLY_COOKIES:
        eintrag("warnung", "Cookies",
                "Sitzungs-Cookies sind nicht auf HTTPS beschränkt. Für den "
                "Testbetrieb in Ordnung, im echten Betrieb ein Risiko.")
    if cfg.APP_ENV != "production" and cfg.SITE_URL.startswith("https"):
        eintrag("warnung", "Umgebung",
                "Die Anwendung läuft im Entwicklungsmodus, die Adresse zeigt "
                "aber auf den echten Betrieb. In config.cmd APP_ENV=production "
                "setzen.")

    return punkte
