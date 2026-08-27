"""Nachrichten, Support, E-Mail-Vordrucke, WhatsApp-Bot."""

import os
import secrets

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from sqlalchemy import func

from dashboard.hilfen import (
    Anmeldung, fehler, gut, info, papierkorb_hinweis, teil, warnung, zahl,
)
from kern import (
    benachrichtigung, mail, papierkorb, protokoll, push, push_anmeldung, werte,
    support_ki, whatsapp,
)
from kern import einstellungen as cfg
from kern.modelle import (
    ContactMessage, DeliveryLog, DirectMessage, DirectMessageRecipient,
    PushSubscription, SupportMessage, SupportTicket, User, WhatsAppNachricht,
)
from kern.sicherheit import geraet_beschreiben
from kern.text import kuerzen, sauber, utcnow

router = APIRouter(prefix="/dashboard")


#  Nachrichten (Postfach + eigene Zustellwege + Rundnachricht)
def _nachrichten_ansicht(a: Anmeldung, meldung=None, versand=None):
    db, user = a.db, a.user
    eingang = (db.query(DirectMessageRecipient, DirectMessage)
               .join(DirectMessage, DirectMessage.id == DirectMessageRecipient.message_id)
               .filter(DirectMessageRecipient.user_id == user.id)
               .order_by(DirectMessage.created_at.desc()).limit(60).all())
    pref = benachrichtigung.einstellung(db, user.id)
    geraete = push.geraete(db, user.id)

    kontakt = []
    if a.darf("nachrichten"):
        kontakt = (db.query(ContactMessage)
                   .order_by(ContactMessage.created_at.desc()).limit(40).all())

    empfaenger = []
    if a.darf("benachrichtigungen_admin"):
        alle = db.query(User).filter(User.status == "aktiv").order_by(
            User.department, User.vorname).all()
        prefs = benachrichtigung.einstellungen_fuer(db, alle)
        for person in alle:
            p = prefs.get(person.id)
            wege = []
            if p and p.webpush and push.geraete(db, person.id):
                wege.append("Push")
            if p and p.ntfy:
                wege.append("ntfy")
            if p and p.email and mail.versand_moeglich():
                wege.append("Mail")
            empfaenger.append({"person": person, "wege": wege,
                               "nur_mail": wege == ["Mail"]})

    protokoll_zeilen = []
    if a.darf("benachrichtigungen_admin"):
        protokoll_zeilen = (db.query(DeliveryLog)
                            .order_by(DeliveryLog.created_at.desc()).limit(40).all())

    return teil("dashboard/nachrichten.html", a,
                eingang=eingang, pref=pref, geraete=geraete,
                geraet_name=geraet_beschreiben,
                kategorien=benachrichtigung.KATEGORIEN,
                erlaubt=benachrichtigung.kategorien_erlaubt(user, db),
                kontakt=kontakt, empfaenger=empfaenger,
                zustellprotokoll=protokoll_zeilen,
                mail_moeglich=mail.versand_moeglich(),
                push_testmodus=werte.an_db(db, werte.PUSH_TESTMODUS),
                versand=versand, meldung=meldung)


@router.get("/nachrichten")
def nachrichten(a: Anmeldung = Depends(Anmeldung.pflicht)):
    # Beim Öffnen als gelesen markieren - ein extra Klick dafür wäre nur
    # Arbeit ohne Nutzen.
    a.db.query(DirectMessageRecipient).filter(
        DirectMessageRecipient.user_id == a.user.id,
        DirectMessageRecipient.read_at.is_(None)).update(
            {"read_at": utcnow()}, synchronize_session=False)
    a.db.commit()
    return _nachrichten_ansicht(a)


@router.post("/nachrichten/einstellungen")
def zustellwege(enabled: str = Form(""), webpush: str = Form(""),
                ntfy: str = Form(""), email: str = Form(""),
                kategorien: list = Form([]), csrf: str = Form(""),
                a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    from dashboard.hilfen import uhrzeit
    pref = benachrichtigung.einstellung(a.db, a.user.id)
    pref.enabled = 1 if enabled else 0
    pref.webpush = 1 if webpush else 0
    pref.ntfy = 1 if ntfy else 0
    pref.email = 1 if email else 0
    for kategorie in benachrichtigung.KATEGORIEN:
        setattr(pref, kategorie, 1 if kategorie in kategorien else 0)
    a.db.commit()
    return _nachrichten_ansicht(a, gut("Deine Zustellwege sind gespeichert."))


@router.get("/nachrichten/push-schluessel", include_in_schema=False)
def push_schluessel(a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Der oeffentliche VAPID-Schluessel - den braucht der Browser zum Anmelden."""
    _, oeffentlich = push.vapid_schluessel(a.db)
    return PlainTextResponse(oeffentlich)


@router.post("/nachrichten/push-anmelden")
def push_anmelden(endpoint: str = Form(""), p256dh: str = Form(""),
                  auth: str = Form(""), csrf: str = Form(""),
                  a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    erfolg, kennung = push_anmeldung.anmelden(
        a.db, a.request, a.user, endpoint, p256dh, auth, ursprung="dashboard")
    if not erfolg:
        return PlainTextResponse("Unvollständig", status_code=400)
    antwort = PlainTextResponse("ok")
    push_anmeldung.kennung_mitgeben(antwort, kennung)
    return antwort


@router.post("/nachrichten/push-abmelden")
def push_abmelden(endpoint: str = Form(""), csrf: str = Form(""),
                  a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    push_anmeldung.abmelden(a.db, a.user, endpoint)
    return PlainTextResponse("ok")


@router.post("/nachrichten/geraet/{abo_id}/entfernen")
def geraet_entfernen(abo_id: int, csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    abo = a.db.get(PushSubscription, abo_id)
    if abo and abo.user_id == a.user.id:
        a.db.delete(abo)
        a.db.commit()
    return _nachrichten_ansicht(a, gut("Gerät entfernt."))


@router.post("/nachrichten/test")
def test_meldung(csrf: str = Form(""),
                 a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Eine Probemeldung an die eigenen Geraete - mit ehrlicher Bilanz."""
    a.pruefe_csrf(csrf)
    pref = benachrichtigung.einstellung(a.db, a.user.id)
    ergebnisse = []
    if pref.webpush:
        ok, grund = push.webpush_an_person(
            a.user.id, "Probemeldung", "Wenn du das liest, kommt Push an.",
            warten=True, ziel=a.user.name, anlass="test")
        ergebnisse.append(("Push", ok, grund))
    if pref.ntfy:
        ok, grund = push.ntfy_an_thema(
            pref.topic, "Probemeldung", "Wenn du das liest, kommt ntfy an.",
            warten=True, ziel=a.user.name, anlass="test")
        ergebnisse.append(("ntfy", ok, grund))
    if pref.email and mail.versand_moeglich():
        ok = mail.sende_vordruck(a.db, a.user, "notification", warten=True,
                                 titel="Probemeldung",
                                 text="Wenn du das liest, kommt E-Mail an.")
        ergebnisse.append(("E-Mail", ok, "" if ok else "Versand fehlgeschlagen"))

    if not ergebnisse:
        return _nachrichten_ansicht(a, warnung(
            "Es ist kein Zustellweg eingeschaltet – deshalb ging nichts raus."))
    geklappt = [n for n, ok, _ in ergebnisse if ok]
    schief = [f"{n} ({g})" for n, ok, g in ergebnisse if not ok]
    text = ""
    if geklappt:
        text += "Verschickt über: " + ", ".join(geklappt) + ". "
    if schief:
        text += "Nicht geklappt: " + "; ".join(schief) + "."
    return _nachrichten_ansicht(a, gut(text) if geklappt else fehler(text))


@router.post("/nachrichten/senden")
def rundnachricht(betreff: str = Form(""), text: str = Form(""),
                  empfaenger: list = Form([]), kanaele: list = Form([]),
                  csrf: str = Form(""),
                  a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("benachrichtigungen_admin")
    a.pruefe_csrf(csrf)
    db, user = a.db, a.user

    betreff_ = sauber(betreff)[:160]
    inhalt = sauber(text)[:4000]
    ids = {zahl(e) for e in empfaenger if zahl(e)}
    if not betreff_ or not inhalt:
        return _nachrichten_ansicht(a, fehler("Betreff und Text werden gebraucht."))
    if not ids:
        return _nachrichten_ansicht(a, fehler("Bitte mindestens eine Person auswählen."))

    personen = db.query(User).filter(User.id.in_(ids), User.status == "aktiv").all()
    nachricht = DirectMessage(sender_id=user.id, subject=betreff_, body=inhalt)
    db.add(nachricht)
    db.flush()
    for person in personen:
        db.add(DirectMessageRecipient(message_id=nachricht.id, user_id=person.id))
    protokoll.notiere(db, user.id, "rundnachricht",
                      f"{len(personen)} Empfänger: {kuerzen(betreff_, 80)}")
    db.commit()

    gewaehlt = {k for k in kanaele if k in ("webpush", "ntfy", "email")}
    bilanz = benachrichtigung.verteile(db, personen, gewaehlt, betreff_, inhalt)
    return _nachrichten_ansicht(
        a, gut(f"Nachricht liegt im Postfach von {len(personen)} Person(en)."),
        versand=bilanz)


@router.post("/nachrichten/{eintrag_id}/loeschen")
def postfach_loeschen(eintrag_id: int, csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(DirectMessageRecipient, eintrag_id)
    if eintrag and eintrag.user_id == a.user.id:
        a.db.delete(eintrag)
        a.db.commit()
    return _nachrichten_ansicht(a, gut("Aus deinem Postfach entfernt."))


@router.post("/nachrichten/kontakt/{msg_id}/antwort")
def kontakt_antwort(msg_id: int, antwort: str = Form(""),
                    csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Eine Anfrage von der Website beantworten - per E-Mail.

    Ueber das Kontaktformular schreiben Leute, die kein Konto haben und keins
    bekommen werden: Eltern, Interessenten, die Schule. Eine Antwort, die nur
    im Dashboard steht, erreicht sie nie. Der einzige Rueckweg ist die
    Adresse, die sie selbst angegeben haben - und Mail kann die Plattform.

    Drei Dinge sind hier anders als beim uebrigen Mailversand:

    * **Eigener Vordruck** (`contact_reply`). Der Benachrichtigungsrahmen
      haette einen Dashboard-Link und einen Abmeldehinweis mitgeschickt,
      beides sinnlos fuer jemanden von aussen.
    * **Es wird gewartet** (`warten=True`). Sonst stuende in der Rueckmeldung
      "verschickt", waehrend der Faden im Hintergrund noch scheitert - und
      der Fehler faende sich nur im Zustellprotokoll.
    * **Reply-To auf die antwortende Person.** Wer zurueckschreibt, soll bei
      der ankommen, die geantwortet hat, nicht in einem Sammelpostfach.
    """
    a.verlange("nachrichten")
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(ContactMessage, msg_id)
    if not eintrag:
        return _nachrichten_ansicht(a, fehler("Diese Anfrage gibt es nicht mehr."))
    text = sauber(antwort)[:4000]
    if not text:
        return _nachrichten_ansicht(a, fehler("Ohne Text keine Antwort."))

    if not mail.versand_moeglich():
        # Nicht als beantwortet vermerken. Sonst verschwindet die Anfrage aus
        # der offenen Liste, ohne dass je jemand etwas bekommen hat.
        return _nachrichten_ansicht(a, fehler(
            "Es ist kein Mailversand eingerichtet - die Antwort waere bei "
            f"{eintrag.email} nie angekommen. Bitte SMTP in der config.cmd "
            "hinterlegen oder direkt aus dem eigenen Postfach schreiben."))

    versandt, grund = _kontakt_mail(a, eintrag, text)

    eintrag.reply = _antwort_anhaengen(eintrag.reply, text)
    eintrag.replied_by = a.user.id
    eintrag.replied_at = utcnow()
    eintrag.reply_mail_ok = 1 if versandt else 0
    eintrag.reply_mail_fehler = None if versandt else (grund or "")[:300]
    a.db.commit()

    if versandt:
        return _nachrichten_ansicht(a, gut(
            f"Antwort an {eintrag.email} verschickt."))
    return _nachrichten_ansicht(a, fehler(
        f"Die Antwort ist gespeichert, aber NICHT bei {eintrag.email} "
        f"angekommen: {grund or 'Grund unbekannt'}. Bitte noch einmal "
        "abschicken oder direkt aus dem eigenen Postfach schreiben."))


def _kontakt_mail(a: Anmeldung, eintrag, text: str) -> tuple:
    """(verschickt, Fehlergrund) - die Antwortmail an eine Kontaktanfrage."""
    class _Empfaenger:
        """Der Mailversand erwartet ein Konto; hier gibt es keins.

        Nur die drei Felder, die `sende_vordruck` wirklich liest. `id = None`
        ist gewollt: An dieser Anfrage haengt keine Person aus der Datenbank,
        und sie soll auch nicht versehentlich einer zugeordnet werden.
        """
        id = None
        role = "member"
        department = "exekutive"
        vorname = (sauber(eintrag.name).split(" ")[0]
                   if sauber(eintrag.name) else "du")
        nachname = ""
        email = eintrag.email
        name = eintrag.name

    wann = eintrag.created_at
    versandt = mail.sende_vordruck(
        a.db, _Empfaenger(), "contact_reply", warten=True,
        antwort_an=sauber(getattr(a.user, "email", "")),
        automatisch=False,
        antwort=text,
        frage=eintrag.message or "",
        datum=wann.strftime("%d.%m.%Y") if wann else "damals",
        absender=a.user.name or "Der Vorstand")
    if versandt:
        return True, ""
    return False, _letzter_mailfehler(a.db, eintrag.email)


def _letzter_mailfehler(db, adresse: str) -> str:
    """Warum es nicht geklappt hat - aus dem Zustellprotokoll.

    `sende_vordruck` gibt nur wahr/falsch zurueck. Der Grund steht eine
    Ebene tiefer im Protokoll, und genau der ist das, was weiterhilft:
    "Authentifizierung abgelehnt" verlangt etwas anderes als "Zeit
    ueberschritten".
    """
    zeile = (db.query(DeliveryLog)
             .filter(DeliveryLog.kanal == "email",
                     DeliveryLog.ziel == adresse,
                     DeliveryLog.erfolg == 0)
             .order_by(DeliveryLog.created_at.desc()).first())
    return sauber(zeile.fehler) if zeile and zeile.fehler else ""


def _antwort_anhaengen(bisher: str, neu: str) -> str:
    """Mehrere Antworten untereinander statt uebereinander.

    Wer nachfasst, soll die erste Antwort nicht verlieren - sonst steht im
    Dashboard etwas anderes, als bei der Person angekommen ist.
    """
    bisher = (bisher or "").strip()
    if not bisher:
        return neu
    return f"{bisher}\n\n--- Nachgefasst ---\n{neu}"


@router.post("/nachrichten/kontakt/{msg_id}/loeschen")
def kontakt_loeschen(msg_id: int, csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("nachrichten")
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(ContactMessage, msg_id)
    if eintrag:
        papierkorb.hinein(a.db, "contact_message", eintrag, a.user.id,
                          f"{eintrag.name}: {kuerzen(eintrag.message, 100)}")
        a.db.commit()
    return _nachrichten_ansicht(a,
        papierkorb_hinweis("Aus dem Postfach entfernt – 30 Tage im Papierkorb."))


@router.post("/nachrichten/push-testmodus")
def push_testmodus(csrf: str = Form(""),
                   a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("benachrichtigungen_admin")
    a.pruefe_csrf(csrf)
    neu = not werte.an_db(a.db, werte.PUSH_TESTMODUS)
    werte.schalte(a.db, werte.PUSH_TESTMODUS, neu)
    return _nachrichten_ansicht(a, info(
        "Testmodus an – Meldungen gehen nur noch an die Verwalter." if neu
        else "Testmodus aus – Meldungen gehen wieder an alle."))


#  Support
def _support_ansicht(a: Anmeldung, meldung=None):
    db, user = a.db, a.user
    verwaltet = a.darf("support_verwaltung")
    abfrage = db.query(SupportTicket)
    if not verwaltet:
        abfrage = abfrage.filter(SupportTicket.user_id == user.id)
    tickets = abfrage.order_by(SupportTicket.status,
                               SupportTicket.created_at.desc()).limit(80).all()
    verlauf = {}
    for nachricht in (db.query(SupportMessage)
                      .filter(SupportMessage.ticket_id.in_(
                          [t.id for t in tickets] or [0]))
                      .order_by(SupportMessage.created_at).all()):
        verlauf.setdefault(nachricht.ticket_id, []).append(nachricht)
    return teil("dashboard/support.html", a, tickets=tickets, verlauf=verlauf,
                verwaltet=verwaltet, meldung=meldung)


@router.get("/support")
def support(a: Anmeldung = Depends(Anmeldung.pflicht)):
    return _support_ansicht(a)


@router.post("/support")
async def support_anlegen(betreff: str = Form(""), text: str = Form(""),
                          bild: UploadFile = File(None), csrf: str = Form(""),
                          a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    betreff_ = sauber(betreff)[:160]
    inhalt = sauber(text)[:8000]
    if not betreff_ or not inhalt:
        return _support_ansicht(a, fehler("Betreff und Beschreibung werden gebraucht."))

    dateiname = None
    if bild is not None and bild.filename:
        daten = await bild.read()
        if len(daten) > cfg.MAX_SCREENSHOT_BYTES:
            return _support_ansicht(a, fehler(
                f"Das Bild ist zu groß (höchstens "
                f"{cfg.MAX_SCREENSHOT_BYTES // 1024 // 1024} MB)."))
        endung = cfg.ERLAUBTE_BILDTYPEN.get(bild.content_type or "")
        if not endung:
            return _support_ansicht(a, fehler("Erlaubt sind PNG, JPG und WebP."))
        dateiname = secrets.token_hex(16) + endung
        os.makedirs(cfg.SUPPORT_UPLOAD_DIR, exist_ok=True)
        with open(os.path.join(cfg.SUPPORT_UPLOAD_DIR, dateiname), "wb") as ziel:
            ziel.write(daten)

    ticket = SupportTicket(user_id=a.user.id, subject=betreff_, message=inhalt,
                           attachment_filename=dateiname)
    a.db.add(ticket)
    a.db.flush()
    support_ki.entwurf_erzeugen(ticket)
    a.db.commit()
    benachrichtigung.melde_rechteinhabern(
        a.db, "support_verwaltung", "support", "Neue Support-Anfrage",
        f"{a.user.name}: {kuerzen(betreff_, 100)}", ausser_id=a.user.id)
    return _support_ansicht(a, gut(
        "Deine Anfrage ist angekommen. Das Support-Team meldet sich."))


@router.post("/support/{ticket_id}/antwort")
async def support_antwort(ticket_id: int, text: str = Form(""),
                          bild: UploadFile = File(None), csrf: str = Form(""),
                          a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    db, user = a.db, a.user
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        return _support_ansicht(a, fehler("Diese Anfrage gibt es nicht mehr."))
    verwaltet = a.darf("support_verwaltung")
    if ticket.user_id != user.id and not verwaltet:
        return _support_ansicht(a, fehler("Dieses Anliegen gehört zu einem anderen Konto."))
    inhalt = sauber(text)[:8000]
    if not inhalt:
        return _support_ansicht(a, fehler("Ohne Text geht es nicht."))

    dateiname = None
    if bild is not None and bild.filename:
        daten = await bild.read()
        endung = cfg.ERLAUBTE_BILDTYPEN.get(bild.content_type or "")
        if endung and len(daten) <= cfg.MAX_SCREENSHOT_BYTES:
            dateiname = secrets.token_hex(16) + endung
            os.makedirs(cfg.SUPPORT_UPLOAD_DIR, exist_ok=True)
            with open(os.path.join(cfg.SUPPORT_UPLOAD_DIR, dateiname), "wb") as ziel:
                ziel.write(daten)

    db.add(SupportMessage(ticket_id=ticket.id, sender_id=user.id,
                          message=inhalt, attachment_filename=dateiname))
    ticket.ai_draft = None
    if ticket.ai_status != "gesendet":
        ticket.ai_status = "manuell"
    if verwaltet and ticket.user_id != user.id:
        ticket.status = "beantwortet"
        ticket.replied_by = user.id
        ticket.replied_at = utcnow()
        benachrichtigung.melde(db, ticket.user_id, "support", "Antwort vom Support",
                               f"Zu „{ticket.subject}“: {kuerzen(inhalt, 120)}")
    else:
        ticket.status = "offen"
        benachrichtigung.melde_rechteinhabern(
            db, "support_verwaltung", "support", "Rückfrage im Support",
            f"{user.name} zu „{ticket.subject}“", ausser_id=user.id)
    db.commit()
    return _support_ansicht(a, gut("Antwort gespeichert."))


@router.post("/support/{ticket_id}/ki-entwurf")
def support_ki_entwurf(ticket_id: int, csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("support_verwaltung")
    a.pruefe_csrf(csrf)
    ticket = a.db.get(SupportTicket, ticket_id)
    if not ticket:
        return _support_ansicht(a, fehler("Diese Anfrage gibt es nicht mehr."))
    if ticket.status == "geschlossen":
        return _support_ansicht(a, fehler("Geschlossene Anfragen werden nicht automatisch beantwortet."))
    if support_ki.entwurf_erzeugen(ticket):
        a.db.commit()
        return _support_ansicht(a, gut("Antwortentwurf generiert. Bitte vor dem Senden prüfen."))
    a.db.commit()
    if ticket.ai_status == "deaktiviert":
        meldung = "Die Support-Automatik ist nicht eingerichtet. GROQ_API_KEY in config.cmd eintragen."
    elif ticket.ai_status == "kein_verwalter":
        meldung = "Kein aktives Konto mit Support-Berechtigung gefunden."
    elif ticket.ai_status == "fehler" and ticket.ai_error and "Invalid API Key" in ticket.ai_error:
        meldung = "Der Groq-API-Key ist ungültig. Bitte GROQ_API_KEY in config.cmd prüfen."
    else:
        meldung = "Die automatische Antwort konnte nicht erstellt werden. Das Ticket bleibt offen."
    return _support_ansicht(a, fehler(meldung))


@router.post("/support/{ticket_id}/ki-senden")
def support_ki_senden(ticket_id: int, csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("support_verwaltung")
    a.pruefe_csrf(csrf)
    ticket = a.db.get(SupportTicket, ticket_id)
    if not ticket:
        return _support_ansicht(a, fehler("Diese Anfrage gibt es nicht mehr."))
    if ticket.status == "geschlossen":
        return _support_ansicht(a, fehler("Geschlossene Anfragen werden nicht automatisch beantwortet."))
    if support_ki.entwurf_senden(a.db, ticket):
        a.db.commit()
        benachrichtigung.melde(
            a.db, ticket.user_id, "support", "Antwort vom Support",
            f"Zu „{ticket.subject}“ gibt es eine Antwort.")
        return _support_ansicht(a, gut("Antwort gesendet."))
    a.db.commit()
    return _support_ansicht(a, fehler("Es gibt keinen gültigen Antwortentwurf zum Senden."))


@router.post("/support/{ticket_id}/schliessen")
def support_schliessen(ticket_id: int, csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    ticket = a.db.get(SupportTicket, ticket_id)
    if ticket and (ticket.user_id == a.user.id or a.darf("support_verwaltung")):
        ticket.status = "geschlossen"
        a.db.commit()
    return _support_ansicht(a, gut("Anfrage geschlossen."))


@router.post("/support/{ticket_id}/loeschen")
def support_loeschen(ticket_id: int, csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("support_verwaltung")
    a.pruefe_csrf(csrf)
    ticket = a.db.get(SupportTicket, ticket_id)
    if ticket:
        papierkorb.hinein(a.db, "support_ticket", ticket, a.user.id, ticket.subject)
        a.db.commit()
    return _support_ansicht(a,
        papierkorb_hinweis("Das Anliegen liegt im Papierkorb – 30 Tage lang "
                          "wiederherstellbar."))


@router.get("/support/bild/{dateiname}")
def support_bild(dateiname: str, a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Ein hochgeladenes Bild - nur fuer Beteiligte."""
    if "/" in dateiname or "\\" in dateiname or ".." in dateiname:
        return Response("Nicht gefunden", status_code=404, media_type="text/plain")
    db, user = a.db, a.user
    erlaubt = a.darf("support_verwaltung")
    if not erlaubt:
        eigenes = db.query(SupportTicket).filter(
            SupportTicket.user_id == user.id,
            SupportTicket.attachment_filename == dateiname).first()
        eigene_nachricht = db.query(SupportMessage).join(
            SupportTicket, SupportTicket.id == SupportMessage.ticket_id).filter(
                SupportTicket.user_id == user.id,
                SupportMessage.attachment_filename == dateiname).first()
        erlaubt = bool(eigenes or eigene_nachricht)
    if not erlaubt:
        return Response("Kein Zugriff", status_code=403, media_type="text/plain")
    pfad = os.path.join(cfg.SUPPORT_UPLOAD_DIR, dateiname)
    if not os.path.exists(pfad):
        return Response("Nicht gefunden", status_code=404, media_type="text/plain")
    return FileResponse(pfad)


#  E-Mail-Vordrucke
def _vordrucke_ansicht(a: Anmeldung, meldung=None):
    from kern.modelle import EmailTemplate
    db = a.db
    vorhandene = {t.key: t for t in db.query(EmailTemplate).all()}
    liste = []
    for schluessel, (betreff, rumpf, beschreibung, platzhalter) in mail.VORDRUCKE.items():
        vorlage = vorhandene.get(schluessel)
        liste.append({
            "key": schluessel,
            "betreff": vorlage.subject if vorlage else betreff,
            "text": vorlage.body if vorlage else rumpf,
            "beschreibung": beschreibung,
            "platzhalter": platzhalter,
            "geaendert": vorlage.updated_at if vorlage else None,
            "abweichend": bool(vorlage and (vorlage.subject != betreff
                                            or vorlage.body != rumpf)),
        })
    return teil("dashboard/vordrucke.html", a, vordrucke=liste,
                testmodus=werte.an_db(db, werte.EMAIL_TESTMODUS),
                mail_moeglich=mail.versand_moeglich(),
                meldung=meldung)


@router.get("/vordrucke")
def vordrucke(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("email_vorlagen")
    return _vordrucke_ansicht(a)


@router.post("/vordrucke/testmodus")
def vordruck_testmodus(csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("email_vorlagen")
    a.pruefe_csrf(csrf)
    neu = not werte.an_db(a.db, werte.EMAIL_TESTMODUS)
    werte.schalte(a.db, werte.EMAIL_TESTMODUS, neu)
    return _vordrucke_ansicht(a, info(
        "Testmodus an – E-Mails gehen nur noch an die Vordruck-Verwalter." if neu
        else "Testmodus aus – E-Mails gehen wieder an alle."))


@router.post("/vordrucke/{schluessel}")
def vordruck_speichern(schluessel: str, betreff: str = Form(""),
                       text: str = Form(""), csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("email_vorlagen")
    a.pruefe_csrf(csrf)
    from kern.modelle import EmailTemplate
    if schluessel not in mail.VORDRUCKE:
        return _vordrucke_ansicht(a, fehler("Diesen Vordruck gibt es nicht."))
    betreff_ = sauber(betreff)[:200]
    inhalt = sauber(text)[:20000]
    if not betreff_ or not inhalt:
        return _vordrucke_ansicht(a, fehler("Betreff und Text dürfen nicht leer sein."))
    vorlage = a.db.get(EmailTemplate, schluessel)
    if vorlage:
        vorlage.subject, vorlage.body = betreff_, inhalt
        vorlage.updated_by = a.user.id
    else:
        a.db.add(EmailTemplate(key=schluessel, subject=betreff_, body=inhalt,
                               updated_by=a.user.id))
    a.db.commit()
    return _vordrucke_ansicht(a, gut("Vordruck gespeichert."))


@router.post("/vordrucke/{schluessel}/zuruecksetzen")
def vordruck_zurueck(schluessel: str, csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("email_vorlagen")
    a.pruefe_csrf(csrf)
    from kern.modelle import EmailTemplate
    if schluessel in mail.VORDRUCKE:
        betreff, rumpf, _, _ = mail.VORDRUCKE[schluessel]
        vorlage = a.db.get(EmailTemplate, schluessel)
        if vorlage:
            vorlage.subject, vorlage.body = betreff, rumpf
            vorlage.updated_by = a.user.id
            a.db.commit()
    return _vordrucke_ansicht(a, gut("Auf den ursprünglichen Text zurückgesetzt."))


@router.post("/vordrucke/{schluessel}/testen")
def vordruck_testen(schluessel: str, csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("email_vorlagen")
    a.pruefe_csrf(csrf)
    if not mail.versand_moeglich():
        return _vordrucke_ansicht(a, warnung(
            "Es ist kein Mailversand eingerichtet – ein Test geht nicht."))
    beispiel = {"status": "Angenommen", "passwort": "BeispielPasswort123",
                "link": f"{cfg.WEBSITE_URL}/passwort-neu?token=beispiel",
                "minuten": 60, "stunden": 24, "titel": "Probemeldung",
                "text": "Das ist ein Test aus dem Dashboard.",
                "abteilung": "Tech"}
    ok = mail.sende_vordruck(a.db, a.user, schluessel, warten=True, **beispiel)
    ziel = "die Vordruck-Verwalter" if werte.an_db(
        a.db, werte.EMAIL_TESTMODUS) else a.user.email
    return _vordrucke_ansicht(
        a, gut(f"Testmail an {ziel} verschickt.") if ok
        else fehler("Der Versand hat nicht geklappt – siehe Zustellprotokoll."))


#  WhatsApp-Bot
def _whatsapp_ansicht(a: Anmeldung, meldung=None, verbindung=None):
    db = a.db
    korb = (db.query(WhatsAppNachricht)
            .order_by(WhatsAppNachricht.status != "bereit",
                      WhatsAppNachricht.created_at.desc()).limit(60).all())
    bereit, hinweis = whatsapp.einsatzbereit()
    beispiel = whatsapp.fuelle_vorlage(whatsapp.vorlage(db), a.user)
    ohne_nummer = db.query(func.count(User.id)).filter(
        User.status == "aktiv",
        (User.telefonnummer.is_(None)) | (User.telefonnummer == "")).scalar() or 0
    return teil("dashboard/whatsapp.html", a,
                korb=korb, zahlen=whatsapp.uebersicht(db),
                vorlage=whatsapp.vorlage(db), beispiel=beispiel,
                platzhalter=whatsapp.PLATZHALTER,
                modus=whatsapp.modus(), bereit=bereit, hinweis=hinweis,
                automatik=whatsapp.automatik_an(db),
                testmodus=werte.an_db(db, werte.WHATSAPP_TESTMODUS),
                ohne_nummer=ohne_nummer,
                wa_link=whatsapp.wa_link,
                web=whatsapp.web_zustand() if whatsapp.modus() == "web" else None,
                vorlage_name=cfg.WHATSAPP_VORLAGE_NAME,
                vorlage_parameter=werte.hole_db(
                    db, whatsapp.WERTE_VORLAGE_PARAMETER, "vorname"),
                vorlage_sprache=werte.hole_db(
                    db, whatsapp.WERTE_VORLAGE_SPRACHE, "de"),
                beispiel_parameter=whatsapp.vorlagen_parameter(db, a.user),
                verbindung=verbindung,
                meldung=meldung)


@router.get("/whatsapp")
def whatsapp_bereich(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("whatsapp_bot")
    return _whatsapp_ansicht(a)


@router.post("/whatsapp/vorlage")
def whatsapp_vorlage(text: str = Form(""), csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("whatsapp_bot")
    a.pruefe_csrf(csrf)
    inhalt = sauber(text)[:4000]
    if not inhalt:
        return _whatsapp_ansicht(a, fehler("Der Willkommenstext darf nicht leer sein."))
    werte.setze(a.db, werte.WHATSAPP_WILLKOMMEN, inhalt)
    return _whatsapp_ansicht(a, gut("Willkommenstext gespeichert."))


@router.post("/whatsapp/vorlage-zuruecksetzen")
def whatsapp_vorlage_zurueck(csrf: str = Form(""),
                             a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("whatsapp_bot")
    a.pruefe_csrf(csrf)
    werte.setze(a.db, werte.WHATSAPP_WILLKOMMEN, whatsapp.WILLKOMMEN_STANDARD)
    return _whatsapp_ansicht(a, gut("Auf den Standardtext zurückgesetzt."))


@router.post("/whatsapp/automatik")
def whatsapp_automatik(csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("whatsapp_bot")
    a.pruefe_csrf(csrf)
    neu = not whatsapp.automatik_an(a.db)
    werte.schalte(a.db, werte.WHATSAPP_AUTOMATIK, neu)
    return _whatsapp_ansicht(a, info(
        "Neue Mitglieder werden ab jetzt automatisch begrüßt." if neu
        else "Automatische Begrüßung ist aus – du kannst weiter von Hand verschicken."))


@router.post("/whatsapp/testmodus")
def whatsapp_testmodus(csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("whatsapp_bot")
    a.pruefe_csrf(csrf)
    neu = not werte.an_db(a.db, werte.WHATSAPP_TESTMODUS)
    werte.schalte(a.db, werte.WHATSAPP_TESTMODUS, neu)
    return _whatsapp_ansicht(a, info(
        "Testmodus an – es wird nichts wirklich verschickt." if neu
        else "Testmodus aus."))


@router.post("/whatsapp/senden")
def whatsapp_senden(csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("whatsapp_bot")
    a.pruefe_csrf(csrf)
    if whatsapp.modus() == "manuell":
        return _whatsapp_ansicht(a, info(
            "Im manuellen Betrieb verschickt der Server nichts. Nutze den "
            "Knopf „In WhatsApp öffnen“ bei den einzelnen Nachrichten."))
    bilanz = whatsapp.korb_abarbeiten()
    return _whatsapp_ansicht(a, gut(
        f"{bilanz['gesendet']} verschickt, {bilanz['fehlgeschlagen']} fehlgeschlagen."))


@router.post("/whatsapp/verbindung")
def whatsapp_verbindung(csrf: str = Form(""),
                        a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Prueft die Verbindung - ohne dass jemand Post bekommt."""
    a.verlange("whatsapp_bot")
    a.pruefe_csrf(csrf)
    if whatsapp.modus() == "web":
        # Hier ist das Warten der Zweck des Knopfes.
        stand = whatsapp.web_zustand(warten=True)
        gut_ = stand.get("zustand") == "bereit"
        text = stand.get("meldung") or stand.get("zustand", "")
    else:
        gut_, text = whatsapp.verbindung_pruefen()
    return _whatsapp_ansicht(a, verbindung={"gut": gut_, "text": text})


@router.get("/whatsapp/kopplung")
def whatsapp_kopplung(a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Nur der Kopplungskasten - die Seite fragt ihn alle paar Sekunden ab.

    Der QR-Code von WhatsApp läuft nach etwa einer Minute ab und wird durch
    einen neuen ersetzt. Ohne Nachladen scannt man einen toten Code und
    wundert sich, warum nichts passiert.
    """
    a.verlange("whatsapp_bot")
    return teil("dashboard/teile/whatsapp_kopplung.html", a,
                web=whatsapp.web_zustand())


@router.post("/whatsapp/abmelden")
def whatsapp_abmelden(csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("whatsapp_bot")
    a.pruefe_csrf(csrf)
    erfolg, text = whatsapp.web_abmelden()
    return _whatsapp_ansicht(a, gut("Abgemeldet. Der Dienst zeigt gleich einen "
                                    "neuen QR-Code zum Koppeln.")
                             if erfolg else fehler(text))


@router.post("/whatsapp/vorlage-einstellungen")
def whatsapp_vorlage_einstellungen(parameter: str = Form(""),
                                   sprache: str = Form("de"),
                                   csrf: str = Form(""),
                                   a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Welche Werte in welcher Reihenfolge in die Meta-Vorlage gehen."""
    a.verlange("whatsapp_bot")
    a.pruefe_csrf(csrf)
    erlaubt = {n.strip("{}") for n in whatsapp.PLATZHALTER}
    namen = [n.strip() for n in sauber(parameter).split(",") if n.strip()]
    unbekannt = [n for n in namen if n not in erlaubt]
    if unbekannt:
        return _whatsapp_ansicht(a, fehler(
            "Unbekannte Platzhalter: " + ", ".join(unbekannt)
            + ". Erlaubt sind: " + ", ".join(sorted(erlaubt)) + "."))
    werte.setze(a.db, whatsapp.WERTE_VORLAGE_PARAMETER, ",".join(namen))
    werte.setze(a.db, whatsapp.WERTE_VORLAGE_SPRACHE,
                sauber(sprache)[:10] or "de")
    return _whatsapp_ansicht(a, gut(
        f"Gespeichert. Die Vorlage bekommt {len(namen)} Parameter – sie muss "
        f"also genau {{{{1}}}}" + (f" bis {{{{{len(namen)}}}}}" if len(namen) > 1 else "")
        + " enthalten."))


@router.post("/whatsapp/{eintrag_id}/erledigt")
def whatsapp_erledigt(eintrag_id: int, csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Von Hand als verschickt abhaken - fuer den manuellen Betrieb."""
    a.verlange("whatsapp_bot")
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(WhatsAppNachricht, eintrag_id)
    if eintrag:
        eintrag.status = "gesendet"
        eintrag.gesendet_am = utcnow()
        eintrag.fehler = None
        a.db.commit()
    return _whatsapp_ansicht(a, gut("Als verschickt vermerkt."))


@router.post("/whatsapp/{eintrag_id}/loeschen")
def whatsapp_loeschen(eintrag_id: int, csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("whatsapp_bot")
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(WhatsAppNachricht, eintrag_id)
    if eintrag:
        a.db.delete(eintrag)
        a.db.commit()
    return _whatsapp_ansicht(a, gut("Eintrag entfernt."))


@router.post("/whatsapp/erneut/{person_id}")
def whatsapp_erneut(person_id: int, csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Eine Begruessung noch einmal vorbereiten - etwa nach einem Zahlendreher."""
    a.verlange("whatsapp_bot")
    a.pruefe_csrf(csrf)
    person = a.db.get(User, person_id)
    if not person:
        return _whatsapp_ansicht(a, fehler("Diese Person gibt es nicht mehr."))
    whatsapp.einreihen(a.db, person, anlass="willkommen")
    a.db.commit()
    if whatsapp.modus() != "manuell":
        whatsapp.korb_anstossen()
    return _whatsapp_ansicht(a, gut(f"Begrüßung für {person.vorname} liegt bereit."))
