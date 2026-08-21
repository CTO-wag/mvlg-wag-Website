"""Datenbankverbindung.

Eine einzige Engine fuer beide Server-Prozesse. Laeuft wahlweise gegen die
SQLite-Datei im Datenordner oder gegen Postgres (Supabase) - entschieden wird
das ueber DATABASE_URL in der config.cmd.

Der Unterschied ist groesser, als er aussieht: SQLite liegt neben der
Anwendung, eine Abfrage kostet Mikrosekunden. Postgres liegt im Netz, jede
Abfrage kostet einen Hin- und Rueckweg. Deshalb sind die Vorraete
unterschiedlich gross und die Wartezeiten unterschiedlich gesetzt.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from kern.einstellungen import DATABASE_URL

IST_SQLITE = DATABASE_URL.startswith("sqlite")
IST_POSTGRES = DATABASE_URL.startswith("postgres")

if IST_SQLITE:
    # Seit die Routen in Arbeitsfaeden laufen (siehe kern/webbasis.py), koennen
    # mehrere Anfragen wirklich gleichzeitig an der Datenbank sein. Ein Vorrat
    # von fuenf haette daraus eine neue Warteschlange gemacht. Lesen kostet
    # unter WAL nichts, eine offene SQLite-Verbindung ist ein Dateihandle.
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 20},
        pool_pre_ping=True,
        pool_size=20, max_overflow=30, pool_timeout=10,
    )
else:
    # Gegen Supabase laeuft die Verbindung ueber deren Pooler. Der buendelt
    # viele Anwendungsverbindungen auf wenige echte - ein grosser Vorrat auf
    # unserer Seite braecht dort nur an eine andere Grenze. pool_recycle,
    # weil der Pooler stille Verbindungen nach einiger Zeit schliesst und ein
    # Zugriff darauf sonst mit einem Fehler endet, den niemand versteht.
    engine = create_engine(
        DATABASE_URL,
        connect_args={"connect_timeout": 15,
                      "application_name": "wag-plattform"},
        pool_pre_ping=True,
        pool_size=5, max_overflow=10, pool_timeout=30,
        pool_recycle=280,
    )

if IST_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_einstellungen(verbindung, _datensatz):
        zeiger = verbindung.cursor()
        try:
            # WAL: zwei Prozesse gleichzeitig sind erst damit unproblematisch.
            zeiger.execute("PRAGMA journal_mode=WAL")
            zeiger.execute("PRAGMA synchronous=NORMAL")
            # Wartet, statt sofort "database is locked" zu melden.
            zeiger.execute("PRAGMA busy_timeout=8000")
            # Ohne das setzt SQLite Fremdschluessel gar nicht durch.
            zeiger.execute("PRAGMA foreign_keys=ON")
        finally:
            zeiger.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                            expire_on_commit=False)
Base = declarative_base()


def hole_db():
    """FastAPI-Abhaengigkeit: eine Sitzung je Anfrage."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class sitzung:
    """Sitzung fuer Hintergrundarbeit: ``with sitzung() as db: ...``

    Schliesst zuverlaessig und rollt bei einem Fehler zurueck - in
    Hintergrundfaeden war ein vergessenes close() in V1 die haeufigste
    Ursache fuer haengende Verbindungen.
    """

    def __enter__(self):
        self.db = SessionLocal()
        return self.db

    def __exit__(self, art, wert, spur):
        try:
            if art is not None:
                self.db.rollback()
        finally:
            self.db.close()
        return False
