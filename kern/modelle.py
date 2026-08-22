"""Alle Tabellen der Plattform.

Grundregel fuer V2: Tabellen- und Spaltennamen bleiben exakt wie in V1.
Die bestehende Datenbank wird weiterbenutzt, nicht ersetzt - deshalb wird hier
nichts umbenannt, auch wo ein Name heute anders ausfiele. Neues kommt als
zusaetzliche Tabelle oder zusaetzliche Spalte dazu (siehe migration.py).

Neu in V2 sind unten:
  UserPermission   - Rechte je Person, zusaetzlich zu Rolle und Abteilung
  Leistung         - dauerhafter Nachweis erledigter Arbeit (ueberlebt Loeschen)
  WhatsAppNachricht- Ausgangskorb des Willkommens-Bots
  Inhalt           - anpassbare Bloecke der Startseite ("Unsere Arbeit")
  Anmeldeversuch   - Anmeldeprotokoll fuer die Sicherheitsuebersicht
"""

from datetime import date

from sqlalchemy import (
    Column, Date, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship

from kern.datenbank import Base
from kern.text import utcnow

#  Feste Listen
USER_STATUS = ("aktiv", "inaktiv")
APPLICATION_STATUS = ("neu", "in_pruefung", "angenommen", "abgelehnt")
TASK_STATUS = ("offen", "in_bearbeitung", "erledigt")
TASK_PRIORITY = ("niedrig", "mittel", "hoch")
CONTENT_KANAELE = ("instagram", "aushang", "website", "newsletter", "sonstiges")
CONTENT_STATUS = ("idee", "geplant", "in_arbeit", "veroeffentlicht")
PROJEKT_STATUS = ("planung", "laufend", "abgeschlossen")
WETTBEWERB_STATUS = ("geplant", "aktiv", "abgeschlossen")


#  Personen und Zugang
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    vorname = Column(String(80), nullable=False)
    nachname = Column(String(80), nullable=False)
    email = Column(String(160), unique=True, nullable=False, index=True)
    telefonnummer = Column(String(40), nullable=True)
    password_hash = Column(String(200), nullable=False)
    role = Column(String(40), nullable=False, default="member")
    department = Column(String(30), nullable=False, default="exekutive")
    status = Column(String(20), nullable=False, default="aktiv")
    eintrittsdatum = Column(Date, default=date.today)
    created_at = Column(DateTime, default=utcnow)
    failed_logins = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    # Kalender-Apps koennen sich nicht anmelden - die Berechtigung fuer das
    # .ics-Abo steckt deshalb in diesem Token in der URL.
    calendar_token = Column(String(48), nullable=True, unique=True, index=True)
    # Wann die Kalender-App dieses Abo zuletzt abgeholt hat. Nur daran
    # laesst sich erkennen, ob jemand die neue Adresse wirklich
    # eingetragen hat - eine Kalender-App meldet sich sonst nirgends.
    calendar_last_fetch = Column(DateTime, nullable=True)

    # --- neu in V2 ---------------------------------------------------------
    # Zweiter Faktor (TOTP). Leer = aus. Das Geheimnis steht im Klartext, weil
    # der Server es zum Pruefen im Klartext braucht; wer die Datenbank hat,
    # haette ohnehin die Passwort-Hashes.
    totp_secret = Column(String(64), nullable=True)
    totp_aktiv = Column(Integer, nullable=False, default=0)
    # Ersatzcodes fuer den zweiten Faktor, als JSON-Liste von Pruefwerten.
    # Ohne sie ist ein verlorenes Handy gleichbedeutend mit einem
    # verlorenen Konto - siehe kern/sicherheit.ersatzcodes_erzeugen().
    totp_ersatzcodes = Column(Text, nullable=True)
    # Zeitpunkt der letzten Passwortaenderung - fuer die Sicherheitsuebersicht.
    passwort_geaendert_am = Column(DateTime, nullable=True)
    # Hat der Willkommens-Bot diese Person schon begruesst?
    willkommen_gesendet_am = Column(DateTime, nullable=True)

    tasks = relationship("Task", back_populates="assignee",
                         foreign_keys="[Task.assignee_id]")
    created_tasks = relationship("Task", back_populates="creator",
                                 foreign_keys="[Task.creator_id]")
    preferences = relationship("UserPreference", back_populates="user",
                               uselist=False,
                               foreign_keys="[UserPreference.user_id]")

    @property
    def name(self) -> str:
        return f"{self.vorname} {self.nachname}".strip()


class UserSession(Base):
    """Serverseitig verfolgte Anmeldung - einsehbar und aus der Ferne beendbar."""
    __tablename__ = "user_sessions"
    id = Column(String(48), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(240), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    last_active = Column(DateTime, default=utcnow)
    revoked = Column(Integer, nullable=False, default=0)
    # Neu: Fingerabdruck des Browsers. Wandert eine Sitzungs-ID in einen
    # anderen Browser, passt er nicht mehr und die Sitzung wird verworfen.
    geraete_hash = Column(String(64), nullable=True)
    # 1 = "eingeloggt bleiben" (Standard). Bestehende Sitzungen bekommen
    # ebenfalls 1 - eine Aenderung an den Fristen darf niemanden hinauswerfen.
    dauerhaft = Column(Integer, nullable=False, default=1)


class Anmeldeversuch(Base):
    """Wer sich wann von wo angemeldet hat - oder es vergeblich versucht hat.

    V1 wusste nur, dass eine Anmeldung geklappt hat (ActivityLog). Bei einem
    Verdachtsfall liess sich nicht nachsehen, wie oft und von wo jemand
    vergeblich probiert hat.
    """
    __tablename__ = "anmeldeversuche"
    id = Column(Integer, primary_key=True)
    email = Column(String(160), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    erfolg = Column(Integer, nullable=False, default=0)
    grund = Column(String(60), nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(240), nullable=True)
    created_at = Column(DateTime, default=utcnow, index=True)


class PasswordResetToken(Base):
    """Einmal-Token fuers Zuruecksetzen. Gespeichert wird nur der SHA-256-Hash."""
    __tablename__ = "password_reset_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class EmailChangeRequest(Base):
    """Angefangener Wechsel der eigenen Adresse - gilt erst nach Bestaetigung."""
    __tablename__ = "email_change_requests"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    new_email = Column(String(160), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class UserPreference(Base):
    __tablename__ = "user_preferences"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    task_view_mode = Column(String(20), nullable=False, default="department")
    tutorial_erledigt = Column(Integer, nullable=False, default=0)
    tutorial_gefragt = Column(Integer, nullable=False, default=0)
    tutorial_version = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    # Neu: Startbereich des Dashboards und Kompaktansicht.
    startbereich = Column(String(40), nullable=True)
    kompakt = Column(Integer, nullable=False, default=0)
    # Der Umzugs-Rundgang wird getrennt vom Erst-Rundgang gezaehlt. Wer die
    # Plattform laengst kennt, braucht keine Einfuehrung, sehr wohl aber die
    # Liste dessen, was sich geaendert hat - und umgekehrt.
    neuerungen_version = Column(String(20), nullable=True)
    neuerungen_erledigt = Column(Integer, nullable=False, default=0)
    neuerungen_gefragt = Column(Integer, nullable=False, default=0)
    # "Ich nutze keinen Kalender": Ohne das stuende die Umzugsliste bei
    # jemandem, der nie ein Termin-Abo hatte, bis in alle Ewigkeit da.
    umzug_ohne_kalender = Column(Integer, nullable=False, default=0)
    # "Mein Passwort bleibt": Der Hinweis auf das Startpasswort ist ein
    # Rat, keine Vorschrift. Wer ihn einmal beantwortet hat, soll ihn
    # nicht bei jedem Anmelden wieder lesen - sonst liest man ihn
    # irgendwann gar nicht mehr, auch nicht den naechsten.
    startpasswort_egal = Column(Integer, nullable=False, default=0)
    # Wann diese Person das Dashboard zuletzt aus einer echten App heraus
    # geoeffnet hat (Startbildschirm statt Browser-Tab). Der Browser sagt uns
    # das selbst; wir merken es uns, weil die Frage "hat er es installiert?"
    # sonst bei jedem Aufruf neu und nur fuer DIESES Geraet zu beantworten
    # waere. Ein Zeitpunkt statt eines Hakens, damit man spaeter sehen kann,
    # ob es noch benutzt wird.
    als_app_am = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="preferences",
                        foreign_keys=[user_id])


#  Rollen, Abteilungen, Rechte
#  Die Rechtespalten werden nicht von Hand aufgezaehlt, sondern unten aus
#  PERM_KEYS angehaengt. Eine zweite, handgepflegte Liste war in V1 der Grund,
#  warum das Anlegen einer Rolle zeitweise mit einem Serverfehler abbrach.
class Role(Base):
    __tablename__ = "roles"
    key = Column(String(40), primary_key=True)
    label = Column(String(80), nullable=False)
    protected = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)
    # Neu: Rangfolge. Wer einen niedrigeren Rang hat, kann Personen mit
    # hoeherem Rang nicht bearbeiten - unabhaengig von den Einzelrechten.
    rang = Column(Integer, nullable=False, default=50)
    beschreibung = Column(Text, nullable=True)


class Department(Base):
    __tablename__ = "departments"
    key = Column(String(30), primary_key=True)
    label = Column(String(60), nullable=False)
    farbe = Column(String(7), nullable=False, default="#4A5568")
    beschreibung = Column(Text, nullable=True)
    reihenfolge = Column(Integer, nullable=False, default=100)
    aktiv = Column(Integer, nullable=False, default=1)
    geschuetzt = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)
    # Die drei abteilungseigenen Funktionen aus V1 - unveraendert, damit die
    # bestehenden Spalten weiterbenutzt werden.
    redaktionsplan = Column(Integer, nullable=False, default=0)
    ideensammlung = Column(Integer, nullable=False, default=0)
    bewerbungen_abteilung = Column(Integer, nullable=False, default=0)


class UserPermission(Base):
    """Ein Recht, das genau einer Person zusaetzlich gegeben oder ausdruecklich
    entzogen wird.

    Der Kern der besseren Rechteverteilung in V2. Bisher gab es nur zwei
    Achsen (Rolle, Abteilung), und beide gelten fuer Gruppen. Wollte man einer
    einzelnen Person das Kassenbuch geben, musste man entweder eine neue Rolle
    erfinden oder es gleich der halben AG geben.

    wert = 1 gibt frei, wert = 0 entzieht. Ein Entzug schlaegt alles andere -
    sonst liesse sich ein zu weit gefasstes Rollenrecht nicht mehr einfangen.
    """
    __tablename__ = "user_permissions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    perm = Column(String(60), nullable=False)
    wert = Column(Integer, nullable=False, default=1)
    notiz = Column(String(200), nullable=True)
    gesetzt_von = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "perm", name="uq_recht_pro_person"),)


#  Aufgaben
class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    titel = Column(String(160), nullable=False)
    beschreibung = Column(Text, nullable=True)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assignee_department = Column(String(30), nullable=True)
    task_department = Column(String(30), nullable=False, default="exekutive")
    deadline = Column(Date, nullable=True)
    priority = Column(String(20), nullable=False, default="mittel")
    status = Column(String(20), nullable=False, default="offen")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at = Column(DateTime, nullable=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reminder_sent_on = Column(Date, nullable=True)

    assignee = relationship("User", back_populates="tasks",
                            foreign_keys=[assignee_id])
    creator = relationship("User", back_populates="created_tasks",
                           foreign_keys=[creator_id])


class TaskChecklistItem(Base):
    __tablename__ = "task_checklist_items"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    text = Column(String(200), nullable=False)
    done = Column(Integer, nullable=False, default=0)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)


class TaskComment(Base):
    __tablename__ = "task_comments"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    user = relationship("User", foreign_keys=[user_id])


class Leistung(Base):
    """Dauerhafter Nachweis erbrachter Arbeit.

    Das Kernstueck des automatischen Scorings. In V1 wurde der Leadership-Wert
    aus der Aufgabentabelle gerechnet - loeschte jemand eine erledigte Aufgabe,
    sank sein Wert rueckwirkend, obwohl die Arbeit getan war. Das war der
    Fehlanreiz: aufraeumen wurde bestraft.

    Hier wird jede Erledigung einmal festgehalten und danach nie mehr
    angefasst. Die Zeile ueberlebt Papierkorb und endgueltiges Loeschen; sie
    haengt bewusst an KEINEM Fremdschluessel auf tasks.
    """
    __tablename__ = "leistungen"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    art = Column(String(30), nullable=False, index=True)   # aufgabe, treffen, ...
    quelle_id = Column(Integer, nullable=True)             # urspruengliche ID
    titel = Column(String(200), nullable=True)
    abteilung = Column(String(30), nullable=True)
    punkte = Column(Integer, nullable=False, default=1)
    zeitpunkt = Column(DateTime, nullable=False, default=utcnow, index=True)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        # Dieselbe Erledigung darf nicht zweimal zaehlen - etwa wenn eine
        # Aufgabe auf "offen" und wieder auf "erledigt" gesetzt wird.
        UniqueConstraint("user_id", "art", "quelle_id", name="uq_leistung_einmalig"),
    )


class LeadershipScore(Base):
    __tablename__ = "leadership_scores"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    attendance_score = Column(Integer, nullable=False, default=0)
    task_completion_score = Column(Integer, nullable=False, default=0)
    competition_score = Column(Integer, nullable=False, default=0)
    project_activity_score = Column(Integer, nullable=False, default=0)
    leadership_potential = Column(String(20), nullable=False, default="developing")
    recommended_for = Column(Text, nullable=True)
    last_updated = Column(DateTime, default=utcnow, onupdate=utcnow)
    # Neu: Gesamtwert und Verlaesslichkeit als eigene Spalten, damit sich
    # danach sortieren laesst, ohne alles neu zu rechnen.
    gesamt = Column(Integer, nullable=False, default=0)
    zuverlaessigkeit = Column(Integer, nullable=False, default=0)
    initiative = Column(Integer, nullable=False, default=0)


class SuccessionCandidate(Base):
    __tablename__ = "succession_candidates"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    position = Column(String(80), nullable=False)
    ranking = Column(Integer, nullable=True)
    confidence = Column(Integer, nullable=True)
    readiness_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


#  Bewerbungen
class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True)
    vorname = Column(String(80), nullable=False)
    nachname = Column(String(80), nullable=False)
    klasse = Column(String(40), nullable=False)
    email = Column(String(160), nullable=False)
    telefonnummer = Column(String(40), nullable=False)
    motivation = Column(Text, nullable=False)
    interessen = Column(Text, nullable=False)
    vorwissen = Column(Text, nullable=True)
    department = Column(String(30), nullable=True, default=None)
    status = Column(String(20), nullable=False, default="neu")
    email_sent = Column(Integer, nullable=False, default=0)
    # Wann zuletzt daran erinnert wurde, dass diese Bewerbung noch wartet.
    erinnert_am = Column(Date, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class ApplicationReview(Base):
    __tablename__ = "application_reviews"
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id"),
                            nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    bewertung = Column(Integer, nullable=False, default=3)
    notiz = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", foreign_keys=[user_id])
    __table_args__ = (UniqueConstraint("application_id", "user_id",
                                       name="uq_review_pro_person"),)


#  Redaktionsplan
class ContentItem(Base):
    __tablename__ = "content_items"
    id = Column(Integer, primary_key=True)
    abteilung = Column(String(30), nullable=False, index=True)
    titel = Column(String(160), nullable=False)
    kanal = Column(String(20), nullable=False, default="sonstiges")
    datum = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default="idee")
    verantwortlich_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notiz = Column(Text, nullable=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    verantwortlich = relationship("User", foreign_keys=[verantwortlich_id])


class ContentAttachment(Base):
    __tablename__ = "content_attachments"
    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("content_items.id"),
                     nullable=False, index=True)
    dateiname = Column(String(160), nullable=False)
    speichername = Column(String(80), nullable=False)
    groesse = Column(Integer, nullable=False, default=0)
    hochgeladen_von = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)


#  Termine, Treffen, Anwesenheit
class Meeting(Base):
    __tablename__ = "meetings"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    date = Column(Date, default=date.today)
    # An welchem Tag zuletzt erinnert wurde - verhindert, dass ein Neustart
    # dieselbe Erinnerung ein zweites Mal schickt.
    erinnert_am = Column(Date, nullable=True)
    protocol = Column(Text, nullable=True)
    attendees = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    # An welchem Tag die Zu- und Absagen zu diesem Treffen in den
    # Leadership-Wert eingerechnet wurden. Ohne diesen Merker liefe die
    # Abrechnung jede Nacht erneut - und wer eine Woche spaeter noch
    # nachtraeglich als anwesend eingetragen wird, bekaeme seine Punkte
    # zweimal. Steht am Treffen und nicht im Arbeitsspeicher, damit ein
    # Neustart nichts zurueckdreht.
    leistung_verrechnet = Column(Date, nullable=True)


class MeetingRueckmeldung(Base):
    """Zu- oder Absage zu einem Treffen - vorher, nicht hinterher.

    Anwesenheit (Attendance) wird nach dem Treffen erfasst und zaehlt fuer
    den Leadership-Wert. Das hier ist etwas anderes: die Ansage vorher, damit
    man planen kann. Beides getrennt zu halten ist Absicht - wer zusagt und
    dann doch nicht kommt, war nicht da, und wer absagt und trotzdem kommt,
    war da.
    """
    __tablename__ = "meeting_rueckmeldungen"
    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False,
                        index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # "ja" oder "nein". Kein "vielleicht": Damit kann die Planung nichts
    # anfangen, und es ist die bequeme Antwort, die dann alle waehlen.
    antwort = Column(String(10), nullable=False, default="ja")
    grund = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class MeetingPunkt(Base):
    """Ein Punkt fuer die Tagesordnung, vorher eingetragen.

    Bisher gab es nur das Protokoll - also das, was hinterher aufgeschrieben
    wird. Wer vorher etwas besprechen wollte, musste daran denken und es im
    Treffen von sich aus ansprechen.
    """
    __tablename__ = "meeting_punkte"
    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False,
                        index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    text = Column(String(300), nullable=False)
    erledigt = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)


class Attendance(Base):
    __tablename__ = "attendance"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=True)
    event_type = Column(String(80), nullable=False)
    event_date = Column(Date, nullable=False, default=date.today)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String(200), nullable=True)
    start_date = Column(Date, nullable=False, default=date.today)
    start_time = Column(String(5), nullable=True)
    end_time = Column(String(5), nullable=True)
    end_date = Column(Date, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    target_type = Column(String(20), nullable=False, default="alle")
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    target_department = Column(String(30), nullable=True)
    erinnert_am = Column(Date, nullable=True)

    targets = relationship("CalendarEventTarget", cascade="all, delete-orphan",
                           lazy="selectin", back_populates="event")


class CalendarEventTarget(Base):
    __tablename__ = "calendar_event_targets"
    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("calendar_events.id"),
                      nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    department = Column(String(30), nullable=True)

    event = relationship("CalendarEvent", back_populates="targets")


#  Projekte und Wettbewerbe
class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="planung")
    lead_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    deadline = Column(Date, nullable=True)
    progress = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ProjectTeamMember(Base):
    __tablename__ = "project_team_members"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(80), nullable=True)
    joined_at = Column(DateTime, default=utcnow)


class Competition(Base):
    __tablename__ = "competitions"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    date = Column(Date, nullable=True)
    location = Column(String(200), nullable=True)
    organizer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), nullable=False, default="geplant")
    created_at = Column(DateTime, default=utcnow)


class CompetitionParticipant(Base):
    __tablename__ = "competition_participants"
    id = Column(Integer, primary_key=True)
    competition_id = Column(Integer, ForeignKey("competitions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    team_name = Column(String(200), nullable=True)
    placement = Column(Integer, nullable=True)
    points = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


#  Kommunikation
class ContactMessage(Base):
    __tablename__ = "contact_messages"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    email = Column(String(160), nullable=False)
    message = Column(Text, nullable=False)
    reply = Column(Text, nullable=True)
    replied_by = Column(Integer, nullable=True)
    replied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    subject = Column(String(160), nullable=False)
    message = Column(Text, nullable=False)
    attachment_filename = Column(String(120), nullable=True)
    reply = Column(Text, nullable=True)
    replied_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    replied_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="offen")
    created_at = Column(DateTime, default=utcnow)
    sender = relationship("User", foreign_keys=[user_id])
    responder = relationship("User", foreign_keys=[replied_by])


class SupportMessage(Base):
    __tablename__ = "support_messages"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("support_tickets.id"),
                       nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    attachment_filename = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    sender = relationship("User", foreign_keys=[sender_id])


class DirectMessage(Base):
    __tablename__ = "direct_messages"
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subject = Column(String(160), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    sender = relationship("User", foreign_keys=[sender_id])


class DirectMessageRecipient(Base):
    __tablename__ = "direct_message_recipients"
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("direct_messages.id"),
                        nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    read_at = Column(DateTime, nullable=True)
    message = relationship("DirectMessage", foreign_keys=[message_id])


class NotificationPreference(Base):
    """Zustellwege je Person. Das Thema (topic) ist der ntfy-Kanal.

    Diese Tabelle wird unveraendert aus V1 uebernommen - deshalb behalten alle
    Mitglieder ihr eingerichtetes ntfy-Thema und muessen nichts neu einrichten.
    """
    __tablename__ = "notification_preferences"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    topic = Column(String(64), unique=True, nullable=False)
    enabled = Column(Integer, nullable=False, default=1)
    tasks = Column(Integer, nullable=False, default=1)
    applications = Column(Integer, nullable=False, default=1)
    messages = Column(Integer, nullable=False, default=1)
    support = Column(Integer, nullable=False, default=1)
    direct = Column(Integer, nullable=False, default=1)
    # Stoerungsmeldungen (Sicherung gescheitert, WhatsApp abgemeldet).
    # Verschickt werden sie nur an den Vorstand - siehe kern/stoerung.py.
    system = Column(Integer, nullable=False, default=1)
    email = Column(Integer, nullable=False, default=1)
    webpush = Column(Integer, nullable=False, default=1)
    ntfy = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=utcnow)
    # Ruhezeiten gab es einmal; sie sind auf Wunsch wieder abgeschafft worden
    # (August 2026). Die Spalten bleiben stehen: Loeschen brauchte in SQLite
    # einen Tabellenumbau, und die Regel dieses Projekts ist, dass eine
    # Migration nur hinzufuegt. Gelesen werden sie nirgends mehr.
    ruhe_von = Column(String(5), nullable=True)   # ungenutzt
    ruhe_bis = Column(String(5), nullable=True)   # ungenutzt


class PushSubscription(Base):
    """Ein Geraet, das Web-Push empfangen darf. Bleibt aus V1 erhalten."""
    __tablename__ = "push_subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    endpoint = Column(Text, nullable=False, unique=True)
    p256dh = Column(String(200), nullable=False)
    auth = Column(String(100), nullable=False)
    geraet = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    last_ok_at = Column(DateTime, nullable=True)
    # Von welcher Adresse aus angemeldet - "website" oder "dashboard".
    # Beide koennen sich anmelden, damit es keine Rolle spielt, welche der
    # beiden Seiten jemand auf dem Startbildschirm liegen hat.
    ursprung = Column(String(16), nullable=True)
    # Kennung des Geraets, geteilt ueber beide Adressen (Cookie auf der
    # gemeinsamen Domain). Sie verhindert, dass dasselbe Handy jede Meldung
    # zweimal bekommt, nur weil beide Seiten angemeldet sind.
    geraete_id = Column(String(40), nullable=True, index=True)


class DeliveryLog(Base):
    """Was tatsaechlich rausging - und was nicht."""
    __tablename__ = "delivery_log"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=utcnow, index=True)
    kanal = Column(String(16), nullable=False)      # push | email | whatsapp
    ziel = Column(String(160), nullable=False)
    betreff = Column(String(200), nullable=True)
    erfolg = Column(Integer, nullable=False, default=0)
    fehler = Column(String(300), nullable=True)
    anlass = Column(String(40), nullable=True)


class EmailTemplate(Base):
    __tablename__ = "email_templates"
    key = Column(String(60), primary_key=True)
    subject = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)


class WhatsAppNachricht(Base):
    """Ausgangskorb des WhatsApp-Bots.

    Bewusst eine eigene Tabelle statt eines Direktversands: Der Versand kann
    scheitern (Netz weg, Kontingent leer, falsche Nummer). Steht die Nachricht
    im Korb, geht sie nicht verloren, sondern wird erneut versucht - und man
    sieht im Dashboard, was offen ist.
    """
    __tablename__ = "whatsapp_nachrichten"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    nummer = Column(String(40), nullable=False)
    name = Column(String(160), nullable=True)
    text = Column(Text, nullable=False)
    anlass = Column(String(40), nullable=False, default="willkommen")
    status = Column(String(20), nullable=False, default="offen", index=True)
    versuche = Column(Integer, nullable=False, default=0)
    fehler = Column(String(300), nullable=True)
    gesendet_am = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, index=True)

    empfaenger = relationship("User", foreign_keys=[user_id])


#  Kasse
class Buchung(Base):
    __tablename__ = "kassenbuch"
    id = Column(Integer, primary_key=True)
    datum = Column(Date, nullable=False, default=date.today, index=True)
    zweck = Column(String(200), nullable=False)
    betrag_cent = Column(Integer, nullable=False)
    kategorie = Column(String(40), nullable=False, default="sonstiges")
    abteilung = Column(String(30), nullable=True)
    beleg = Column(String(60), nullable=True)
    notiz = Column(Text, nullable=True)
    erfasser_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    dauerauftrag_id = Column(Integer, ForeignKey("kassen_dauerauftraege.id"),
                             nullable=True)
    created_at = Column(DateTime, default=utcnow)

    erfasser = relationship("User", foreign_keys=[erfasser_id])


class Budget(Base):
    __tablename__ = "kassen_budgets"
    id = Column(Integer, primary_key=True)
    abteilung = Column(String(30), nullable=False, index=True)
    bezeichnung = Column(String(120), nullable=False)
    von = Column(Date, nullable=False)
    bis = Column(Date, nullable=False)
    betrag_cent = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class Dauerauftrag(Base):
    __tablename__ = "kassen_dauerauftraege"
    id = Column(Integer, primary_key=True)
    zweck = Column(String(200), nullable=False)
    betrag_cent = Column(Integer, nullable=False)
    kategorie = Column(String(40), nullable=False, default="sonstiges")
    abteilung = Column(String(30), nullable=True)
    rhythmus = Column(String(20), nullable=False, default="monatlich")
    start_datum = Column(Date, nullable=False)
    ausfuehrungen = Column(Integer, nullable=False, default=0)
    naechste_faelligkeit = Column(Date, nullable=False, index=True)
    aktiv = Column(Integer, nullable=False, default=1)
    letzte_ausfuehrung = Column(Date, nullable=True)
    angelegt_von = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)


#  System
class AppSetting(Base):
    __tablename__ = "app_settings"
    key = Column(String(60), primary_key=True)
    value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ActivityLog(Base):
    __tablename__ = "activity_log"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    event_type = Column(String(40), nullable=False)
    # Text statt String(200): Bei "rolle_rechte_geaendert" steht hier die
    # ganze Rechteliste, und die waechst mit jedem neuen Recht. SQLite hat
    # die Laenge nie geprueft, Postgres weist sie ab.
    value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class TrashItem(Base):
    """Papierkorb: haelt Geloeschtes eine Zeit lang zum Wiederherstellen."""
    __tablename__ = "trash_items"
    id = Column(Integer, primary_key=True)
    entity_type = Column(String(40), nullable=False, index=True)
    entity_id = Column(Integer, nullable=True)
    label = Column(String(240), nullable=False)
    payload = Column(Text, nullable=False)
    children = Column(Text, nullable=True)
    deleted_by = Column(Integer, nullable=True)
    deleted_at = Column(DateTime, default=utcnow, index=True)


class Inhalt(Base):
    """Ein anpassbarer Block der oeffentlichen Startseite.

    Anlass: Die Sektion "Was wir konkret machen" stand fest im Quelltext. Eine
    neue Aktivitaet aufzunehmen hiess: Code aendern, Server neu starten - also
    genau das, was der CTO nicht bei jeder Kleinigkeit machen will.

    bereich   welcher Abschnitt der Seite:
              "portfolio"  was die AG schon gemacht hat (mit Zeitraum/Ergebnis)
              "angebot"    womit wir uns beschaeftigen
              "vorteile"   was man mitnimmt
              "stufen"     der Weg vom Einstieg ins Core-Team
    zeitraum  nur beim Portfolio: "Schuljahr 2025/26", "Herbst 2025"
    ergebnis  nur beim Portfolio: "2. Platz im Landesfinale"
    farbe     Randfarbe der Karte
    """
    __tablename__ = "seiten_inhalte"
    id = Column(Integer, primary_key=True)
    bereich = Column(String(30), nullable=False, index=True, default="portfolio")
    titel = Column(String(160), nullable=False)
    text = Column(Text, nullable=True)
    # Bleibt als Spalte bestehen, wird aber nicht mehr benutzt: die Startseite
    # kommt ohne Bildzeichen aus. Eine Spalte zu loeschen waere mehr Risiko
    # als Nutzen - sie stoert niemanden.
    icon = Column(String(16), nullable=True)
    farbe = Column(String(7), nullable=True)
    zeitraum = Column(String(60), nullable=True)
    ergebnis = Column(String(120), nullable=True)
    reihenfolge = Column(Integer, nullable=False, default=100)
    aktiv = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    geaendert_von = Column(Integer, ForeignKey("users.id"), nullable=True)


# Ein Index, der in V1 fehlte: die Aufgabenliste filtert praktisch immer nach
# Status und Abteilung. Bei wenigen hundert Zeilen faellt das nicht auf, bei
# ein paar tausend schon.
Index("ix_tasks_status_abteilung", Task.status, Task.task_department)
Index("ix_leistung_user_art", Leistung.user_id, Leistung.art)
