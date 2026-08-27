"""config.cmd einlesen, bevor irgendetwas anderes die Umgebung liest.

Warum ein eigenes Modul: `kern/einstellungen.py` liest die Umgebung beim
Import. Wer die Konfiguration nachlesen will, muss das also VOR diesem Import
tun - und darf dafuer nichts importieren, was seinerseits einstellungen
hereinzieht. Deshalb steht hier nur `os` und `re` und sonst nichts.

Zwei Programme brauchen das: `server.py`, wenn jemand ohne start.bat startet,
und `werkzeuge/auffangnetz_bauen.py`, das die Startseiten-Bloecke aus der
Datenbank holt. Zwei Fassungen derselben Suche gingen irgendwann auseinander,
und dann liefe eines von beiden auf der falschen Datenbank.
"""

import os
import re

# Der Programmordner (Management-System-V2), unabhaengig davon, von wo
# gestartet wurde.
PROGRAMM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Auch die V1 daneben wird angesehen: Beim Umstieg lag die einzige gepflegte
# config.cmd noch dort, und ein Start ohne sie liefe auf einer frischen,
# leeren Datenbank - genau der Fehler, der einmal einen ganzen Datenstand
# kostet.
KANDIDATEN = (
    os.path.join(PROGRAMM_DIR, "config.cmd"),
    os.path.join(os.path.dirname(PROGRAMM_DIR), "Management-System-V1",
                 "config.cmd"),
)

# Wer das setzt, sagt: Die Konfiguration steht schon in der Umgebung, lies
# nichts nach. Das braucht start-entwicklung.bat: Dort wird config.cmd zuerst
# gelesen und danach werden einzelne Werte mit Absicht GELEERT - eigene
# Datenbank, kein Mailversand, kein Auffangnetz. In cmd loescht  set "VAR="
# die Variable aber, statt sie leer zu setzen; sie steht danach nicht mehr in
# der Umgebung. Ohne diesen Schalter holte die Schleife unten genau diese
# Werte zurueck, und die Entwicklung liefe auf der Produktionsdatenbank.
SCHALTER = "KONFIG_GELESEN"


def einlesen(erzwingen: bool = False) -> str:
    """Werte aus config.cmd in die Umgebung uebernehmen.

    Gibt den Pfad der benutzten Datei zurueck, oder "" wenn keine gelesen
    wurde. Bereits gesetzte Umgebungsvariablen gewinnen: wer etwas
    ausdruecklich vorgibt, will das auch.
    """
    if not erzwingen and os.environ.get(SCHALTER, "").strip():
        return ""
    for kandidat in KANDIDATEN:
        if not os.path.exists(kandidat):
            continue
        try:
            with open(kandidat, "r", encoding="utf-8", errors="replace") as datei:
                for zeile in datei:
                    treffer = re.match(r'\s*set\s+"([^=]+)=(.*)"\s*$', zeile)
                    if not treffer:
                        treffer = re.match(r"\s*set\s+([A-Za-z_]\w*)=(.*?)\s*$",
                                           zeile)
                    if not treffer:
                        continue
                    name, wert = treffer.group(1).strip(), treffer.group(2)
                    if name and name not in os.environ:
                        os.environ[name] = wert
        except OSError:
            continue
        return kandidat
    return ""
