"""Uebersicht, globale Suche und Statistiken.

Die Uebersicht ist die Startseite des Dashboards und beantwortet genau eine
Frage: Was steht fuer mich an? In V1 war das eine Kachelwand mit Zahlen, die
niemanden betrafen - "48 Konten" hilft beim Arbeiten nicht weiter.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_

from dashboard.hilfen import Anmeldung, teil
from kern import diagramme, kasse, umzug
from kern.aufgaben import kennzahlen, liste as aufgabenliste, sichtbar_filter
from kern.modelle import (
    Application, Attendance, CalendarEvent, Competition, ContactMessage,
    DirectMessage, DirectMessageRecipient, Leistung, Meeting, Project,
    SupportTicket, Task, User,
)
from kern.rechte import abteilung_label, zustaendige_abteilungen
from kern.text import heute_berlin, nach_berlin, prozent, utcnow

router = APIRouter(prefix="/dashboard")


def _startpasswort_abgewaehlt(db, user) -> bool:
    """Hat die Person gesagt, dass sie ihr Passwort behalten will?"""
    from kern.modelle import UserPreference
    vorlieben = db.query(UserPreference).filter(
        UserPreference.user_id == user.id).first()
    return bool(vorlieben and vorlieben.startpasswort_egal)


def _naechster_termin(db, user):
    """Der naechste Termin, der diese Person betrifft."""
    heute = date.today()
    meine = set(zustaendige_abteilungen(user))
    kandidaten = (db.query(CalendarEvent)
                  .filter(CalendarEvent.start_date >= heute)
                  .order_by(CalendarEvent.start_date, CalendarEvent.start_time)
                  .limit(30).all())
    for termin in kandidaten:
        if termin.target_type == "alle":
            return termin
        if termin.target_type == "person" and termin.target_user_id == user.id:
            return termin
        if termin.target_type == "abteilung" and termin.target_department in meine:
            return termin
        if termin.target_type == "auswahl":
            for ziel in termin.targets:
                if ziel.user_id == user.id or (ziel.department and ziel.department in meine):
                    return termin
    # Ein AG-Treffen ist auch ein Termin - und oft der naechste.
    treffen = (db.query(Meeting).filter(Meeting.date >= heute)
               .order_by(Meeting.date).first())
    return treffen


def _wochenblick(aufgaben, heute) -> list:
    """Die naechsten sieben Tage als Leiste.

    Beantwortet die Frage, die eine reine Liste nicht beantwortet: Wo haeuft
    es sich? Man sieht auf einen Blick, ob Donnerstag drei Sachen fällig sind
    und der Rest der Woche leer ist.
    """
    tage = []
    for versatz in range(7):
        tag = heute + timedelta(days=versatz)
        drauf = [t for t in aufgaben
                 if t.status != "erledigt" and t.deadline == tag]
        tage.append({
            "tag": tag,
            "kurz": ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")[tag.weekday()],
            "zahl": tag.day,
            "anzahl": len(drauf),
            "heute": versatz == 0,
            "wochenende": tag.weekday() >= 5,
        })
    return tage


@router.get("/uebersicht")
def uebersicht(a: Anmeldung = Depends(Anmeldung.pflicht)):
    db, user = a.db, a.user
    heute = date.today()

    meine_aufgaben = aufgabenliste(db, user, "abteilung")
    zahlen = kennzahlen(meine_aufgaben)

    persoenlich = [t for t in meine_aufgaben if t.assignee_id == user.id]
    offen_persoenlich = [t for t in persoenlich if t.status != "erledigt"]
    # Zuerst das Überfällige, dann nach Frist, Fristloses ganz zuletzt.
    offen_persoenlich.sort(
        key=lambda t: (t.deadline is None, t.deadline or heute,
                       {"hoch": 0, "mittel": 1, "niedrig": 2}.get(t.priority, 1)))

    ungelesen = (db.query(DirectMessageRecipient, DirectMessage)
                 .join(DirectMessage, DirectMessage.id == DirectMessageRecipient.message_id)
                 .filter(DirectMessageRecipient.user_id == user.id,
                         DirectMessageRecipient.read_at.is_(None))
                 .order_by(DirectMessage.created_at.desc()).limit(4).all())

    # Was diese Person selbst geschafft hat - der sichtbare Teil des
    # automatischen Scorings. Zaehlt auch, was inzwischen geloescht wurde.
    erledigt_gesamt = db.query(func.count(Leistung.id)).filter(
        Leistung.user_id == user.id, Leistung.art == "aufgabe").scalar() or 0
    erledigt_30 = db.query(func.count(Leistung.id)).filter(
        Leistung.user_id == user.id, Leistung.art == "aufgabe",
        Leistung.zeitpunkt >= heute - timedelta(days=30)).scalar() or 0
    erledigt_vormonat = db.query(func.count(Leistung.id)).filter(
        Leistung.user_id == user.id, Leistung.art == "aufgabe",
        Leistung.zeitpunkt >= heute - timedelta(days=60),
        Leistung.zeitpunkt < heute - timedelta(days=30)).scalar() or 0

    # --- Was wartet ------------------------------------------------------
    # Nur, was die Rolle wirklich betrifft, und mit dem Dringendsten oben.
    wartet = []

    def merken(anzahl, einzahl, mehrzahl, bereich, dringend=False):
        if anzahl:
            wartet.append({
                "anzahl": anzahl,
                "text": einzahl if anzahl == 1 else mehrzahl,
                "bereich": bereich, "dringend": dringend})

    merken(zahlen["ueberfaellig"], "überfällige Aufgabe", "überfällige Aufgaben",
           "aufgaben", dringend=True)
    if a.darf("bewerbungen"):
        merken(db.query(func.count(Application.id)).filter(
            Application.status == "neu").scalar() or 0,
            "neue Bewerbung", "neue Bewerbungen", "bewerbungen")
    if a.darf("support_verwaltung"):
        merken(db.query(func.count(SupportTicket.id)).filter(
            SupportTicket.status == "offen").scalar() or 0,
            "offene Support-Anfrage", "offene Support-Anfragen", "support")
    if a.darf("nachrichten"):
        merken(db.query(func.count(ContactMessage.id)).filter(
            ContactMessage.reply.is_(None)).scalar() or 0,
            "unbeantwortete Anfrage über die Website",
            "unbeantwortete Anfragen über die Website", "nachrichten")
    if a.darf("whatsapp_bot"):
        from kern.whatsapp import uebersicht as wa_uebersicht
        merken(wa_uebersicht(db)["offen"],
               "Willkommensnachricht wartet", "Willkommensnachrichten warten",
               "whatsapp")

    # --- Was in der AG passiert ist --------------------------------------
    # Für Leitungsrollen: der Blick über den eigenen Schreibtisch hinaus.
    puls = None
    if a.darf("aufgaben_all", "leadership", "mitglieder_view"):
        seit = utcnow() - timedelta(days=7)
        erledigt_team = (db.query(Leistung, User)
                         .join(User, User.id == Leistung.user_id)
                         .filter(Leistung.art == "aufgabe", Leistung.zeitpunkt >= seit)
                         .order_by(Leistung.zeitpunkt.desc()).limit(6).all())
        puls = {
            "erledigt": erledigt_team,
            "anzahl": db.query(func.count(Leistung.id)).filter(
                Leistung.art == "aufgabe", Leistung.zeitpunkt >= seit).scalar() or 0,
            "neue_mitglieder": db.query(func.count(User.id)).filter(
                User.created_at >= seit).scalar() or 0,
        }

    # Eine Begruessung, die zur Uhrzeit passt. Kleinigkeit, aber ein
    # "Guten Morgen" um 22 Uhr wirkt wie eine Maschine.
    stunde = int(nach_berlin(utcnow(), "%H"))
    gruss = ("Guten Morgen" if 5 <= stunde < 11 else
             "Moin" if 11 <= stunde < 14 else
             "Guten Tag" if 14 <= stunde < 18 else
             "Guten Abend" if 18 <= stunde < 23 else "Noch wach")

    return teil("dashboard/uebersicht.html", a,
                gruss=gruss,
                # Wer sein Passwort noch nie selbst geändert hat, benutzt
                # noch das, was jemand anderes gesetzt hat - und das steht in
                # einer E-Mail oder einer WhatsApp-Nachricht, die nicht
                # verschwindet. Ein Hinweis dort, wo man ohnehin hinschaut.
                startpasswort_hinweis=(not user.passwort_geaendert_am
                                       and not _startpasswort_abgewaehlt(db, user)),
                # Was nach dem Umzug noch jeder selbst erledigen muss. Steht
                # hier, weil ein Rundgang vorbeigeht - eine Liste bleibt, bis
                # sie leer ist, und dann verschwindet sie von selbst.
                umzug_offen=umzug.offene_punkte(db, user),
                zahlen=zahlen,
                meine=offen_persoenlich[:5],
                meine_gesamt=len(offen_persoenlich),
                woche=_wochenblick(meine_aufgaben, heute),
                ungelesen=ungelesen,
                wartet=wartet,
                naechster=_naechster_termin(db, user),
                erledigt_gesamt=erledigt_gesamt,
                erledigt_30=erledigt_30,
                erledigt_vormonat=erledigt_vormonat,
                puls=puls)


#  Globale Suche
@router.get("/suche")
def suche(q: str = "", a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Sucht ueber alles, was die Person sehen darf.

    Bewusst eine eigene Abfrage je Bereich statt einer grossen Volltextsuche:
    So gilt fuer jeden Treffer dieselbe Rechteregel wie im Bereich selbst.
    Eine gemeinsame Suchtabelle waere schneller, wuerde aber genau diese
    Pruefung umgehen - und dann taucht in der Trefferliste etwas auf, das man
    nicht sehen darf.
    """
    db, user = a.db, a.user
    begriff = (q or "").strip()
    if len(begriff) < 2:
        return teil("dashboard/teile/suchtreffer.html", a, gruppen=[])

    muster = f"%{begriff}%"
    gruppen = []

    aufgaben = (db.query(Task)
                .filter(sichtbar_filter(user, db),
                        or_(Task.titel.ilike(muster), Task.beschreibung.ilike(muster)))
                .order_by(Task.status, Task.id.desc()).limit(6).all())
    if aufgaben:
        gruppen.append(("Aufgaben", [
            {"text": t.titel, "meta": t.status.replace("_", " ").title(),
             "bereich": "aufgaben"} for t in aufgaben]))

    if a.darf("accounts_all", "mitglieder_view"):
        personen = (db.query(User)
                    .filter(or_(User.vorname.ilike(muster),
                                User.nachname.ilike(muster),
                                User.email.ilike(muster)))
                    .order_by(User.vorname).limit(6).all())
        if personen:
            gruppen.append(("Personen", [
                {"text": p.name,
                 "meta": abteilung_label(p.department),
                 "bereich": "konten" if a.darf("accounts_all") else "mitglieder"}
                for p in personen]))

    if a.darf("bewerbungen"):
        bewerbungen = (db.query(Application)
                       .filter(or_(Application.vorname.ilike(muster),
                                   Application.nachname.ilike(muster),
                                   Application.email.ilike(muster)))
                       .order_by(Application.created_at.desc()).limit(5).all())
        if bewerbungen:
            gruppen.append(("Bewerbungen", [
                {"text": f"{b.vorname} {b.nachname}", "meta": b.klasse,
                 "bereich": "bewerbungen"} for b in bewerbungen]))

    termine = (db.query(CalendarEvent)
               .filter(CalendarEvent.title.ilike(muster))
               .order_by(CalendarEvent.start_date.desc()).limit(4).all())
    if termine:
        gruppen.append(("Termine", [
            {"text": t.title, "meta": nach_berlin(t.start_date),
             "bereich": "kalender"} for t in termine]))

    treffen = (db.query(Meeting)
               .filter(or_(Meeting.title.ilike(muster), Meeting.protocol.ilike(muster)))
               .order_by(Meeting.date.desc()).limit(4).all())
    if treffen:
        gruppen.append(("AG-Treffen", [
            {"text": t.title, "meta": nach_berlin(t.date), "bereich": "treffen"}
            for t in treffen]))

    if a.darf("projects"):
        projekte = (db.query(Project).filter(Project.title.ilike(muster))
                    .order_by(Project.id.desc()).limit(4).all())
        if projekte:
            gruppen.append(("Projekte", [
                {"text": p.title, "meta": p.status.title(), "bereich": "projekte"}
                for p in projekte]))

    if a.darf("competitions"):
        wettbewerbe = (db.query(Competition).filter(Competition.title.ilike(muster))
                       .order_by(Competition.id.desc()).limit(4).all())
        if wettbewerbe:
            gruppen.append(("Wettbewerbe", [
                {"text": w.title, "meta": w.status.title(), "bereich": "wettbewerbe"}
                for w in wettbewerbe]))

    if a.darf("support_verwaltung"):
        tickets = (db.query(SupportTicket)
                   .filter(or_(SupportTicket.subject.ilike(muster),
                               SupportTicket.message.ilike(muster)))
                   .order_by(SupportTicket.created_at.desc()).limit(4).all())
        if tickets:
            gruppen.append(("Support", [
                {"text": t.subject, "meta": t.status.title(), "bereich": "support"}
                for t in tickets]))

    return teil("dashboard/teile/suchtreffer.html", a, gruppen=gruppen,
                begriff=begriff)


#  Statistiken
@router.get("/statistiken")
def statistiken(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("statistiken")
    db = a.db
    heute = heute_berlin()

    # Aufgaben nach Status und Abteilung
    nach_status = dict(db.query(Task.status, func.count(Task.id))
                       .group_by(Task.status).all())
    nach_abteilung = dict(db.query(Task.task_department, func.count(Task.id))
                          .group_by(Task.task_department).all())

    # Erledigungen je Monat - aus dem Leistungsnachweis, also einschliesslich
    # der Aufgaben, die inzwischen geloescht wurden.
    monatswerte = []
    jahr, monat = heute.year, heute.month
    for _ in range(6):
        von = date(jahr, monat, 1)
        bis = date(jahr + (monat == 12), (monat % 12) + 1, 1)
        anzahl = db.query(func.count(Leistung.id)).filter(
            Leistung.art == "aufgabe", Leistung.zeitpunkt >= von,
            Leistung.zeitpunkt < bis).scalar() or 0
        from kern.text import MONATE
        monatswerte.append((MONATE[monat - 1][:3], anzahl))
        monat -= 1
        if monat == 0:
            monat, jahr = 12, jahr - 1
    monatswerte.reverse()

    personen_gesamt = db.query(func.count(User.id)).scalar() or 0
    aktive = db.query(func.count(User.id)).filter(User.status == "aktiv").scalar() or 0
    bewerbungen = dict(db.query(Application.status, func.count(Application.id))
                       .group_by(Application.status).all())

    return teil("dashboard/statistiken.html", a,
                status_diagramm=diagramme.ring(
                    [(s.replace("_", " ").title(), n) for s, n in nach_status.items()]),
                abteilung_diagramm=diagramme.balken(
                    [(abteilung_label(k), n) for k, n in nach_abteilung.items() if k]),
                monats_diagramm=diagramme.balken(monatswerte, farbe_index=2),
                bewerbungs_diagramm=diagramme.ring(
                    [(s.replace("_", " ").title(), n) for s, n in bewerbungen.items()]),
                personen_gesamt=personen_gesamt, aktive=aktive,
                aufgaben_gesamt=sum(nach_status.values()),
                erledigt=nach_status.get("erledigt", 0),
                erledigt_anteil=prozent(nach_status.get("erledigt", 0),
                                        sum(nach_status.values())),
                anwesenheiten=db.query(func.count(Attendance.id)).scalar() or 0,
                treffen=db.query(func.count(Meeting.id)).scalar() or 0,
                kassenstand=kasse.stand(db) if a.darf("finanzen") else None)
