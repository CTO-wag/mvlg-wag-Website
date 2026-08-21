"""Das oeffentliche Bewerbungsformular."""

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from kern import benachrichtigung, mail
from kern.datenbank import hole_db
from kern.modelle import Application
from kern.rechte import bewerbbare_abteilungen, abteilung_label
from kern.sitzung import angemeldete_person, csrf_gueltig, csrf_token
from kern.text import (
    email_gueltig, email_normal, sauber, telefon_anzeige,
    telefon_gueltig, utcnow,
)
from kern.vorlagen import zeige

router = APIRouter()

FELDGRENZEN = {"vorname": 80, "nachname": 80, "klasse": 40, "email": 160,
               "telefonnummer": 40, "motivation": 3000, "interessen": 3000,
               "vorwissen": 3000}


# Welche Klassenstufen sich bewerben duerfen. An EINER Stelle, weil es sonst
# drei sind: das Auswahlfeld, die Pruefung und der Text auf der Startseite.
# Seit dem 19.08.2026 ist die 9 dabei.
STUFEN = ("9", "10", "11", "12", "13")

# Schuladressen kommen hier nicht durch. Zwei Gruende, und der zweite wiegt
# schwerer: Erstens erlischt das Postfach mit dem Abschluss, und die Anlage
# schreibt dann ins Leere. Zweitens laesst die Schule nicht jede Post an
# diese Adressen durch - eine Bewerbungsbestaetigung, die im Filter haengen
# bleibt, sieht fuer die bewerbende Person aus wie eine Absage.
#
# Unterdomains sind mitgemeint (schueler.mvlg-ko.de und dergleichen).
GESPERRTE_MAILDOMAENEN = ("mvlg-ko.de",)


def schuladresse(post: str) -> bool:
    """Gehoert diese Adresse zur Schule? Unterdomains zaehlen mit."""
    teil = (post or "").strip().lower().rsplit("@", 1)
    if len(teil) != 2:
        return False
    bereich = teil[1]
    return any(bereich == d or bereich.endswith("." + d)
               for d in GESPERRTE_MAILDOMAENEN)


def _seite(request: Request, db: Session, **rest):
    grund = dict(
        user=angemeldete_person(request, db), csrf=csrf_token(request),
        abteilungen_wahl=bewerbbare_abteilungen(), stufen_wahl=STUFEN,
        werte={}, fehler=None,
        erfolg=None, mail_versandt=False,
        seitentitel="Bewerbung: Wirtschafts- & Investment-AG am MvLG Koblenz",
        seitenbeschreibung="In fünf Minuten beworben: Schüler-AG für Börse, "
                           "Finanzen und Gründen am Max-von-Laue-Gymnasium "
                           "Koblenz. Klasse 9 bis 13, kein Vorwissen nötig.",
        # Eigenes Vorschaubild: Dieser Link wird herumgeschickt, um Leute zum
        # Mitmachen zu bewegen. Dann soll im Chat auch "Bewirb dich" stehen
        # und nicht dasselbe Bild wie bei der Startseite.
        vorschaubild="vorschaubild-bewerbung.png",
        vorschaubild_alt="Bewirb dich für die Wirtschafts- & Investment-AG "
                         "am MvLG Koblenz",
        pfad="/bewerbung")
    grund.update(rest)
    return zeige("oeffentlich/bewerbung.html", request=request, **grund)


@router.get("/bewerbung")
def formular(request: Request, db: Session = Depends(hole_db)):
    return _seite(request, db)


@router.post("/bewerbung")
def absenden(request: Request,
             vorname: str = Form(""), nachname: str = Form(""),
             klasse: str = Form(""), email: str = Form(""),
             telefonnummer: str = Form(""), abteilung: str = Form(""),
             motivation: str = Form(""), interessen: str = Form(""),
             vorwissen: str = Form(""), webseite: str = Form(""),
             csrf: str = Form(""), db: Session = Depends(hole_db)):
    eingabe = {
        "vorname": sauber(vorname)[:FELDGRENZEN["vorname"]],
        "nachname": sauber(nachname)[:FELDGRENZEN["nachname"]],
        "klasse": sauber(klasse)[:FELDGRENZEN["klasse"]],
        "email": email_normal(email)[:FELDGRENZEN["email"]],
        "telefonnummer": sauber(telefonnummer)[:FELDGRENZEN["telefonnummer"]],
        "abteilung": sauber(abteilung),
        "motivation": sauber(motivation)[:FELDGRENZEN["motivation"]],
        "interessen": sauber(interessen)[:FELDGRENZEN["interessen"]],
        "vorwissen": sauber(vorwissen)[:FELDGRENZEN["vorwissen"]],
    }

    if not csrf_gueltig(request, csrf):
        return _seite(request, db, werte=eingabe, fehler=(
            "Das Formular war zu lange offen. Bitte noch einmal abschicken – "
            "deine Eingaben stehen noch da."))

    if sauber(webseite):
        # Honigtopf ausgefuellt: kein Mensch. Freundlich tun, nichts speichern.
        return _seite(request, db, erfolg=eingabe["vorname"] or "dir")

    pflicht = ("vorname", "nachname", "klasse", "email", "telefonnummer",
               "motivation", "interessen")
    if not all(eingabe[f] for f in pflicht):
        return _seite(request, db, werte=eingabe,
                      fehler="Bitte alle Pflichtfelder ausfüllen.")
    if not email_gueltig(eingabe["email"]):
        return _seite(request, db, werte=eingabe,
                      fehler="Diese E-Mail-Adresse sieht nicht richtig aus.")
    if schuladresse(eingabe["email"]):
        return _seite(request, db, werte=eingabe, fehler=(
            "Bitte eine private E-Mail-Adresse angeben – die Schuladresse "
            "geht nicht. Sie fällt mit dem Abschluss weg, und unsere Post "
            "bleibt dort oft im Filter hängen."))
    # Das Auswahlfeld allein ist keine Pruefung - es steht im Browser des
    # Absenders und laesst sich dort aendern.
    if eingabe["klasse"] not in STUFEN:
        return _seite(request, db, werte=eingabe, fehler=(
            "Bitte wähle deine Stufe aus. Die AG ist für die Stufen "
            + " bis ".join((STUFEN[0], STUFEN[-1])) + " offen."))
    # Sehr viele schreiben ihre Nummer ohne Vorsatz: "1516 1234567". Das ist
    # keine Schlamperei, sondern wie man sie jemandem zuruft - also wird sie
    # hier in Ordnung gebracht statt abgelehnt. Nur wenn sie auch danach
    # unmoeglich ist, kommt eine Rueckfrage.
    if not telefon_gueltig(eingabe["telefonnummer"]):
        return _seite(request, db, werte=eingabe, fehler=(
            "Diese Telefonnummer scheint nicht zu stimmen – bitte mit "
            "Vorwahl, zum Beispiel 0163 1234567."))
    eingabe["telefonnummer"] = telefon_anzeige(eingabe["telefonnummer"])
    if len(eingabe["motivation"]) < 20:
        return _seite(request, db, werte=eingabe, fehler=(
            "Schreib bitte ein paar Sätze zu deiner Motivation – daran "
            "entscheidet sich einiges."))

    # Die Abteilung ist Pflicht: Ohne sie beginnt jedes Gespraech mit
    # derselben Rueckfrage, und die Bewerbung liegt so lange herum.
    # Vorher wurde eine unbekannte Angabe still verworfen - wer im Formular
    # nichts auswaehlte, merkte davon nichts.
    erlaubte = {a["key"] for a in bewerbbare_abteilungen()}
    if eingabe["abteilung"] not in erlaubte:
        return _seite(request, db, werte=eingabe, fehler=(
            "Bitte wähle eine Wunsch-Abteilung aus. Festgelegt bist du damit "
            "nicht – wir sprechen darüber."))

    # Doppelte Einsendung innerhalb eines Tages abfangen. Passiert oft ganz
    # harmlos - jemand drueckt zweimal, weil die Antwort dauert.
    von_heute = db.query(Application).filter(
        Application.email == eingabe["email"],
        Application.created_at >= utcnow().replace(hour=0, minute=0, second=0,
                                                   microsecond=0)).first()
    if von_heute:
        return _seite(request, db, erfolg=eingabe["vorname"])

    bewerbung = Application(
        vorname=eingabe["vorname"], nachname=eingabe["nachname"],
        klasse=eingabe["klasse"], email=eingabe["email"],
        telefonnummer=eingabe["telefonnummer"],
        motivation=eingabe["motivation"], interessen=eingabe["interessen"],
        vorwissen=eingabe["vorwissen"] or None,
        department=eingabe["abteilung"] or None)
    db.add(bewerbung)
    db.commit()

    # Bestaetigung an die bewerbende Person. Es gibt hier kein Konto, deshalb
    # ein kleines Stellvertreter-Objekt statt eines User-Datensatzes.
    versandt = False
    if mail.versand_moeglich():
        class _Empfaenger:
            id = None
            role = "member"
            department = "exekutive"
            vorname = bewerbung.vorname
            nachname = bewerbung.nachname
            email = bewerbung.email
            name = f"{bewerbung.vorname} {bewerbung.nachname}"

        versandt = mail.sende_vordruck(
            db, _Empfaenger(), "application_received",
            abteilung=abteilung_label(bewerbung.department) if bewerbung.department else "offen")
        if versandt:
            bewerbung.email_sent = 1
            db.commit()

    benachrichtigung.melde_rechteinhabern(
        db, "bewerbungen", "applications", "Neue Bewerbung",
        f"{bewerbung.vorname} {bewerbung.nachname} ({bewerbung.klasse}) "
        f"hat sich beworben.")

    return _seite(request, db, erfolg=bewerbung.vorname, mail_versandt=versandt)
