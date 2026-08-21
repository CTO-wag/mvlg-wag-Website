"""Aufgaben, Projekte, Wettbewerbe."""

from fastapi import APIRouter, Depends, Form
from sqlalchemy import func

from dashboard.hilfen import (
    Anmeldung, als_csv, datum, fehler, gut, papierkorb_hinweis, teil, warnung,
    zahl,
)
from kern import benachrichtigung, leistung, papierkorb, protokoll
from kern.aufgaben import (
    ERLEDIGT_SICHTBAR_TAGE, aeltere_erledigte, checklisten, darf_aendern,
    darf_sehen, kennzahlen, kommentare, liste, nach_status, status_setzen,
    zuteilbare_abteilungen, zuteilbare_personen,
)
from kern.modelle import (
    Competition, CompetitionParticipant, Project, ProjectTeamMember, Task,
    TaskChecklistItem, TaskComment, User,
)
from kern.rechte import abteilung_label, zustaendige_abteilungen
from kern.text import kuerzen, sauber, utcnow

router = APIRouter(prefix="/dashboard")


#  Aufgaben
def _zustaendig(wert: str, person: str = "", abteilung: str = ""):
    """Zerlegt die Zuständigkeits-Auswahl in (person_id, abteilung).

    Das Formular schickt einen einzigen Wert - "p:12" oder "a:finanzen".
    Zwei getrennte Felder liessen beides gleichzeitig zu; welches dann gewinnt,
    musste man im Quelltext nachlesen. Mit einem Feld kann der Widerspruch
    gar nicht erst entstehen.

    person/abteilung bleiben als Rückfallweg bestehen: ältere Lesezeichen und
    Skripte, die noch die alten Feldnamen schicken, sollen weiter gehen.
    """
    wert = (wert or "").strip()
    if wert.startswith("p:"):
        return zahl(wert[2:]), ""
    if wert.startswith("a:"):
        return None, sauber(wert[2:])
    if wert:
        # Nur eine Zahl: das ist eine Person (so schickte es V1).
        return zahl(wert), ""
    return zahl(person), sauber(abteilung)


def _aufgaben_ansicht(a: Anmeldung, meldung=None, ansicht: str = None,
                      alles: bool = False, formular_offen: bool = False):
    db, user = a.db, a.user
    from kern.modelle import UserPreference
    vorlieben = db.query(UserPreference).filter(
        UserPreference.user_id == user.id).first()
    if ansicht is None:
        ansicht = (vorlieben.task_view_mode if vorlieben else "department")

    # Erledigtes aelter als 30 Tage bleibt draussen, bis jemand ausdruecklich
    # danach fragt - siehe kern/aufgaben.py.
    aufgaben = liste(db, user, ansicht,
                     erledigt_tage=0 if alles else ERLEDIGT_SICHTBAR_TAGE)
    verborgen = 0 if alles else aeltere_erledigte(db, user, ansicht)
    return teil("dashboard/aufgaben.html", a,
                gruppen=nach_status(aufgaben),
                zahlen=kennzahlen(aufgaben),
                verborgen=verborgen, alles=alles,
                formular_offen=formular_offen,
                checklisten=checklisten(db, aufgaben),
                kommentare=kommentare(db, aufgaben),
                ansicht=ansicht,
                darf_anlegen=a.darf("aufgaben_all") or True,
                personen=zuteilbare_personen(db, user),
                abteilungen_wahl=zuteilbare_abteilungen(user, db),
                aenderbar={t.id: darf_aendern(user, t, db) for t in aufgaben},
                meldung=meldung)


@router.get("/aufgaben")
def aufgaben(alles: int = 0, a: Anmeldung = Depends(Anmeldung.pflicht)):
    return _aufgaben_ansicht(a, alles=bool(alles))


@router.post("/aufgaben/ansicht")
def ansicht_wechseln(ansicht: str = Form("department"),
                     csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    from kern.modelle import UserPreference
    if ansicht not in ("personal", "department"):
        ansicht = "department"
    vorlieben = a.db.query(UserPreference).filter(
        UserPreference.user_id == a.user.id).first()
    if not vorlieben:
        vorlieben = UserPreference(user_id=a.user.id)
        a.db.add(vorlieben)
    vorlieben.task_view_mode = ansicht
    a.db.commit()
    return _aufgaben_ansicht(a, ansicht=ansicht)


@router.post("/aufgaben")
def aufgabe_anlegen(titel: str = Form(""), beschreibung: str = Form(""),
                    zustaendig: str = Form(""),
                    person: str = Form(""), abteilung: str = Form(""),
                    frist: str = Form(""), rang: str = Form("mittel"),
                    csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    db, user = a.db, a.user

    titel_ = sauber(titel)[:160]
    if not titel_:
        return _aufgaben_ansicht(a, fehler("Ohne Titel geht es nicht."))

    person_id, abteilung_ = _zustaendig(zustaendig, person, abteilung)
    # Zuteilung ist Pflicht: eine Aufgabe ohne Verantwortliche wird niemals
    # erledigt und steht in einem halben Jahr immer noch da.
    if not person_id and not abteilung_:
        return _aufgaben_ansicht(a, fehler(
            "Bitte eine Person oder eine Abteilung zuständig machen – sonst "
            "fühlt sich niemand angesprochen."))

    if person_id:
        ziel = db.get(User, person_id)
        erlaubte = {p.id for p in zuteilbare_personen(db, user)}
        if not ziel or ziel.id not in erlaubte:
            return _aufgaben_ansicht(a, fehler("Diese Person kannst du nicht zuteilen."))
        abteilung_ = ""
    if abteilung_ and abteilung_ not in zuteilbare_abteilungen(user, db):
        return _aufgaben_ansicht(a, fehler("Diese Abteilung kannst du nicht wählen."))

    # Zu welcher Abteilung die Aufgabe zaehlt - fuer die Leitungssicht.
    if abteilung_:
        heimat = abteilung_
    elif person_id:
        heimat = db.get(User, person_id).department
    else:
        heimat = zustaendige_abteilungen(user)[0]

    aufgabe = Task(
        titel=titel_, beschreibung=sauber(beschreibung)[:4000] or None,
        assignee_id=person_id or None,
        assignee_department=abteilung_ or None,
        task_department=heimat,
        deadline=datum(frist),
        priority=rang if rang in ("niedrig", "mittel", "hoch") else "mittel",
        creator_id=user.id)
    db.add(aufgabe)
    db.flush()
    protokoll.notiere(db, user.id, "aufgabe_neu", kuerzen(titel_, 120))
    db.commit()

    # Wer sie erledigen soll, erfaehrt davon.
    if aufgabe.assignee_id and aufgabe.assignee_id != user.id:
        benachrichtigung.melde(db, aufgabe.assignee_id, "tasks", "Neue Aufgabe",
                               f"{user.name} hat dir „{titel_}“ zugeteilt.")
    elif aufgabe.assignee_department:
        benachrichtigung.melde_abteilung(
            db, aufgabe.assignee_department, "tasks", "Neue Aufgabe",
            f"Für {abteilung_label(aufgabe.assignee_department)}: „{titel_}“.",
            ausser_id=user.id)

    # Formular bleibt offen: nach einer Sitzung trägt man selten nur eine
    # Aufgabe ein, und jedes Mal neu aufzuklappen ist ein Klick zu viel.
    return _aufgaben_ansicht(a, gut(f"„{kuerzen(titel_, 60)}“ ist angelegt."),
                             formular_offen=True)


@router.post("/aufgaben/{task_id}/status")
def aufgabe_status(task_id: int, status: str = Form(""),
                   csrf: str = Form(""),
                   a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    aufgabe = a.db.get(Task, task_id)
    if not aufgabe or not darf_aendern(a.user, aufgabe, a.db):
        return _aufgaben_ansicht(a, fehler("Diese Aufgabe kannst du nicht ändern."))
    if status_setzen(a.db, aufgabe, status, a.user):
        a.db.commit()
        return _aufgaben_ansicht(a, gut("Stand aktualisiert."))
    return _aufgaben_ansicht(a)


@router.post("/aufgaben/{task_id}/aendern")
def aufgabe_aendern(task_id: int, titel: str = Form(""),
                    beschreibung: str = Form(""), frist: str = Form(""),
                    rang: str = Form("mittel"), person: str = Form(""),
                    zustaendig: str = Form(""), abteilung: str = Form(""),
                    csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    db, user = a.db, a.user
    aufgabe = db.get(Task, task_id)
    if not aufgabe or not darf_aendern(user, aufgabe, db):
        return _aufgaben_ansicht(a, fehler("Diese Aufgabe kannst du nicht ändern."))

    neuer_titel = sauber(titel)[:160]
    if neuer_titel:
        aufgabe.titel = neuer_titel
    aufgabe.beschreibung = sauber(beschreibung)[:4000] or None
    aufgabe.deadline = datum(frist)
    if rang in ("niedrig", "mittel", "hoch"):
        aufgabe.priority = rang

    neue_person, neue_abteilung = _zustaendig(zustaendig, person, abteilung)
    if neue_person != aufgabe.assignee_id:
        erlaubte = {p.id for p in zuteilbare_personen(db, user)}
        if neue_person and neue_person in erlaubte:
            aufgabe.assignee_id = neue_person
            aufgabe.assignee_department = None
            benachrichtigung.melde(db, neue_person, "tasks", "Aufgabe für dich",
                                   f"{user.name} hat dir „{aufgabe.titel}“ übergeben.")
        elif not neue_person:
            aufgabe.assignee_id = None
    if neue_abteilung and neue_abteilung != aufgabe.assignee_department:
        if neue_abteilung in zuteilbare_abteilungen(user, db):
            aufgabe.assignee_id = None
            aufgabe.assignee_department = neue_abteilung
            aufgabe.task_department = neue_abteilung
            benachrichtigung.melde_abteilung(
                db, neue_abteilung, "tasks", "Aufgabe für eure Abteilung",
                f"{user.name} hat euch „{aufgabe.titel}“ übergeben.",
                ausser_id=user.id)
    elif not neue_abteilung and not neue_person:
        aufgabe.assignee_department = None

    aufgabe.updated_at = utcnow()
    protokoll.notiere(db, user.id, "aufgabe_geaendert", f"#{aufgabe.id}")
    db.commit()
    return _aufgaben_ansicht(a, gut("Gespeichert."))


@router.post("/aufgaben/{task_id}/loeschen")
def aufgabe_loeschen(task_id: int, csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    aufgabe = a.db.get(Task, task_id)
    if not aufgabe or not darf_aendern(a.user, aufgabe, a.db):
        return _aufgaben_ansicht(a, fehler("Diese Aufgabe kannst du nicht löschen."))
    war_erledigt = aufgabe.status == "erledigt"
    titel = aufgabe.titel
    papierkorb.hinein(a.db, "task", aufgabe, a.user.id)
    protokoll.notiere(a.db, a.user.id, "aufgabe_geloescht", kuerzen(titel, 120))
    a.db.commit()
    # Der Leistungsnachweis bleibt ausdruecklich stehen - genau darum geht es.
    hinweis = (" Die Erledigung zählt weiter für den Leadership-Wert."
               if war_erledigt else "")
    return _aufgaben_ansicht(a, papierkorb_hinweis(
        f"„{kuerzen(titel, 60)}“ liegt im Papierkorb.{hinweis}"))


@router.post("/aufgaben/{task_id}/checkliste")
def checkliste_anlegen(task_id: int, text: str = Form(""),
                       csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    aufgabe = a.db.get(Task, task_id)
    if not aufgabe or not darf_sehen(a.user, aufgabe, a.db):
        return _aufgaben_ansicht(a, fehler("Diese Aufgabe gehört weder dir noch deiner Abteilung."))
    inhalt = sauber(text)[:200]
    if inhalt:
        letzte = a.db.query(func.coalesce(func.max(TaskChecklistItem.position), 0)) \
            .filter(TaskChecklistItem.task_id == task_id).scalar() or 0
        a.db.add(TaskChecklistItem(task_id=task_id, text=inhalt, position=letzte + 1))
        a.db.commit()
    return _aufgaben_ansicht(a)


@router.post("/aufgaben/checkliste/{punkt_id}/umschalten")
def checkliste_umschalten(punkt_id: int, csrf: str = Form(""),
                          a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    punkt = a.db.get(TaskChecklistItem, punkt_id)
    if punkt:
        aufgabe = a.db.get(Task, punkt.task_id)
        if aufgabe and darf_sehen(a.user, aufgabe, a.db):
            punkt.done = 0 if punkt.done else 1
            a.db.commit()
    return _aufgaben_ansicht(a)


@router.post("/aufgaben/checkliste/{punkt_id}/loeschen")
def checkliste_loeschen(punkt_id: int, csrf: str = Form(""),
                        a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    punkt = a.db.get(TaskChecklistItem, punkt_id)
    if punkt:
        aufgabe = a.db.get(Task, punkt.task_id)
        if aufgabe and darf_aendern(a.user, aufgabe, a.db):
            a.db.delete(punkt)
            a.db.commit()
    return _aufgaben_ansicht(a)


@router.post("/aufgaben/{task_id}/kommentar")
def kommentar(task_id: int, text: str = Form(""), csrf: str = Form(""),
              a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    db, user = a.db, a.user
    aufgabe = db.get(Task, task_id)
    if not aufgabe or not darf_sehen(user, aufgabe, db):
        return _aufgaben_ansicht(a, fehler("Diese Aufgabe gehört weder dir noch deiner Abteilung."))
    inhalt = sauber(text)[:2000]
    if not inhalt:
        return _aufgaben_ansicht(a)
    db.add(TaskComment(task_id=task_id, user_id=user.id, message=inhalt))
    db.commit()
    # Alle Beteiligten ausser dem Schreiber selbst.
    for wen in {aufgabe.assignee_id, aufgabe.creator_id} - {None, user.id}:
        benachrichtigung.melde(db, wen, "tasks", "Neuer Kommentar",
                               f"{user.name} zu „{aufgabe.titel}“: "
                               f"{kuerzen(inhalt, 120)}")
    return _aufgaben_ansicht(a, gut("Kommentar gespeichert."))


@router.get("/aufgaben/export.csv")
def aufgaben_export(a: Anmeldung = Depends(Anmeldung.pflicht)):
    aufgaben = liste(a.db, a.user, "department")
    zeilen = [(t.id, t.titel, t.status, t.priority,
               t.deadline.isoformat() if t.deadline else "",
               t.assignee.name if t.assignee else
               (abteilung_label(t.assignee_department) if t.assignee_department else ""),
               abteilung_label(t.task_department),
               t.completed_at.isoformat() if t.completed_at else "")
              for t in aufgaben]
    return als_csv(zeilen,
                   ["ID", "Titel", "Status", "Priorität", "Frist",
                    "Zuständig", "Abteilung", "Erledigt am"],
                   "aufgaben.csv")


#  Projekte
def _projekte_ansicht(a: Anmeldung, meldung=None):
    db = a.db
    projekte = db.query(Project).order_by(Project.status,
                                          Project.deadline.is_(None),
                                          Project.deadline).all()
    teams = {}
    for eintrag, person in (db.query(ProjectTeamMember, User)
                            .join(User, User.id == ProjectTeamMember.user_id).all()):
        teams.setdefault(eintrag.project_id, []).append((eintrag, person))
    return teil("dashboard/projekte.html", a, projekte=projekte, teams=teams,
                personen=db.query(User).filter(User.status == "aktiv")
                          .order_by(User.vorname).all(),
                meldung=meldung)


@router.get("/projekte")
def projekte(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("projects")
    return _projekte_ansicht(a)


@router.post("/projekte")
def projekt_anlegen(titel: str = Form(""), beschreibung: str = Form(""),
                    leitung: str = Form(""), frist: str = Form(""),
                    csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("projects")
    a.pruefe_csrf(csrf)
    titel_ = sauber(titel)[:200]
    if not titel_:
        return _projekte_ansicht(a, fehler("Ohne Titel geht es nicht."))
    projekt = Project(title=titel_, description=sauber(beschreibung)[:4000] or None,
                      lead_id=zahl(leitung) or None, deadline=datum(frist))
    a.db.add(projekt)
    a.db.flush()
    if projekt.lead_id:
        a.db.add(ProjectTeamMember(project_id=projekt.id, user_id=projekt.lead_id,
                                   role="Leitung"))
    protokoll.notiere(a.db, a.user.id, "projekt_neu", kuerzen(titel_, 120))
    a.db.commit()
    if projekt.lead_id:
        leistung.anstossen(projekt.lead_id)
        benachrichtigung.melde(a.db, projekt.lead_id, "messages", "Projektleitung",
                               f"Du leitest jetzt „{titel_}“.")
    return _projekte_ansicht(a, gut(f"Projekt „{kuerzen(titel_, 60)}“ angelegt."))


@router.post("/projekte/{projekt_id}/aendern")
def projekt_aendern(projekt_id: int, titel: str = Form(""),
                    beschreibung: str = Form(""), status: str = Form(""),
                    fortschritt: str = Form("0"), leitung: str = Form(""),
                    frist: str = Form(""), csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("projects")
    a.pruefe_csrf(csrf)
    projekt = a.db.get(Project, projekt_id)
    if not projekt:
        return _projekte_ansicht(a, fehler("Dieses Projekt gibt es nicht mehr."))
    if sauber(titel):
        projekt.title = sauber(titel)[:200]
    projekt.description = sauber(beschreibung)[:4000] or None
    if status in ("planung", "laufend", "abgeschlossen"):
        projekt.status = status
    projekt.progress = max(0, min(100, zahl(fortschritt, 0) or 0))
    projekt.lead_id = zahl(leitung) or None
    projekt.deadline = datum(frist)
    projekt.updated_at = utcnow()
    a.db.commit()
    return _projekte_ansicht(a, gut("Gespeichert."))


@router.post("/projekte/{projekt_id}/mitglied")
def projekt_mitglied(projekt_id: int, person: str = Form(""),
                     rolle: str = Form(""), csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("projects")
    a.pruefe_csrf(csrf)
    person_id = zahl(person)
    if not person_id or not a.db.get(Project, projekt_id):
        return _projekte_ansicht(a, fehler("Bitte eine Person auswählen."))
    schon_da = a.db.query(ProjectTeamMember).filter(
        ProjectTeamMember.project_id == projekt_id,
        ProjectTeamMember.user_id == person_id).first()
    if schon_da:
        return _projekte_ansicht(a, warnung("Diese Person ist schon im Team."))
    eintrag = ProjectTeamMember(project_id=projekt_id, user_id=person_id,
                                role=sauber(rolle)[:80] or None)
    a.db.add(eintrag)
    a.db.flush()
    leistung.projekt_mitarbeit(a.db, eintrag)
    a.db.commit()
    leistung.anstossen(person_id)
    benachrichtigung.melde(a.db, person_id, "messages", "Neues Projekt",
                           f"Du bist jetzt im Team von "
                           f"„{a.db.get(Project, projekt_id).title}“.")
    return _projekte_ansicht(a, gut("Zum Team hinzugefügt."))


@router.post("/projekte/mitglied/{eintrag_id}/entfernen")
def projekt_mitglied_weg(eintrag_id: int, csrf: str = Form(""),
                         a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("projects")
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(ProjectTeamMember, eintrag_id)
    if eintrag:
        a.db.delete(eintrag)
        a.db.commit()
    return _projekte_ansicht(a, gut("Aus dem Team entfernt."))


@router.post("/projekte/{projekt_id}/loeschen")
def projekt_loeschen(projekt_id: int, csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("projects")
    a.pruefe_csrf(csrf)
    projekt = a.db.get(Project, projekt_id)
    if projekt:
        papierkorb.hinein(a.db, "project", projekt, a.user.id)
        a.db.commit()
    return _projekte_ansicht(a,
        papierkorb_hinweis("Das Projekt liegt im Papierkorb – 30 Tage lang "
                           "wiederherstellbar."))


#  Wettbewerbe
def _wettbewerbe_ansicht(a: Anmeldung, meldung=None):
    db = a.db
    wettbewerbe = db.query(Competition).order_by(
        Competition.date.is_(None), Competition.date.desc()).all()
    teilnahmen = {}
    for eintrag, person in (db.query(CompetitionParticipant, User)
                            .join(User, User.id == CompetitionParticipant.user_id).all()):
        teilnahmen.setdefault(eintrag.competition_id, []).append((eintrag, person))
    for liste_ in teilnahmen.values():
        liste_.sort(key=lambda z: (z[0].placement is None, z[0].placement or 0))
    return teil("dashboard/wettbewerbe.html", a, wettbewerbe=wettbewerbe,
                teilnahmen=teilnahmen,
                personen=db.query(User).filter(User.status == "aktiv")
                          .order_by(User.vorname).all(),
                meldung=meldung)


@router.get("/wettbewerbe")
def wettbewerbe(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("competitions")
    return _wettbewerbe_ansicht(a)


@router.post("/wettbewerbe")
def wettbewerb_anlegen(titel: str = Form(""), beschreibung: str = Form(""),
                       wann: str = Form(""), ort: str = Form(""),
                       csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("competitions")
    a.pruefe_csrf(csrf)
    titel_ = sauber(titel)[:200]
    if not titel_:
        return _wettbewerbe_ansicht(a, fehler("Ohne Titel geht es nicht."))
    a.db.add(Competition(title=titel_, description=sauber(beschreibung)[:4000] or None,
                         date=datum(wann), location=sauber(ort)[:200] or None,
                         organizer_id=a.user.id))
    a.db.commit()
    benachrichtigung.melde_vielen(
        a.db, a.db.query(User).filter(User.status == "aktiv").all(),
        "messages", "Neuer Wettbewerb",
        f"„{titel_}“ steht an. Wer mitmachen will, meldet sich beim Vorstand.",
        ausser_id=a.user.id)
    return _wettbewerbe_ansicht(a, gut(f"„{kuerzen(titel_, 60)}“ angelegt."))


@router.post("/wettbewerbe/{comp_id}/aendern")
def wettbewerb_aendern(comp_id: int, titel: str = Form(""),
                       beschreibung: str = Form(""), status: str = Form(""),
                       wann: str = Form(""), ort: str = Form(""),
                       csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("competitions")
    a.pruefe_csrf(csrf)
    wettbewerb = a.db.get(Competition, comp_id)
    if not wettbewerb:
        return _wettbewerbe_ansicht(a, fehler("Diesen Wettbewerb gibt es nicht mehr."))
    if sauber(titel):
        wettbewerb.title = sauber(titel)[:200]
    wettbewerb.description = sauber(beschreibung)[:4000] or None
    if status in ("geplant", "aktiv", "abgeschlossen"):
        wettbewerb.status = status
    wettbewerb.date = datum(wann)
    wettbewerb.location = sauber(ort)[:200] or None
    a.db.commit()
    return _wettbewerbe_ansicht(a, gut("Gespeichert."))


@router.post("/wettbewerbe/{comp_id}/teilnahme")
def teilnahme_anlegen(comp_id: int, person: str = Form(""),
                      team: str = Form(""), platz: str = Form(""),
                      punkte: str = Form(""), notiz: str = Form(""),
                      csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("competitions")
    a.pruefe_csrf(csrf)
    person_id = zahl(person)
    if not person_id or not a.db.get(Competition, comp_id):
        return _wettbewerbe_ansicht(a, fehler("Bitte eine Person auswählen."))
    if a.db.query(CompetitionParticipant).filter(
            CompetitionParticipant.competition_id == comp_id,
            CompetitionParticipant.user_id == person_id).first():
        return _wettbewerbe_ansicht(a, warnung("Diese Person ist schon eingetragen."))
    eintrag = CompetitionParticipant(
        competition_id=comp_id, user_id=person_id,
        team_name=sauber(team)[:200] or None, placement=zahl(platz),
        points=zahl(punkte), notes=sauber(notiz)[:2000] or None)
    a.db.add(eintrag)
    a.db.flush()
    leistung.wettbewerb_erfasst(a.db, eintrag)
    a.db.commit()
    leistung.anstossen(person_id)
    return _wettbewerbe_ansicht(a, gut("Teilnahme eingetragen."))


@router.post("/wettbewerbe/teilnahme/{eintrag_id}/entfernen")
def teilnahme_weg(eintrag_id: int, csrf: str = Form(""),
                  a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("competitions")
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(CompetitionParticipant, eintrag_id)
    if eintrag:
        person_id = eintrag.user_id
        a.db.delete(eintrag)
        a.db.commit()
        leistung.anstossen(person_id)
    return _wettbewerbe_ansicht(a, gut("Teilnahme entfernt."))


@router.post("/wettbewerbe/{comp_id}/loeschen")
def wettbewerb_loeschen(comp_id: int, csrf: str = Form(""),
                        a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("competitions")
    a.pruefe_csrf(csrf)
    wettbewerb = a.db.get(Competition, comp_id)
    if wettbewerb:
        papierkorb.hinein(a.db, "competition", wettbewerb, a.user.id)
        a.db.commit()
    return _wettbewerbe_ansicht(a,
        papierkorb_hinweis("Der Wettbewerb liegt im Papierkorb – 30 Tage lang "
                              "wiederherstellbar."))
