"""Den Datenbestand von der SQLite-Datei nach Supabase kopieren.

    python werkzeuge/nach_supabase.py --pruefen
    python werkzeuge/nach_supabase.py --umziehen

--pruefen  verbindet sich, zaehlt beide Seiten und aendert nichts.
--umziehen legt die Tabellen an und kopiert alles hinueber.

Die Quelle wird nur gelesen. Geht beim Umzug etwas schief, ist die
SQLite-Datei unveraendert - man stellt DATABASE_URL zurueck und alles laeuft
wie vorher.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def hole_ziel() -> str:
    # config.cmd selbst einlesen, genau wie server.py es tut. Sonst muesste
    # man vorher "call config.cmd" aufrufen - und bekaeme, wenn man es
    # vergisst, eine Meldung ueber eine Einstellung, die man laengst
    # eingetragen hat.
    from server import _config_einlesen
    quelle = _config_einlesen()
    if quelle:
        print(f"Konfiguration: {quelle}")

    ziel = os.environ.get("DATABASE_URL", "").strip()
    if not ziel:
        print("In der config.cmd steht keine DATABASE_URL.")
        print()
        print("Pruef zwei Dinge:")
        print("  1. Steht die Zeile da, und steht KEIN 'REM' davor?")
        print("     Die Beispielzeile ist auskommentiert - das REM muss weg.")
        print("  2. Sieht sie so aus?")
        print('     set "DATABASE_URL=postgresql+psycopg2://..."')
        raise SystemExit(1)
    if ziel.startswith("sqlite"):
        print("DATABASE_URL zeigt noch auf SQLite. Dann gibt es nichts zu tun.")
        raise SystemExit(1)
    return ziel


def hole_quelle() -> str:
    from kern.einstellungen import DATENBANK_DATEI
    if not os.path.exists(DATENBANK_DATEI):
        print(f"Die Datei {DATENBANK_DATEI} gibt es nicht.")
        raise SystemExit(1)
    return "sqlite:///" + DATENBANK_DATEI.replace("\\", "/")


def zeige(titel: str, zahlen: dict) -> int:
    gesamt = sum(zahlen.values())
    nicht_leer = {t: n for t, n in zahlen.items() if n}
    print(f"\n{titel}: {len(zahlen)} Tabellen, {gesamt} Zeilen")
    for tabelle, anzahl in sorted(nicht_leer.items(), key=lambda x: -x[1])[:12]:
        print(f"   {tabelle:32} {anzahl:>6}")
    if len(nicht_leer) > 12:
        print(f"   ... und {len(nicht_leer) - 12} weitere")
    return gesamt


def main() -> int:
    zerleger = argparse.ArgumentParser(description="Umzug nach Supabase")
    zerleger.add_argument("--pruefen", action="store_true",
                          help="nur verbinden und zaehlen, nichts aendern")
    zerleger.add_argument("--umziehen", action="store_true",
                          help="Tabellen anlegen und Daten kopieren")
    args = zerleger.parse_args()
    if not (args.pruefen or args.umziehen):
        zerleger.print_help()
        return 1

    ziel = hole_ziel()
    quelle = hole_quelle()
    from kern.datenumzug import kopiere, verbinde, zaehle

    # Der Adresse fehlt nie das Passwort, aber sie soll trotzdem nicht
    # vollstaendig im Fenster stehen - Bildschirmfotos wandern weiter.
    ohne_geheimnis = ziel.split("@")[-1] if "@" in ziel else ziel
    print(f"Quelle: {quelle}")
    print(f"Ziel  : ...@{ohne_geheimnis}")

    try:
        zaehler_ziel = zaehle(verbinde(ziel))
    except Exception as fehler:
        print(f"\nVerbindung zu Supabase fehlgeschlagen:\n  "
              f"{type(fehler).__name__}: {fehler}\n\n"
              "Haeufigste Ursachen: falsches Passwort in der Adresse, der\n"
              "Teil ':6543' fehlt, oder das Projekt ist pausiert (Supabase\n"
              "pausiert kostenlose Projekte nach einer Woche ohne Zugriff).")
        return 1

    zaehler_quelle = zaehle(verbinde(quelle))
    zeige("Vorhanden in der SQLite-Datei", zaehler_quelle)
    zeige("Vorhanden bei Supabase", zaehler_ziel)

    if args.pruefen:
        print("\nNur geprueft, nichts geaendert.")
        return 0

    if sum(zaehler_ziel.values()):
        print("\nBei Supabase stehen schon Daten. Der Umzug leert die Tabellen\n"
              "vorher - was dort steht, ist danach weg.")
        if input("Trotzdem fortfahren? (ja/nein) ").strip().lower() != "ja":
            print("Abgebrochen.")
            return 1

    print("\nKopiere ...")
    bilanz = kopiere(quelle, ziel)
    nachher = zaehle(verbinde(ziel))

    abweichung = {t: (zaehler_quelle[t], nachher.get(t, 0))
                  for t in zaehler_quelle
                  if nachher.get(t, 0) != zaehler_quelle[t]}
    zeige("Jetzt bei Supabase", nachher)
    if abweichung:
        print(f"\nACHTUNG - diese Tabellen stimmen nicht ueberein:")
        for tabelle, (soll, ist) in abweichung.items():
            print(f"   {tabelle}: erwartet {soll}, gefunden {ist}")
        return 1
    print(f"\nFertig. {sum(bilanz.values())} Zeilen in {len(bilanz)} Tabellen.")
    print("Die SQLite-Datei ist unveraendert - sie bleibt als Rueckweg liegen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
