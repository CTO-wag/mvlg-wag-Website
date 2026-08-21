"""Datenbankverbindung.

Eine einzige Engine fuer beide Server-Prozesse (Website und Dashboard).
SQLite kommt damit klar, solange WAL eingeschaltet ist: dann behindern sich
Lesen und Schreiben nicht mehr, und zwei Prozesse koennen dieselbe Datei
benutzen. Ohne WAL sperrte jedes Speichern kurz die ganze Datei - bei zwei
Prozessen waeren daraus regelmaessig "database is locked"-Fehler geworden.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from kern.einstellungen import DATABASE_URL

IST_SQLITE = DATABASE_URL.startswith("sqlite")

# Seit die Routen in Arbeitsfaeden laufen (siehe kern/webbasis.py), koennen
# mehrere Anfragen wirklich gleichzeitig an der Datenbank sein. Der Vorrat von
# fuenf Verbindungen haette daraus eine neue Warteschlange gemacht: Faden 6
# haette bis zu dreissig Sekunden auf eine freie Verbindung gewartet - genau
# das Stocken, das wir gerade abgestellt haben. Lesen kostet unter WAL nichts,
# eine offene SQLite-Verbindung ist ein Dateihandle.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 20} if IST_SQLITE else {},
    pool_pre_ping=True,
    pool_size=20, max_overflow=30, pool_timeout=10,
)

if IST_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_einstellungen(verbindung, _datensatz):
        zeiger = verbindung.cursor()
        try:
            # WAL: zwei Prozesse (8000 und 8001) gleichzeitig sind erst damit
            # unproblematisch. NORMAL: SQLite wartet nicht nach jedem Schreiben
            # auf die Platte - der uebliche Betriebsmodus zusammen mit WAL.
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
