"""Uebersicht, globale Suche und Statistiken.

Die Uebersicht ist die Startseite des Dashboards und beantwortet genau eine
Frage: Was steht fuer mich an? In V1 war das eine Kachelwand mit Zahlen, die
niemanden betrafen - "48 Konten" hilft beim Arbeiten nicht weiter.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import String, and_, cast, func, or_

from dashboard.hilfen import Anmeldung, teil
from kern import diagramme, kasse, umzug
from kern.aufgaben import kennzahlen, liste as aufgabenliste, sichtbar_filter
from kern.modelle import (
    Application, Attendance, CalendarEvent, Competition, ContactMessage,
    DirectMessage, DirectMessageRecipient, Leistung, Meeting, Project,
    SupportTicket, Task, User, Role, Department, ContentItem, EmailTemplate,
    Buchung, Budget, Dauerauftrag,
)
from kern.rechte import abteilung_label, zustaendige_abteilungen
from kern.text import heute_berlin, nach_berlin, prozent, utcnow

router = APIRouter(prefix="/dashboard")

_SUCH_AUSNAHMEN = {
    "password_hash", "totp_secret", "totp_ersatzcodes", "calendar_token",
    "session_token", "api_token", "secret",
}


_TELEFON_SPALTEN = {
    "telefon", "telefonnummer", "phone", "phone_number", "mobile",
    "mobil", "mobile_phone",
}


def _telefonvarianten(wert: str) -> list[str]:
    ziffern = "".join(zeichen for zeichen in wert if zeichen.isdigit())
    if len(ziffern) < 2:
        return []
    varianten = {ziffern}
    if ziffern.startswith("00"):
        varianten.add(ziffern[2:])
    if ziffern.startswith("0") and not ziffern.startswith("00"):
        varianten.add("49" + ziffern[1:])
    if ziffern.startswith("49"):
        varianten.add("0" + ziffern[2:])
    return list(varianten)


def _telefon_normalisiert(spalte):
    """Entfernt alle gaengigen Schreibtrennzeichen direkt in SQL."""
    ausdruck = cast(spalte, String)
    for zeichen in (" ", "-", "(", ")", ".", "/", "+"):
        ausdruck = func.replace(ausdruck, zeichen, "")
    return ausdruck


def _suchfilter(modell, begriff: str):
    """Durchsucht alle nicht sensiblen Spalten, inklusive formatierter Telefone.

    Mehrere Suchwoerter duerfen aus unterschiedlichen Feldern desselben
    Datensatzes stammen, z. B. Name plus Abteilung.
    """
    spalten = []
    for spalte in modell.__table__.columns:
        if spalte.name in _SUCH_AUSNAHMEN:
            continue
        if spalte.name in _TELEFON_SPALTEN:
            varianten = _telefonvarianten(begriff)
            telefon = or_(*(
                _telefon_normalisiert(spalte).ilike(_suchmuster(variante))
                for variante in varianten))
            spalten.append(telefon if varianten else
                           cast(spalte, String).ilike(_suchmuster(begriff)))
        else:
            spalten.append(cast(spalte, String).ilike(_suchmuster(begriff)))
    return or_(*spalten) if spalten else False


def _suchfilter_mehrere(modell, begriff: str):
    teile = [teil for teil in begriff.split() if teil]
    return and_(*(_suchfilter(modell, teil) for teil in teile)
                ) if teile else False


def _suchmuster(begriff: str) -> str:
    return f"%{begriff}%"


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
                  .order_by(CalendarEvent.start_date,
                            CalendarEvent.start_time.asc().nullsfirst())
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

    gruppen = []

    aufgaben = (db.query(Task)
                .filter(sichtbar_filter(user, db),
                        _suchfilter_mehrere(Task, begriff))
                .order_by(Task.status, Task.id.desc()).limit(6).all())
    if aufgaben:
        gruppen.append(("Aufgaben", [
            {"text": t.titel, "meta": t.status.replace("_", " ").title(),
             "bereich": "aufgaben"} for t in aufgaben]))

    if a.darf("accounts_all", "mitglieder_view"):
        personen = (db.query(User)
                    .filter(_suchfilter_mehrere(User, begriff))
                    .order_by(User.vorname).limit(6).all())
        if personen:
            gruppen.append(("Personen", [
                {"text": p.name,
                 "meta": abteilung_label(p.department),
                 "bereich": "konten" if a.darf("accounts_all") else "mitglieder"}
                for p in personen]))

    if a.darf("bewerbungen"):
        bewerbungen = (db.query(Application)
                       .filter(_suchfilter_mehrere(Application, begriff))
                       .order_by(Application.created_at.desc()).limit(5).all())
        if bewerbungen:
            gruppen.append(("Bewerbungen", [
                {"text": f"{b.vorname} {b.nachname}", "meta": b.klasse,
                 "bereich": "bewerbungen"} for b in bewerbungen]))

    termine = (db.query(CalendarEvent)
               .filter(_suchfilter_mehrere(CalendarEvent, begriff))
               .order_by(CalendarEvent.start_date.desc()).limit(4).all())
    if termine:
        gruppen.append(("Termine", [
            {"text": t.title, "meta": nach_berlin(t.start_date),
             "bereich": "kalender"} for t in termine]))

    treffen = (db.query(Meeting)
               .filter(_suchfilter_mehrere(Meeting, begriff))
               .order_by(Meeting.date.desc()).limit(4).all())
    if treffen:
        gruppen.append(("AG-Treffen", [
            {"text": t.title, "meta": nach_berlin(t.date), "bereich": "treffen"}
            for t in treffen]))

    if a.darf("projects"):
        projekte = (db.query(Project).filter(_suchfilter_mehrere(Project, begriff))
                    .order_by(Project.id.desc()).limit(4).all())
        if projekte:
            gruppen.append(("Projekte", [
                {"text": p.title, "meta": p.status.title(), "bereich": "projekte"}
                for p in projekte]))

    if a.darf("competitions"):
        wettbewerbe = (db.query(Competition).filter(
                       _suchfilter_mehrere(Competition, begriff))
                       .order_by(Competition.id.desc()).limit(4).all())
        if wettbewerbe:
            gruppen.append(("Wettbewerbe", [
                {"text": w.title, "meta": w.status.title(), "bereich": "wettbewerbe"}
                for w in wettbewerbe]))

    if a.darf("support_verwaltung"):
        tickets = (db.query(SupportTicket)
                   .filter(_suchfilter_mehrere(SupportTicket, begriff))
                   .order_by(SupportTicket.created_at.desc()).limit(4).all())
        if tickets:
            gruppen.append(("Support", [
                {"text": t.subject, "meta": t.status.title(), "bereich": "support"}
                for t in tickets]))

    if a.darf("nachrichten"):
        kontakt = (db.query(ContactMessage)
                   .filter(_suchfilter_mehrere(ContactMessage, begriff))
                   .order_by(ContactMessage.created_at.desc()).limit(4).all())
        if kontakt:
            gruppen.append(("Kontaktanfragen", [
                {"text": c.subject or c.email, "meta": c.name or c.email,
                 "bereich": "nachrichten"} for c in kontakt]))

    if a.darf("attendance"):
        attendance = (db.query(Attendance)
                      .filter(_suchfilter_mehrere(Attendance, begriff))
                      .order_by(Attendance.event_date.desc()).limit(4).all())
        if attendance:
            gruppen.append(("Anwesenheit", [
                {"text": f"Anwesenheit #{x.id}",
                 "meta": f"{x.event_type} · {x.event_date}",
                 "bereich": "anwesenheit"} for x in attendance]))

    if a.darf("rollen"):
        rollen_treffer = (db.query(Role).filter(_suchfilter_mehrere(Role, begriff))
                          .order_by(Role.key).limit(4).all())
        abteilungen_treffer = (db.query(Department)
                               .filter(_suchfilter_mehrere(Department, begriff))
                               .order_by(Department.key).limit(4).all())
        if rollen_treffer:
            gruppen.append(("Rollen", [
                {"text": r.label, "meta": r.key, "bereich": "rollen"}
                for r in rollen_treffer]))
        if abteilungen_treffer:
            gruppen.append(("Abteilungen", [
                {"text": d.label, "meta": d.key, "bereich": "rollen"}
                for d in abteilungen_treffer]))

    if a.darf("seiteninhalte"):
        inhalte = (db.query(ContentItem).filter(
                   _suchfilter_mehrere(ContentItem, begriff))
                   .order_by(ContentItem.id.desc()).limit(4).all())
        if inhalte:
            gruppen.append(("Startseiten-Inhalte", [
                {"text": x.titel, "meta": x.abteilung, "bereich": "redaktion"}
                for x in inhalte]))

    if a.darf("email_vorlagen"):
        vorlagen = (db.query(EmailTemplate)
                    .filter(_suchfilter_mehrere(EmailTemplate, begriff))
                    .order_by(EmailTemplate.updated_at.desc()).limit(4).all())
        if vorlagen:
            gruppen.append(("E-Mail-Vorlagen", [
                {"text": x.key, "meta": x.subject, "bereich": "vordrucke"}
                for x in vorlagen]))

    if a.darf("finanzen"):
        for modell, name, bereich in (
                (Buchung, "Buchungen", "kassenbuch"),
                (Budget, "Budgets", "kassenbuch"),
                (Dauerauftrag, "Daueraufträge", "kassenbuch")):
            treffer = (db.query(modell).filter(
                       _suchfilter_mehrere(modell, begriff))
                       .limit(4).all())
            if treffer:
                gruppen.append((name, [
                    {"text": next((str(getattr(x, feld)) for feld in
                                   ("zweck", "name", "titel", "beschreibung")
                                   if getattr(x, feld, None)), f"#{x.id}"),
                     "meta": f"#{x.id}", "bereich": bereich} for x in treffer]))

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
