"""Loeschfristen fuer Bewerbungen.

Abgelehnte nach 180 Tagen, angenommene nach 365. Offene Bewerbungen bleiben
stehen - die mahnt kern/hinweise.py an, bis jemand entscheidet.
"""

from kern import einstellungen as cfg
from kern.datenbank import sitzung
from kern.modelle import Application, ApplicationReview
from kern.text import utcnow


def _frist(status: str) -> int:
    """Aufbewahrungsdauer in Tagen. 0 heisst: nicht automatisch loeschen."""
    if status == "abgelehnt":
        return cfg.BEWERBUNG_ABGELEHNT_TAGE
    if status == "angenommen":
        return cfg.BEWERBUNG_ANGENOMMEN_TAGE
    return 0


def faellige_bewerbungen(db, heute=None) -> list:
    """Bewerbungen, deren Frist abgelaufen ist."""
    jetzt = heute or utcnow()
    faellig = []
    for bewerbung in db.query(Application).all():
        frist = _frist(bewerbung.status or "")
        if not frist or not bewerbung.created_at:
            continue
        if (jetzt - bewerbung.created_at).days >= frist:
            faellig.append(bewerbung)
    return faellig


def bewerbungen_aufraeumen(heute=None) -> dict:
    """Abgelaufene Bewerbungen endgueltig loeschen. Gibt die Anzahl je Zustand
    zurueck. Bewusst nicht ueber den Papierkorb - der hielte sie 30 Tage
    laenger."""
    bilanz = {}
    with sitzung() as db:
        for bewerbung in faellige_bewerbungen(db, heute):
            zustand = bewerbung.status or "unbekannt"
            db.query(ApplicationReview).filter(
                ApplicationReview.application_id == bewerbung.id).delete(
                    synchronize_session=False)
            db.delete(bewerbung)
            bilanz[zustand] = bilanz.get(zustand, 0) + 1
        db.commit()
    return bilanz


def bald_faellig(db, tage: int = 30, heute=None) -> list:
    """Was in den naechsten Tagen ablaeuft - fuer die Anzeige bei den
    Bewerbungen. Ohne das wirken die Fristen unsichtbar."""
    jetzt = heute or utcnow()
    bald = []
    for bewerbung in db.query(Application).all():
        frist = _frist(bewerbung.status or "")
        if not frist or not bewerbung.created_at:
            continue
        rest = frist - (jetzt - bewerbung.created_at).days
        if rest <= tage:
            bald.append({"bewerbung": bewerbung, "tage": max(0, rest)})
    bald.sort(key=lambda e: e["tage"])
    return bald
