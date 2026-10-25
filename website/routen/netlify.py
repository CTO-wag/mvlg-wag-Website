"""Öffentlicher, streng begrenzter Eingang für die Netlify-Landingpage."""

from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from kern import benachrichtigung, mail
from kern.datenbank import hole_db
from kern.modelle import Application
from kern.rechte import abteilung_label, bewerbbare_abteilungen
from kern.text import email_gueltig, email_normal, sauber, telefon_anzeige, telefon_gueltig, utcnow
from website.routen.bewerbung import FELDGRENZEN, STUFEN, schuladresse

router = APIRouter(prefix="/api", tags=["öffentlicher Eingang"])


class BewerbungEingang(BaseModel):
    vorname: str = ""
    nachname: str = ""
    klasse: str = ""
    email: str = ""
    telefonnummer: str = ""
    abteilung: str = ""
    motivation: str = ""
    interessen: str = ""
    vorwissen: str = ""
    website: str = ""  # Honigtopf: darf nicht ausgefüllt sein.


def _fehler(text: str) -> dict:
    return {"ok": False, "fehler": text}


@router.post("/bewerbungen", status_code=201)
def bewerbung_annehmen(eingang: BewerbungEingang,
                        db: Session = Depends(hole_db)) -> dict:
    """Speichert eine Bewerbung der statischen Landingpage."""
    daten = {
        "vorname": sauber(eingang.vorname)[:FELDGRENZEN["vorname"]],
        "nachname": sauber(eingang.nachname)[:FELDGRENZEN["nachname"]],
        "klasse": sauber(eingang.klasse)[:FELDGRENZEN["klasse"]],
        "email": email_normal(eingang.email)[:FELDGRENZEN["email"]],
        "telefonnummer": sauber(eingang.telefonnummer)[:FELDGRENZEN["telefonnummer"]],
        "abteilung": sauber(eingang.abteilung),
        "motivation": sauber(eingang.motivation)[:FELDGRENZEN["motivation"]],
        "interessen": sauber(eingang.interessen)[:FELDGRENZEN["interessen"]],
        "vorwissen": sauber(eingang.vorwissen)[:FELDGRENZEN["vorwissen"]],
    }
    if sauber(eingang.website):
        return {"ok": True, "status": "received"}
    pflicht = ("vorname", "nachname", "klasse", "email", "telefonnummer",
               "motivation", "interessen")
    if not all(daten[f] for f in pflicht):
        return _fehler("Bitte alle Pflichtfelder ausfüllen.")
    if not email_gueltig(daten["email"]):
        return _fehler("Diese E-Mail-Adresse sieht nicht richtig aus.")
    if schuladresse(daten["email"]):
        return _fehler("Bitte eine private E-Mail-Adresse angeben.")
    if daten["klasse"] not in STUFEN:
        return _fehler("Bitte wähle eine Klassenstufe von 9 bis 13 aus.")
    if not telefon_gueltig(daten["telefonnummer"]):
        return _fehler("Bitte gib eine gültige Telefonnummer mit Vorwahl an.")
    if len(daten["motivation"]) < 20:
        return _fehler("Schreib bitte ein paar Sätze zu deiner Motivation.")
    erlaubte = {a["key"] for a in bewerbbare_abteilungen()}
    if daten["abteilung"] not in erlaubte:
        return _fehler("Bitte wähle eine Wunsch-Abteilung aus.")
    vorhanden = db.query(Application).filter(
        Application.email == daten["email"],
        Application.created_at >= utcnow().replace(hour=0, minute=0, second=0,
                                                    microsecond=0)).first()
    if vorhanden:
        return {"ok": True, "status": "duplicate"}

    bewerbung = Application(
        vorname=daten["vorname"], nachname=daten["nachname"],
        klasse=daten["klasse"], email=daten["email"],
        telefonnummer=telefon_anzeige(daten["telefonnummer"]),
        motivation=daten["motivation"], interessen=daten["interessen"],
        vorwissen=daten["vorwissen"] or None, department=daten["abteilung"])
    db.add(bewerbung)
    db.commit()
    if mail.versand_moeglich():
        class Empfaenger:
            id = None
            role = "member"
            department = "exekutive"
            vorname = bewerbung.vorname
            nachname = bewerbung.nachname
            email = bewerbung.email
            name = f"{bewerbung.vorname} {bewerbung.nachname}"
        if mail.sende_vordruck(db, Empfaenger(), "application_received",
                               abteilung=abteilung_label(bewerbung.department)):
            bewerbung.email_sent = 1
            db.commit()
    benachrichtigung.melde_rechteinhabern(
        db, "bewerbungen", "applications", "Neue Bewerbung",
        f"{bewerbung.vorname} {bewerbung.nachname} ({bewerbung.klasse}) hat sich beworben.")
    return {"ok": True, "status": "received"}
