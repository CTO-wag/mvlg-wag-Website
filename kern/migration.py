"""Datenbankänderungen, die nicht mit Alembic gemacht werden.

Alembic ist ein Werkzeug fuer automatische Migrations- eigentlich fuer
die richtige Reihenfolge. Hier wird es nicht benutzt, weil:

    * Die Datenbank mit V1 begann und gross ist. Eine Alembic-Historie
      haette damit keine Ruhe vor Anfang an.
    * Autogenerate kennt keine Constraints, die nicht vom Schema
      erkennbar sind.
    * Die meisten Aenderungen sind Hinzufuegungen, keine Umbauten.

Statt dessen: Auflisteung der Aenderungen von V1 zu V2, Funktion pro
Aenderung. Wird bei jedem Start ausgefuehrt, tut aber nur, wenn noetig.
"""

from datetime import datetime
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from kern.datenbank import engine

def hat_spalte(tabelle: str, spalte: str) -> bool:
    """True, wenn die Spalte existiert."""
    try:
        with engine.connect() as conn:
            # SQLite: zwei Wege, abhaengig von der Python/SQLAlchemy-Version
            try:
                result = conn.execute(text(f"PRAGMA table_info({tabelle})"))
                for row in result:
                    if row[1] == spalte:
                        return True
            except Exception:
                # Fallback fuer andere Datenbanken
                result = conn.execute(text(f"SELECT * FROM {tabelle} LIMIT 0"))
                return spalte in result.keys()
    except Exception:
        pass
    return False


def hat_tabelle(tabelle: str) -> bool:
    """True, wenn die Tabelle existiert."""
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SELECT 1 FROM {tabelle} LIMIT 0"))
            return True
    except OperationalError:
        return False
    except Exception:
        return False


def spalte_hinzufuegen(tabelle: str, spalte: str, definition: str) -> None:
    """Eine Spalte hinzufuegen, wenn sie fehlt."""
    if hat_spalte(tabelle, spalte):
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {tabelle} ADD COLUMN {spalte} {definition}"))
    print(f"[Migration] Spalte {tabelle}.{spalte} hinzugefuegt")


def index_hinzufuegen(tabelle: str, spalten: list, name: str = None) -> None:
    """Einen Index hinzufuegen, wenn er fehlt."""
    name = name or f"ix_{tabelle}_{'_'.join(spalten)}"
    spalten_str = ", ".join(spalten)
    try:
        with engine.connect() as conn:
            # SQLite: PRAGMA index_info() prueft, ob ein Index existiert
            result = conn.execute(text(f"PRAGMA index_info({name})"))
            if result.fetchone():
                return
    except Exception:
        pass
    
    with engine.begin() as conn:
        conn.execute(text(f"CREATE INDEX {name} ON {tabelle} ({spalten_str})"))
    print(f"[Migration] Index {name} hinzugefuegt")


# --- Migrationen -------------------------------------------------------

def _v2_initial_schema():
    """Neu in V2: Tabellen und Spalten, die es in V1 nicht gab."""
    # Tabelle fuer Berechtigungen pro Person
    if not hat_tabelle("user_permissions"):
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE user_permissions (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    perm VARCHAR(60) NOT NULL,
                    wert INTEGER NOT NULL DEFAULT 1,
                    notiz VARCHAR(200),
                    gesetzt_von INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    FOREIGN KEY(gesetzt_von) REFERENCES users(id),
                    UNIQUE(user_id, perm)
                )
            """))
        print("[Migration] Tabelle user_permissions erstellt")

    # Tabelle fuer Leistungen (dauerhafter Nachweis)
    if not hat_tabelle("leistungen"):
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE leistungen (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    art VARCHAR(30) NOT NULL,
                    quelle_id INTEGER,
                    titel VARCHAR(200),
                    abteilung VARCHAR(30),
                    punkte INTEGER NOT NULL DEFAULT 1,
                    zeitpunkt DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    UNIQUE(user_id, art, quelle_id)
                )
            """))
            conn.execute(text("CREATE INDEX ix_leistung_user ON leistungen(user_id)"))
            conn.execute(text("CREATE INDEX ix_leistung_art ON leistungen(art)"))
            conn.execute(text("CREATE INDEX ix_leistung_zeit ON leistungen(zeitpunkt)"))
        print("[Migration] Tabelle leistungen erstellt")

    # Spalten zum LeadershipScore hinzufuegen
    spalte_hinzufuegen("leadership_scores", "gesamt",
                       "INTEGER NOT NULL DEFAULT 0")
    spalte_hinzufuegen("leadership_scores", "zuverlaessigkeit",
                       "INTEGER NOT NULL DEFAULT 0")
    spalte_hinzufuegen("leadership_scores", "initiative",
                       "INTEGER NOT NULL DEFAULT 0")

    # Tabelle fuer Anmeldeversuche (Sicherheit)
    if not hat_tabelle("anmeldeversuche"):
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE anmeldeversuche (
                    id INTEGER PRIMARY KEY,
                    email VARCHAR(160) NOT NULL,
                    user_id INTEGER,
                    erfolg INTEGER NOT NULL DEFAULT 0,
                    grund VARCHAR(60),
                    ip_address VARCHAR(64),
                    user_agent VARCHAR(240),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    INDEX(email),
                    INDEX(user_id),
                    INDEX(created_at)
                )
            """))
        print("[Migration] Tabelle anmeldeversuche erstellt")

    # Neue Spalten im User-Tisch
    spalte_hinzufuegen("users", "totp_secret", "VARCHAR(64)")
    spalte_hinzufuegen("users", "totp_aktiv", "INTEGER NOT NULL DEFAULT 0")
    spalte_hinzufuegen("users", "totp_ersatzcodes", "TEXT")
    spalte_hinzufuegen("users", "passwort_geaendert_am", "DATETIME")
    spalte_hinzufuegen("users", "willkommen_gesendet_am", "DATETIME")

    # Sicherheit auf die Startseite: User-Sessions
    if not hat_tabelle("user_sessions"):
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE user_sessions (
                    id VARCHAR(48) PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    ip_address VARCHAR(64),
                    user_agent VARCHAR(240),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_active DATETIME DEFAULT CURRENT_TIMESTAMP,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    geraete_hash VARCHAR(64),
                    dauerhaft INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    INDEX(user_id)
                )
            """))
        print("[Migration] Tabelle user_sessions erstellt")

    # Tabelle fuer anpassbare Inhalte der Startseite
    if not hat_tabelle("seiten_inhalte"):
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE seiten_inhalte (
                    id INTEGER PRIMARY KEY,
                    bereich VARCHAR(30) NOT NULL DEFAULT 'portfolio',
                    titel VARCHAR(160) NOT NULL,
                    text TEXT,
                    icon VARCHAR(16),
                    farbe VARCHAR(7),
                    zeitraum VARCHAR(60),
                    ergebnis VARCHAR(120),
                    reihenfolge INTEGER NOT NULL DEFAULT 100,
                    aktiv INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    geaendert_von INTEGER,
                    FOREIGN KEY(geaendert_von) REFERENCES users(id),
                    INDEX(bereich)
                )
            """))
        print("[Migration] Tabelle seiten_inhalte erstellt")

    # WhatsApp-Nachrichtenkorb
    if not hat_tabelle("whatsapp_nachrichten"):
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE whatsapp_nachrichten (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    nummer VARCHAR(40) NOT NULL,
                    name VARCHAR(160),
                    text TEXT NOT NULL,
                    anlass VARCHAR(40) NOT NULL DEFAULT 'willkommen',
                    status VARCHAR(20) NOT NULL DEFAULT 'offen',
                    versuche INTEGER NOT NULL DEFAULT 0,
                    fehler VARCHAR(300),
                    gesendet_am DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id),
                    INDEX(user_id),
                    INDEX(status),
                    INDEX(created_at)
                )
            """))
        print("[Migration] Tabelle whatsapp_nachrichten erstellt")


def _manuelle_leadership_punkte():
    """Leadership-Punkte, die manuell vergeben werden können."""
    spalte_hinzufuegen("leadership_scores", "manuelle_punkte",
                       "INTEGER NOT NULL DEFAULT 0")
    spalte_hinzufuegen("leadership_scores", "manuelle_punkte_notiz", "TEXT")
    spalte_hinzufuegen("leadership_scores", "manuelle_punkte_von",
                       "INTEGER")
    spalte_hinzufuegen("leadership_scores", "manuelle_punkte_am",
                       "DATETIME")
    # Fremdschluessel fuer die Person, die die Punkte vergeben hat
    if hat_spalte("leadership_scores", "manuelle_punkte_von"):
        try:
            with engine.begin() as conn:
                # Versuchen, einen Fremdschluessel zu setzen
                # SQLite erlaubt das nur beim Create, daher nur ein Comment
                pass
        except Exception:
            pass


# --- Alle Migrationen durchlaufen ---
def alle_ausführen():
    """Alle ausstehenden Migrationen durchführen."""
    _v2_initial_schema()
    _manuelle_leadership_punkte()
    print("[Migration] Abgeschlossen")
