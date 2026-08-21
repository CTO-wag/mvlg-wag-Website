"""Anpassbare Bloecke der oeffentlichen Startseite.

Die Sektion „Unsere Arbeit“ stand in V1 fest im Quelltext. Eine neue
Aktivitaet aufzunehmen hiess: Datei aendern, Server neu starten - also genau
das, was niemand bei jeder Kleinigkeit machen will, weshalb die Seite auch
zwei Jahre lang dieselben vier Karten zeigte.

Jetzt kommen die Bloecke aus der Datenbank und lassen sich im Dashboard
pflegen. Der Text der bisherigen vier Karten wurde bei der Migration
unveraendert uebernommen - die Seite sah nach dem Umstieg also genauso aus
wie vorher.
"""

import threading
import time

from kern.datenbank import sitzung
from kern.modelle import Inhalt
from kern.text import utcnow

BEREICHE = {
    "portfolio": ("Unsere Arbeit",
                  "Was die AG schon gemacht hat – Wettbewerbe, Projekte, "
                  "Aktionen. Mit Zeitraum und Ergebnis. Diese Sektion "
                  "erscheint auf der Startseite erst, wenn hier etwas steht."),
    "angebot": ("Womit wir uns beschäftigen",
                "Die Karten weiter oben auf der Startseite. Sie beschreiben, "
                "worum es in der AG geht – nicht, was schon passiert ist."),
    "vorteile": ("Was du mitnimmst",
                 "Die Liste im Kasten neben „Über uns“. Nur eine Zeile je "
                 "Punkt – der Text darunter bleibt leer."),
    "stufen": ("Dein Weg",
               "Die nummerierten Stufen vom Einstieg bis ins Core-Team. "
               "Titel ist die Überschrift, Text die Erklärung dahinter."),
}

# Nur beim Portfolio gibt es Zeitraum und Ergebnis - bei einer Aufzählung
# wären die Felder nur Ballast.
MIT_ZEITRAUM = ("portfolio",)
MIT_TEXT = ("portfolio", "angebot", "stufen")
MIT_FARBE = ("portfolio", "angebot")

FARBVORSCHLAEGE = ("#0E2647", "#B7791F", "#2F855A", "#B83280", "#2B6CB0",
                   "#805AD5", "#C53030")

# Die Seite wird oft aufgerufen und selten geaendert - deshalb kurz merken.
_CACHE_SEKUNDEN = 20
_cache = {}
_sperre = threading.Lock()


def verwerfen() -> None:
    with _sperre:
        _cache.clear()


def bloecke(bereich: str, nur_aktive: bool = True) -> list:
    """Die Bloecke eines Bereichs als einfache dicts."""
    schluessel = (bereich, nur_aktive)
    with _sperre:
        eintrag = _cache.get(schluessel)
        if eintrag and time.monotonic() - eintrag[1] < _CACHE_SEKUNDEN:
            return eintrag[0]
    with sitzung() as db:
        abfrage = db.query(Inhalt).filter(Inhalt.bereich == bereich)
        if nur_aktive:
            abfrage = abfrage.filter(Inhalt.aktiv == 1)
        daten = [{"id": b.id, "titel": b.titel, "text": b.text or "",
                  "farbe": b.farbe or "", "zeitraum": b.zeitraum or "",
                  "ergebnis": b.ergebnis or "",
                  "reihenfolge": b.reihenfolge, "aktiv": bool(b.aktiv)}
                 for b in abfrage.order_by(Inhalt.reihenfolge, Inhalt.id).all()]
    with _sperre:
        _cache[schluessel] = (daten, time.monotonic())
    return daten


def alle_bloecke(db) -> dict:
    """Alle Bereiche mit allen Bloecken - fuer die Bearbeitung im Dashboard."""
    ergebnis = {schluessel: [] for schluessel in BEREICHE}
    for block in db.query(Inhalt).order_by(Inhalt.bereich, Inhalt.reihenfolge,
                                           Inhalt.id).all():
        ergebnis.setdefault(block.bereich, []).append(block)
    return ergebnis


def anlegen(db, bereich: str, titel: str, text: str = "", farbe: str = "",
            zeitraum: str = "", ergebnis: str = "", von_id: int = None) -> Inhalt:
    letzte = db.query(Inhalt).filter(Inhalt.bereich == bereich).count()
    block = Inhalt(bereich=bereich, titel=titel[:160], text=text or None,
                   farbe=(farbe or "")[:7] or None,
                   zeitraum=(zeitraum or "")[:60] or None,
                   ergebnis=(ergebnis or "")[:120] or None,
                   reihenfolge=(letzte + 1) * 10, geaendert_von=von_id)
    db.add(block)
    return block


def verschieben(db, block_id: int, richtung: int) -> None:
    """Einen Block um eine Position nach oben oder unten.

    Ueber die Reihenfolge zweier Nachbarn statt ueber eine Neunummerierung
    aller Zeilen: das ist eine Aenderung statt zehn, und bei zwei Personen,
    die gleichzeitig sortieren, geht dabei nichts durcheinander.
    """
    block = db.get(Inhalt, block_id)
    if not block:
        return
    geschwister = (db.query(Inhalt)
                   .filter(Inhalt.bereich == block.bereich)
                   .order_by(Inhalt.reihenfolge, Inhalt.id).all())
    stelle = next((i for i, b in enumerate(geschwister) if b.id == block.id), None)
    if stelle is None:
        return
    ziel = stelle + (1 if richtung > 0 else -1)
    if ziel < 0 or ziel >= len(geschwister):
        return
    anderer = geschwister[ziel]
    block.reihenfolge, anderer.reihenfolge = anderer.reihenfolge, block.reihenfolge
    block.updated_at = utcnow()


# Die Zahlenreihe unter dem Aufmacher ist bewusst entfernt worden. Eine
# Schueler-AG mit acht Mitgliedern wirbt mit der Zahl gegen sich selbst, und
# eine Zahl, die von der Kontenverwaltung abhaengt, gehoert ohnehin nicht auf
# eine Werbeseite. Was die AG kann, zeigt jetzt das Portfolio.
