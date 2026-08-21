"""Automatische Sicherungen der Datenbank.

Ueber die SQLite-eigene Sicherungsfunktion statt ueber ein Kopieren der Datei:
im WAL-Betrieb stehen die juengsten Aenderungen noch in der Begleitdatei, eine
blosse Kopie der .db waere also unvollstaendig - und das merkt man erst in dem
Moment, in dem man sie braucht.
"""

import os
import sqlite3
from datetime import datetime

from kern.einstellungen import (BACKUP_DIR, BACKUP_KEEP, DATABASE_URL,
                                DATENBANK_DATEI)


def _liegt_lokal() -> bool:
    """Liegt die Datenbank als Datei neben der Anwendung?

    Bei Supabase nicht. Dann gibt es keine Datei zum Kopieren, und die
    Sicherung entsteht stattdessen als Auszug: alle Tabellen in eine
    SQLite-Datei. Die laesst sich herunterladen, ansehen und zurueckspielen -
    genau wie vorher.
    """
    return DATABASE_URL.startswith("sqlite")


def _auszug(ziel: str) -> None:
    """Den Inhalt der Datenbank in eine SQLite-Datei schreiben."""
    from kern.datenumzug import kopiere
    kopiere(DATABASE_URL, "sqlite:///" + ziel.replace("\\", "/"),
            melden=lambda _: None)

NAMENSMUSTER = "ag_plattform_%Y-%m-%d_%H-%M.db"
# Kopien, die vor einer Aenderung an der Struktur entstehen. Der alte
# Name "vor-v2-" bleibt erkannt, damit bestehende Dateien mitgezaehlt
# werden - neue heissen "vor-migration-", weil V2 laengst laeuft.
VOR_MIGRATION = ("vor-v2-", "vor-migration-")


def erstelle() -> str:
    """Legt eine Sicherung an und raeumt alte weg. Gibt den Dateinamen zurueck."""
    if _liegt_lokal() and not os.path.exists(DATENBANK_DATEI):
        return ""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ziel = os.path.join(BACKUP_DIR, datetime.now().strftime(NAMENSMUSTER))
    if os.path.exists(ziel):
        # Innerhalb derselben Minute schon eine da - dann ist nichts zu tun.
        return ""
    if _liegt_lokal():
        quelle = sqlite3.connect(DATENBANK_DATEI)
        try:
            kopie = sqlite3.connect(ziel)
            try:
                with kopie:
                    quelle.backup(kopie)
            finally:
                kopie.close()
        finally:
            quelle.close()
    else:
        _auszug(ziel)
    alte_entfernen()
    return os.path.basename(ziel)


def vorhandene() -> list:
    """Alle Sicherungen, die neueste zuerst: (Name, Groesse, Zeitpunkt)."""
    if not os.path.isdir(BACKUP_DIR):
        return []
    eintraege = []
    for name in os.listdir(BACKUP_DIR):
        if not name.endswith(".db"):
            continue
        pfad = os.path.join(BACKUP_DIR, name)
        try:
            angaben = os.stat(pfad)
        except OSError:
            continue
        eintraege.append({
            "name": name,
            "groesse": angaben.st_size,
            "zeitpunkt": datetime.fromtimestamp(angaben.st_mtime),
            "vor_umstieg": name.startswith(VOR_MIGRATION),
        })
    eintraege.sort(key=lambda e: e["zeitpunkt"], reverse=True)
    return eintraege


def rueckweg() -> str:
    """Die eine Sicherung, die nie geloescht wird - oder leer.

    Das ist die AELTESTE Kopie aus der Zeit vor dem Umstieg: der Stand von
    V1, bevor die Migration das erste Mal etwas angefasst hat. Sie ist der
    einzige Weg zurueck zur alten Fassung und darf deshalb nicht der
    Aufbewahrungsgrenze zum Opfer fallen. Alle spaeteren Kopien sind
    Zwischenstaende von V2 und rotieren wie jede andere Sicherung.
    """
    vor = [e for e in vorhandene() if e["vor_umstieg"]]
    return vor[-1]["name"] if vor else ""


def alte_entfernen() -> int:
    """Behaelt die neuesten BACKUP_KEEP - und den Rueckweg nach V1.

    Frueher waren ALLE "vor-v2"-Kopien von der Grenze ausgenommen. Weil vor
    jedem Start eine neue angelegt wurde, wuchs der Ordner unbegrenzt: nach
    einer Woche lagen dort ein Dutzend fast gleicher Dateien. Ausgenommen ist
    jetzt nur noch die eine, die wirklich etwas kann, was keine andere kann -
    siehe rueckweg().
    """
    dauerhaft = rueckweg()
    alle = [e for e in vorhandene() if e["name"] != dauerhaft]
    entfernt = 0
    for eintrag in alle[BACKUP_KEEP:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, eintrag["name"]))
            entfernt += 1
        except OSError:
            pass
    return entfernt


def einspielen(name: str) -> tuple:
    """Eine Sicherung zurueckspielen. (geklappt, Meldung).

    Der Weg zurueck, den es bisher nur von Hand gab - und von Hand heisst:
    unter Zeitdruck, ohne Anleitung, mit laufendem Server. Hier passiert das
    in drei Schritten:

    1. **Erst den jetzigen Stand sichern.** Wer die falsche Datei erwischt,
       soll nicht auch noch das verlieren, was gerade da war.
    2. **Ueber die SQLite-eigene Sicherungsfunktion einspielen**, nicht
       ueber ein Kopieren der Datei. Die Anwendung laeuft weiter und haelt
       Verbindungen offen; eine ausgetauschte Datei unter einer offenen
       Verbindung ist der sichere Weg in eine kaputte Datenbank. Die
       Sicherungsfunktion schreibt stattdessen Seite fuer Seite in die
       bestehende Datei und nimmt sich dafuer die noetigen Sperren.
    3. **Verbindungen verwerfen.** Was der Verbindungspool noch im Griff
       hat, zeigt sonst den alten Stand.
    """
    quelle = pfad_von(name)
    if not quelle:
        return False, "Diese Sicherung gibt es nicht."
    if _liegt_lokal() and not os.path.exists(DATENBANK_DATEI):  # pragma: no cover
        return False, "Es gibt keine Datenbank, in die eingespielt werden könnte."

    vorher = os.path.join(
        BACKUP_DIR, datetime.now().strftime("vor-einspielen_%Y-%m-%d_%H-%M.db"))
    try:
        if _liegt_lokal():
            quell_db = sqlite3.connect(DATENBANK_DATEI)
            try:
                kopie = sqlite3.connect(vorher)
                try:
                    with kopie:
                        quell_db.backup(kopie)
                finally:
                    kopie.close()
            finally:
                quell_db.close()
        else:
            _auszug(vorher)
    except Exception as fehler:                              # pragma: no cover
        return False, f"Der jetzige Stand liess sich nicht sichern: {fehler}"

    try:
        from kern.datenbank import engine
        engine.dispose()
        if _liegt_lokal():
            alt = sqlite3.connect(quelle)
            try:
                ziel = sqlite3.connect(DATENBANK_DATEI)
                try:
                    with ziel:
                        alt.backup(ziel)
                finally:
                    ziel.close()
            finally:
                alt.close()
        else:
            # Zurueck in die entfernte Datenbank: Tabelle fuer Tabelle, nicht
            # als Datei. Die Zaehler der Primaerschluessel zieht kopiere()
            # danach selbst nach.
            from kern.datenumzug import kopiere
            kopiere("sqlite:///" + quelle.replace("\\", "/"), DATABASE_URL,
                    melden=lambda _: None)
        engine.dispose()
    except Exception as fehler:
        return False, (f"Das Einspielen ist gescheitert: {fehler}. Der Stand "
                       f"von eben liegt als {os.path.basename(vorher)} bereit.")
    return True, (f"„{name}“ ist eingespielt. Der Stand von eben liegt als "
                  f"{os.path.basename(vorher)} daneben, falls es doch die "
                  "falsche Datei war. Starte die Server neu, damit alle "
                  "Bereiche den neuen Stand sehen.")


def pfad_von(name: str) -> str:
    """Sicherer Pfad zu einer Sicherung - oder leer.

    Der Name kommt aus einer Adresszeile. Ohne diese Pruefung liesse sich
    ueber ..\\..\\ jede Datei des Rechners herunterladen.
    """
    if not name or "/" in name or "\\" in name or not name.endswith(".db"):
        return ""
    pfad = os.path.abspath(os.path.join(BACKUP_DIR, name))
    if not pfad.startswith(os.path.abspath(BACKUP_DIR) + os.sep):
        return ""
    return pfad if os.path.exists(pfad) else ""
