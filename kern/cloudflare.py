"""Serverseitige Verwaltung der festen Cloudflare Email-Routing-Adressen."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kern import einstellungen as cfg
from kern.modelle import Funktionsadresse, User
from kern.text import email_normal, utcnow

FUNKTIONEN = (
    ("mail", "Allgemeine Mail", "mail@mvlg-wag.de", "coo", "exekutive"),
    ("kontakt", "Kontakt", "kontakt@mvlg-wag.de", "coo", "exekutive"),
    ("ceo", "CEO", "ceo@exekutive.mvlg-wag.de", "ceo", "exekutive"),
    ("coo", "COO", "coo@exekutive.mvlg-wag.de", "coo", "exekutive"),
    ("cmo", "CMO", "cmo@marketing.mvlg-wag.de", "cmo", "marketing"),
    ("cro", "CRO", "cro@recruitment.mvlg-wag.de", "cro", "recruitment"),
    ("cto", "CTO", "cto@tech.mvlg-wag.de", "cto", "tech"),
)
API = "https://api.cloudflare.com/client/v4"


class CloudflareFehler(RuntimeError):
    pass


def konfiguriert() -> bool:
    return bool(cfg.CLOUDFLARE_API_TOKEN and cfg.CLOUDFLARE_ACCOUNT_ID
                and cfg.CLOUDFLARE_ZONE_ID)


def vorbefuellen(db) -> None:
    vorhanden = {x.key for x in db.query(Funktionsadresse.key).all()}
    for key, label, address, _, _ in FUNKTIONEN:
        if key not in vorhanden:
            db.add(Funktionsadresse(key=key, label=label,
                                    routing_address=address))
    db.commit()


def aus_konten_aktualisieren(db) -> None:
    """Übernimmt die Zuständigkeiten aus den bestehenden Rollen-Konten."""
    for position in db.query(Funktionsadresse).all():
        eintrag = next((x for x in FUNKTIONEN if x[0] == position.key), None)
        if not eintrag:
            continue
        _, _, _, rolle, abteilung = eintrag
        person = (db.query(User).filter(User.role == rolle,
                                        User.department == abteilung,
                                        User.status == "aktiv")
                  .order_by(User.id).first())
        if not person:
            person = (db.query(User).filter(User.role == rolle,
                                            User.status == "aktiv")
                      .order_by(User.id).first())
        if person:
            position.person_name = person.name
            if position.destination_email != email_normal(person.email):
                position.destination_email = email_normal(person.email)
                position.destination_verified = 0
                position.routing_active = 0
                position.sync_status = "Änderung ausstehend"


def synchronisiere_aus_konten(db, rollen=None) -> int:
    """Synchronisiert nur Funktionsadressen betroffener Rollen-Konten."""
    rollen = set(rollen or ("ceo", "coo", "cmo", "cro", "cto"))
    aus_konten_aktualisieren(db)
    erledigt = 0
    for position in db.query(Funktionsadresse).all():
        eintrag = next((x for x in FUNKTIONEN if x[0] == position.key), None)
        if not eintrag or eintrag[3] not in rollen or not position.destination_email:
            continue
        try:
            synchronisieren(position)
            erledigt += 1
        except CloudflareFehler as problem:
            position.sync_status = "Synchronisation fehlgeschlagen"
            position.last_error = str(problem)[:500]
    db.commit()
    return erledigt


def _anfrage(methode: str, pfad: str, daten=None):
    if not konfiguriert():
        raise CloudflareFehler("Cloudflare ist nicht vollständig konfiguriert.")
    koerper = None if daten is None else json.dumps(daten).encode("utf-8")
    request = Request(f"{API}{pfad}", data=koerper, method=methode,
                      headers={"Authorization": f"Bearer {cfg.CLOUDFLARE_API_TOKEN}",
                               "Content-Type": "application/json",
                               "Accept": "application/json"})
    try:
        with urlopen(request, timeout=20) as antwort:
            inhalt = json.loads(antwort.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as problem:
        detail = getattr(problem, "read", lambda: b"")()
        try:
            detail = json.loads(detail.decode("utf-8")).get("errors", [])
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
            detail = str(problem)
        raise CloudflareFehler(f"Cloudflare API: {detail}") from problem
    if not inhalt.get("success"):
        raise CloudflareFehler(f"Cloudflare API: {inhalt.get('errors')}")
    return inhalt.get("result")


def _seitenweise(pfad: str) -> list:
    result, page = [], 1
    while True:
        daten = _anfrage("GET", f"{pfad}?page={page}&per_page=100")
        if isinstance(daten, dict) and "result" in daten:
            result.extend(daten["result"])
            info = daten.get("result_info", {})
            if page >= info.get("total_pages", page):
                break
        else:
            result.extend(daten or [])
            break
        page += 1
    return result


def _ziele() -> list:
    return _seitenweise(f"/accounts/{cfg.CLOUDFLARE_ACCOUNT_ID}/email/routing/addresses")


def _regeln() -> list:
    return _seitenweise(f"/zones/{cfg.CLOUDFLARE_ZONE_ID}/email/routing/rules")


def _regel_fuer(regeln: list, adresse: str):
    return next((r for r in regeln if any(
        m.get("type") == "literal" and m.get("field") == "to"
        and email_normal(m.get("value", "")) == email_normal(adresse)
        for m in r.get("matchers", []))), None)


def synchronisieren(position: Funktionsadresse) -> str:
    """Synchronisiert eine Position, ohne eine unbestätigte Adresse zu aktivieren."""
    if not konfiguriert():
        position.sync_status = "Cloudflare nicht konfiguriert"
        position.last_error = "CLOUDFLARE_API_TOKEN, ACCOUNT_ID und ZONE_ID fehlen."
        return position.sync_status
    ziele = _ziele()
    regeln = _regeln()
    regel = _regel_fuer(regeln, position.routing_address)

    # Beim erstmaligen Einrichten wird die bestehende, korrekte Cloudflare-
    # Konfiguration übernommen. Es wird dabei nichts an Cloudflare geändert.
    if not position.destination_email and regel:
        weiterleitungen = [
            a.get("value", []) for a in regel.get("actions", [])
            if a.get("type") == "forward"
        ]
        aktuell = next((x for x in weiterleitungen if x), None)
        if aktuell:
            email = email_normal(aktuell[0])
            ziel = next((x for x in ziele
                         if email_normal(x.get("email", "")) == email), None)
            position.destination_email = email
            position.destination_id = ziel.get("id") if ziel else None
            position.destination_verified = 1 if ziel and ziel.get("verified") else 0
            position.routing_rule_id = regel.get("id")
            position.routing_active = 1 if regel.get("enabled") else 0
            position.sync_status = ("Synchronisiert" if position.routing_active
                                    and position.destination_verified
                                    else "Verifizierung ausstehend")
            position.last_error = None
            position.last_synced_at = utcnow()
            return position.sync_status

    if not position.destination_email:
        position.sync_status = "Kein Ziel hinterlegt"
        position.last_error = None
        return position.sync_status

    email = email_normal(position.destination_email)
    ziel = next((x for x in ziele if email_normal(x.get("email", "")) == email), None)
    if not ziel:
        ziel = _anfrage(
            "POST", f"/accounts/{cfg.CLOUDFLARE_ACCOUNT_ID}/email/routing/addresses",
            {"email": email})
        ziele.append(ziel)
    position.destination_id = ziel.get("id")
    position.destination_verified = 1 if ziel.get("verified") else 0
    if not position.destination_verified:
        position.routing_active = 0
        position.sync_status = "Verifizierung ausstehend"
        position.last_error = None
        position.last_synced_at = utcnow()
        return position.sync_status

    aktionen = [{"type": "forward", "value": [email]}]
    if regel:
        _anfrage("PUT",
                 f"/zones/{cfg.CLOUDFLARE_ZONE_ID}/email/routing/rules/{regel['id']}",
                 {"actions": aktionen, "enabled": True, "matchers": regel["matchers"]})
        position.routing_rule_id = regel["id"]
    else:
        regel = _anfrage(
            "POST", f"/zones/{cfg.CLOUDFLARE_ZONE_ID}/email/routing/rules",
            {"actions": aktionen, "enabled": True,
             "matchers": [{"field": "to", "type": "literal",
                           "value": position.routing_address}]})
        position.routing_rule_id = regel.get("id")
    position.routing_active = 1
    position.sync_status = "Synchronisiert"
    position.last_error = None
    position.last_synced_at = utcnow()
    return position.sync_status
