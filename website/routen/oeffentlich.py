"""Startseite, Quiz, Rechtstexte, Kontaktformular."""

import json
import os

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import (
    FileResponse, PlainTextResponse, RedirectResponse, Response,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

from kern import benachrichtigung, inhalte, speicher
from kern import einstellungen as cfg
from kern.datenbank import hole_db
from kern.modelle import ContactMessage, Inhalt
from kern.sitzung import angemeldete_person, csrf_gueltig, csrf_token
from kern.text import email_gueltig, email_normal, kuerzen, sauber
from kern.vorlagen import zeige

router = APIRouter()
NETLIFY_DIST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "wag-koblenz", "dist")


def _galerienamen(wert: str) -> set[str]:
    try:
        bilder = json.loads(wert or "[]")
    except (TypeError, ValueError):
        return set()
    return {bild.get("name") for bild in bilder
            if isinstance(bild, dict) and bild.get("name")}


@router.get("/bilder/startseite/{speichername}")
def startseitenbild(speichername: str, db: Session = Depends(hole_db)):
    einzelbild = db.query(Inhalt.id).filter(
        Inhalt.bild_speichername == speichername, Inhalt.aktiv == 1).first()
    galerie = db.query(Inhalt.bilder).filter(Inhalt.aktiv == 1).all()
    in_galerie = any(
        speichername in _galerienamen(bilder)
        for bilder, in galerie
    )
    if not einzelbild and not in_galerie:
        return Response("Nicht gefunden", status_code=404, media_type="text/plain")
    return speicher.antwort(speicher.REDAKTION, speichername)

#  Quiz
#  Die Fragen stehen hier und nicht in der Datenbank: sie sind Teil der
#  Aussenwirkung, aendern sich fast nie, und ein Pflegebereich fuer zehn
#  Fragen waere mehr Aufwand als Nutzen.
QUIZ_FRAGEN = (
    {"frage": "Was bedeutet Inflation?",
     "optionen": ("Das allgemeine Preisniveau steigt, Geld verliert an Kaufkraft",
                  "Die Zinsen der Zentralbank steigen",
                  "Der Aktienmarkt bricht ein",
                  "Der Staat gibt neue Anleihen aus"),
     "richtig": 0},
    {"frage": "Wofür steht die Abkürzung BIP?",
     "optionen": ("Bank-Investitions-Programm", "Bruttoinlandsprodukt",
                  "Börsenindex Preisniveau", "Betriebliches Investitionspotenzial"),
     "richtig": 1},
    {"frage": "Was passiert typischerweise, wenn das Angebot steigt und die "
              "Nachfrage gleich bleibt?",
     "optionen": ("Der Preis steigt", "Der Preis bleibt gleich",
                  "Der Preis sinkt", "Die Nachfrage steigt automatisch mit"),
     "richtig": 2},
    {"frage": "Was ist ein ETF?",
     "optionen": ("Ein Kredit mit fester Laufzeit",
                  "Ein börsengehandelter Fonds, der meist einen Index abbildet",
                  "Eine Steuer auf Finanzgeschäfte",
                  "Ein Vertrag über einen künftigen Kauf"),
     "richtig": 1},
    {"frage": "Was bedeutet Diversifikation bei der Geldanlage?",
     "optionen": ("Möglichst viel in eine Aktie stecken",
                  "Das Risiko auf verschiedene Anlagen verteilen",
                  "Nur in das eigene Land investieren",
                  "Immer zum Höchstkurs verkaufen"),
     "richtig": 1},
    {"frage": "Was ist eine Aktie?",
     "optionen": ("Ein Darlehen an ein Unternehmen",
                  "Ein Anteil am Eigenkapital eines Unternehmens",
                  "Eine Versicherung gegen Kursverluste",
                  "Ein Sparvertrag mit fester Verzinsung"),
     "richtig": 1},
    {"frage": "Was beschreibt die Rendite?",
     "optionen": ("Den Kaufpreis einer Anlage",
                  "Den Ertrag einer Anlage im Verhältnis zum eingesetzten Kapital",
                  "Die Höhe der Steuern auf Gewinne",
                  "Die Anzahl der gehandelten Stücke"),
     "richtig": 1},
    {"frage": "Wozu dient ein Geschäftsmodell?",
     "optionen": ("Es beschreibt, wie ein Unternehmen Geld verdient",
                  "Es ist die Steuererklärung eines Unternehmens",
                  "Es legt die Anzahl der Mitarbeiter fest",
                  "Es bestimmt den Aktienkurs"),
     "richtig": 0},
    {"frage": "Was macht eine Zentralbank, wenn sie die Leitzinsen erhöht?",
     "optionen": ("Kredite werden günstiger",
                  "Sparen wird unattraktiver",
                  "Kredite werden teurer, das bremst die Wirtschaft",
                  "Die Inflation steigt sofort"),
     "richtig": 2},
    {"frage": "Was ist eine Zielgruppe?",
     "optionen": ("Alle Menschen in einem Land",
                  "Die Gruppe, für die ein Angebot gemacht wird",
                  "Die Mitarbeiter eines Unternehmens",
                  "Die Konkurrenz am Markt"),
     "richtig": 1},
)


def _kontext(request: Request, db: Session, **rest) -> dict:
    return dict(user=angemeldete_person(request, db),
                csrf=csrf_token(request), **rest)


@router.get("/")
def startseite():
    return FileResponse(os.path.join(NETLIFY_DIST, "index.html"))


@router.get("/kontakt", include_in_schema=False)
def kontakt_seite(request: Request):
    """Das Formular steht auf der Startseite - hierher gehoert nur der Weg.

    /kontakt ist eine Adresse, die man von Hand eintippt oder aus einem
    Aushang abschreibt. Ohne diese Zeile antwortete der Server darauf mit
    "405 Methode nicht erlaubt" - eine Fehlerseite fuer jemanden, der
    schlicht Kontakt aufnehmen wollte.
    """
    website, _ = cfg.adressen_fuer(request)
    return RedirectResponse(f"{website}/#kontakt", status_code=303)


@router.post("/kontakt")
def kontakt(request: Request,
            name: str = Form(""), email: str = Form(""),
            nachricht: str = Form(""), webseite: str = Form(""),
            csrf: str = Form(""), db: Session = Depends(hole_db)):
    """Kontaktformular. Antwortet mit derselben Seite samt Rueckmeldung."""
    fehler = None
    erfolg = False

    name_ = sauber(name)[:160]
    adresse = email_normal(email)
    text = sauber(nachricht)[:4000]

    if not csrf_gueltig(request, csrf):
        fehler = "Das Formular war zu lange offen. Bitte noch einmal abschicken."
    elif sauber(webseite):
        # Der Honigtopf war ausgefuellt - das war kein Mensch. Nach aussen so
        # tun, als sei alles gut: sonst lernt der Automat, was ihn verraet.
        erfolg = True
    elif not name_ or not text:
        fehler = "Bitte Name und Nachricht ausfüllen."
    elif not email_gueltig(adresse):
        fehler = "Diese E-Mail-Adresse sieht nicht richtig aus."
    elif len(text) < 10:
        fehler = "Ein paar Worte mehr bitte – so können wir nichts damit anfangen."
    else:
        eintrag = ContactMessage(name=name_, email=adresse, message=text)
        db.add(eintrag)
        db.commit()
        benachrichtigung.melde_rechteinhabern(
            db, "nachrichten", "messages",
            "Neue Nachricht über die Website",
            f"{name_}: {kuerzen(text, 140)}")
        erfolg = True

    return zeige("oeffentlich/start.html", request=request,
                 **_kontext(request, db,
                            angebot=inhalte.bloecke("angebot"),
                            portfolio=inhalte.bloecke("portfolio"),
                            vorteile=inhalte.bloecke("vorteile"),
                            stufen=inhalte.bloecke("stufen"),
                            quiz_anzahl=len(QUIZ_FRAGEN),
                            kontakt_erfolg=erfolg, kontakt_fehler=fehler,
                            pfad="/"))


@router.get("/quiz")
def quiz(request: Request, db: Session = Depends(hole_db)):
    return zeige("oeffentlich/quiz.html", request=request,
                 **_kontext(request, db, fragen=QUIZ_FRAGEN,
                            seitentitel="Wirtschafts-Quiz | Wirtschafts- & "
                                        "Investment-AG (MvLG Koblenz)",
                            seitenbeschreibung="Zehn Fragen zu Inflation, BIP, "
                                               "Angebot und Nachfrage – ohne "
                                               "Anmeldung, mit sofortiger "
                                               "Auswertung.",
                            pfad="/quiz"))


@router.get("/impressum")
def impressum(request: Request, db: Session = Depends(hole_db)):
    return zeige("oeffentlich/impressum.html", request=request,
                 **_kontext(request, db,
                            seitentitel="Impressum | Wirtschafts- & Investment-AG (MvLG)",
                            seitenbeschreibung="Impressum der Wirtschafts- & "
                                               "Investment-AG am Max-von-Laue-"
                                               "Gymnasium Koblenz.",
                            pfad="/impressum"))


@router.get("/datenschutz")
def datenschutz(request: Request, db: Session = Depends(hole_db)):
    return zeige("oeffentlich/datenschutz.html", request=request,
                 **_kontext(request, db, stand="August 2026",
                            seitentitel="Datenschutz | Wirtschafts- & Investment-AG (MvLG)",
                            seitenbeschreibung="Datenschutzerklärung der "
                                               "Wirtschafts- & Investment-AG.",
                            pfad="/datenschutz"))


#  Suchmaschinen
# Welche Seiten in die Sitemap gehoeren. Die Vorlage steht dabei, weil sich
# das Aenderungsdatum daran ablesen laesst: eine Seite, deren Text seit einem
# halben Jahr gleich ist, soll auch "seit einem halben Jahr unveraendert"
# melden. Frueher stand hier stur das heutige Datum - eine Suchmaschine, der
# man jeden Tag "alles neu" meldet, glaubt einem das Datum irgendwann nicht
# mehr.
OEFFENTLICHE_SEITEN = (
    ("/", "1.0", "weekly", "oeffentlich/start.html"),
    ("/bewerbung", "0.9", "monthly", "oeffentlich/bewerbung.html"),
    ("/quiz", "0.6", "monthly", "oeffentlich/quiz.html"),
    ("/impressum", "0.3", "yearly", "oeffentlich/impressum.html"),
    ("/datenschutz", "0.3", "yearly", "oeffentlich/datenschutz.html"),
)

# Was nicht in den Index gehoert. Teils, weil es nichts zu finden gibt (die
# Anmeldung), teils, weil die Adresse ein Geheimnis enthaelt (Kalender-Abo,
# Passwort-Link) - eine indizierte Adresse ist eine oeffentliche Adresse.
GESPERRT = (
    "/dashboard",             # eigener Server, hier nur zur Sicherheit
    "/login",
    "/logout",
    "/passwort-vergessen",
    "/passwort-neu",
    "/benachrichtigungen",    # gibt es nicht mehr, alte Verweise sollen
    "/push-schluessel",       # trotzdem nicht in einer Sitemap landen
    "/kalender/",             # persoenliches Abo mit Token in der Adresse
    "/api/",
)


def _geaendert_am(vorlage: str) -> "date":
    """Datum der letzten Aenderung einer Vorlage - oder heute."""
    import os
    from datetime import date
    pfad = os.path.join(cfg.VORLAGEN_DIR, vorlage)
    try:
        return date.fromtimestamp(os.path.getmtime(pfad))
    except OSError:                                          # pragma: no cover
        return date.today()


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(db: Session = Depends(hole_db)):
    from datetime import date
    from kern.modelle import Inhalt

    # Die Startseite aendert sich nicht nur mit der Vorlage, sondern auch,
    # wenn jemand im Dashboard einen Portfolio-Eintrag pflegt. Beides zaehlt -
    # sonst meldet die Seite "seit Monaten unveraendert", obwohl gestern ein
    # neuer Erfolg dazugekommen ist.
    neuester = db.query(func.max(Inhalt.updated_at)).filter(
        Inhalt.aktiv == 1).scalar()
    inhalt_datum = neuester.date() if neuester else None
    heute = date.today()

    zeilen = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for pfad, gewicht, takt, vorlage in OEFFENTLICHE_SEITEN:
        stand = _geaendert_am(vorlage)
        if pfad == "/" and inhalt_datum:
            stand = max(stand, inhalt_datum)
        zeilen.append(
            f"  <url><loc>{cfg.SITE_URL}{pfad}</loc>"
            f"<lastmod>{min(stand, heute).isoformat()}</lastmod>"
            f"<changefreq>{takt}</changefreq>"
            f"<priority>{gewicht}</priority></url>")
    zeilen.append("</urlset>")
    return Response("\n".join(zeilen), media_type="application/xml",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/.well-known/security.txt", include_in_schema=False)
def security_txt():
    """Wohin man sich wendet, wenn man eine Sicherheitsluecke findet.

    Ein Standard (RFC 9116). Ohne diese Datei schreibt jemand, der etwas
    entdeckt, entweder gar nicht - oder oeffentlich in eine WhatsApp-Gruppe.
    """
    from datetime import date, timedelta
    laeuft_ab = date.today().replace(month=12, day=31) + timedelta(days=365)
    kontakt = cfg.MAIL_REPLY_TO or cfg.SMTP_FROM or "kontakt@mvlg-wag.de"
    return PlainTextResponse(
        f"Contact: mailto:{kontakt}\n"
        f"Expires: {laeuft_ab.isoformat()}T23:59:00.000Z\n"
        "Preferred-Languages: de, en\n"
        f"Canonical: {cfg.SITE_URL}/.well-known/security.txt\n"
        "\n"
        "# Diese Seite ist eine Schüler-AG, kein Unternehmen. Wer einen\n"
        "# Fehler findet: bitte melden, bevor er öffentlich wird. Danke.\n",
        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/robots.txt", include_in_schema=False)
def robots():
    zeilen = ["User-agent: *", "Allow: /"]
    zeilen += [f"Disallow: {p}" for p in GESPERRT]
    zeilen += [
        "",
        # Die grossen Bilder- und Textsammler laden gern jede Seite mehrfach
        # hintereinander. Auf einem Schulrechner hinter einem Tunnel merkt man
        # das. Eine Sekunde Abstand reicht ihnen.
        "User-agent: AhrefsBot",
        "Crawl-delay: 10",
        "",
        "User-agent: SemrushBot",
        "Crawl-delay: 10",
        "",
        f"Sitemap: {cfg.SITE_URL}/sitemap.xml",
        "",
    ]
    return PlainTextResponse("\n".join(zeilen),
                             headers={"Cache-Control": "public, max-age=86400"})
