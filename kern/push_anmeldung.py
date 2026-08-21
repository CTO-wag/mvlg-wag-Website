"""Geraete fuer Web Push an- und abmelden - von beiden Servern aus.

Warum das an zwei Stellen gebraucht wird:

Eine Push-Anmeldung gehoert zu genau einem Ursprung (Schema + Host). Wer die
Startseite auf den Startbildschirm legt, hat eine App vom Ursprung der
Website; wer das Dashboard ablegt, eine vom Ursprung des Dashboards. Nur die
jeweils dort angemeldete Adresse bekommt Meldungen. Laufen beide unter
verschiedenen Namen (mvlg-wag.de und app.mvlg-wag.de), musste man bisher die
richtige Seite erwischen - sonst blieb das Handy still.

Deshalb duerfen sich jetzt beide Seiten anmelden. Damit dasselbe Geraet nicht
jede Meldung doppelt bekommt, traegt jede Anmeldung eine Geraetekennung. Die
steht in einem Cookie, das fuer beide Adressen gilt (siehe COOKIE_DOMAIN).
Beim Verschicken wird je Geraet nur eine Anmeldung bedient - siehe
kern/push.py.
"""

import secrets

from fastapi import Response

from kern import einstellungen as cfg
from kern.modelle import PushSubscription
from kern.sicherheit import geraet_beschreiben
from kern.text import sauber

GERAETE_COOKIE = "wag_geraet"
# Zwei Jahre. Der Wert ist keine Anmeldung und verraet nichts ueber die
# Person - er sagt nur "dies ist dasselbe Geraet wie vorhin".
GERAETE_DAUER = 2 * 365 * 24 * 3600


def geraete_id(request) -> str:
    """Die Kennung dieses Geraets aus dem Cookie - oder eine neue."""
    vorhanden = sauber(request.cookies.get(GERAETE_COOKIE, ""))[:40]
    # Nur Hexzeichen: alles andere hat hier nichts verloren.
    if vorhanden and all(c in "0123456789abcdef" for c in vorhanden):
        return vorhanden
    return secrets.token_hex(16)


def kennung_mitgeben(antwort: Response, kennung: str) -> None:
    antwort.set_cookie(
        GERAETE_COOKIE, kennung, max_age=GERAETE_DAUER,
        httponly=True, samesite="lax", secure=cfg.HTTPS_ONLY_COOKIES,
        domain=cfg.COOKIE_DOMAIN or None, path="/")


def anmelden(db, request, user, endpoint: str, p256dh: str, auth: str,
             ursprung: str) -> tuple:
    """(erfolg, Geraetekennung). Legt an oder frischt auf."""
    endpoint_ = sauber(endpoint)
    if not endpoint_ or not sauber(p256dh) or not sauber(auth):
        return False, ""

    kennung = geraete_id(request)
    beschreibung = geraet_beschreiben(request.headers.get("user-agent", ""))[:120]
    vorhanden = db.query(PushSubscription).filter(
        PushSubscription.endpoint == endpoint_).first()
    if vorhanden:
        # Derselbe Endpunkt kann nach einer Neuinstallation bei einer anderen
        # Person landen - dann wandert er mit.
        vorhanden.user_id = user.id
        vorhanden.p256dh = sauber(p256dh)[:200]
        vorhanden.auth = sauber(auth)[:100]
        vorhanden.geraet = beschreibung
        vorhanden.ursprung = ursprung
        vorhanden.geraete_id = kennung
    else:
        db.add(PushSubscription(
            user_id=user.id, endpoint=endpoint_,
            p256dh=sauber(p256dh)[:200], auth=sauber(auth)[:100],
            geraet=beschreibung, ursprung=ursprung, geraete_id=kennung))
    db.commit()
    return True, kennung


def abmelden(db, user, endpoint: str) -> None:
    db.query(PushSubscription).filter(
        PushSubscription.endpoint == sauber(endpoint),
        PushSubscription.user_id == user.id).delete(synchronize_session=False)
    db.commit()


def stand(db, request, user) -> dict:
    """Was dieses Geraet schon angemeldet hat - fuer die Anzeige."""
    kennung = sauber(request.cookies.get(GERAETE_COOKIE, ""))[:40]
    if not kennung:
        return {"website": False, "dashboard": False, "kennung": ""}
    zeilen = db.query(PushSubscription).filter(
        PushSubscription.user_id == user.id,
        PushSubscription.geraete_id == kennung).all()
    arten = {z.ursprung for z in zeilen}
    return {"website": "website" in arten, "dashboard": "dashboard" in arten,
            "kennung": kennung}
