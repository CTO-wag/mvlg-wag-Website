"""Papierkorb: haelt Geloeschtes eine Zeit lang zum Wiederherstellen.

Bewusst ein eigener Speicher statt einer „geloescht“-Markierung in jeder
Tabelle: so kann keine der vielen bestehenden Abfragen versehentlich
Geloeschtes mit ausgeben. Der Datensatz wird als JSON abgelegt und beim
Wiederherstellen daraus neu angelegt - samt der Kinder, die daran hingen
(Checklistenpunkte, Kommentare, Anhaenge).

Was der Papierkorb NICHT anfasst: den Leistungsnachweis. Wer eine erledigte
Aufgabe loescht, behaelt seine Punkte - siehe kern/leistung.py.
"""

import json
from datetime import date, datetime, timedelta

from kern.einstellungen import TRASH_RETENTION_DAYS
from kern.datenbank import sitzung
from kern.modelle import (
    Application, ApplicationReview, Attendance, Buchung, CalendarEvent,
    CalendarEventTarget, Competition, CompetitionParticipant, ContactMessage,
    ContentAttachment, ContentItem, DirectMessage, Meeting,
    MeetingPunkt, MeetingRueckmeldung, Project,
    ProjectTeamMember, SupportMessage, SupportTicket, Task, TaskChecklistItem,
    TaskComment, TrashItem, User,
)
from kern.text import utcnow

# Was in den Papierkorb wandern kann: Kennung -> (Modell, Anzeigename).
MODELLE = {
    "task": (Task, "Aufgabe"),
    "application": (Application, "Bewerbung"),
    "meeting": (Meeting, "AG-Treffen"),
    "project": (Project, "Projekt"),
    "competition": (Competition, "Wettbewerb"),
    "calendar_event": (CalendarEvent, "Termin"),
    "content_item": (ContentItem, "Redaktionseintrag"),
    "attendance": (Attendance, "Anwesenheit"),
    "contact_message": (ContactMessage, "Kontaktanfrage"),
    "support_ticket": (SupportTicket, "Support-Anfrage"),
    "direct_message": (DirectMessage, "Nachricht"),
    "buchung": (Buchung, "Buchung"),
    "user": (User, "Konto"),
}

# Kinder, die mitgehen und mit zurueckkommen: Elternkennung -> [(Modell, Spalte)]
KINDER = {
    "task": [(TaskChecklistItem, "task_id"), (TaskComment, "task_id")],
    "application": [(ApplicationReview, "application_id")],
    "project": [(ProjectTeamMember, "project_id")],
    "competition": [(CompetitionParticipant, "competition_id")],
    "calendar_event": [(CalendarEventTarget, "event_id")],
    "content_item": [(ContentAttachment, "item_id")],
    "support_ticket": [(SupportMessage, "ticket_id")],
    # Ohne diese Zeile bricht das Loeschen eines Treffens mit einem
    # Fremdschluessel-Fehler ab, sobald jemand zu- oder abgesagt oder einen
    # Punkt eingetragen hat.
    "meeting": [(MeetingRueckmeldung, "meeting_id"), (MeetingPunkt, "meeting_id")],
}


def _als_dict(objekt) -> dict:
    """Einen Datensatz in einfache Werte umwandeln - JSON-tauglich."""
    daten = {}
    for spalte in objekt.__table__.columns:
        wert = getattr(objekt, spalte.name, None)
        if isinstance(wert, (datetime, date)):
            wert = wert.isoformat()
        daten[spalte.name] = wert
    return daten


def _aus_dict(modell, daten: dict):
    """Aus gespeicherten Werten wieder einen Datensatz machen."""
    from sqlalchemy import Date, DateTime
    objekt = modell()
    for spalte in modell.__table__.columns:
        if spalte.name not in daten:
            continue
        wert = daten[spalte.name]
        if wert is not None and isinstance(spalte.type, DateTime):
            try:
                wert = datetime.fromisoformat(wert)
            except (TypeError, ValueError):
                wert = None
        elif wert is not None and isinstance(spalte.type, Date):
            try:
                wert = date.fromisoformat(wert)
            except (TypeError, ValueError):
                wert = None
        setattr(objekt, spalte.name, wert)
    return objekt


def hinein(db, art: str, objekt, von_id=None, beschriftung: str = None) -> TrashItem:
    """Einen Datensatz samt Kindern in den Papierkorb legen und loeschen."""
    if art not in MODELLE:
        raise ValueError(f"Unbekannte Art: {art}")
    modell, name = MODELLE[art]

    kinder = {}
    for kind_modell, spalte in KINDER.get(art, []):
        zeilen = db.query(kind_modell).filter(
            getattr(kind_modell, spalte) == objekt.id).all()
        if zeilen:
            kinder[kind_modell.__tablename__] = [_als_dict(z) for z in zeilen]
            for zeile in zeilen:
                db.delete(zeile)
    if kinder:
        # Die Kinder muessen WIRKLICH weg sein, bevor der Elterndatensatz
        # geloescht wird. Ohne dieses flush() entscheidet SQLAlchemy selbst
        # ueber die Reihenfolge - und weil zwischen den Tabellen nur ein
        # Fremdschluessel steht und keine ORM-Beziehung, kam der Elternteil
        # zuerst dran: "FOREIGN KEY constraint failed". Ein Projekt mit
        # Team oder ein Wettbewerb mit Teilnehmern liess sich dadurch
        # ueberhaupt nicht loeschen.
        db.flush()

    eintrag = TrashItem(
        entity_type=art, entity_id=objekt.id,
        label=(beschriftung or _beschriftung(art, objekt))[:240],
        payload=json.dumps(_als_dict(objekt), ensure_ascii=False),
        children=json.dumps(kinder, ensure_ascii=False) if kinder else None,
        deleted_by=von_id)
    db.add(eintrag)
    db.delete(objekt)
    return eintrag


def _beschriftung(art: str, objekt) -> str:
    for feld in ("titel", "title", "subject", "zweck", "bezeichnung", "name"):
        wert = getattr(objekt, feld, None)
        if wert:
            return str(wert)
    if art == "user":
        return f"{objekt.vorname} {objekt.nachname}"
    if art == "application":
        return f"{objekt.vorname} {objekt.nachname}"
    return f"{MODELLE[art][1]} #{objekt.id}"


def zurueck(db, trash_id: int) -> tuple:
    """(geklappt, Meldung). Stellt einen Eintrag samt Kindern wieder her."""
    eintrag = db.get(TrashItem, trash_id)
    if not eintrag:
        return False, "Dieser Eintrag ist nicht mehr da."
    if eintrag.entity_type not in MODELLE:
        return False, "Diese Art lässt sich nicht wiederherstellen."

    modell, name = MODELLE[eintrag.entity_type]
    try:
        daten = json.loads(eintrag.payload)
    except (TypeError, ValueError):
        return False, "Die gespeicherten Daten sind unleserlich."

    # Steht die alte ID inzwischen wieder in Gebrauch, wird eine neue vergeben.
    alte_id = daten.get("id")
    if alte_id and db.get(modell, alte_id):
        daten.pop("id", None)
        alte_id = None

    objekt = _aus_dict(modell, daten)
    db.add(objekt)
    db.flush()          # ID besorgen, bevor die Kinder daran gehaengt werden

    if eintrag.children:
        try:
            kinder = json.loads(eintrag.children)
        except (TypeError, ValueError):
            kinder = {}
        for kind_modell, spalte in KINDER.get(eintrag.entity_type, []):
            for zeile in kinder.get(kind_modell.__tablename__, []):
                zeile = dict(zeile)
                zeile.pop("id", None)
                zeile[spalte] = objekt.id
                db.add(_aus_dict(kind_modell, zeile))

    db.delete(eintrag)
    return True, f"{name} „{eintrag.label}“ ist wieder da."


def endgueltig(db, trash_id: int) -> bool:
    eintrag = db.get(TrashItem, trash_id)
    if not eintrag:
        return False
    db.delete(eintrag)
    return True


def inhalt(db, grenze: int = 200) -> list:
    return (db.query(TrashItem).order_by(TrashItem.deleted_at.desc())
            .limit(grenze).all())


def aufraeumen(tage: int = None) -> int:
    """Alles endgueltig entfernen, was laenger als die Frist im Korb liegt."""
    tage = TRASH_RETENTION_DAYS if tage is None else tage
    with sitzung() as db:
        anzahl = db.query(TrashItem).filter(
            TrashItem.deleted_at < utcnow() - timedelta(days=tage)
        ).delete(synchronize_session=False)
        db.commit()
        return anzahl


def konto_daten_loesen(db, ziel: User) -> None:
    """Verweise auf ein Konto loesen, bevor es geloescht wird.

    Ohne das schlagen die Fremdschluessel zu, und was daran haengt, waere
    verloren: Aufgaben, die die Person erstellt hat, Kommentare, Buchungen.
    Die Sachen bleiben, nur der Verweis auf die Person faellt weg.
    """
    db.query(Task).filter(Task.assignee_id == ziel.id).update(
        {"assignee_id": None}, synchronize_session=False)
    db.query(Task).filter(Task.creator_id == ziel.id).update(
        {"creator_id": None}, synchronize_session=False)
    db.query(ContentItem).filter(ContentItem.verantwortlich_id == ziel.id).update(
        {"verantwortlich_id": None}, synchronize_session=False)
    db.query(ContentItem).filter(ContentItem.creator_id == ziel.id).update(
        {"creator_id": None}, synchronize_session=False)
    db.query(Buchung).filter(Buchung.erfasser_id == ziel.id).update(
        {"erfasser_id": None}, synchronize_session=False)
    db.query(Project).filter(Project.lead_id == ziel.id).update(
        {"lead_id": None}, synchronize_session=False)
    db.query(Competition).filter(Competition.organizer_id == ziel.id).update(
        {"organizer_id": None}, synchronize_session=False)
    db.query(CalendarEvent).filter(CalendarEvent.created_by == ziel.id).update(
        {"created_by": None}, synchronize_session=False)

    # Was ohne die Person keinen Sinn mehr ergibt, geht mit.
    from kern.modelle import (
        ActivityLog, DirectMessageRecipient, Leistung, NotificationPreference,
        PasswordResetToken, PushSubscription, UserPermission, UserPreference,
        UserSession, WhatsAppNachricht,
    )
    for modell in (UserSession, UserPreference, NotificationPreference,
                   PushSubscription, PasswordResetToken, UserPermission,
                   ActivityLog, Leistung, WhatsAppNachricht):
        db.query(modell).filter(modell.user_id == ziel.id).delete(
            synchronize_session=False)
    db.query(DirectMessageRecipient).filter(
        DirectMessageRecipient.user_id == ziel.id).delete(synchronize_session=False)
    db.query(ApplicationReview).filter(
        ApplicationReview.user_id == ziel.id).delete(synchronize_session=False)
    db.query(TaskComment).filter(TaskComment.user_id == ziel.id).delete(
        synchronize_session=False)
    db.query(Attendance).filter(Attendance.user_id == ziel.id).delete(
        synchronize_session=False)
    db.query(ProjectTeamMember).filter(
        ProjectTeamMember.user_id == ziel.id).delete(synchronize_session=False)
    db.query(CompetitionParticipant).filter(
        CompetitionParticipant.user_id == ziel.id).delete(synchronize_session=False)
    db.query(CalendarEventTarget).filter(
        CalendarEventTarget.user_id == ziel.id).delete(synchronize_session=False)
    from kern.modelle import LeadershipScore, SuccessionCandidate
    db.query(LeadershipScore).filter(
        LeadershipScore.user_id == ziel.id).delete(synchronize_session=False)
    db.query(SuccessionCandidate).filter(
        SuccessionCandidate.user_id == ziel.id).delete(synchronize_session=False)
    db.query(SupportMessage).filter(
        SupportMessage.sender_id == ziel.id).delete(synchronize_session=False)
    db.query(SupportTicket).filter(
        SupportTicket.user_id == ziel.id).delete(synchronize_session=False)
