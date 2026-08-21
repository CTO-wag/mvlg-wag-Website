"""Wer ist angemeldet - und darf die Person das?

Beide Server-Prozesse benutzen dieselbe Cookie-Sitzung. Das funktioniert,
weil Cookies nicht nach Port getrennt werden: was localhost:8000 setzt,
schickt der Browser auch an localhost:8001. Beide Prozesse lesen denselben
SECRET_KEY aus config.cmd und dieselbe Tabelle user_sessions.

Der Cookie allein wuerde nicht genuegen. Er ist signiert, aber der Server
koennte ihn nicht zurueckziehen - eine gestohlene Sitzung liefe bis zum
Ablauf weiter. Deshalb traegt er nur eine Sitzungs-ID, und die eigentliche
Sitzung steht in der Datenbank: dort laesst sie sich beenden, ihr Alter
pruefen und an den Browser binden.
"""

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from kern.einstellungen import (
    SITZUNG_DAUERHAFT_LEERLAUF_TAGE, SITZUNG_DAUERHAFT_TAGE,
    SECRET_KEY, SITZUNG_HOECHSTDAUER_STUNDEN, SITZUNG_LEERLAUF_MINUTEN,
    adressen_fuer,
)
from kern.modelle import Anmeldeversuch, User, UserSession
from kern.rechte import hat_recht, persoenliche_rechte, rechte_von
from kern.sicherheit import geraete_fingerabdruck, token_erzeugen
from kern.text import utcnow


def client_ip(request: Request, proxy_vertrauen: bool) -> str:
    ip = request.client.host if request.client else "unbekannt"
    if proxy_vertrauen:
        weiter = request.headers.get("x-forwarded-for")
        if weiter:
            ip = weiter.split(",")[0].strip()
    return ip[:64]


def sitzung_anlegen(db, request: Request, user: User, proxy_vertrauen: bool,
                    dauerhaft: bool = True) -> str:
    """Neue serverseitige Sitzung. Gibt die ID zurueck.

    `dauerhaft` entscheidet ueber die Fristen: mit Haken die langen (Monate),
    ohne die kurzen (Stunden). Standard ist mit - das ist der Alltag, und ein
    gemeinsam benutzter Rechner ist die Ausnahme.
    """
    sid = token_erzeugen(32)
    ua = (request.headers.get("user-agent") or "")[:240]
    db.add(UserSession(
        id=sid, user_id=user.id,
        ip_address=client_ip(request, proxy_vertrauen),
        user_agent=ua,
        geraete_hash=geraete_fingerabdruck(ua, SECRET_KEY),
        dauerhaft=1 if dauerhaft else 0,
    ))
    request.session.clear()          # alte Inhalte nicht mitschleppen
    request.session["user_id"] = user.id
    request.session["sid"] = sid
    return sid


def sitzung_beenden(db, request: Request) -> None:
    sid = request.session.get("sid")
    if sid:
        eintrag = db.get(UserSession, sid)
        if eintrag:
            eintrag.revoked = 1
    request.session.clear()


def angemeldete_person(request: Request, db):
    """Die angemeldete Person - oder None.

    Prueft der Reihe nach: Gibt es das Konto noch, ist es aktiv, lebt die
    Sitzung, gehoert sie zu diesem Konto, ist sie nicht zu alt und kommt sie
    aus demselben Browser. Faellt eine Pruefung durch, wird der Cookie
    geleert; ein halb gueltiger Zustand waere die schlimmste Variante.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if not user or user.status != "aktiv":
        request.session.clear()
        return None

    sid = request.session.get("sid")
    if not sid:
        # Sitzungen aus V1 trugen bereits eine sid; fehlt sie, ist der Cookie
        # von Hand gebastelt oder uralt.
        request.session.clear()
        return None

    eintrag = db.get(UserSession, sid)
    jetzt = utcnow()
    if not eintrag or eintrag.revoked or eintrag.user_id != user.id:
        request.session.clear()
        return None

    # Welche Fristen gelten, haengt an der Wahl beim Anmelden.
    if getattr(eintrag, "dauerhaft", 1):
        leerlauf = SITZUNG_DAUERHAFT_LEERLAUF_TAGE * 86400
        hoechstdauer = SITZUNG_DAUERHAFT_TAGE * 86400
    else:
        leerlauf = SITZUNG_LEERLAUF_MINUTEN * 60
        hoechstdauer = SITZUNG_HOECHSTDAUER_STUNDEN * 3600

    letzte = eintrag.last_active or eintrag.created_at or jetzt
    if (jetzt - letzte).total_seconds() > leerlauf:
        eintrag.revoked = 1
        db.commit()
        request.session.clear()
        return None
    begonnen = eintrag.created_at or jetzt
    if (jetzt - begonnen).total_seconds() > hoechstdauer:
        eintrag.revoked = 1
        db.commit()
        request.session.clear()
        return None

    # Browserbindung. Sitzungen aus V1 haben noch keinen Fingerabdruck - die
    # bekommen ihn jetzt, statt abgewiesen zu werden. Sonst waere der erste
    # Effekt des Umstiegs, dass alle rausfliegen.
    aktuell = geraete_fingerabdruck(request.headers.get("user-agent") or "", SECRET_KEY)
    if not eintrag.geraete_hash:
        eintrag.geraete_hash = aktuell
    elif eintrag.geraete_hash != aktuell:
        eintrag.revoked = 1
        db.commit()
        request.session.clear()
        return None

    # Nicht bei jedem Aufruf schreiben - das waere ein Schreibzugriff je Bild
    # und je htmx-Nachladung.
    if (jetzt - letzte).total_seconds() > 60:
        eintrag.last_active = jetzt
        db.commit()

    # Persoenliche Rechteausnahmen einmal je Anfrage laden und am Objekt
    # merken, damit rechte_von() sie ohne weitere Abfrage findet.
    user._rechte_ausnahmen = persoenliche_rechte(db, user.id)
    return user


def anmeldung_protokollieren(db, request: Request, email: str, user, erfolg: bool,
                             grund: str, proxy_vertrauen: bool) -> None:
    db.add(Anmeldeversuch(
        email=(email or "")[:160],
        user_id=user.id if user else None,
        erfolg=1 if erfolg else 0,
        grund=(grund or "")[:60] or None,
        ip_address=client_ip(request, proxy_vertrauen),
        user_agent=(request.headers.get("user-agent") or "")[:240],
    ))


#  Wachen
def wache(user, request: Request = None, anmelde_url: str = None):
    """Antwort, wenn niemand angemeldet ist - sonst None.

    Bei einem htmx-Nachladen darf kein Redirect kommen: der wuerde die
    Anmeldeseite in den Inhaltsbereich des Dashboards laden. Stattdessen ein
    kurzer Hinweis mit Verweis, und ein Kopfzeilen-Befehl fuer htmx, die ganze
    Seite umzuleiten.
    """
    if user:
        return None
    if not anmelde_url:
        anmelde_url = f"{adressen_fuer(request)[0]}/login"
    ziel = anmelde_url
    if request is not None and request.headers.get("HX-Request") == "true":
        # Bewusst KEIN HX-Redirect: der wuerde die Seite auf der Stelle
        # wechseln. Wer gerade einen langen Text getippt hat, verliert ihn
        # dann ersatzlos - und sieht nicht einmal, warum. So bleibt das
        # Fenster stehen, der Text ist noch da und laesst sich kopieren.
        return HTMLResponse(
            '<div class="panel meldung meldung-warnung"><div>'
            '<strong>Deine Anmeldung ist abgelaufen.</strong>'
            '<p>Aus Sicherheitsgründen endet eine Sitzung nach längerer '
            'Pause. Falls du gerade etwas eingetippt hast: kopier es dir '
            'kurz heraus, bevor du dich neu anmeldest.</p>'
            f'<p style="margin-top:.75rem;"><a class="btn" href="{ziel}">'
            'Neu anmelden</a></p></div></div>',
            status_code=401)
    return RedirectResponse(ziel, status_code=303)


def verlange(user, perm: str, db=None) -> None:
    """Bricht mit 403 ab, wenn das Recht fehlt."""
    if not hat_recht(user, perm, db):
        raise HTTPException(403, "Für diesen Bereich fehlt dir die Berechtigung.")


def verlange_eines(user, *perms, db=None) -> None:
    """Mindestens eines der genannten Rechte muss vorhanden sein."""
    rechte = rechte_von(user, db)
    if not any(rechte.get(p) for p in perms):
        raise HTTPException(403, "Für diesen Bereich fehlt dir die Berechtigung.")


#  CSRF
#  Doppelte Absicherung: Der Token steht in der Sitzung UND im Formular. Ein
#  fremdes Formular auf einer fremden Seite kann den Sitzungswert nicht lesen
#  und damit auch nicht mitschicken.

def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = token_erzeugen(16)
        request.session["csrf"] = token
    return token


def csrf_gueltig(request: Request, token: str) -> bool:
    from kern.sicherheit import gleich
    erwartet = request.session.get("csrf")
    return bool(token and erwartet) and gleich(token, erwartet)


def csrf_hinweis(request: Request, https_pflicht: bool, proxy_vertrauen: bool) -> str:
    """Verstaendliche Meldung statt eines nackten Fehlers 400.

    Haeufigste Ursache im Betrieb: Die Seite wurde ueber http:// geoeffnet,
    waehrend die Cookies als "nur HTTPS" markiert sind. Der Browser schickt
    sie dann nicht zurueck und jede Anmeldung scheitert.
    """
    ueber_https = request.url.scheme == "https" or (
        proxy_vertrauen and request.headers.get("x-forwarded-proto") == "https")
    if https_pflicht and not ueber_https:
        return ("Die Anmeldung ist über eine unverschlüsselte Verbindung nicht "
                "möglich. Bitte rufe die Seite über https:// auf.")
    return "Das Formular war zu lange offen. Bitte noch einmal abschicken."
