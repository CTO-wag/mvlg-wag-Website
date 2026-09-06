"""Nutzer-Analyse: alles, was über eine Person technisch bekannt ist.

Der Bereich beantwortet die Frage, mit der jede zweite Support-Anfrage
anfängt: "Bei mir geht das nicht." Statt drei Rückfragen zu stellen, wählt
der Support die Person aus und sieht Gerät, Browser, Leitung, Zeitzone,
Push-Berechtigung, die letzten Anmeldungen, die letzten Browserfehler und
was an Meldungen tatsächlich rausgegangen ist.

Zusammengetragen wird hier nur - erhoben wird an anderer Stelle. Die Quellen
stehen bereits alle in der Datenbank (Sitzungen, Anmeldeversuche,
Aktivitätsprotokoll, Zustellprotokoll, Push-Anmeldungen) oder kommen aus
kern/diagnose.py. Dieser Bereich legt nichts Neues an.

Zugang nur für den CTO. Nicht über ein Recht, das sich vergeben ließe: Wer
hier hereinsieht, sieht IP-Adressen und Geräte von Minderjährigen. Das ist
kein Recht, das man im Vorbeigehen an eine Rolle hängt - wer es braucht,
bekommt es als bewusste Änderung an dieser Zeile.

Jeder Aufruf wird protokolliert (activity_log). Eine Einsicht, die niemand
nachvollziehen kann, ist keine Einsicht, sondern eine Überwachung.
"""

import json

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy import func, or_

from dashboard.hilfen import Anmeldung, gut, teil, zahl
from kern import diagnose, protokoll
from kern import einstellungen as cfg
from kern.modelle import (
    ActivityLog, Anmeldeversuch, ClientFehler, DeliveryLog, Geraeteprofil,
    NotificationPreference, PushSubscription, SupportTicket, User,
    UserPreference, UserSession,
)
from kern.text import utcnow

router = APIRouter(prefix="/dashboard")


def _nur_cto(a: Anmeldung) -> None:
    """Die Grenze dieses Bereichs. Bewusst hart und ohne Ausnahme.

    Kein `a.verlange(...)`: Ein Recht wäre über die Rollenverwaltung
    vergebbar, und damit wäre in einem halben Jahr nicht mehr
    nachvollziehbar, wer die Geräte- und Anmeldedaten aller Mitglieder
    einsehen kann. Wer das ändern will, ändert diese Zeile - und merkt
    dabei, dass er es tut.
    """
    if a.user.role != "cto":
        raise HTTPException(
            403, "Die Nutzer-Analyse ist dem CTO vorbehalten.")


def _json(text) -> dict:
    try:
        wert = json.loads(text or "{}")
        return wert if isinstance(wert, dict) else {}
    except (ValueError, TypeError):
        return {}


#  Übersicht: wer ist auszuwählen
def _uebersicht(a: Anmeldung, meldung=None):
    db = a.db
    personen = (db.query(User)
                .order_by(User.status, User.vorname, User.nachname).all())

    # Alles in drei Abfragen statt in drei je Person - bei fünfzig
    # Mitgliedern wären das sonst hundertfünfzig.
    letzte = dict(db.query(Geraeteprofil.user_id,
                           func.max(Geraeteprofil.zuletzt))
                  .group_by(Geraeteprofil.user_id).all())
    geraete_zahl = dict(db.query(Geraeteprofil.user_id,
                                 func.count(Geraeteprofil.id))
                        .group_by(Geraeteprofil.user_id).all())
    fehler_zahl = dict(db.query(ClientFehler.user_id,
                                func.count(ClientFehler.id))
                       .group_by(ClientFehler.user_id).all())
    offene_tickets = dict(db.query(SupportTicket.user_id,
                                   func.count(SupportTicket.id))
                          .filter(SupportTicket.status == "offen")
                          .group_by(SupportTicket.user_id).all())
    verdacht = dict(db.query(Geraeteprofil.user_id,
                             func.max(Geraeteprofil.vpn_verdacht))
                    .group_by(Geraeteprofil.user_id).all())

    zeilen = [{
        "person": p,
        "zuletzt": letzte.get(p.id),
        "geraete": geraete_zahl.get(p.id, 0),
        "fehler": fehler_zahl.get(p.id, 0),
        "tickets": offene_tickets.get(p.id, 0),
        "vpn": verdacht.get(p.id, 0) or 0,
    } for p in personen]

    return teil("dashboard/analyse.html", a, zeilen=zeilen, dossier=None,
                erfassung_an=cfg.DIAGNOSE_AKTIV,
                ip_dienst_an=cfg.IP_INFO_AKTIV,
                aufbewahrung=cfg.DIAGNOSE_TAGE, meldung=meldung)


@router.get("/analyse")
def analyse(a: Anmeldung = Depends(Anmeldung.pflicht)):
    _nur_cto(a)
    return _uebersicht(a)


#  Das Dossier einer Person
def _dossier(db, person: User) -> dict:
    """Alles über eine Person, aus allen Quellen zusammengezogen."""
    jetzt = utcnow()

    profile = (db.query(Geraeteprofil)
               .filter(Geraeteprofil.user_id == person.id)
               .order_by(Geraeteprofil.zuletzt.desc()).limit(20).all())
    aufbereitet = []
    for p in profile:
        browser = _json(p.browserdaten)
        kopf = _json(p.kopfdaten)
        # Nach Gruppen sortiert, damit die Vorlage nur noch ausgeben muss.
        gruppen = {}
        for schluessel, name, gruppe, einheit in diagnose.BROWSER_FELDER:
            if schluessel not in browser:
                continue
            gruppen.setdefault(gruppe, []).append(
                (name, f"{browser[schluessel]}{einheit}"))
        kopfzeilen = [(name, kopf[s]) for s, name in diagnose.KOPF_FELDER
                      if kopf.get(s)]
        aufbereitet.append({
            "profil": p,
            "gruppen": [(g, gruppen[g]) for g in diagnose.BROWSER_GRUPPEN
                        if g in gruppen],
            "kopfzeilen": kopfzeilen,
            "hat_browserdaten": bool(browser),
        })

    sitzungen = (db.query(UserSession)
                 .filter(UserSession.user_id == person.id)
                 .order_by(UserSession.last_active.desc()).limit(15).all())

    versuche = (db.query(Anmeldeversuch)
                .filter(or_(Anmeldeversuch.user_id == person.id,
                            Anmeldeversuch.email == person.email))
                .order_by(Anmeldeversuch.created_at.desc()).limit(30).all())

    aktivitaet = (db.query(ActivityLog)
                  .filter(ActivityLog.user_id == person.id)
                  .order_by(ActivityLog.created_at.desc()).limit(40).all())

    browserfehler = (db.query(ClientFehler)
                     .filter(ClientFehler.user_id == person.id)
                     .order_by(ClientFehler.created_at.desc()).limit(30).all())

    # Das Zustellprotokoll kennt keine Konto-Nummer, nur ein "Ziel" - je
    # nach Kanal die Adresse oder der Name. Deshalb über beides suchen.
    zustellungen = (db.query(DeliveryLog)
                    .filter(or_(DeliveryLog.ziel == person.email,
                                DeliveryLog.ziel == person.name))
                    .order_by(DeliveryLog.created_at.desc()).limit(30).all())

    push_geraete = (db.query(PushSubscription)
                    .filter(PushSubscription.user_id == person.id)
                    .order_by(PushSubscription.id.desc()).all())

    tickets = (db.query(SupportTicket)
               .filter(SupportTicket.user_id == person.id)
               .order_by(SupportTicket.created_at.desc()).limit(15).all())

    pref = db.query(UserPreference).filter(
        UserPreference.user_id == person.id).first()
    melde_pref = db.query(NotificationPreference).filter(
        NotificationPreference.user_id == person.id).first()

    # Die paar Zahlen, die oben als Kacheln stehen.
    fehlversuche = sum(1 for v in versuche if not v.erfolg)
    passwort_alter = ((jetzt - person.passwort_geaendert_am).days
                      if person.passwort_geaendert_am else None)

    return {
        "person": person,
        "profile": aufbereitet,
        "sitzungen": sitzungen,
        "versuche": versuche,
        "fehlversuche": fehlversuche,
        "aktivitaet": aktivitaet,
        "browserfehler": browserfehler,
        "zustellungen": zustellungen,
        "push_geraete": push_geraete,
        "tickets": tickets,
        "pref": pref,
        "melde_pref": melde_pref,
        "passwort_alter": passwort_alter,
        "gesperrt": bool(person.locked_until and person.locked_until > jetzt),
    }


@router.get("/analyse/{user_id}")
def analyse_person(user_id: int, a: Anmeldung = Depends(Anmeldung.pflicht)):
    _nur_cto(a)
    person = a.db.get(User, user_id)
    if not person:
        return _uebersicht(a)

    # Wer hier hereingesehen hat, steht im Protokoll. Ohne diese Zeile wäre
    # der Bereich eine stille Einsicht in fremde Geräte- und Anmeldedaten.
    protokoll.notiere(a.db, a.user.id, "analyse_eingesehen",
                      f"{person.name} (#{person.id})")
    a.db.commit()

    return teil("dashboard/analyse.html", a, zeilen=None,
                dossier=_dossier(a.db, person),
                erfassung_an=cfg.DIAGNOSE_AKTIV,
                ip_dienst_an=cfg.IP_INFO_AKTIV,
                aufbewahrung=cfg.DIAGNOSE_TAGE, meldung=None)


@router.post("/analyse/{user_id}/herkunft")
def herkunft_neu(user_id: int, profil_id: str = Form(""), csrf: str = Form(""),
                 a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Die Herkunft einer IP-Adresse jetzt sofort neu abfragen.

    Normalerweise passiert das von selbst, höchstens einmal am Tag je Gerät.
    Wenn jemand gerade am Telefon sitzt und wissen will, ob das ein VPN ist,
    hilft "höchstens einmal am Tag" aber nicht.
    """
    _nur_cto(a)
    a.pruefe_csrf(csrf)
    profil = a.db.get(Geraeteprofil, zahl(profil_id, 0) or 0)
    if not profil or profil.user_id != user_id:
        return analyse_person(user_id, a)

    # Der Zwischenspeicher würde sonst dieselbe alte Antwort zurückgeben.
    diagnose._IP_CACHE.pop(profil.ip_address or "", None)
    diagnose._herkunft_nachtragen(profil.id, profil.ip_address or "")
    a.db.expire_all()

    person = a.db.get(User, user_id)
    return teil("dashboard/analyse.html", a, zeilen=None,
                dossier=_dossier(a.db, person),
                erfassung_an=cfg.DIAGNOSE_AKTIV,
                ip_dienst_an=cfg.IP_INFO_AKTIV,
                aufbewahrung=cfg.DIAGNOSE_TAGE,
                meldung=gut("Herkunft der Adresse neu abgefragt."))
