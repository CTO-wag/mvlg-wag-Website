"""Mein Konto und der Rundgang."""

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, Form
from fastapi.responses import PlainTextResponse, Response

from dashboard.hilfen import Anmeldung, fehler, gut, info, teil, warnung
from kern import benachrichtigung, kalender, mail, papierkorb, protokoll
from kern import einstellungen as cfg
from kern.modelle import (
    EmailChangeRequest, Leistung, Task, User, UserPreference, UserSession,
)
from kern.rechte import rechte_von, zustaendige_abteilungen
from kern.sicherheit import (
    PASSWORT_REGEL, geraet_beschreiben, passwort_bewerten, passwort_hashen,
    ersatzcodes_erzeugen, ersatzcodes_offen, passwort_pruefen,
    token_erzeugen, token_hashen, totp_geheimnis,
    totp_pruefen, totp_url,
)
from kern.text import (
    email_gueltig, email_normal, sauber, telefon_anzeige, telefon_gueltig, utcnow,
)

router = APIRouter(prefix="/dashboard")

ADRESSWECHSEL_STUNDEN = 24


#  Mein Konto
def _konto_ansicht(a: Anmeldung, meldung=None, totp_start=None,
                   ersatzcodes=None):
    db, user = a.db, a.user
    from kern import leistung as leistungsmodul

    vorlieben = db.query(UserPreference).filter(
        UserPreference.user_id == user.id).first()
    sitzungen = (db.query(UserSession)
                 .filter(UserSession.user_id == user.id, UserSession.revoked == 0)
                 .order_by(UserSession.last_active.desc()).all())
    offener_wechsel = (db.query(EmailChangeRequest)
                       .filter(EmailChangeRequest.user_id == user.id,
                               EmailChangeRequest.used_at.is_(None),
                               EmailChangeRequest.expires_at > utcnow())
                       .order_by(EmailChangeRequest.created_at.desc()).first())

    offene_aufgaben = db.query(Task).filter(
        Task.assignee_id == user.id, Task.status != "erledigt").count()
    erledigt = db.query(Leistung).filter(
        Leistung.user_id == user.id, Leistung.art == "aufgabe").count()

    return teil("dashboard/mein_konto.html", a,
                vorlieben=vorlieben, sitzungen=sitzungen,
                aktuelle_sid=a.request.session.get("sid"),
                geraet_name=geraet_beschreiben,
                offener_wechsel=offener_wechsel,
                abo_adresse=kalender.abo_adresse(db, user),
                passwort_regel=PASSWORT_REGEL,
                mail_moeglich=mail.versand_moeglich(),
                totp_start=totp_start,
                ersatzcodes=ersatzcodes,
                ersatzcodes_offen=ersatzcodes_offen(a.user.totp_ersatzcodes),
                werte=leistungsmodul.werte_fuer(db, user.id),
                verlauf=leistungsmodul.verlauf(db, user.id),
                offene_aufgaben=offene_aufgaben, erledigt=erledigt,
                meine_abteilungen=zustaendige_abteilungen(user),
                meldung=meldung)


@router.get("/mein-konto")
def mein_konto(a: Anmeldung = Depends(Anmeldung.pflicht)):
    return _konto_ansicht(a)


@router.post("/mein-konto/passwort")
def passwort_aendern(alt: str = Form(""), neu: str = Form(""),
                     neu2: str = Form(""), csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    user = a.user
    if not passwort_pruefen(alt, user.password_hash):
        return _konto_ansicht(a, fehler("Das bisherige Passwort stimmt nicht."))
    if neu != neu2:
        return _konto_ansicht(a, fehler("Die beiden neuen Passwörter stimmen nicht überein."))
    ok, meldung_ = passwort_bewerten(neu, (user.vorname, user.nachname))
    if not ok:
        return _konto_ansicht(a, fehler(meldung_))

    user.password_hash = passwort_hashen(neu)
    user.passwort_geaendert_am = utcnow()
    # Andere Sitzungen beenden, die eigene behalten: Wer sein Passwort
    # ändert, will meistens genau das - andere raus, selbst drin bleiben.
    eigene = a.request.session.get("sid")
    a.db.query(UserSession).filter(
        UserSession.user_id == user.id, UserSession.id != eigene,
        UserSession.revoked == 0).update({"revoked": 1}, synchronize_session=False)
    protokoll.notiere(a.db, user.id, "passwort_geaendert")
    a.db.commit()
    return _konto_ansicht(a, gut(
        "Passwort geändert. Alle anderen Anmeldungen wurden beendet."))


@router.post("/mein-konto/profil")
def profil_aendern(vorname: str = Form(""), nachname: str = Form(""),
                   telefon: str = Form(""), csrf: str = Form(""),
                   a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    user = a.user
    if sauber(vorname):
        user.vorname = sauber(vorname)[:80]
    if sauber(nachname):
        user.nachname = sauber(nachname)[:80]
    if telefon and not telefon_gueltig(telefon):
        return _konto_ansicht(a, fehler(
            "Die Telefonnummer scheint nicht zu stimmen – bitte mit Vorwahl, "
            "zum Beispiel 0163 1234567."))
    # Einheitlich als "+49 163 1234567": daran haengt, ob die
    # WhatsApp-Begruessung ankommt.
    user.telefonnummer = telefon_anzeige(telefon) or None
    a.db.commit()
    return _konto_ansicht(a, gut("Gespeichert."))


@router.post("/mein-konto/email")
def email_aendern(neue: str = Form(""), passwort: str = Form(""),
                  csrf: str = Form(""),
                  a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Adresswechsel - gilt erst nach Bestaetigung an der neuen Adresse.

    Sonst sperrt man sich mit einem Tippfehler aus dem eigenen Konto aus,
    oder jemand, der kurz an einem offenen Rechner sitzt, uebernimmt es still.
    """
    a.pruefe_csrf(csrf)
    db, user = a.db, a.user
    adresse = email_normal(neue)
    if not passwort_pruefen(passwort, user.password_hash):
        return _konto_ansicht(a, fehler("Zur Sicherheit bitte das aktuelle Passwort."))
    if not email_gueltig(adresse):
        return _konto_ansicht(a, fehler("Diese Adresse sieht nicht richtig aus."))
    if adresse == user.email:
        return _konto_ansicht(a, info("Das ist bereits deine Adresse."))
    if db.query(User).filter(User.email == adresse).first():
        return _konto_ansicht(a, fehler("Diese Adresse hat schon ein Konto."))
    if not mail.versand_moeglich():
        return _konto_ansicht(a, warnung(
            "Ohne Mailversand lässt sich die neue Adresse nicht bestätigen. "
            "Bitte den Vorstand bitten, sie einzutragen."))

    db.query(EmailChangeRequest).filter(
        EmailChangeRequest.user_id == user.id,
        EmailChangeRequest.used_at.is_(None)).update(
            {"used_at": utcnow()}, synchronize_session=False)
    roh = token_erzeugen(32)
    db.add(EmailChangeRequest(
        user_id=user.id, new_email=adresse, token_hash=token_hashen(roh),
        expires_at=utcnow() + timedelta(hours=ADRESSWECHSEL_STUNDEN)))
    db.commit()

    class _Ziel:
        id = user.id
        role = user.role
        department = user.department
        vorname = user.vorname
        nachname = user.nachname
        email = adresse
        name = user.name

    mail.sende_vordruck(db, _Ziel(), "email_change",
                        # Wie beim Passwort-Link: dorthin, wo die Person
                        # gerade ist (siehe website/routen/anmeldung.py).
                        link=f"{cfg.adressen_fuer(a.request)[0]}"
                             f"/email-bestaetigen?token={roh}",
                        stunden=ADRESSWECHSEL_STUNDEN)
    return _konto_ansicht(a, gut(
        f"Eine Bestätigung ist an {adresse} unterwegs. Bis zum Klick auf den "
        "Link bleibt deine alte Adresse gültig."))


@router.post("/mein-konto/email/abbrechen")
def email_abbrechen(csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    a.db.query(EmailChangeRequest).filter(
        EmailChangeRequest.user_id == a.user.id,
        EmailChangeRequest.used_at.is_(None)).update(
            {"used_at": utcnow()}, synchronize_session=False)
    a.db.commit()
    return _konto_ansicht(a, gut("Adresswechsel abgebrochen."))


# --- Zweiter Faktor ---------------------------------------------------------
@router.post("/mein-konto/2fa/ersatzcodes")
def totp_ersatzcodes_neu(passwort: str = Form(""), csrf: str = Form(""),
                         a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Neue Ersatzcodes erzeugen - die alten gelten dann nicht mehr.

    Gedacht fuer zwei Faelle: Der Zettel ist weg, oder es sind nur noch ein,
    zwei Codes uebrig. Das Passwort wird verlangt, weil sonst jeder an einem
    unbeaufsichtigten Bildschirm acht Dauerschluessel abgreifen koennte.
    """
    a.pruefe_csrf(csrf)
    if not a.user.totp_aktiv:
        return _konto_ansicht(a, info("Der zweite Faktor ist gar nicht an."))
    if not passwort_pruefen(passwort, a.user.password_hash):
        return _konto_ansicht(a, fehler("Zur Sicherheit bitte das Passwort."))
    klartext, gespeichert = ersatzcodes_erzeugen()
    a.user.totp_ersatzcodes = gespeichert
    protokoll.notiere(a.db, a.user.id, "2fa_ersatzcodes_neu")
    a.db.commit()
    return _konto_ansicht(a, gut("Neue Ersatzcodes. Die alten gelten nicht "
                                 "mehr."), ersatzcodes=klartext)


@router.post("/mein-konto/2fa/start")
def totp_start(csrf: str = Form(""),
               a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Erzeugt ein Geheimnis und zeigt es an - scharf ist es erst nach dem
    ersten richtigen Code."""
    a.pruefe_csrf(csrf)
    if a.user.totp_aktiv:
        return _konto_ansicht(a, info("Der zweite Faktor ist schon eingeschaltet."))
    geheimnis = totp_geheimnis()
    a.user.totp_secret = geheimnis
    a.user.totp_aktiv = 0
    a.db.commit()
    return _konto_ansicht(a, None, totp_start={
        "geheimnis": geheimnis,
        "url": totp_url(geheimnis, a.user.email),
    })


@router.post("/mein-konto/2fa/bestaetigen")
def totp_bestaetigen(code: str = Form(""), csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    user = a.user
    if not user.totp_secret:
        return _konto_ansicht(a, fehler("Erst einrichten, dann bestätigen."))
    if not totp_pruefen(user.totp_secret, code):
        return _konto_ansicht(a, fehler(
            "Der Code stimmt nicht. Prüf, ob die Uhrzeit deines Geräts richtig "
            "geht – daran liegt es meistens."), totp_start={
                "geheimnis": user.totp_secret,
                "url": totp_url(user.totp_secret, user.email)})
    user.totp_aktiv = 1
    # Acht Ersatzcodes, genau jetzt und nur jetzt im Klartext zu sehen.
    # Gespeichert werden nur Pruefwerte; wer sie verliert, braucht den
    # Vorstand. Ohne diesen Schritt waere ein verlorenes Handy gleichbedeutend
    # mit einem verlorenen Konto.
    klartext, gespeichert = ersatzcodes_erzeugen()
    user.totp_ersatzcodes = gespeichert
    protokoll.notiere(a.db, user.id, "2fa_an")
    a.db.commit()
    return _konto_ansicht(a, gut(
        "Zweiter Faktor ist an. Schreib dir jetzt die Ersatzcodes auf – "
        "danach sind sie nicht mehr einsehbar."), ersatzcodes=klartext)


@router.post("/mein-konto/2fa/aus")
def totp_aus(passwort: str = Form(""), csrf: str = Form(""),
             a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    if not passwort_pruefen(passwort, a.user.password_hash):
        return _konto_ansicht(a, fehler("Zur Sicherheit bitte das Passwort."))
    a.user.totp_aktiv = 0
    a.user.totp_secret = None
    a.user.totp_ersatzcodes = None
    protokoll.notiere(a.db, a.user.id, "2fa_aus")
    a.db.commit()
    return _konto_ansicht(a, gut("Zweiter Faktor ist aus."))


# --- Sitzungen --------------------------------------------------------------
@router.post("/mein-konto/sitzung/{sid}/beenden")
def sitzung_beenden(sid: str, csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(UserSession, sid)
    if eintrag and eintrag.user_id == a.user.id:
        eintrag.revoked = 1
        a.db.commit()
    return _konto_ansicht(a, gut("Sitzung beendet."))


@router.post("/mein-konto/sitzungen/andere-beenden")
def andere_beenden(csrf: str = Form(""),
                   a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    eigene = a.request.session.get("sid")
    anzahl = a.db.query(UserSession).filter(
        UserSession.user_id == a.user.id, UserSession.id != eigene,
        UserSession.revoked == 0).update({"revoked": 1}, synchronize_session=False)
    a.db.commit()
    return _konto_ansicht(a, gut(f"{anzahl} andere Anmeldung(en) beendet."))


@router.get("/mein-konto/meine-daten.json")
def daten_export(a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Alles, was ueber diese Person gespeichert ist - als Datei.

    Verlangt die Datenschutz-Grundverordnung, und es ist ohnehin die
    freundlichere Art, mit Daten umzugehen.
    """
    db, user = a.db, a.user
    from kern.modelle import (
        ActivityLog, Attendance, DirectMessageRecipient, SupportTicket,
        TaskComment,
    )

    def zeit(wert):
        return wert.isoformat() if wert else None

    daten = {
        "konto": {
            "id": user.id, "vorname": user.vorname, "nachname": user.nachname,
            "email": user.email, "telefonnummer": user.telefonnummer,
            "rolle": user.role, "abteilung": user.department,
            "status": user.status, "eintritt": zeit(user.eintrittsdatum),
            "angelegt": zeit(user.created_at),
            "zweiter_faktor": bool(user.totp_aktiv),
        },
        "aufgaben": [
            {"titel": t.titel, "status": t.status, "frist": zeit(t.deadline),
             "erledigt_am": zeit(t.completed_at)}
            for t in db.query(Task).filter(Task.assignee_id == user.id).all()],
        "leistungen": [
            {"art": l.art, "titel": l.titel, "punkte": l.punkte,
             "zeitpunkt": zeit(l.zeitpunkt)}
            for l in db.query(Leistung).filter(Leistung.user_id == user.id).all()],
        "anwesenheit": [
            {"datum": zeit(x.event_date), "anlass": x.event_type}
            for x in db.query(Attendance).filter(Attendance.user_id == user.id).all()],
        "kommentare": [
            {"text": k.message, "wann": zeit(k.created_at)}
            for k in db.query(TaskComment).filter(TaskComment.user_id == user.id).all()],
        "support": [
            {"betreff": t.subject, "text": t.message, "status": t.status,
             "wann": zeit(t.created_at)}
            for t in db.query(SupportTicket).filter(SupportTicket.user_id == user.id).all()],
        "nachrichten": [
            {"betreff": e.message.subject if e.message else "",
             "gelesen": zeit(e.read_at)}
            for e in db.query(DirectMessageRecipient).filter(
                DirectMessageRecipient.user_id == user.id).all()],
        "sitzungen": [
            {"geraet": s.user_agent, "ip": s.ip_address,
             "angelegt": zeit(s.created_at), "zuletzt": zeit(s.last_active),
             "beendet": bool(s.revoked)}
            for s in db.query(UserSession).filter(UserSession.user_id == user.id).all()],
        "protokoll": [
            {"was": p.event_type, "wert": p.value, "wann": zeit(p.created_at)}
            for p in db.query(ActivityLog).filter(ActivityLog.user_id == user.id).all()],
    }
    inhalt = json.dumps(daten, ensure_ascii=False, indent=2)
    return Response(inhalt, media_type="application/json; charset=utf-8",
                    headers={"Content-Disposition":
                             'attachment; filename="meine-daten.json"'})


@router.post("/mein-konto/loeschen")
def konto_selbst_loeschen(passwort: str = Form(""), bestaetigung: str = Form(""),
                          csrf: str = Form(""),
                          a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    db, user = a.db, a.user
    if not passwort_pruefen(passwort, user.password_hash):
        return _konto_ansicht(a, fehler("Zur Sicherheit bitte das Passwort."))
    if sauber(bestaetigung).upper() != "LÖSCHEN":
        return _konto_ansicht(a, fehler(
            "Bitte LÖSCHEN in das Feld schreiben, damit das nicht aus Versehen passiert."))
    if user.role == "cto":
        andere = db.query(User).filter(User.role == "cto", User.status == "aktiv",
                                       User.id != user.id).count()
        if not andere:
            return _konto_ansicht(a, fehler(
                "Du bist das letzte aktive CTO-Konto. Erst jemand anderen "
                "einsetzen, sonst kommt niemand mehr an die Verwaltung."))

    name = user.name
    papierkorb.konto_daten_loesen(db, user)
    papierkorb.hinein(db, "user", user, user.id, name)
    db.commit()
    a.request.session.clear()
    return Response(
        f'<div class="panel meldung meldung-gut"><div>'
        f'<strong>Dein Konto wurde gelöscht.</strong>'
        f'<p>Du wirst gleich abgemeldet.</p></div></div>',
        media_type="text/html",
        headers={"HX-Redirect": f"{cfg.adressen_fuer(a.request)[0]}/"})


#  Rundgang
# Fassung des Rundgangs. Sie zaehlt hoch, wenn sich die Plattform so
# veraendert hat, dass die alte Anleitung nicht mehr genuegt - dann wird er
# allen erneut angeboten, auch denen, die ihn schon kannten.
RUNDGANG_FASSUNG = "2.0"
# Wie oft jemand die Einladung hoechstens zu sehen bekommt. Wer sie dreimal
# weggeklickt hat, will sie nicht. Ueber den Support bleibt der Rundgang
# jederzeit erreichbar.
MAX_FRAGEN = 3


def _stand(db, user) -> UserPreference:
    """Der Rundgang-Stand, bezogen auf die aktuelle Fassung.

    Stammt der gespeicherte Stand von einer aelteren Fassung, faengt alles
    von vorn an - sonst bekaeme jemand, der frueher dreimal abgelehnt hat,
    die neuen Bereiche nie zu sehen.
    """
    vorlieben = db.query(UserPreference).filter(
        UserPreference.user_id == user.id).first()
    if not vorlieben:
        vorlieben = UserPreference(user_id=user.id)
        db.add(vorlieben)
        db.commit()
    if (vorlieben.tutorial_version or "") != RUNDGANG_FASSUNG:
        vorlieben.tutorial_erledigt = 0
        vorlieben.tutorial_gefragt = 0
        vorlieben.tutorial_version = RUNDGANG_FASSUNG
        db.commit()
    return vorlieben


def rundgang_faellig(db, user) -> bool:
    vorlieben = _stand(db, user)
    if vorlieben.tutorial_erledigt:
        return False
    if (vorlieben.tutorial_gefragt or 0) >= MAX_FRAGEN:
        return False
    # Der Zaehler steigt erst, wenn die Einladung wirklich gezeigt wird -
    # ein Seitenaufruf ohne sichtbare Einladung verbraucht keine Frage.
    vorlieben.tutorial_gefragt = (vorlieben.tutorial_gefragt or 0) + 1
    db.commit()
    return True


@router.post("/rundgang/gesehen")
def rundgang_gesehen(erledigt: str = Form(""), csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.pruefe_csrf(csrf)
    vorlieben = _stand(a.db, a.user)
    if erledigt:
        vorlieben.tutorial_erledigt = 1
        vorlieben.tutorial_version = RUNDGANG_FASSUNG
    a.db.commit()
    return PlainTextResponse("ok")


@router.get("/rundgang")
def rundgang(a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Die Schritte des Rundgangs als JSON - je nach Rolle nur die eigenen.

    Bewusst reines JSON und kein HTML-Schnipsel mit eingebettetem Skript:
    Ein per htmx nachgeladenes <script> laeuft unter einer Nonce-basierten
    Sicherheitsrichtlinie nicht. htmx baut das Skript neu auf und liest die
    Attribute mit getAttribute() aus - und genau die Nonce liefert der
    Browser dabei aus Sicherheitsgruenden leer zurueck. Das Skript hatte
    danach keine gueltige Nonce mehr und wurde blockiert. Der Rundgang
    startete deshalb nie. Jetzt holt ihn das bereits geladene Skript selbst
    per fetch ab; es wird ueberhaupt kein Skript mehr nachgeladen.

    Bausteine statt HTML-Zeichenketten: Das Skript baut daraus DOM-Knoten.
    Damit kann kein Text aus der Datenbank versehentlich als Markup landen.
    """
    db, user = a.db, a.user
    r = rechte_von(user, db)
    pref = benachrichtigung.einstellung(db, user.id)
    schritte = []

    def schritt(titel, teile, bereich=None, ziel=None):
        schritte.append({"titel": titel, "teile": teile,
                         "bereich": bereich, "ziel": ziel})

    def absatz(*stuecke):
        return {"art": "absatz", "teile": [
            s if isinstance(s, dict) else {"t": s} for s in stuecke]}

    schritt("Willkommen, " + user.vorname + "!", [
        absatz("Kurz durch das Dashboard – etwa drei Minuten. Am Ende sind "
               "auch deine Benachrichtigungen und dein Kalender eingerichtet."),
        absatz("Du kannst jederzeit abbrechen und den Rundgang später unter "
               "„Support“ neu starten."),
    ])

    schritt("Links stehen deine Bereiche", [
        absatz("Alles, was du darfst, findest du in der Leiste. Was dort nicht "
               "steht, ist für deine Rolle nicht freigegeben."),
        absatz("Eine Zahl am Eintrag heißt: dort wartet etwas auf dich."),
        absatz({"t": "Auf dem Handy", "stark": True},
               " liegt die Leiste hinter dem Menü-Knopf oben."),
    ], ziel=".dash-leiste|#leisten-schalter")

    schritt("Die Übersicht", [
        absatz("Deine Startseite. Sie zeigt, was für dich ansteht – nicht "
               "Zahlen über die ganze AG."),
        absatz("Ganz oben steht der nächste Termin, darunter deine offenen "
               "Aufgaben."),
    ], bereich="uebersicht", ziel='.leisten-punkt[data-bereich="uebersicht"]')

    schritt("Aufgaben", [
        absatz("Hier steht, was zu tun ist. Aufklappen zeigt Beschreibung, "
               "Teilschritte und den Verlauf."),
        {"art": "liste", "punkte": [
            {"titel": "Teilschritte:", "text": "eine große Aufgabe in kleine zerlegen"},
            {"titel": "Verlauf:", "text": "Rückfragen und Zwischenstände festhalten"},
            {"titel": "Erledigt:", "text": "ein Klick, fertig"},
        ]},
        absatz("Was du erledigst, zählt dauerhaft – auch wenn die Aufgabe "
               "später gelöscht wird. Aufräumen kostet dich nichts."),
    ], bereich="aufgaben", ziel='.leisten-punkt[data-bereich="aufgaben"]')

    if r.get("bewerbungen"):
        schritt("Bewerbungen", [
            absatz("Jede Bewerbung kannst du mit Sternen und einer kurzen "
                   "Begründung einschätzen. Alle Einschätzungen stehen "
                   "nebeneinander – so ist später nachlesbar, warum "
                   "entschieden wurde."),
        ], bereich="bewerbungen", ziel='.leisten-punkt[data-bereich="bewerbungen"]')

    schritt("Benachrichtigungen aufs Handy", [
        absatz("Damit du nichts verpasst. Zwei Wege, du kannst beide nutzen."),
        {"art": "hinweis",
         "text": "Auf dem iPhone geht Push erst, wenn die Seite auf dem "
                 "Startbildschirm liegt.",
         "titel": "So legst du sie dort ab",
         "schritte": ["In Safari das Teilen-Symbol antippen (Quadrat mit Pfeil)",
                      "„Zum Home-Bildschirm“ wählen",
                      "Die App von dort öffnen – nicht mehr über Safari",
                      "Dann hier unter „Nachrichten“ auf „Dieses Gerät anmelden“"]},
        absatz({"t": "Weg 2 – ntfy:", "stark": True},
               " kostenlose App aus dem Store, dann dieses Thema abonnieren:"),
        {"art": "kopieren", "wert": pref.topic},
        absatz("Das Thema ist geheim – wer es kennt, liest mit."),
    ], bereich="nachrichten", ziel='.leisten-punkt[data-bereich="nachrichten"]')

    schritt("Termine im eigenen Kalender", [
        absatz("Diese Adresse einmal in die Kalender-App eintragen, dann "
               "erscheinen alle AG-Termine dort automatisch."),
        {"art": "kopieren", "wert": kalender.abo_adresse(db, user)},
        {"art": "geraete", "namen": ["iPhone", "Android", "Rechner"]},
        absatz("Die Adresse ist persönlich – du siehst nur, was dich betrifft."),
    ], bereich="kalender", ziel='.leisten-punkt[data-bereich="kalender"]')

    if r.get("finanzen"):
        schritt("Kassenbuch", [
            absatz("Beiträge, Sponsoring, Materialkosten – alles an einer "
                   "Stelle. Budgets zeigen, wie viel eine Abteilung noch hat, "
                   "Daueraufträge legen wiederkehrende Buchungen von selbst an."),
        ], bereich="kassenbuch", ziel='.leisten-punkt[data-bereich="kassenbuch"]')

    if r.get("leadership"):
        schritt("Leadership", [
            absatz("Rechnet sich von selbst aus Aufgaben, Anwesenheit, "
                   "Projekten und Wettbewerben. Niemand muss einen Knopf drücken."),
            absatz("Der wichtigste Teilwert ist Zuverlässigkeit: Wie viel vom "
                   "Übernommenen wird auch fertig."),
        ], bereich="leistung", ziel='.leisten-punkt[data-bereich="leistung"]')

    schritt("Dein Konto", [
        absatz("Oben links über deinen Namen. Dort änderst du Passwort und "
               "Kontaktdaten, siehst deine aktiven Anmeldungen und kannst "
               "einen zweiten Faktor einschalten."),
        absatz("Der zweite Faktor ist freiwillig, aber er macht dein Konto "
               "deutlich sicherer – besonders, wenn du viel darfst."),
    ], ziel="#dash-ich")

    schritt("Das war es", [
        absatz("Du findest alles wieder. Wenn etwas unklar ist oder nicht "
               "funktioniert: unter „Support“ fragen – dort lässt sich auch "
               "dieser Rundgang neu starten."),
        absatz("Viel Erfolg!"),
    ])

    from fastapi.responses import JSONResponse
    return JSONResponse(schritte)
