from fastapi import APIRouter, Depends, Form

from dashboard.hilfen import Anmeldung, fehler, gut, teil
from kern import cloudflare, protokoll
from kern.modelle import Funktionsadresse
from kern.text import email_gueltig, email_normal, sauber

router = APIRouter(prefix="/dashboard")


def _ansicht(a, meldung=None):
    cloudflare.vorbefuellen(a.db)
    cloudflare.aus_konten_aktualisieren(a.db)
    return teil("dashboard/funktionsadressen.html", a,
                positionen=a.db.query(Funktionsadresse)
                .order_by(Funktionsadresse.id).all(),
                cloudflare_konfiguriert=cloudflare.konfiguriert(),
                meldung=meldung)


@router.get("/funktionsadressen")
def bereich(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("funktionsadressen")
    return _ansicht(a)


@router.post("/funktionsadressen/{position_id}")
def speichern(position_id: int, person: str = Form(""),
              email: str = Form(""), csrf: str = Form(""),
              a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("funktionsadressen")
    a.pruefe_csrf(csrf)
    cloudflare.vorbefuellen(a.db)
    cloudflare.aus_konten_aktualisieren(a.db)
    position = a.db.get(Funktionsadresse, position_id)
    if not position:
        return _ansicht(a, fehler("Diese Funktionsadresse gibt es nicht mehr."))
    try:
        if position.destination_email:
            status = cloudflare.synchronisieren(position)
            if status == "Synchronisiert":
                protokoll.notiere(a.db, a.user.id, "cloudflare_synchronisiert",
                                  position.routing_address)
        else:
            position.sync_status = "Kein Ziel hinterlegt"
            position.last_error = None
        a.db.commit()
    except cloudflare.CloudflareFehler as problem:
        position.sync_status = "Synchronisation fehlgeschlagen"
        position.last_error = str(problem)[:500]
        a.db.commit()
        return _ansicht(a, fehler(f"Cloudflare konnte nicht synchronisieren: {problem}"))
    return _ansicht(a, gut("Funktionsadresse gespeichert und Cloudflare geprüft."))


@router.post("/funktionsadressen/synchronisieren")
def alle_synchronisieren(csrf: str = Form(""),
                          a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("funktionsadressen")
    a.pruefe_csrf(csrf)
    cloudflare.vorbefuellen(a.db)
    cloudflare.aus_konten_aktualisieren(a.db)
    fehler_anzahl = 0
    for position in a.db.query(Funktionsadresse).order_by(Funktionsadresse.id):
        try:
            status = cloudflare.synchronisieren(position)
            if status == "Synchronisiert":
                protokoll.notiere(a.db, a.user.id, "cloudflare_synchronisiert",
                                  position.routing_address)
        except cloudflare.CloudflareFehler as problem:
            position.sync_status = "Synchronisation fehlgeschlagen"
            position.last_error = str(problem)[:500]
            fehler_anzahl += 1
    a.db.commit()
    if fehler_anzahl:
        return _ansicht(a, fehler(f"{fehler_anzahl} Synchronisation(en) fehlgeschlagen."))
    return _ansicht(a, gut("Cloudflare-Status wurde geprüft."))
