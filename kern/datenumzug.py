"""Alle Tabellen von einer Datenbank in eine andere kopieren.

Drei Verwendungen, dieselbe Mechanik:

  SQLite -> Postgres   der Umzug zu Supabase (werkzeuge/nach_supabase.py)
  Postgres -> SQLite   die Sicherung, wenn die Datenbank nicht mehr lokal
                       liegt (kern/sicherung.py)
  SQLite -> Postgres   das Zurueckspielen einer solchen Sicherung

Kopiert wird ueber die Modelle, nicht ueber SQL-Abzuege. Damit ist es egal,
welche Datenbank auf welcher Seite steht, und die Reihenfolge der Tabellen
ergibt sich aus den Fremdschluesseln - sonst schluege das Einfuegen fehl,
weil die Zeile, auf die verwiesen wird, noch nicht da ist.
"""

from sqlalchemy import create_engine, inspect, select, text

from kern.datenbank import Base
# Muss importiert werden, auch wenn es hier nicht benutzt wird: Erst dadurch
# stehen die Tabellen in Base.metadata. Ohne das kopiert dieses Modul nichts
# und meldet trotzdem Erfolg.
from kern import modelle                                     # noqa: F401


def verbinde(url: str):
    """Engine fuer eine beliebige Datenbank-Adresse."""
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


def tabellen_in_reihenfolge() -> list:
    """Tabellen so sortiert, dass Verweise immer schon vorhanden sind."""
    return list(Base.metadata.sorted_tables)


def zaehle(engine) -> dict:
    """Zeilen je Tabelle. Fehlende Tabellen werden uebersprungen."""
    vorhanden = set(inspect(engine).get_table_names())
    ergebnis = {}
    with engine.connect() as verbindung:
        for tabelle in tabellen_in_reihenfolge():
            if tabelle.name not in vorhanden:
                continue
            ergebnis[tabelle.name] = verbindung.execute(
                select(text("count(*)")).select_from(tabelle)).scalar()
    return ergebnis


def kopiere(quelle_url: str, ziel_url: str, leeren: bool = True,
            melden=print) -> dict:
    """Kopiert alle Tabellen. Gibt die Zeilenzahl je Tabelle zurueck.

    `leeren` raeumt die Zieltabellen vorher aus. Ohne das kaeme es bei einem
    zweiten Lauf zu doppelten Schluesseln.
    """
    quelle = verbinde(quelle_url)
    ziel = verbinde(ziel_url)
    try:
        Base.metadata.create_all(ziel)
        vorhanden = set(inspect(quelle).get_table_names())
        bilanz = {}

        with ziel.begin() as schreiben:
            if leeren:
                # Rueckwaerts: erst die Tabellen, die auf andere verweisen.
                for tabelle in reversed(tabellen_in_reihenfolge()):
                    schreiben.execute(tabelle.delete())

            with quelle.connect() as lesen:
                for tabelle in tabellen_in_reihenfolge():
                    if tabelle.name not in vorhanden:
                        melden(f"  {tabelle.name}: in der Quelle nicht da")
                        continue
                    zeilen = [dict(z) for z in
                              lesen.execute(select(tabelle)).mappings()]
                    if zeilen:
                        schreiben.execute(tabelle.insert(), zeilen)
                    bilanz[tabelle.name] = len(zeilen)

        if ziel.dialect.name == "postgresql":
            zaehler_nachziehen(ziel, melden)
        return bilanz
    finally:
        quelle.dispose()
        ziel.dispose()


def zaehler_nachziehen(engine, melden=print) -> int:
    """Die Zaehler der Primaerschluessel auf den hoechsten Wert setzen.

    Ohne das vergibt Postgres bei der naechsten neuen Zeile die 1 - die es
    laengst gibt. Der erste Klick nach dem Umzug endet dann mit einem Fehler,
    und zwar an einer voellig unverdaechtigen Stelle.
    """
    angepasst = 0
    with engine.begin() as verbindung:
        for tabelle in tabellen_in_reihenfolge():
            for spalte in tabelle.primary_key.columns:
                if not spalte.autoincrement or spalte.type.python_type is not int:
                    continue
                folge = verbindung.execute(text(
                    "SELECT pg_get_serial_sequence(:t, :s)"),
                    {"t": tabelle.name, "s": spalte.name}).scalar()
                if not folge:
                    continue
                hoechster = verbindung.execute(text(
                    f'SELECT COALESCE(MAX("{spalte.name}"), 0) '
                    f'FROM "{tabelle.name}"')).scalar()
                verbindung.execute(text("SELECT setval(:f, :w, true)"),
                                   {"f": folge, "w": max(1, int(hoechster))})
                angepasst += 1
    melden(f"  {angepasst} Zaehler nachgezogen")
    return angepasst
