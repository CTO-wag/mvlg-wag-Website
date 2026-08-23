"""Startet einen der beiden Server.

    python server.py website     - oeffentliche Seite   (Port 8000)
    python server.py dashboard   - Verwaltung           (Port 8001)
    python server.py beide       - beide in einem Fenster

Der uebliche Weg ist start.bat; fuer eine getrennte lokale Umgebung gibt es
start-entwicklung.bat. Dieses Skript ist der direkte Einstieg fuer Entwicklung
und Fehlersuche.

Warum zwei Prozesse und nicht eine Anwendung mit zwei Praefixen? Weil sie
verschiedene Aufgaben haben. Die Website ist oeffentlich und muss schnell und
robust sein; das Dashboard ist ein Arbeitswerkzeug hinter der Anmeldung.
Getrennt lassen sie sich getrennt haerten, getrennt neu starten und im
Ernstfall getrennt abschalten - eine Ueberlastung der oeffentlichen Seite legt
dann nicht die Verwaltung mit lahm.
"""

import argparse
import os
import re
import sys
import threading

# Damit "kern", "website" und "dashboard" gefunden werden, egal aus welchem
# Ordner gestartet wurde.
HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)


def _config_einlesen() -> str:
    """Liest config.cmd selbst ein, falls start.bat das nicht getan hat.

    start.bat setzt die Werte normalerweise vorher in die Umgebung. Wer aber
    direkt "python server.py" aufruft - beim Entwickeln, in der Testumgebung,
    aus dem Editor heraus - haette sonst keinen SECRET_KEY und keinen
    Datenordner und liefe versehentlich auf einer frischen, leeren Datenbank.
    Genau dieser Fehler kostet einmal einen ganzen Datenstand.

    Bereits gesetzte Umgebungsvariablen gewinnen: wer etwas ausdruecklich
    vorgibt, will das auch.
    """
    for kandidat in (os.path.join(HIER, "config.cmd"),
                     os.path.join(os.path.dirname(HIER),
                                  "Management-System-V1", "config.cmd")):
        if not os.path.exists(kandidat):
            continue
        try:
            with open(kandidat, "r", encoding="utf-8", errors="replace") as datei:
                for zeile in datei:
                    treffer = re.match(r'\s*set\s+"([^=]+)=(.*)"\s*$', zeile)
                    if not treffer:
                        treffer = re.match(r"\s*set\s+([A-Za-z_]\w*)=(.*?)\s*$", zeile)
                    if not treffer:
                        continue
                    name, wert = treffer.group(1).strip(), treffer.group(2)
                    if name and name not in os.environ:
                        os.environ[name] = wert
        except OSError:
            continue
        return kandidat
    return ""


def _starte(anwendung: str, host: str, port: int, neuladen: bool) -> None:
    import uvicorn
    uvicorn.run(anwendung, host=host, port=port, reload=neuladen,
                log_level="info", access_log=False,
                # Ohne das meldet uvicorn beim Beenden jede offene Verbindung
                # einzeln - beim Schliessen des Fensters eine Bildschirmseite
                # voll Warnungen, die nichts bedeuten.
                timeout_graceful_shutdown=5)


def main() -> int:
    quelle = _config_einlesen()
    from kern import einstellungen as cfg
    if quelle:
        print(f"  Konfiguration: {quelle}")

    zerleger = argparse.ArgumentParser(description="AG-Plattform V2")
    zerleger.add_argument("was", nargs="?", default="beide",
                          choices=("website", "dashboard", "beide"))
    zerleger.add_argument("--host", default="0.0.0.0")
    zerleger.add_argument("--port", type=int, default=None)
    zerleger.add_argument("--neuladen", action="store_true",
                          help="Bei Codeänderungen automatisch neu starten.")
    args = zerleger.parse_args()

    if args.was == "website":
        _starte("website.app:app", args.host,
                args.port or cfg.WEBSITE_PORT, args.neuladen)
    elif args.was == "dashboard":
        _starte("dashboard.app:app", args.host,
                args.port or cfg.DASHBOARD_PORT, args.neuladen)
    else:
        # Beide in einem Fenster: bequem zum Ausprobieren. Im Betrieb startet
        # start.bat zwei eigene Fenster - dann stuerzt nicht beides zugleich
        # ab und man sieht getrennte Protokolle.
        faden = threading.Thread(
            target=_starte,
            args=("website.app:app", args.host, cfg.WEBSITE_PORT, False),
            daemon=True, name="website")
        faden.start()
        _starte("dashboard.app:app", args.host, cfg.DASHBOARD_PORT, False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
