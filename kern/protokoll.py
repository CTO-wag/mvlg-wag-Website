"""Zwei Protokolle: was jemand getan hat, und was der Server verschickt hat.

Beide schreiben viel und werden selten gelesen. Deshalb raeumen sie sich
selbst auf - ein Protokoll, das jahrelang waechst, wird irgendwann zum
groessten Teil der Datenbank und liest sich trotzdem niemand.
"""

from datetime import timedelta

from kern.datenbank import sitzung
from kern.einstellungen import DELIVERY_LOG_TAGE
from kern.modelle import ActivityLog, Anmeldeversuch, DeliveryLog
from kern.text import utcnow

ANMELDEPROTOKOLL_TAGE = 90
AKTIVITAET_TAGE = 365


def notiere(db, user_id, art: str, wert: str = None) -> None:
    """Eine Handlung festhalten. Ohne commit - der Aufrufer speichert ohnehin.

    In V1 machte jeder Aufruf sein eigenes commit; bei einer Handlung, die
    mehrere Dinge aendert, waren das drei Schreibvorgaenge statt einem, und
    bei einem Fehler dazwischen blieb ein halber Zustand stehen.
    """
    db.add(ActivityLog(user_id=user_id, event_type=art[:40],
                       value=(wert or "")[:200] or None))


def zustellung(kanal: str, ziel: str, betreff: str, erfolg: bool,
               fehler: str = None, anlass: str = None) -> None:
    """Was rausging - mit eigener Sitzung, weil das aus Hintergrundfaeden kommt.

    Anlass: Push- und Mailversand laufen nebenher. Scheitern sie, stand das
    in V1 hoechstens in der Serverkonsole - also in einem Fenster, das
    niemand ansieht und das beim Neustart verschwindet.
    """
    try:
        with sitzung() as db:
            db.add(DeliveryLog(
                kanal=kanal[:16], ziel=(ziel or "")[:160],
                betreff=(betreff or "")[:200] or None,
                erfolg=1 if erfolg else 0,
                fehler=(fehler or "")[:300] or None,
                anlass=(anlass or "")[:40] or None))
            db.commit()
    except Exception as problem:                             # pragma: no cover
        print(f"[Protokoll] Zustellung nicht vermerkt: {problem}")


def aufraeumen() -> dict:
    """Alte Eintraege entfernen. Gibt zurueck, was weggeraeumt wurde."""
    jetzt = utcnow()
    bilanz = {}
    with sitzung() as db:
        bilanz["zustellungen"] = db.query(DeliveryLog).filter(
            DeliveryLog.created_at < jetzt - timedelta(days=DELIVERY_LOG_TAGE)
        ).delete(synchronize_session=False)
        bilanz["anmeldungen"] = db.query(Anmeldeversuch).filter(
            Anmeldeversuch.created_at < jetzt - timedelta(days=ANMELDEPROTOKOLL_TAGE)
        ).delete(synchronize_session=False)
        bilanz["aktivitaeten"] = db.query(ActivityLog).filter(
            ActivityLog.created_at < jetzt - timedelta(days=AKTIVITAET_TAGE)
        ).delete(synchronize_session=False)
        db.commit()
    return {k: v for k, v in bilanz.items() if v}
