"""Anmelden, abmelden, Passwort zuruecksetzen, Adresse bestaetigen.

Der Ablauf hat gegenueber V1 einen zusaetzlichen Schritt: Ist fuer ein Konto
der zweite Faktor eingeschaltet, wird nach dem Passwort noch der Code aus der
Authenticator-App verlangt. Bis dahin liegt nur ein Vermerk in der Sitzung -
angemeldet ist noch niemand.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from kern import einstellungen as cfg
from kern import mail, protokoll
from kern.datenbank import hole_db
from kern.modelle import EmailChangeRequest, PasswordResetToken, User
from kern.sicherheit import (
    LOGIN_MAX_VERSUCHE, LOGIN_SPERRE_MINUTEN, PASSWORT_REGEL, gleich,
    hash_veraltet, konto_gesperrt_bis, passwort_bewerten, passwort_hashen,
    ersatzcode_einloesen, ersatzcodes_offen, passwort_pruefen,
    token_erzeugen, token_hashen, totp_pruefen,
)
from kern.sitzung import (
    anmeldung_protokollieren, csrf_gueltig, csrf_hinweis, csrf_token,
    sitzung_anlegen, sitzung_beenden, angemeldete_person,
)
from kern.text import email_gueltig, email_normal, utcnow
from kern.vorlagen import zeige

router = APIRouter()

RESET_GUELTIG_MINUTEN = 60
ADRESSWECHSEL_GUELTIG_STUNDEN = 24
# Wie lange man Zeit hat, den zweiten Faktor einzugeben. Danach faengt die
# Anmeldung von vorn an - ein halb angemeldeter Zustand soll nicht stundenlang
# in der Sitzung liegen.
ZWEITER_FAKTOR_MINUTEN = 5


def _anmeldeseite(request: Request, **rest):
    grund = dict(
        user=None, csrf=csrf_token(request), fehler=None, hinweis=None,
        email="", zweiter_faktor=False,
        # Kein Schulname im Titel und keine Beschreibung: Eine Seite mit
        # Passwortfeld, die eine fremde Einrichtung im Kopf traegt, sieht fuer
        # einen Phishing-Filter aus wie ein Nachbau. Genau daran hat sich
        # Chrome gestossen. Siehe vorlagen/oeffentlich/basis_web.html.
        seitentitel="Anmelden | Wirtschafts- & Investment-AG",
        seitenbeschreibung="",
        anmeldeseite=True,
        robots="noindex, nofollow", pfad="/login")
    grund.update(rest)
    return zeige("oeffentlich/anmeldung.html", request=request, **grund)


@router.get("/login")
def anmelden_seite(request: Request, abbrechen: int = 0,
                   db: Session = Depends(hole_db)):
    if abbrechen:
        request.session.pop("halbe_anmeldung", None)
    if angemeldete_person(request, db):
        return RedirectResponse(f"{cfg.adressen_fuer(request)[1]}/", status_code=303)
    offen = request.session.get("halbe_anmeldung")
    return _anmeldeseite(request, zweiter_faktor=bool(offen))


@router.post("/login")
def anmelden(request: Request, email: str = Form(""),
             passwort: str = Form(""), csrf: str = Form(""),
             angemeldet_bleiben: str = Form(""),
             db: Session = Depends(hole_db)):
    if not csrf_gueltig(request, csrf):
        # Kein harter Fehler: das passiert regelmaessig ganz harmlos, etwa
        # wenn das Formular lange offen lag oder der Server neu gestartet
        # wurde. Es gibt das Formular mit frischem Token zurueck.
        return _anmeldeseite(request, email=email, fehler=csrf_hinweis(
            request, cfg.HTTPS_ONLY_COOKIES, cfg.TRUST_PROXY_HEADERS))

    adresse = email_normal(email)
    person = db.query(User).filter(User.email == adresse).first()
    jetzt = utcnow()

    gesperrt_bis = konto_gesperrt_bis(person)
    if gesperrt_bis:
        rest = max(1, int((gesperrt_bis - jetzt).total_seconds() // 60) + 1)
        anmeldung_protokollieren(db, request, adresse, person, False,
                                 "gesperrt", cfg.TRUST_PROXY_HEADERS)
        db.commit()
        return _anmeldeseite(request, email=email, fehler=(
            f"Zu viele Fehlversuche. Bitte in {rest} Minute"
            f"{'n' if rest != 1 else ''} noch einmal versuchen."))

    if not person or not passwort_pruefen(passwort, person.password_hash):
        if person:
            person.failed_logins = (person.failed_logins or 0) + 1
            if person.failed_logins >= LOGIN_MAX_VERSUCHE:
                person.locked_until = jetzt + timedelta(minutes=LOGIN_SPERRE_MINUTEN)
                person.failed_logins = 0
                anmeldung_protokollieren(db, request, adresse, person, False,
                                         "gesperrt", cfg.TRUST_PROXY_HEADERS)
                db.commit()
                return _anmeldeseite(request, email=email, fehler=(
                    f"Zu viele Fehlversuche. Das Konto ist für "
                    f"{LOGIN_SPERRE_MINUTEN} Minuten gesperrt."))
        anmeldung_protokollieren(db, request, adresse, person, False,
                                 "falsches passwort", cfg.TRUST_PROXY_HEADERS)
        db.commit()
        return _anmeldeseite(request, email=email,
                             fehler="E-Mail oder Passwort ist falsch.")

    if person.status != "aktiv":
        anmeldung_protokollieren(db, request, adresse, person, False,
                                 "konto inaktiv", cfg.TRUST_PROXY_HEADERS)
        db.commit()
        return _anmeldeseite(request, email=email,
                             fehler="Dieses Konto ist deaktiviert.")

    person.failed_logins = 0
    person.locked_until = None

    # Passwort mit veralteter Kostenstufe still nachziehen. Der Klartext liegt
    # genau jetzt vor - eine zweite Gelegenheit gibt es nicht.
    if hash_veraltet(person.password_hash):
        person.password_hash = passwort_hashen(passwort)

    if person.totp_aktiv and person.totp_secret:
        request.session["halbe_anmeldung"] = {
            "user_id": person.id,
            # Die Wahl von Schritt eins muss den zweiten Schritt ueberleben -
            # dort gibt es das Kaestchen nicht noch einmal.
            "bleiben": bool(angemeldet_bleiben),
            "bis": (jetzt + timedelta(minutes=ZWEITER_FAKTOR_MINUTEN)).isoformat(),
        }
        db.commit()
        # Die Bremse zaehlt das nicht als Fehlversuch - das Passwort stimmte.
        request.state.bremse_frei = True
        return _anmeldeseite(request, zweiter_faktor=True)

    return _abschliessen(request, db, person, bool(angemeldet_bleiben))


@router.post("/login/zweiter-faktor")
def zweiter_faktor(request: Request, code: str = Form(""),
                   csrf: str = Form(""), db: Session = Depends(hole_db)):
    offen = request.session.get("halbe_anmeldung")
    if not offen:
        return _anmeldeseite(request, fehler="Bitte melde dich neu an.")
    if not csrf_gueltig(request, csrf):
        return _anmeldeseite(request, zweiter_faktor=True, fehler=csrf_hinweis(
            request, cfg.HTTPS_ONLY_COOKIES, cfg.TRUST_PROXY_HEADERS))

    from datetime import datetime
    try:
        abgelaufen = datetime.fromisoformat(offen["bis"]) < utcnow()
    except Exception:
        abgelaufen = True
    if abgelaufen:
        request.session.pop("halbe_anmeldung", None)
        return _anmeldeseite(request, fehler=(
            "Das hat zu lange gedauert. Bitte melde dich noch einmal an."))

    person = db.get(User, offen["user_id"])
    if not person or person.status != "aktiv":
        request.session.pop("halbe_anmeldung", None)
        return _anmeldeseite(request, fehler="Bitte melde dich neu an.")

    if not totp_pruefen(person.totp_secret, code):
        # Kein Zahlencode? Dann vielleicht einer der Ersatzcodes. Er gilt
        # genau einmal und wird dabei verbraucht.
        geklappt, rest = ersatzcode_einloesen(person.totp_ersatzcodes, code)
        if not geklappt:
            anmeldung_protokollieren(db, request, person.email, person, False,
                                     "falscher code", cfg.TRUST_PROXY_HEADERS)
            db.commit()
            return _anmeldeseite(request, zweiter_faktor=True,
                                 fehler="Der Code stimmt nicht. Noch einmal versuchen.")
        person.totp_ersatzcodes = rest
        uebrig = ersatzcodes_offen(rest)
        protokoll.notiere(db, person.id, "2fa_ersatzcode", f"noch {uebrig}")
        db.commit()
        # Wer hier landet, hat sein Handy nicht zur Hand. Ein Hinweis per
        # E-Mail ist zugleich die Warnung, falls es nicht er selbst war.
        try:
            mail.sende_vordruck(db, person, "notification",
                                titel="Ersatzcode benutzt",
                                text=("Bei einer Anmeldung wurde einer deiner "
                                      f"Ersatzcodes eingelöst. Es sind noch "
                                      f"{uebrig} übrig. Warst du das nicht, "
                                      "ändere sofort dein Passwort."))
        except Exception:                                    # pragma: no cover
            pass

    bleiben = bool(offen.get("bleiben", True))
    request.session.pop("halbe_anmeldung", None)
    return _abschliessen(request, db, person, bleiben)


def _abschliessen(request: Request, db: Session, person: User,
                  angemeldet_bleiben: bool = True):
    """Sitzung anlegen und ins Dashboard schicken."""
    sitzung_anlegen(db, request, person, cfg.TRUST_PROXY_HEADERS,
                    dauerhaft=angemeldet_bleiben)
    anmeldung_protokollieren(db, request, person.email, person, True, "",
                             cfg.TRUST_PROXY_HEADERS)
    protokoll.notiere(db, person.id, "login")
    db.commit()
    # Eine geglueckte Anmeldung ist kein Angriffsversuch - sonst blockierten
    # sich beim AG-Treffen alle gegenseitig, die hinter derselben Adresse sitzen.
    request.state.bremse_frei = True
    return RedirectResponse(f"{cfg.adressen_fuer(request)[1]}/", status_code=303)


@router.get("/logout")
def abmelden(request: Request, db: Session = Depends(hole_db)):
    sitzung_beenden(db, request)
    db.commit()
    return RedirectResponse("/", status_code=303)


#  Passwort vergessen
@router.get("/passwort-vergessen")
def passwort_vergessen_seite(request: Request, db: Session = Depends(hole_db)):
    if angemeldete_person(request, db):
        return RedirectResponse(f"{cfg.adressen_fuer(request)[1]}/", status_code=303)
    return zeige("oeffentlich/passwort.html", request=request, user=None,
                 art="anfordern", csrf=csrf_token(request), erfolg=False,
                 fehler=None, minuten=RESET_GUELTIG_MINUTEN,
                 mail_moeglich=mail.versand_moeglich(),
                 robots="noindex, nofollow", pfad="/passwort-vergessen",
                 seitentitel="Passwort vergessen | Wirtschafts- & Investment-AG",
                 seitenbeschreibung="", anmeldeseite=True)


@router.post("/passwort-vergessen")
def passwort_vergessen(request: Request, email: str = Form(""),
                       csrf: str = Form(""),
                       db: Session = Depends(hole_db)):
    def antwort(erfolg, fehler=None):
        return zeige("oeffentlich/passwort.html", request=request, user=None,
                     art="anfordern", csrf=csrf_token(request), erfolg=erfolg,
                     fehler=fehler, minuten=RESET_GUELTIG_MINUTEN,
                     mail_moeglich=mail.versand_moeglich(),
                     robots="noindex, nofollow", pfad="/passwort-vergessen")

    if not csrf_gueltig(request, csrf):
        return antwort(False, csrf_hinweis(request, cfg.HTTPS_ONLY_COOKIES,
                                           cfg.TRUST_PROXY_HEADERS))
    adresse = email_normal(email)
    if not email_gueltig(adresse):
        return antwort(False, "Diese E-Mail-Adresse sieht nicht richtig aus.")

    person = db.query(User).filter(User.email == adresse,
                                   User.status == "aktiv").first()
    if person:
        # Aeltere, noch offene Token entwerten: sonst haette jemand, der eine
        # alte Mail in die Finger bekommt, weiterhin einen gueltigen Weg hinein.
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == person.id,
            PasswordResetToken.used_at.is_(None)).update(
                {"used_at": utcnow()}, synchronize_session=False)
        roh = token_erzeugen(32)
        db.add(PasswordResetToken(
            user_id=person.id, token_hash=token_hashen(roh),
            expires_at=utcnow() + timedelta(minutes=RESET_GUELTIG_MINUTEN)))
        db.commit()
        # Der Link muss auf die Seite zeigen, auf der die Person GERADE
        # steht. Vorher stand hier fest cfg.WEBSITE_URL: Wer die Anlage
        # oertlich oder unter einem anderen Namen benutzte, bekam eine Mail
        # mit einem Link auf den Live-Betrieb - und dort gilt das Token
        # nicht. Fuer alle anderen aendert sich nichts, weil der Aufruf von
        # aussen ohnehin die eingestellte Adresse liefert.
        website, _ = cfg.adressen_fuer(request)
        mail.sende_vordruck(db, person, "password_reset",
                            link=f"{website}/passwort-neu?token={roh}",
                            minuten=RESET_GUELTIG_MINUTEN)
    # Immer dieselbe Antwort - sonst verraet die Seite, welche Adressen es gibt.
    return antwort(True)


@router.get("/passwort-neu")
def passwort_neu_seite(request: Request, token: str = "",
                       db: Session = Depends(hole_db)):
    eintrag = _reset_token(db, token)
    return zeige("oeffentlich/passwort.html", request=request, user=None,
                 art="neu", csrf=csrf_token(request), erfolg=False, fehler=None,
                 gueltig=bool(eintrag), token=token, regel=PASSWORT_REGEL,
                 robots="noindex, nofollow", pfad="/passwort-neu",
                 seitentitel="Neues Passwort | Wirtschafts- & Investment-AG",
                 seitenbeschreibung="", anmeldeseite=True)


@router.post("/passwort-neu")
def passwort_neu(request: Request, token: str = Form(""),
                 passwort: str = Form(""), passwort2: str = Form(""),
                 csrf: str = Form(""), db: Session = Depends(hole_db)):
    def antwort(erfolg, fehler=None, gueltig=True):
        return zeige("oeffentlich/passwort.html", request=request, user=None,
                     art="neu", csrf=csrf_token(request), erfolg=erfolg,
                     fehler=fehler, gueltig=gueltig, token=token,
                     regel=PASSWORT_REGEL, robots="noindex, nofollow",
                     pfad="/passwort-neu")

    if not csrf_gueltig(request, csrf):
        return antwort(False, csrf_hinweis(request, cfg.HTTPS_ONLY_COOKIES,
                                           cfg.TRUST_PROXY_HEADERS))
    eintrag = _reset_token(db, token)
    if not eintrag:
        return antwort(False, gueltig=False)
    if not gleich(passwort, passwort2):
        return antwort(False, "Die beiden Passwörter stimmen nicht überein.")

    person = db.get(User, eintrag.user_id)
    if not person:
        return antwort(False, gueltig=False)
    gut, meldung = passwort_bewerten(passwort, (person.vorname, person.nachname))
    if not gut:
        return antwort(False, meldung)

    person.password_hash = passwort_hashen(passwort)
    person.passwort_geaendert_am = utcnow()
    person.failed_logins = 0
    person.locked_until = None
    eintrag.used_at = utcnow()
    # Alle offenen Sitzungen beenden: Wer sein Passwort zuruecksetzt, hat oft
    # den Verdacht, dass jemand anderes drin war. Dann muss der auch raus.
    from kern.modelle import UserSession
    db.query(UserSession).filter(UserSession.user_id == person.id,
                                 UserSession.revoked == 0).update(
                                     {"revoked": 1}, synchronize_session=False)
    protokoll.notiere(db, person.id, "passwort_zurueckgesetzt")
    db.commit()
    request.state.bremse_frei = True
    return antwort(True)


def _reset_token(db: Session, roh: str):
    if not roh:
        return None
    eintrag = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hashen(roh)).first()
    if not eintrag or eintrag.used_at or eintrag.expires_at < utcnow():
        return None
    return eintrag


#  Adresswechsel bestaetigen
@router.get("/email-bestaetigen")
def email_bestaetigen(request: Request, token: str = "",
                      db: Session = Depends(hole_db)):
    def antwort(erfolg, fehler=None, neue=None):
        return zeige("oeffentlich/passwort.html", request=request, user=None,
                     art="email", csrf=csrf_token(request), erfolg=erfolg,
                     fehler=fehler, neue_adresse=neue,
                     robots="noindex, nofollow", pfad="/email-bestaetigen")

    if not token:
        return antwort(False)
    eintrag = db.query(EmailChangeRequest).filter(
        EmailChangeRequest.token_hash == token_hashen(token)).first()
    if not eintrag or eintrag.used_at or eintrag.expires_at < utcnow():
        return antwort(False)

    person = db.get(User, eintrag.user_id)
    if not person:
        return antwort(False)
    neue = email_normal(eintrag.new_email)
    # In der Zwischenzeit koennte die Adresse vergeben worden sein.
    if db.query(User).filter(User.email == neue, User.id != person.id).first():
        eintrag.used_at = utcnow()
        db.commit()
        return antwort(False, "Diese Adresse wird inzwischen von einem anderen "
                              "Konto benutzt.")

    person.email = neue
    eintrag.used_at = utcnow()
    protokoll.notiere(db, person.id, "email_geaendert", neue)
    db.commit()
    return antwort(True, neue=neue)
