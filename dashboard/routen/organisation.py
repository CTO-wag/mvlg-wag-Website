"""AG-Treffen, Kalender, Redaktionsplan."""

import os
import secrets
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, Response

from dashboard.hilfen import (
    Anmeldung, datum, fehler, gut, papierkorb_hinweis, teil, uhrzeit, warnung, zahl,
)
from kern import benachrichtigung, kalender, leistung, papierkorb, protokoll
from kern import einstellungen as cfg
from kern.modelle import (
    Attendance, CalendarEvent, CalendarEventTarget, ContentAttachment,
    ContentItem, Meeting, User,
    MeetingPunkt, MeetingRueckmeldung,
)
from kern.rechte import (
    abteilungs_keys, darf_ideensammlung, darf_redaktionsplan,
    redaktions_abteilungen,
)
from kern.text import sauber, utcnow

router = APIRouter(prefix="/dashboard")


#  AG-Treffen
def _treffen_ansicht(a: Anmeldung, meldung=None):
    db = a.db
    treffen = db.query(Meeting).order_by(Meeting.date.desc()).limit(60).all()
    anwesend = {}
    for eintrag, person in (db.query(Attendance, User)
                            .join(User, User.id == Attendance.user_id)
                            .filter(Attendance.meeting_id.isnot(None)).all()):
        anwesend.setdefault(eintrag.meeting_id, []).append(person)

    # Zu- und Absagen je Treffen, und was diese Person selbst geantwortet hat.
    zusagen, absagen, eigene = {}, {}, {}
    for r, person in (db.query(MeetingRueckmeldung, User)
                      .join(User, User.id == MeetingRueckmeldung.user_id).all()):
        korb = zusagen if r.antwort == "ja" else absagen
        korb.setdefault(r.meeting_id, []).append((person, r.grund))
        if r.user_id == a.user.id:
            eigene[r.meeting_id] = r

    punkte = {}
    for punkt, person in (db.query(MeetingPunkt, User)
                          .outerjoin(User, User.id == MeetingPunkt.user_id)
                          .order_by(MeetingPunkt.created_at).all()):
        punkte.setdefault(punkt.meeting_id, []).append((punkt, person))

    return teil("dashboard/treffen.html", a, treffen=treffen, anwesend=anwesend,
                personen=db.query(User).filter(User.status == "aktiv")
                          .order_by(User.vorname).all(),
                zusagen=zusagen, absagen=absagen, eigene_antwort=eigene,
                punkte=punkte,
                darf_verwalten=a.darf("meetings_manage"),
                meldung=meldung)


@router.get("/treffen")
def treffen(a: Anmeldung = Depends(Anmeldung.pflicht)):
    return _treffen_ansicht(a)


@router.post("/treffen")
def treffen_anlegen(titel: str = Form(""), wann: str = Form(""),
                    protokoll_text: str = Form(""), csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("meetings_manage")
    a.pruefe_csrf(csrf)
    titel_ = sauber(titel)[:200]
    if not titel_:
        return _treffen_ansicht(a, fehler("Ohne Titel geht es nicht."))
    tag = datum(wann) or date.today()
    a.db.add(Meeting(title=titel_, date=tag,
                     protocol=sauber(protokoll_text)[:20000] or None))
    protokoll.notiere(a.db, a.user.id, "treffen_neu", titel_)
    a.db.commit()
    # Nur ankuendigen, was noch kommt - ein nachgetragenes Protokoll von
    # letzter Woche muss niemandem auf dem Handy klingeln.
    if tag >= date.today():
        benachrichtigung.melde_vielen(
            a.db, a.db.query(User).filter(User.status == "aktiv").all(),
            "messages", "AG-Treffen", f"„{titel_}“ am {tag.strftime('%d.%m.%Y')}.",
            ausser_id=a.user.id)
    return _treffen_ansicht(a, gut("Treffen angelegt."))


@router.post("/treffen/{treffen_id}/antwort")
def treffen_antwort(treffen_id: int, antwort: str = Form("ja"),
                    grund: str = Form(""), csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Zusagen oder absagen. Jeder fuer sich, jederzeit aenderbar.

    Bewusst kein eigenes Recht: Ueber das eigene Kommen entscheidet jeder
    selbst. Und bewusst aenderbar - eine Absage am Montag ist keine
    Entscheidung fuer alle Zeit.
    """
    a.pruefe_csrf(csrf)
    treffen = a.db.get(Meeting, treffen_id)
    if not treffen:
        return _treffen_ansicht(a, fehler("Dieses Treffen gibt es nicht mehr."))
    wert = "nein" if sauber(antwort) == "nein" else "ja"
    eintrag = (a.db.query(MeetingRueckmeldung)
               .filter(MeetingRueckmeldung.meeting_id == treffen_id,
                       MeetingRueckmeldung.user_id == a.user.id).first())
    if not eintrag:
        eintrag = MeetingRueckmeldung(meeting_id=treffen_id, user_id=a.user.id)
        a.db.add(eintrag)
    eintrag.antwort = wert
    eintrag.grund = sauber(grund)[:200] or None
    a.db.flush()
    # Die Ansage zaehlt fuer den Leadership-Wert - vorlaeufig jetzt, endgueltig
    # nach dem Treffen (kern/leistung.py). Deshalb hier und nicht erst nachts:
    # Wer zusagt, soll die Wirkung sehen, sonst verbindet er sie nie mit der
    # eigenen Handlung.
    leistung.rueckmeldung_erfasst(a.db, eintrag)
    a.db.commit()
    leistung.anstossen([a.user.id])
    if wert == "ja":
        return _treffen_ansicht(a, gut("Zugesagt. Bis dann."))
    return _treffen_ansicht(a, gut("Abgesagt. Der Vorstand sieht das in der "
                                   "Liste."))


@router.post("/treffen/{treffen_id}/punkt")
def treffen_punkt(treffen_id: int, text: str = Form(""),
                  csrf: str = Form(""),
                  a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Einen Punkt fuer die Tagesordnung eintragen - vor dem Treffen."""
    a.pruefe_csrf(csrf)
    treffen = a.db.get(Meeting, treffen_id)
    if not treffen:
        return _treffen_ansicht(a, fehler("Dieses Treffen gibt es nicht mehr."))
    inhalt = sauber(text)[:300]
    if not inhalt:
        return _treffen_ansicht(a, fehler("Ohne Text kein Punkt."))
    a.db.add(MeetingPunkt(meeting_id=treffen_id, user_id=a.user.id,
                          text=inhalt))
    a.db.commit()
    return _treffen_ansicht(a, gut("Steht auf der Tagesordnung."))


@router.post("/treffen/punkt/{punkt_id}/abhaken")
def treffen_punkt_abhaken(punkt_id: int, csrf: str = Form(""),
                          a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Waehrend des Treffens abhaken - besprochen.

    Gemeldet: "jeder kann Treffen bearbeiten". Genau hier war es so. Anlegen,
    Aendern und Loeschen hingen von Anfang an am Recht "AG-Treffen", dieser
    eine Handgriff nicht - und er ist keine Kleinigkeit: Ein Haken sagt "das
    haben wir besprochen". Wer ihn setzt oder wieder wegnimmt, aendert das
    Protokoll eines Treffens, auch eines laengst vergangenen.

    Eintragen darf weiterhin jeder (siehe treffen_punkt), und den eigenen
    Punkt auch jeder wieder zuruecknehmen. Nur das Abhaken gehoert dem, der
    das Treffen fuehrt.
    """
    a.verlange("meetings_manage")
    a.pruefe_csrf(csrf)
    punkt = a.db.get(MeetingPunkt, punkt_id)
    if not punkt:
        return _treffen_ansicht(a, fehler("Diesen Punkt gibt es nicht mehr."))
    punkt.erledigt = 0 if punkt.erledigt else 1
    a.db.commit()
    return _treffen_ansicht(a)


@router.post("/treffen/punkt/{punkt_id}/loeschen")
def treffen_punkt_loeschen(punkt_id: int, csrf: str = Form(""),
                           a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Den eigenen Punkt zuruecknehmen - oder jeden, wer Treffen verwaltet."""
    a.pruefe_csrf(csrf)
    punkt = a.db.get(MeetingPunkt, punkt_id)
    if not punkt:
        return _treffen_ansicht(a, fehler("Diesen Punkt gibt es nicht mehr."))
    if punkt.user_id != a.user.id and not a.darf("meetings_manage"):
        return _treffen_ansicht(a, fehler("Das ist nicht dein Punkt."))
    a.db.delete(punkt)
    a.db.commit()
    return _treffen_ansicht(a, gut("Punkt entfernt."))


@router.post("/treffen/{treffen_id}/aendern")
def treffen_aendern(treffen_id: int, titel: str = Form(""),
                    wann: str = Form(""), protokoll_text: str = Form(""),
                    csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("meetings_manage")
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(Meeting, treffen_id)
    if not eintrag:
        return _treffen_ansicht(a, fehler("Dieses Treffen gibt es nicht mehr."))
    if sauber(titel):
        eintrag.title = sauber(titel)[:200]
    neues_datum = datum(wann)
    if neues_datum:
        eintrag.date = neues_datum
    eintrag.protocol = sauber(protokoll_text)[:20000] or None
    a.db.commit()
    return _treffen_ansicht(a, gut("Gespeichert."))


@router.post("/treffen/{treffen_id}/loeschen")
def treffen_loeschen(treffen_id: int, csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("meetings_manage")
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(Meeting, treffen_id)
    if eintrag:
        papierkorb.hinein(a.db, "meeting", eintrag, a.user.id)
        a.db.commit()
    return _treffen_ansicht(a,
        papierkorb_hinweis("Das Treffen liegt im Papierkorb – 30 Tage lang "
                          "wiederherstellbar."))


#  Kalender
def _kalender_ansicht(a: Anmeldung, meldung=None):
    db, user = a.db, a.user
    heute = date.today()
    kommende = (db.query(CalendarEvent)
                .filter(CalendarEvent.start_date >= heute - timedelta(days=1))
                .order_by(CalendarEvent.start_date,
                          CalendarEvent.start_time.asc().nullsfirst())
                .limit(80).all())
    vergangene = (db.query(CalendarEvent)
                  .filter(CalendarEvent.start_date < heute - timedelta(days=1))
                  .order_by(CalendarEvent.start_date.desc()).limit(20).all())
    sichtbar = [t for t in kommende if kalender.sichtbar_fuer(t, user)]
    # Gemeldet: "Kalender-Anzeige zeigt AG-Treffen nicht an". Sie standen nur
    # unter "Treffen" und im Abo, nicht hier - wer sich einen Ueberblick ueber
    # die naechsten Wochen holen wollte, sah alles ausser dem Wichtigsten.
    # Bearbeitet werden sie weiterhin dort, wo sie hingehoeren; hier stehen
    # sie zum Lesen, mit einem Weg dorthin.
    treffen = (db.query(Meeting)
               .filter(Meeting.date >= heute - timedelta(days=1))
               .order_by(Meeting.date).limit(20).all())
    return teil("dashboard/kalender.html", a,
                termine=sichtbar, treffen=treffen,
                vergangene=[t for t in vergangene if kalender.sichtbar_fuer(t, user)],
                abo_adresse=kalender.abo_adresse(db, user),
                personen=db.query(User).filter(User.status == "aktiv")
                          .order_by(User.vorname).all(),
                abteilungen_wahl=abteilungs_keys(),
                darf_verwalten=a.darf("kalender_verwalten"),
                meldung=meldung)


@router.get("/kalender")
def kalender_bereich(a: Anmeldung = Depends(Anmeldung.pflicht)):
    return _kalender_ansicht(a)


def _ziele_setzen(db, termin, art, person_id, abteilung, auswahl_personen,
                  auswahl_abteilungen):
    termin.target_type = art if art in ("alle", "person", "abteilung", "auswahl") else "alle"
    termin.target_user_id = None
    termin.target_department = None
    termin.targets.clear()
    if termin.target_type == "person":
        termin.target_user_id = zahl(person_id)
    elif termin.target_type == "abteilung":
        termin.target_department = abteilung if abteilung in abteilungs_keys() else None
    elif termin.target_type == "auswahl":
        for pid in {zahl(p) for p in auswahl_personen if zahl(p)}:
            termin.targets.append(CalendarEventTarget(user_id=pid))
        for key in {sauber(d) for d in auswahl_abteilungen}:
            if key in abteilungs_keys():
                termin.targets.append(CalendarEventTarget(department=key))


@router.post("/kalender")
def termin_anlegen(titel: str = Form(""), beschreibung: str = Form(""),
                   ort: str = Form(""), von: str = Form(""),
                   bis: str = Form(""), start: str = Form(""),
                   ende: str = Form(""), ziel: str = Form("alle"),
                   person: str = Form(""), abteilung: str = Form(""),
                   auswahl_person: list = Form([]),
                   auswahl_abteilung: list = Form([]),
                   csrf: str = Form(""),
                   a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("kalender_verwalten")
    a.pruefe_csrf(csrf)
    titel_ = sauber(titel)[:200]
    tag = datum(von)
    if not titel_ or not tag:
        return _kalender_ansicht(a, fehler("Titel und Datum werden gebraucht."))

    termin = CalendarEvent(
        title=titel_, description=sauber(beschreibung)[:4000] or None,
        location=sauber(ort)[:200] or None, start_date=tag,
        end_date=datum(bis), start_time=uhrzeit(start) or None,
        end_time=uhrzeit(ende) or None, created_by=a.user.id)
    _ziele_setzen(a.db, termin, ziel, person, abteilung,
                  auswahl_person, auswahl_abteilung)
    a.db.add(termin)
    a.db.commit()

    betroffene = kalender.betroffene_personen(a.db, termin)
    benachrichtigung.melde_vielen(
        a.db, betroffene, "messages", "Neuer Termin",
        f"„{titel_}“ am {tag.strftime('%d.%m.%Y')}"
        + (f" um {termin.start_time} Uhr" if termin.start_time else ""),
        ausser_id=a.user.id)
    return _kalender_ansicht(a, gut(
        f"Termin angelegt – {len(betroffene)} Person(en) betroffen."))


@router.post("/kalender/{termin_id}/aendern")
def termin_aendern(termin_id: int, titel: str = Form(""),
                   beschreibung: str = Form(""), ort: str = Form(""),
                   von: str = Form(""), bis: str = Form(""),
                   start: str = Form(""), ende: str = Form(""),
                   ziel: str = Form("alle"), person: str = Form(""),
                   abteilung: str = Form(""),
                   auswahl_person: list = Form([]),
                   auswahl_abteilung: list = Form([]),
                   csrf: str = Form(""),
                   a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("kalender_verwalten")
    a.pruefe_csrf(csrf)
    termin = a.db.get(CalendarEvent, termin_id)
    if not termin:
        return _kalender_ansicht(a, fehler("Diesen Termin gibt es nicht mehr."))
    if sauber(titel):
        termin.title = sauber(titel)[:200]
    termin.description = sauber(beschreibung)[:4000] or None
    termin.location = sauber(ort)[:200] or None
    neues_datum = datum(von)
    if neues_datum:
        termin.start_date = neues_datum
    termin.end_date = datum(bis)
    termin.start_time = uhrzeit(start) or None
    termin.end_time = uhrzeit(ende) or None
    _ziele_setzen(a.db, termin, ziel, person, abteilung,
                  auswahl_person, auswahl_abteilung)
    termin.updated_at = utcnow()
    a.db.commit()
    return _kalender_ansicht(a, gut("Termin gespeichert."))


@router.post("/kalender/{termin_id}/loeschen")
def termin_loeschen(termin_id: int, csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("kalender_verwalten")
    a.pruefe_csrf(csrf)
    termin = a.db.get(CalendarEvent, termin_id)
    if termin:
        papierkorb.hinein(a.db, "calendar_event", termin, a.user.id)
        a.db.commit()
    return _kalender_ansicht(a,
        papierkorb_hinweis("Der Termin liegt im Papierkorb – 30 Tage lang "
                           "wiederherstellbar."))


@router.post("/kalender/abo-erneuern")
def abo_erneuern(csrf: str = Form(""),
                 a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Neue Abo-Adresse erzeugen - die alte wird damit ungueltig."""
    a.pruefe_csrf(csrf)
    a.user.calendar_token = secrets.token_urlsafe(24)[:48]
    a.db.commit()
    return _kalender_ansicht(a, gut(
        "Neue Adresse erzeugt. Die alte funktioniert nicht mehr – in der "
        "Kalender-App muss das Abo neu eingetragen werden."))


@router.post("/kalender/abo-pruefen")
def kalender_abo_pruefen(csrf: str = Form(""),
                         a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Nachsehen, was eine Kalender-App an dieser Adresse vorfindet."""
    a.pruefe_csrf(csrf)
    from kern.kalender_abo import pruefe
    adresse = kalender.abo_adresse(a.db, a.user)
    geklappt, meldung = pruefe(adresse)
    return _kalender_ansicht(a, (gut if geklappt else fehler)(meldung))


# Die Auslieferung des Abos steht in kern/kalender_abo.py und haengt an
# BEIDEN Anwendungen - siehe dort. Hier ist deshalb nichts mehr.


#  Redaktionsplan
def _redaktion_ansicht(a: Anmeldung, meldung=None):
    db, user = a.db, a.user
    meine = [x["key"] for x in redaktions_abteilungen(user, db)]
    if not meine:
        return teil("dashboard/redaktion.html", a, ideen=[], geplant=[],
                    anhaenge={}, abteilungen_wahl=[], personen=[],
                    meldung=warnung("Für deine Abteilung ist der Redaktionsplan "
                                    "nicht freigeschaltet."))
    eintraege = (db.query(ContentItem)
                 .filter(ContentItem.abteilung.in_(meine))
                 .order_by(ContentItem.datum.is_(None), ContentItem.datum,
                           ContentItem.id.desc()).all())
    anhaenge = {}
    for anhang in db.query(ContentAttachment).filter(
            ContentAttachment.item_id.in_([e.id for e in eintraege] or [0])).all():
        anhaenge.setdefault(anhang.item_id, []).append(anhang)
    return teil("dashboard/redaktion.html", a,
                ideen=[e for e in eintraege if not e.datum],
                geplant=[e for e in eintraege if e.datum],
                anhaenge=anhaenge, abteilungen_wahl=meine,
                personen=db.query(User).filter(User.status == "aktiv")
                          .order_by(User.vorname).all(),
                meldung=meldung)


@router.get("/redaktion")
def redaktion(a: Anmeldung = Depends(Anmeldung.pflicht)):
    if not (darf_redaktionsplan(a.user, a.db) or darf_ideensammlung(a.user, a.db)):
        a.verlange("redaktion")
    return _redaktion_ansicht(a)


@router.post("/redaktion")
def redaktion_anlegen(titel: str = Form(""), abteilung: str = Form(""),
                      kanal: str = Form("sonstiges"), wann: str = Form(""),
                      verantwortlich: str = Form(""), notiz: str = Form(""),
                      csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    if not (darf_redaktionsplan(a.user, a.db) or darf_ideensammlung(a.user, a.db)):
        a.verlange("redaktion")
    a.pruefe_csrf(csrf)
    titel_ = sauber(titel)[:160]
    meine = [x["key"] for x in redaktions_abteilungen(a.user, a.db)]
    if not titel_:
        return _redaktion_ansicht(a, fehler("Ohne Titel geht es nicht."))
    if abteilung not in meine:
        abteilung = meine[0] if meine else "marketing"
    a.db.add(ContentItem(
        abteilung=abteilung, titel=titel_,
        kanal=kanal if kanal in ("instagram", "aushang", "website",
                                 "newsletter", "sonstiges") else "sonstiges",
        datum=datum(wann),
        status="geplant" if datum(wann) else "idee",
        verantwortlich_id=zahl(verantwortlich),
        notiz=sauber(notiz)[:4000] or None, creator_id=a.user.id))
    a.db.commit()
    return _redaktion_ansicht(a, gut("Eintrag angelegt."))


@router.post("/redaktion/{item_id}/aendern")
def redaktion_aendern(item_id: int, titel: str = Form(""),
                      kanal: str = Form(""), wann: str = Form(""),
                      status: str = Form(""), verantwortlich: str = Form(""),
                      notiz: str = Form(""), csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(ContentItem, item_id)
    meine = [x["key"] for x in redaktions_abteilungen(a.user, a.db)]
    if not eintrag or eintrag.abteilung not in meine:
        return _redaktion_ansicht(a, fehler("Dieser Eintrag gehört zu einer anderen Abteilung."))
    if sauber(titel):
        eintrag.titel = sauber(titel)[:160]
    if kanal:
        eintrag.kanal = kanal
    eintrag.datum = datum(wann)
    # Ein Datum macht aus einer Idee einen Planeintrag - und umgekehrt.
    if status in ("idee", "geplant", "in_arbeit", "veroeffentlicht"):
        eintrag.status = status
    elif eintrag.datum and eintrag.status == "idee":
        eintrag.status = "geplant"
    eintrag.verantwortlich_id = zahl(verantwortlich)
    eintrag.notiz = sauber(notiz)[:4000] or None
    eintrag.updated_at = utcnow()
    a.db.commit()
    return _redaktion_ansicht(a, gut("Gespeichert."))


@router.post("/redaktion/{item_id}/loeschen")
def redaktion_loeschen(item_id: int, csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(ContentItem, item_id)
    meine = [x["key"] for x in redaktions_abteilungen(a.user, a.db)]
    if eintrag and eintrag.abteilung in meine:
        for anhang in a.db.query(ContentAttachment).filter(
                ContentAttachment.item_id == eintrag.id).all():
            _datei_weg(anhang.speichername)
        papierkorb.hinein(a.db, "content_item", eintrag, a.user.id)
        a.db.commit()
    return _redaktion_ansicht(a,
        papierkorb_hinweis("Der Eintrag liegt im Papierkorb – 30 Tage lang "
                            "wiederherstellbar."))


def _datei_weg(speichername: str) -> None:
    try:
        pfad = os.path.join(cfg.REDAKTION_UPLOAD_DIR, speichername)
        if os.path.exists(pfad):
            os.remove(pfad)
    except OSError:
        pass


@router.post("/redaktion/{item_id}/datei")
async def redaktion_datei(item_id: int, datei: UploadFile = File(...),
                          csrf: str = Form(""),
                          a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(ContentItem, item_id)
    meine = [x["key"] for x in redaktions_abteilungen(a.user, a.db)]
    if not eintrag or eintrag.abteilung not in meine:
        return _redaktion_ansicht(a, fehler("Dieser Eintrag gehört zu einer anderen Abteilung."))

    inhalt = await datei.read()
    if len(inhalt) > cfg.MAX_REDAKTION_BYTES:
        return _redaktion_ansicht(a, fehler(
            f"Die Datei ist zu groß (höchstens "
            f"{cfg.MAX_REDAKTION_BYTES // 1024 // 1024} MB)."))
    endung = cfg.ERLAUBTE_ANHANGTYPEN.get(datei.content_type or "")
    if not endung:
        return _redaktion_ansicht(a, fehler(
            "Erlaubt sind Bilder (PNG, JPG, WebP, GIF) und PDF."))

    # Zufallsname auf der Platte, echter Name nur in der Datenbank: So kann
    # ein Dateiname aus dem Netz nie einen Pfad bestimmen.
    speichername = secrets.token_hex(16) + endung
    os.makedirs(cfg.REDAKTION_UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(cfg.REDAKTION_UPLOAD_DIR, speichername), "wb") as ziel:
        ziel.write(inhalt)
    a.db.add(ContentAttachment(
        item_id=eintrag.id, dateiname=(datei.filename or "datei")[:160],
        speichername=speichername, groesse=len(inhalt),
        hochgeladen_von=a.user.id))
    a.db.commit()
    return _redaktion_ansicht(a, gut("Datei hinzugefügt."))


@router.get("/redaktion/datei/{anhang_id}")
def redaktion_datei_holen(anhang_id: int,
                          a: Anmeldung = Depends(Anmeldung.pflicht)):
    anhang = a.db.get(ContentAttachment, anhang_id)
    if not anhang:
        return Response("Nicht gefunden", status_code=404, media_type="text/plain")
    eintrag = a.db.get(ContentItem, anhang.item_id)
    meine = [x["key"] for x in redaktions_abteilungen(a.user, a.db)]
    if not eintrag or eintrag.abteilung not in meine:
        return Response("Kein Zugriff", status_code=403, media_type="text/plain")
    pfad = os.path.join(cfg.REDAKTION_UPLOAD_DIR, anhang.speichername)
    if not os.path.exists(pfad):
        return Response("Datei fehlt", status_code=404, media_type="text/plain")
    return FileResponse(pfad, filename=anhang.dateiname)


@router.post("/redaktion/datei/{anhang_id}/loeschen")
def redaktion_datei_weg(anhang_id: int, csrf: str = Form(""),
                        a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    anhang = a.db.get(ContentAttachment, anhang_id)
    if anhang:
        eintrag = a.db.get(ContentItem, anhang.item_id)
        meine = [x["key"] for x in redaktions_abteilungen(a.user, a.db)]
        if eintrag and eintrag.abteilung in meine:
            _datei_weg(anhang.speichername)
            a.db.delete(anhang)
            a.db.commit()
    return _redaktion_ansicht(a, gut("Datei entfernt."))
