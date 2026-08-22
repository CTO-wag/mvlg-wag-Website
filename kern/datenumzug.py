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

from sqlalchemy import (Column, MetaData, String, Table, create_engine,
                        func, inspect, select, text)

from kern.datenbank import Base
# Beide muessen importiert werden, auch wenn sie hier nicht benutzt werden.
# modelle stellt die Tabellen in Base.metadata - ohne das kopiert dieses
# Modul nichts und meldet trotzdem Erfolg. rechte haengt die 28
# Rechte-Spalten an Role und Department; ohne das hat roles nur 6 Spalten,
# der Umzug laesst die Rechte liegen, und im Dashboard steht danach jede
# Rolle mit null Rechten da.
from kern import modelle                                     # noqa: F401
from kern import rechte                                      # noqa: F401


def verbinde(url: str):
    """Engine fuer eine beliebige Datenbank-Adresse."""
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


def tabellen_in_reihenfolge() -> list:
    """Tabellen so sortiert, dass Verweise immer schon vorhanden sind."""
    return list(Base.metadata.sorted_tables)


def zaehle(engine) -> dict:
    """Zeilen je Tabelle - auch die, zu denen es kein Modell gibt."""
    ergebnis = {}
    with engine.connect() as verbindung:
        for name in sorted(_echte_tabellen(engine)):
            ergebnis[name] = verbindung.execute(text(
                f'SELECT count(*) FROM "{name}"')).scalar()
    return ergebnis

def _grenze_im_ziel(tabelle: str, spalte: str, reflektiert) -> int:
    """Wie lang der Wert im Ziel sein darf.

    Fuer Spalten aus dem Modell legt create_all den Typ fest - dort gilt
    das Modell, nicht das, was in der alten Datei steht. activity_log.value
    etwa ist in der Datei noch VARCHAR(200), im Modell laengst Text.
    Fuer alle anderen Spalten wird der Typ aus der Quelle uebernommen.
    """
    im_modell = Base.metadata.tables.get(tabelle)
    if im_modell is not None and spalte in im_modell.c:
        return getattr(im_modell.c[spalte].type, "length", None) or 0
    return getattr(reflektiert, "length", None) or 0


def zu_lange_werte(engine) -> list:
    """Werte, die laenger sind als ihre Spalte im Ziel erlaubt.

    SQLite behandelt VARCHAR(200) als Notiz und schreibt auch 500 Zeichen
    hinein. Postgres lehnt sie ab. Ohne diese Pruefung bricht der Umzug
    mittendrin mit einem Fehler ab, dem man nicht ansieht, welche Zeile
    gemeint ist.

    Liefert (Tabelle, Spalte, Grenze, Anzahl, laengster Wert).
    """
    spiegel = MetaData()
    spiegel.reflect(bind=engine)
    treffer = []
    with engine.connect() as verbindung:
        for tabelle in spiegel.sorted_tables:
            if tabelle.name.startswith("sqlite_"):
                continue
            for spalte in tabelle.columns:
                grenze = _grenze_im_ziel(tabelle.name, spalte.name,
                                         spalte.type)
                if not grenze:
                    continue
                laenge = func.length(spalte)
                anzahl, laengster = verbindung.execute(
                    select(func.count(), func.max(laenge))
                    .where(laenge > grenze)).one()
                if anzahl:
                    treffer.append((tabelle.name, spalte.name, grenze,
                                    anzahl, laengster))
    return treffer

# Reflektierte Typnamen, die Postgres nicht kennt. Anders als die Liste in
# kern/migration.py geht es hier um Typen, die aus einer bestehenden
# SQLite-Datei ausgelesen wurden, nicht um selbst geschriebene.
TYPEN_FUERS_ZIEL = {
    "DATETIME": "TIMESTAMP",
    "REAL": "DOUBLE PRECISION",
    "FLOAT": "DOUBLE PRECISION",
    "BLOB": "BYTEA",
}


def _typ_uebersetzen(ziel, typ) -> str:
    geschrieben = str(typ)
    if ziel.dialect.name != "postgresql":
        return geschrieben
    grund = geschrieben.split("(")[0].strip().upper()
    ersatz = TYPEN_FUERS_ZIEL.get(grund)
    return geschrieben.replace(grund, ersatz, 1) if ersatz else geschrieben


def _echte_tabellen(engine) -> list:
    """Tabellennamen ohne die Verwaltungstabellen von SQLite."""
    return [name for name in inspect(engine).get_table_names()
            if not name.startswith("sqlite_")]


def _fehlende_tabellen_anlegen(quelle, ziel, melden) -> int:
    """Tabellen anlegen, zu denen es kein Modell gibt.

    In der Datenbank stehen noch chats, chat_participants, chat_messages und
    news aus V1. Die Anwendung liest sie nicht, aber wenn sie beim Umzug
    fehlen, sind Datei und Ziel nicht mehr dasselbe.

    Zwei Eigenheiten:

    - Die Typen werden auf ihre allgemeine Form gebracht. Ausgelesen wird
      SQLites DATETIME, und das versteht Postgres nicht.
    - Fremdschluessel werden weggelassen. In diesen Tabellen stehen Verweise
      auf Konten, die es nicht mehr gibt - SQLite hat das nie geprueft. Mit
      Fremdschluessel liesse sich der Altbestand gar nicht mehr uebertragen,
      und zu erzwingen gibt es hier nichts: geschrieben wird da nie wieder.
    """
    da = set(_echte_tabellen(ziel))
    fehlen = [n for n in _echte_tabellen(quelle) if n not in da]
    if not fehlen:
        return 0

    gelesen = MetaData()
    for name in fehlen:
        Table(name, gelesen, autoload_with=quelle)

    gebaut = 0
    for vorlage in gelesen.sorted_tables:
        if vorlage.name not in fehlen:
            continue
        entwurf = MetaData()
        neu = Table(vorlage.name, entwurf)
        for spalte in vorlage.columns:
            try:
                typ = spalte.type.as_generic()
            except (NotImplementedError, AttributeError):
                typ = spalte.type
            neu.append_column(Column(
                spalte.name, typ,
                primary_key=spalte.primary_key,
                nullable=spalte.nullable))
        try:
            neu.create(ziel)
            gebaut += 1
            melden(f"  Tabelle {neu.name} angelegt (kein Modell)")
        except Exception as fehler:
            melden(f"  Tabelle {neu.name} nicht anlegbar: {fehler}")
    return gebaut


def _fehlende_spalten_anlegen(quelle, ziel, melden) -> int:
    """Spalten anlegen, die es nur in der Quelle gibt.

    kern/migration.py haengt die Rechte-Spalten per ALTER TABLE an - im
    Modell stehen sie nicht. Wer ueber die Modelle kopiert, uebersieht
    sie, und danach hat jede Rolle null Rechte.
    """
    pruefer_q, pruefer_z = inspect(quelle), inspect(ziel)
    im_ziel = set(_echte_tabellen(ziel))
    ergaenzt = 0
    for name in _echte_tabellen(quelle):
        if name not in im_ziel:
            continue
        haben = {s["name"] for s in pruefer_z.get_columns(name)}
        for spalte in pruefer_q.get_columns(name):
            if spalte["name"] in haben:
                continue
            typ = _typ_uebersetzen(ziel, spalte["type"])
            with ziel.begin() as verbindung:
                verbindung.execute(text(
                    f'ALTER TABLE "{name}" ADD COLUMN '
                    f'"{spalte["name"]}" {typ}'))
            melden(f"  Spalte ergaenzt: {name}.{spalte['name']} ({typ})")
            ergaenzt += 1
    return ergaenzt

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
        _fehlende_tabellen_anlegen(quelle, ziel, melden)
        _fehlende_spalten_anlegen(quelle, ziel, melden)

        # Beide Seiten auslesen statt die Modelle zu befragen. Die
        # Rechte-Spalten stehen nur in der Datenbank, nicht im Modell.
        von = MetaData()
        von.reflect(bind=quelle)
        nach = MetaData()
        nach.reflect(bind=ziel)
        bilanz = {}

        with ziel.begin() as schreiben:
            if leeren:
                # Rueckwaerts: erst die Tabellen, die auf andere verweisen.
                for tabelle in reversed(nach.sorted_tables):
                    schreiben.execute(tabelle.delete())

            with quelle.connect() as lesen:
                # Reihenfolge nach dem ZIEL, nicht nach der Quelle. In der
                # SQLite-Datei stehen bei manchen Tabellen gar keine
                # Fremdschluessel - email_templates etwa waere vor users
                # einsortiert worden, und Postgres haette den Verweis auf
                # ein noch nicht vorhandenes Konto abgelehnt.
                for ziel_tabelle in nach.sorted_tables:
                    tabelle = von.tables.get(ziel_tabelle.name)
                    if tabelle is None:
                        melden(f"  {ziel_tabelle.name}: in der Quelle "
                               "nicht da")
                        continue
                    nehmen = [s.name for s in tabelle.columns
                              if s.name in ziel_tabelle.c]
                    weg = [s.name for s in tabelle.columns
                           if s.name not in ziel_tabelle.c]
                    if weg:
                        melden(f"  {tabelle.name}: uebersprungen "
                               f"{chr(44).join(weg)}")
                    zeilen = [dict(z) for z in lesen.execute(
                        select(*[tabelle.c[s] for s in nehmen])).mappings()]
                    if zeilen:
                        schreiben.execute(ziel_tabelle.insert(), zeilen)
                    bilanz[tabelle.name] = len(zeilen)

        if ziel.dialect.name == "postgresql":
            zaehler_nachziehen(ziel, melden)
            rls_einschalten(ziel, melden)
        return bilanz
    finally:
        quelle.dispose()
        ziel.dispose()


def _vergleichbar(wert):
    """Werte so angleichen, dass nur echte Unterschiede auffallen.

    Postgres liefert Kommazahlen als Decimal, SQLite als float; Zeitstempel
    kommen einmal mit und einmal ohne Zeitzone zurueck. Das sind keine
    Abweichungen im Datenbestand.
    """
    import datetime
    import decimal
    if isinstance(wert, decimal.Decimal):
        return float(wert)
    if isinstance(wert, datetime.datetime):
        return wert.replace(tzinfo=None)
    if isinstance(wert, bool):
        return int(wert)
    if isinstance(wert, memoryview):
        return bytes(wert)
    return wert


def vergleiche(quelle_url: str, ziel_url: str, melden=print) -> dict:
    """Beide Seiten Zeile fuer Zeile gegeneinanderhalten.

    Zeilenzahlen allein sagen zu wenig: Beim Umzug nach Supabase stimmten sie
    ueberall, und trotzdem fehlten 91 Rechte-Werte, weil die Spalten gar nicht
    erst mitgelesen wurden.

    Liefert je Tabelle eine Liste von Befunden. Leeres Ergebnis heisst: beide
    Seiten sind gleich.
    """
    quelle = verbinde(quelle_url)
    ziel = verbinde(ziel_url)
    try:
        von = MetaData()
        von.reflect(bind=quelle)
        nach = MetaData()
        nach.reflect(bind=ziel)

        befunde = {}
        with quelle.connect() as lesen, ziel.connect() as gegen:
            for tabelle in von.sorted_tables:
                if tabelle.name.startswith("sqlite_"):
                    continue
                eintraege = []
                drueben = nach.tables.get(tabelle.name)
                if drueben is None:
                    befunde[tabelle.name] = ["Tabelle fehlt im Ziel"]
                    continue

                fehlend = [s.name for s in tabelle.columns
                           if s.name not in drueben.c]
                if fehlend:
                    eintraege.append(
                        f"Spalten fehlen im Ziel: {', '.join(fehlend)}")

                nehmen = [s.name for s in tabelle.columns if s.name in drueben.c]
                schluessel = [s.name for s in tabelle.primary_key.columns
                              if s.name in nehmen]

                def hole(verbindung, tab):
                    reihen = verbindung.execute(
                        select(*[tab.c[s] for s in nehmen])).mappings()
                    return [{s: _vergleichbar(z[s]) for s in nehmen}
                            for z in reihen]

                hier, dort = hole(lesen, tabelle), hole(gegen, drueben)

                if not schluessel:
                    # Ohne Primaerschluessel bleibt nur der Vergleich als Menge.
                    a = sorted(tuple(z[s] for s in nehmen) for z in hier)
                    b = sorted(tuple(z[s] for s in nehmen) for z in dort)
                    if a != b:
                        eintraege.append(
                            f"Inhalt weicht ab ({len(a)} hier, {len(b)} dort)")
                    if eintraege:
                        befunde[tabelle.name] = eintraege
                    continue

                def nach_schluessel(zeilen):
                    return {tuple(z[s] for s in schluessel): z for z in zeilen}

                A, B = nach_schluessel(hier), nach_schluessel(dort)
                nur_hier = sorted(set(A) - set(B))
                nur_dort = sorted(set(B) - set(A))
                if nur_hier:
                    eintraege.append(
                        f"{len(nur_hier)} Zeile(n) fehlen im Ziel, "
                        f"z.B. {nur_hier[:3]}")
                if nur_dort:
                    eintraege.append(
                        f"{len(nur_dort)} Zeile(n) zu viel im Ziel, "
                        f"z.B. {nur_dort[:3]}")

                abweichend = {}
                for k in set(A) & set(B):
                    for s in nehmen:
                        if A[k][s] != B[k][s]:
                            abweichend.setdefault(s, []).append(k)
                for s, wo in sorted(abweichend.items()):
                    eintraege.append(
                        f"Spalte {s}: {len(wo)} abweichende(r) Wert(e), "
                        f"z.B. {wo[:3]}")

                if eintraege:
                    befunde[tabelle.name] = eintraege

            # Tabellen, die es nur im Ziel gibt.
            zusatz = [n for n in nach.tables
                      if n not in von.tables and not n.startswith("sqlite_")]
            for name in sorted(zusatz):
                befunde[name] = ["Tabelle gibt es nur im Ziel"]

        return befunde
    finally:
        quelle.dispose()
        ziel.dispose()


def rls_einschalten(engine, melden=print) -> int:
    """Row Level Security auf allen Tabellen einschalten. Nur fuer Postgres.

    Supabase stellt neben der Datenbank eine offene REST-Schnittstelle
    bereit. Die Rolle "anon" darf dort standardmaessig jede Tabelle im Schema
    public lesen UND schreiben; was sie zurueckhaelt, ist allein Row Level
    Security. Ohne die kommt jeder, der den anon-Schluessel hat, an die
    Passwort-Hashes, an die offenen Sitzungen - deren Kennung zugleich der
    Anmeldeschluessel ist - und an die Bewerberdaten.

    Eingeschaltet wird sie ohne jede Richtlinie. Das sperrt anon vollstaendig
    aus. Die Anwendung merkt nichts davon: Sie verbindet sich als "postgres",
    und diese Rolle besitzt die Tabellen und darf RLS umgehen. Waere das
    anders, muesste man FORCE ROW LEVEL SECURITY setzen - genau das tun wir
    hier nicht.
    """
    if engine.dialect.name != "postgresql":
        return 0
    with engine.begin() as verbindung:
        offen = verbindung.execute(text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND NOT rowsecurity "
            "ORDER BY tablename")).scalars().all()
        for name in offen:
            verbindung.execute(text(
                f'ALTER TABLE public."{name}" ENABLE ROW LEVEL SECURITY'))
    if offen:
        melden(f"  RLS eingeschaltet: {len(offen)} Tabelle(n)")
    return len(offen)


def rls_luecken(engine) -> list:
    """Tabellen im Schema public ohne Row Level Security."""
    if engine.dialect.name != "postgresql":
        return []
    with engine.connect() as verbindung:
        return verbindung.execute(text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND NOT rowsecurity "
            "ORDER BY tablename")).scalars().all()


def zaehler_nachziehen(engine, melden=print) -> int:
    """Die Zaehler der Primaerschluessel auf den hoechsten Wert setzen.

    Ohne das vergibt Postgres bei der naechsten neuen Zeile die 1 - die es
    laengst gibt. Der erste Klick nach dem Umzug endet dann mit einem Fehler,
    und zwar an einer voellig unverdaechtigen Stelle.
    """
    # Ueber das, was wirklich in der Datenbank steht: die Altlast-Tabellen
    # aus V1 haben kein Modell, aber auch einen Zaehler.
    spiegel = MetaData()
    spiegel.reflect(bind=engine)
    angepasst = 0
    with engine.begin() as verbindung:
        for tabelle in spiegel.sorted_tables:
            for spalte in tabelle.primary_key.columns:
                if spalte.type.python_type is not int:
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
