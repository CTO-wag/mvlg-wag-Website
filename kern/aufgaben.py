"""Aufgaben: anlegen, zuweisen, erinnern.

Eine Aufgabe gehoert entweder einer Person oder einer Abteilung, nie
beidem. Erinnert wird einmal taeglich, und je Aufgabe hoechstens einmal am
Tag - der Vermerk dafuer steht an der Aufgabe, nicht im Arbeitsspeicher.
"""

from datetime import date, timedelta

from kern.datenbank import sitzung
from kern.modelle import Task, TaskChecklistItem, TaskComment, User
from kern.rechte import (
    abteilungs_keys, hat_recht, rechte_von, zustaendige_abteilungen,
)
from kern.text import utcnow

STATUS_REIHE = ("offen", "in_bearbeitung", "erledigt")


def leitungs_abteilungen(user, db=None) -> tuple:
    """Abteilungen, in die jemand als Leitung hineinsehen darf.
    Die Exekutive ist bewusst nicht dabei."""
    if not user or not hat_recht(user, "aufgaben_all", db):
        return ()
    return tuple(d for d in zustaendige_abteilungen(user) if d != "exekutive")


def sichtbar_filter(user, db=None):
    """Die Sichtbarkeitsregel als Bedingung fuer eine Abfrage."""
    bedingung = (Task.creator_id == user.id) | (Task.assignee_id == user.id)
    eigene = zustaendige_abteilungen(user)
    if eigene:
        bedingung = bedingung | Task.assignee_department.in_(eigene)
    leitung = leitungs_abteilungen(user, db)
    if leitung:
        bedingung = bedingung | Task.task_department.in_(leitung)
    return bedingung


def darf_sehen(user, task, db=None) -> bool:
    if not user or not task:
        return False
    if task.creator_id == user.id or task.assignee_id == user.id:
        return True
    if task.assignee_department and task.assignee_department in zustaendige_abteilungen(user):
        return True
    return bool(task.task_department) and task.task_department in leitungs_abteilungen(user, db)


def darf_aendern(user, task, db=None) -> bool:
    """Wer sie nicht sehen darf, darf sie auch nicht anfassen.

    Das steht ganz vorn, damit ein direkt abgeschicktes Formular nicht an der
    Ansicht vorbei doch noch eine fremde Aufgabe erwischt.
    """
    if not darf_sehen(user, task, db):
        return False
    rechte = rechte_von(user, db)
    if rechte.get("aufgaben_alle_abteilungen"):
        return True
    if rechte.get("aufgaben_all"):
        return (task.task_department in zustaendige_abteilungen(user)
                or task.creator_id == user.id)
    return (task.assignee_id == user.id
            or task.assignee_department == user.department
            or task.creator_id == user.id)


# Wie lange eine erledigte Aufgabe in der Liste stehen bleibt. Danach ist sie
# nicht geloescht - sie wird nur nicht mehr mitgeschleppt. Ohne diese Grenze
# waechst die Seite ueber ein Schuljahr auf hunderte abgehakte Zeilen an, die
# niemand mehr liest, aber jeder Aufruf mitlaedt.
ERLEDIGT_SICHTBAR_TAGE = 30


def liste(db, user, ansicht: str = None, erledigt_tage: int = ERLEDIGT_SICHTBAR_TAGE
          ) -> list:
    """Die Aufgabenliste einer Person - immer nur das Sichtbare.

    "persoenlich" zeigt wirklich nur das eigene, "abteilung" alles Sichtbare.
    Der alte dritte Modus "all" bleibt als Wert zulaessig (er kann in
    gespeicherten Einstellungen stehen) und verhaelt sich wie "abteilung":
    seit die Sichtbarkeitsregel fuer jede Rolle gilt, gaebe es darin nichts
    zusaetzlich zu sehen.

    `erledigt_tage=0` holt auch die alten Erledigten - dafuer gibt es in der
    Oberflaeche den Knopf "Auch ältere zeigen".
    """
    if not user:
        return []
    abfrage = db.query(Task).filter(sichtbar_filter(user, db))
    if ansicht in ("personal", "persoenlich"):
        abfrage = abfrage.filter(Task.assignee_id == user.id)
    if erledigt_tage:
        abfrage = abfrage.filter(_frisch_genug(erledigt_tage))
    return abfrage.order_by(Task.deadline.is_(None), Task.deadline,
                            Task.priority.desc(), Task.id.desc()).all()


def _frisch_genug(tage: int):
    """Bedingung: offen - oder erst kuerzlich erledigt.

    Bei Aufgaben aus V1 kann completed_at leer sein; dann zaehlt, wann sie
    zuletzt angefasst wurden. Sonst verschwaenden alte Erledigte sofort aus
    der Ansicht, und das sieht aus wie Datenverlust.
    """
    from sqlalchemy import func, or_
    grenze = utcnow() - timedelta(days=tage)
    return or_(Task.status != "erledigt",
               func.coalesce(Task.completed_at, Task.updated_at,
                             Task.created_at) >= grenze)


def aeltere_erledigte(db, user, ansicht: str = None,
                      tage: int = ERLEDIGT_SICHTBAR_TAGE) -> int:
    """Wie viele erledigte Aufgaben gerade nicht mitgezeigt werden."""
    from sqlalchemy import func, not_
    if not user:
        return 0
    abfrage = db.query(func.count(Task.id)).filter(sichtbar_filter(user, db))
    if ansicht in ("personal", "persoenlich"):
        abfrage = abfrage.filter(Task.assignee_id == user.id)
    return abfrage.filter(not_(_frisch_genug(tage))).scalar() or 0


def zuteilbare_personen(db, user):
    """Wen jemand als Verantwortliche auswaehlen darf."""
    abfrage = db.query(User).filter(User.status == "aktiv").order_by(
        User.vorname, User.nachname)
    if not hat_recht(user, "aufgaben_all", db):
        abfrage = abfrage.filter(User.department.in_(zustaendige_abteilungen(user)))
    return abfrage.all()


def zuteilbare_abteilungen(user, db=None) -> tuple:
    if hat_recht(user, "aufgaben_all", db):
        return abteilungs_keys()
    return zustaendige_abteilungen(user)


def nach_status(aufgaben) -> list:
    """Gruppiert fuer die Anzeige: offen, in Bearbeitung, erledigt."""
    gruppen = []
    for status in STATUS_REIHE:
        eintraege = [t for t in aufgaben if t.status == status]
        eintraege.sort(key=lambda t: (
            t.assignee.vorname if t.assignee else (t.assignee_department or "zzz"),
            t.titel or ""))
        if eintraege:
            gruppen.append((status, eintraege))
    return gruppen


def kennzahlen(aufgaben) -> dict:
    heute = date.today()
    offen = [t for t in aufgaben if t.status != "erledigt"]
    return {
        "gesamt": len(aufgaben),
        "offen": len(offen),
        "in_arbeit": len([t for t in aufgaben if t.status == "in_bearbeitung"]),
        "erledigt": len([t for t in aufgaben if t.status == "erledigt"]),
        "ueberfaellig": len([t for t in offen if t.deadline and t.deadline < heute]),
        "heute": len([t for t in offen if t.deadline == heute]),
        "diese_woche": len([t for t in offen if t.deadline
                            and heute <= t.deadline <= heute + timedelta(days=7)]),
    }


def checklisten(db, aufgaben) -> dict:
    """Checklisten aller Aufgaben in einer Abfrage statt einer je Aufgabe."""
    ids = [t.id for t in aufgaben]
    if not ids:
        return {}
    ergebnis = {}
    for punkt in (db.query(TaskChecklistItem)
                  .filter(TaskChecklistItem.task_id.in_(ids))
                  .order_by(TaskChecklistItem.position, TaskChecklistItem.id).all()):
        ergebnis.setdefault(punkt.task_id, []).append(punkt)
    return ergebnis


def kommentare(db, aufgaben) -> dict:
    ids = [t.id for t in aufgaben]
    if not ids:
        return {}
    ergebnis = {}
    for eintrag in (db.query(TaskComment)
                    .filter(TaskComment.task_id.in_(ids))
                    .order_by(TaskComment.created_at).all()):
        ergebnis.setdefault(eintrag.task_id, []).append(eintrag)
    return ergebnis


#  Fristerinnerungen
def _empfaenger(db, task) -> list:
    """Wen eine Erinnerung angeht: die zugeteilte Person oder die Abteilung."""
    if task.assignee_id:
        person = db.get(User, task.assignee_id)
        return [person] if person and person.status == "aktiv" else []
    if task.assignee_department:
        return db.query(User).filter(
            User.department == task.assignee_department,
            User.status == "aktiv").all()
    return []


def erinnerungen_verschicken(heute: date = None) -> int:
    """Einmal taeglich: an alles erinnern, was heute oder morgen faellig ist.

    Der Vermerk am Datensatz verhindert, dass bei mehreren Laeufen am selben
    Tag - etwa nach einem Neustart - dieselbe Erinnerung mehrfach ankommt.
    """
    from kern import benachrichtigung
    heute = heute or date.today()
    morgen = heute + timedelta(days=1)
    verschickt = 0

    with sitzung() as db:
        faellige = db.query(Task).filter(
            Task.status != "erledigt",
            Task.deadline.isnot(None),
            Task.deadline <= morgen,
            (Task.reminder_sent_on.is_(None)) | (Task.reminder_sent_on < heute),
        ).all()

        for task in faellige:
            personen = _empfaenger(db, task)
            if not personen:
                task.reminder_sent_on = heute
                continue
            if task.deadline < heute:
                tage = (heute - task.deadline).days
                titel = "Überfällig"
                text = (f"„{task.titel}“ war vor {tage} Tag"
                        f"{'en' if tage != 1 else ''} fällig.")
            elif task.deadline == heute:
                titel = "Heute fällig"
                text = f"„{task.titel}“ ist heute fällig."
            else:
                titel = "Morgen fällig"
                text = f"„{task.titel}“ ist morgen fällig."

            # Ueberfaellig ist dringend.
            benachrichtigung.melde_vielen(
                db, personen, "tasks", titel, text,
                dringend=task.deadline < heute, anlass="erinnerung")
            task.reminder_sent_on = heute
            verschickt += 1
        db.commit()
    return verschickt


def status_setzen(db, task, neuer_status: str, wer) -> bool:
    """Status aendern und dabei alles Weitere anstossen.

    An einer Stelle gebuendelt, weil daran mehr haengt als das Feld selbst:
    der Erledigungszeitpunkt, der dauerhafte Leistungsnachweis und die
    Benachrichtigung. In V1 stand das an drei Stellen und lief auseinander.
    """
    from kern import benachrichtigung, leistung, protokoll
    if neuer_status not in STATUS_REIHE or task.status == neuer_status:
        return False
    vorher = task.status
    task.status = neuer_status
    task.updated_at = utcnow()

    if neuer_status == "erledigt":
        task.completed_at = utcnow()
        leistung.aufgabe_erledigt(db, task)
        # Wer sie vergeben hat, will wissen, dass sie fertig ist.
        if task.creator_id and task.creator_id != wer.id:
            benachrichtigung.melde(
                db, task.creator_id, "tasks", "Aufgabe erledigt",
                f"{wer.name} hat „{task.titel}“ abgeschlossen.")
    elif vorher == "erledigt":
        # Zurueckgeholt: dann war die Erledigung ein Irrtum, und der Nachweis
        # muss weg. Das ist der einzige Fall, in dem Punkte verschwinden.
        task.completed_at = None
        leistung.aufgabe_wieder_offen(db, task)

    protokoll.notiere(db, wer.id, "aufgabe_status",
                      f"#{task.id} {vorher} → {neuer_status}")
    if task.assignee_id:
        leistung.anstossen(task.assignee_id)
    return True
