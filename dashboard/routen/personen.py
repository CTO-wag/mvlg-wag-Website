"""Konten, Mitgliederliste, Bewerbungen, Anwesenheit, Leadership."""

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy import func

from dashboard.hilfen import (
    Anmeldung, als_csv, datum, fehler, gut, papierkorb_hinweis, teil,
    warnung, zahl,
)
from kern import leistung, mail, papierkorb, protokoll, whatsapp
from kern.modelle import (
    Application, ApplicationReview, Attendance, LeadershipScore,
    Meeting, SuccessionCandidate, User, UserPermission,
)
from kern.rechte import (
    PERM_HILFE, PERM_KEYS, PERM_LABELS, abteilung_label, abteilungs_keys,
    darf_bewerbungen, darf_person_bearbeiten, hat_recht, perm_gruppen,
    rang_von, rollen,
)
from kern.sicherheit import (
    PASSWORT_REGEL, passwort_bewerten, passwort_hashen, passwort_vorschlag,
)
from kern.text import (
    email_gueltig, email_normal, sauber, telefon_anzeige,
    telefon_gueltig, utcnow,
)

router = APIRouter(prefix="/dashboard")


#  Konten
def _konten_ansicht(a: Anmeldung, meldung=None, startpasswort=None,
                    passwort_fuer=None):
    db = a.db
    konten = db.query(User).order_by(User.status, User.vorname, User.nachname).all()
    ausnahmen = {}
    for zeile in db.query(UserPermission).all():
        ausnahmen.setdefault(zeile.user_id, {})[zeile.perm] = bool(zeile.wert)
    return teil("dashboard/konten.html", a,
                konten=konten,
                rollen_liste=rollen(),
                abteilungen_wahl=abteilungs_keys(),
                ausnahmen=ausnahmen,
                perm_gruppen=perm_gruppen(),
                perm_labels=PERM_LABELS,
                perm_hilfe=PERM_HILFE,
                bearbeitbar={k.id: darf_person_bearbeiten(a.user, k) for k in konten},
                mein_rang=rang_von(a.user),
                passwort_regel=PASSWORT_REGEL,
                startpasswort=startpasswort, passwort_fuer=passwort_fuer,
                darf_rechte=a.darf("rechte_personen"),
                darf_profil=a.darf("accounts_full_edit"),
                mail_moeglich=mail.versand_moeglich(),
                whatsapp_bereit=whatsapp.automatik_an(db),
                meldung=meldung)


@router.get("/konten")
def konten(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("accounts_all")
    return _konten_ansicht(a)


@router.post("/konten")
def konto_anlegen(vorname: str = Form(""), nachname: str = Form(""),
                  email: str = Form(""), telefon: str = Form(""),
                  rolle: str = Form("member"), abteilung: str = Form(""),
                  passwort: str = Form(""), mail_senden: str = Form(""),
                  whatsapp_senden: str = Form(""), csrf: str = Form(""),
                  a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("accounts_all")
    a.pruefe_csrf(csrf)
    db, user = a.db, a.user

    vor, nach = sauber(vorname)[:80], sauber(nachname)[:80]
    adresse = email_normal(email)
    if not vor or not nach:
        return _konten_ansicht(a, fehler("Vor- und Nachname werden gebraucht."))
    if not email_gueltig(adresse):
        return _konten_ansicht(a, fehler("Diese E-Mail-Adresse sieht nicht richtig aus."))
    if db.query(User).filter(User.email == adresse).first():
        return _konten_ansicht(a, fehler("Diese Adresse hat schon ein Konto."))
    if rolle not in rollen():
        return _konten_ansicht(a, fehler("Diese Rolle gibt es nicht."))
    # Niemand darf ein Konto anlegen, das mehr darf als man selbst - sonst
    # waere die Rangregel mit einem Umweg ausgehebelt.
    if rollen()[rolle].get("rang", 0) > rang_von(user):
        return _konten_ansicht(a, fehler(
            "Du kannst keine Rolle vergeben, die über deiner eigenen steht."))
    if abteilung not in abteilungs_keys():
        abteilung = "exekutive"

    start = sauber(passwort) or passwort_vorschlag()
    gut_, meldung_ = passwort_bewerten(start, (vor, nach))
    if not gut_:
        return _konten_ansicht(a, fehler(meldung_))

    if telefon and not telefon_gueltig(telefon):
        return _konten_ansicht(a, fehler(
            "Die Telefonnummer scheint nicht zu stimmen – bitte mit Vorwahl, "
            "zum Beispiel 0163 1234567."))
    neu = User(vorname=vor, nachname=nach, email=adresse,
               # Einheitlich als "+49 163 1234567" ablegen: WhatsApp braucht
               # die Landesvorwahl, und "1636177263" waere sonst eine
               # Auslandsnummer ins Nichts.
               telefonnummer=telefon_anzeige(telefon) or None,
               password_hash=passwort_hashen(start), role=rolle,
               department=abteilung, status="aktiv",
               eintrittsdatum=date.today(),
               # Bewusst leer: das Passwort hat jemand anderes gesetzt. Erst
               # wenn die Person es selbst aendert, steht hier ein Datum -
               # daran erkennt die Uebersicht, wem sie den Hinweis "du
               # benutzt noch das Startpasswort" zeigen muss.
               passwort_geaendert_am=None)
    db.add(neu)
    db.flush()
    protokoll.notiere(db, user.id, "konto_neu", f"{vor} {nach} ({rolle})")

    versandt = False
    if mail_senden and mail.versand_moeglich():
        versandt = mail.sende_vordruck(db, neu, "account_created", passwort=start)

    wa_eintrag = None
    if whatsapp_senden:
        wa_eintrag = whatsapp.willkommen_ausloesen(db, neu, erzwingen=True)
    db.commit()

    if wa_eintrag and whatsapp.modus() != "manuell":
        whatsapp.korb_anstossen()

    hinweise = []
    if versandt:
        hinweise.append("Zugangsdaten sind per E-Mail unterwegs.")
    elif mail_senden:
        hinweise.append("E-Mail konnte nicht verschickt werden.")
    if wa_eintrag:
        hinweise.append("Die Willkommensnachricht liegt im WhatsApp-Bereich bereit."
                        if whatsapp.modus() == "manuell"
                        else "Die WhatsApp-Begrüßung wird verschickt.")
    return _konten_ansicht(
        a, gut(f"Konto für {vor} {nach} angelegt. " + " ".join(hinweise)),
        startpasswort=start, passwort_fuer=f"{vor} {nach}")


@router.post("/konten/{konto_id}/aendern")
def konto_aendern(konto_id: int, vorname: str = Form(""),
                  nachname: str = Form(""), email: str = Form(""),
                  telefon: str = Form(""), rolle: str = Form(""),
                  abteilung: str = Form(""), status: str = Form(""),
                  csrf: str = Form(""),
                  a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("accounts_all")
    a.pruefe_csrf(csrf)
    db, user = a.db, a.user
    ziel = db.get(User, konto_id)
    if not ziel:
        return _konten_ansicht(a, fehler("Dieses Konto gibt es nicht mehr."))
    if not darf_person_bearbeiten(user, ziel):
        return _konten_ansicht(a, fehler(
            "Dieses Konto steht über deinem Rang – das kannst du nicht ändern."))

    if a.darf("accounts_full_edit"):
        if sauber(vorname):
            ziel.vorname = sauber(vorname)[:80]
        if sauber(nachname):
            ziel.nachname = sauber(nachname)[:80]
        adresse = email_normal(email)
        if adresse and adresse != ziel.email:
            if not email_gueltig(adresse):
                return _konten_ansicht(a, fehler("Die neue Adresse sieht nicht richtig aus."))
            if db.query(User).filter(User.email == adresse, User.id != ziel.id).first():
                return _konten_ansicht(a, fehler("Diese Adresse hat schon ein Konto."))
            ziel.email = adresse
        if telefon and not telefon_gueltig(telefon):
            return _konten_ansicht(a, fehler(
                "Die Telefonnummer scheint nicht zu stimmen – bitte mit "
                "Vorwahl, zum Beispiel 0163 1234567."))
        ziel.telefonnummer = telefon_anzeige(telefon) or None

    if rolle and rolle in rollen():
        if rollen()[rolle].get("rang", 0) > rang_von(user):
            return _konten_ansicht(a, fehler(
                "Du kannst keine Rolle vergeben, die über deiner eigenen steht."))
        # Das letzte handlungsfaehige Konto darf sich nicht selbst entmachten.
        if ziel.role == "cto" and rolle != "cto":
            andere = db.query(User).filter(User.role == "cto", User.status == "aktiv",
                                           User.id != ziel.id).count()
            if not andere:
                return _konten_ansicht(a, fehler(
                    "Das ist das letzte aktive CTO-Konto. Erst ein zweites "
                    "einrichten, sonst kommt niemand mehr an die Verwaltung."))
        ziel.role = rolle
    if abteilung and abteilung in abteilungs_keys():
        ziel.department = abteilung
    if status in ("aktiv", "inaktiv"):
        if status == "inaktiv" and ziel.role == "cto":
            andere = db.query(User).filter(User.role == "cto", User.status == "aktiv",
                                           User.id != ziel.id).count()
            if not andere:
                return _konten_ansicht(a, fehler(
                    "Das letzte aktive CTO-Konto lässt sich nicht abschalten."))
        ziel.status = status

    protokoll.notiere(db, user.id, "konto_geaendert", f"#{ziel.id} {ziel.name}")
    db.commit()
    return _konten_ansicht(a, gut(f"{ziel.name} gespeichert."))


@router.post("/konten/{konto_id}/passwort")
def konto_passwort(konto_id: int, csrf: str = Form(""),
                   a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Setzt ein neues Startpasswort und zeigt es genau einmal an."""
    a.verlange("accounts_all")
    a.pruefe_csrf(csrf)
    ziel = a.db.get(User, konto_id)
    if not ziel or not darf_person_bearbeiten(a.user, ziel):
        return _konten_ansicht(a, fehler("Dieses Konto steht über deinem Rang – Rechte kannst du dort "
               "nicht ändern."))
    neu = passwort_vorschlag()
    ziel.password_hash = passwort_hashen(neu)
    # Nicht "geaendert": geaendert hat es die Verwaltung, nicht die Person.
    ziel.passwort_geaendert_am = None
    ziel.failed_logins = 0
    ziel.locked_until = None
    # Alle Sitzungen beenden: Ein neu gesetztes Passwort soll auch jemanden
    # aussperren, der gerade noch angemeldet war.
    from kern.modelle import UserSession
    a.db.query(UserSession).filter(UserSession.user_id == ziel.id,
                                   UserSession.revoked == 0).update(
                                       {"revoked": 1}, synchronize_session=False)
    protokoll.notiere(a.db, a.user.id, "passwort_gesetzt", f"#{ziel.id}")
    a.db.commit()
    return _konten_ansicht(a, gut(f"Neues Passwort für {ziel.name} gesetzt."),
                           startpasswort=neu, passwort_fuer=ziel.name)


def _rechte_tafel(a: Anmeldung, ziel: User, meldung=None):
    """Nur die Rechtetafel einer Person - der Rest der Seite bleibt stehen."""
    ausnahmen = {z.perm: bool(z.wert) for z in a.db.query(UserPermission).filter(
        UserPermission.user_id == ziel.id).all()}
    return teil("dashboard/teile/konto_rechte.html", a, konto=ziel,
                ausnahmen=ausnahmen, perm_gruppen=perm_gruppen(),
                meldung=meldung)


@router.get("/konten/{konto_id}/rechte")
def konto_rechte(konto_id: int, a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Wird beim Aufklappen nachgeladen - siehe konten.html."""
    a.verlange("rechte_personen")
    ziel = a.db.get(User, konto_id)
    if not ziel:
        raise HTTPException(404, "Dieses Konto gibt es nicht mehr.")
    return _rechte_tafel(a, ziel)


@router.post("/konten/{konto_id}/2fa-zuruecksetzen")
def konto_2fa_zuruecksetzen(konto_id: int, csrf: str = Form(""),
                            a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Den zweiten Faktor einer Person abschalten.

    Der letzte Rueckweg: Handy weg UND Ersatzcodes weg. Ohne diesen Knopf
    bliebe nur, in der Datenbank von Hand zu pfuschen - und bis dahin kaeme
    die Person gar nicht mehr an ihr Konto.

    Bewusst kein stiller Vorgang: Die Person bekommt eine E-Mail, und es
    steht im Protokoll. Wer fremde Konten oeffnen kann, soll dabei Spuren
    hinterlassen.
    """
    a.verlange("accounts_all")
    a.pruefe_csrf(csrf)
    ziel = a.db.get(User, konto_id)
    if not ziel or not darf_person_bearbeiten(a.user, ziel):
        return _konten_ansicht(a, fehler(
            "Dieses Konto steht über deinem Rang."))
    if not ziel.totp_aktiv and not ziel.totp_secret:
        return _konten_ansicht(a, info(
            f"{ziel.name} hat gar keinen zweiten Faktor eingeschaltet."))
    ziel.totp_aktiv = 0
    ziel.totp_secret = None
    ziel.totp_ersatzcodes = None
    protokoll.notiere(a.db, a.user.id, "2fa_zurueckgesetzt", f"#{ziel.id}")
    a.db.commit()
    try:
        mail.sende_vordruck(
            a.db, ziel, "notification",
            titel="Zweiter Faktor zurückgesetzt",
            text=(f"{a.user.name} hat den zweiten Faktor für dein Konto "
                  "abgeschaltet. Du kommst jetzt wieder mit E-Mail und "
                  "Passwort hinein. Richte ihn im Dashboard unter „Mein "
                  "Konto“ neu ein. Warst du das nicht und hast auch nicht "
                  "darum gebeten: sofort melden."))
    except Exception:                                        # pragma: no cover
        pass
    return _konten_ansicht(a, gut(
        f"Zweiter Faktor für {ziel.name} zurückgesetzt. {ziel.name} kann sich "
        "jetzt wieder mit Passwort anmelden und ihn neu einrichten."))


@router.post("/konten/{konto_id}/recht")
def konto_recht(konto_id: int, perm: str = Form(""), wert: str = Form(""),
                csrf: str = Form(""),
                a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Ein Recht fuer genau eine Person setzen, entziehen oder freigeben.

    wert: "an" gibt frei, "aus" entzieht ausdruecklich, "" nimmt die Ausnahme
    zurueck - dann gilt wieder, was Rolle und Abteilung sagen.

    Geantwortet wird nur mit der Tafel dieser einen Person. Frueher kam die
    ganze Kontenliste zurueck - danach war jedes aufgeklappte Konto wieder zu
    und man musste sich zum naechsten Recht neu durchklicken.
    """
    a.verlange("rechte_personen")
    a.pruefe_csrf(csrf)
    db, user = a.db, a.user
    ziel = db.get(User, konto_id)
    if not ziel or not darf_person_bearbeiten(user, ziel):
        return _konten_ansicht(a, fehler("Dieses Konto steht über deinem Rang – Rechte kannst du dort "
               "nicht ändern."))
    if perm not in PERM_KEYS:
        return _rechte_tafel(a, ziel, fehler("Dieses Recht gibt es nicht."))
    # Man kann nur weitergeben, was man selbst hat - sonst waere die
    # Rechteverwaltung ein Selbstbedienungsladen.
    if not hat_recht(user, perm, db) and wert == "an":
        return _rechte_tafel(a, ziel, fehler(
            f"„{PERM_LABELS[perm]}“ hast du selbst nicht – du kannst es "
            "auch nicht vergeben."))

    vorhanden = db.query(UserPermission).filter(
        UserPermission.user_id == ziel.id, UserPermission.perm == perm).first()
    if wert == "":
        if vorhanden:
            db.delete(vorhanden)
        text = (f"„{PERM_LABELS[perm]}“ richtet sich bei {ziel.vorname} wieder "
                "nach Rolle und Abteilung.")
    else:
        an = wert == "an"
        if vorhanden:
            vorhanden.wert = 1 if an else 0
            vorhanden.gesetzt_von = user.id
        else:
            db.add(UserPermission(user_id=ziel.id, perm=perm, wert=1 if an else 0,
                                  gesetzt_von=user.id))
        text = (f"„{PERM_LABELS[perm]}“ für {ziel.vorname} "
                + ("freigegeben." if an else "ausdrücklich entzogen."))
    protokoll.notiere(db, user.id, "recht_gesetzt", f"#{ziel.id} {perm}={wert or 'auto'}")
    db.commit()
    from kern.rechte import cache_verwerfen
    cache_verwerfen()
    return _rechte_tafel(a, ziel, gut(text))


@router.post("/konten/{konto_id}/loeschen")
def konto_loeschen(konto_id: int, csrf: str = Form(""),
                   a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("accounts_all")
    a.pruefe_csrf(csrf)
    db, user = a.db, a.user
    ziel = db.get(User, konto_id)
    if not ziel:
        return _konten_ansicht(a, fehler("Dieses Konto gibt es nicht mehr."))
    if ziel.id == user.id:
        return _konten_ansicht(a, fehler(
            "Das eigene Konto löschst du unter „Mein Konto“ – dort steht auch, "
            "was dabei passiert."))
    if not darf_person_bearbeiten(user, ziel):
        return _konten_ansicht(a, fehler("Dieses Konto steht über deinem Rang."))
    if ziel.role == "cto":
        andere = db.query(User).filter(User.role == "cto", User.status == "aktiv",
                                       User.id != ziel.id).count()
        if not andere:
            return _konten_ansicht(a, fehler("Das letzte CTO-Konto bleibt bestehen."))

    name = ziel.name
    papierkorb.konto_daten_loesen(db, ziel)
    papierkorb.hinein(db, "user", ziel, user.id, name)
    protokoll.notiere(db, user.id, "konto_geloescht", name)
    db.commit()
    return _konten_ansicht(a, papierkorb_hinweis(f"{name} wurde gelöscht – 30 Tage lang "
                                        "wiederherstellbar."))


@router.get("/konten/export.csv")
def konten_export(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("accounts_all")
    # Auch im Export einheitlich: die Datei landet oft direkt im
    # Adressbuch, und dort ist eine Nummer ohne Vorwahl wertlos.
    zeilen = [(k.id, k.vorname, k.nachname, k.email,
               telefon_anzeige(k.telefonnummer),
               k.role, abteilung_label(k.department), k.status,
               k.eintrittsdatum.isoformat() if k.eintrittsdatum else "")
              for k in a.db.query(User).order_by(User.vorname).all()]
    return als_csv(zeilen, ["ID", "Vorname", "Nachname", "E-Mail", "Telefon",
                            "Rolle", "Abteilung", "Status", "Eintritt"],
                   "konten.csv")


#  Mitgliederliste
@router.get("/mitglieder")
def mitglieder(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("mitglieder_view")
    db = a.db
    personen = db.query(User).filter(User.status == "aktiv").order_by(
        User.vorname, User.nachname).all()
    nach_abteilung = {}
    for person in personen:
        nach_abteilung.setdefault(person.department, []).append(person)
    werte = {s.user_id: s for s in db.query(LeadershipScore).all()}
    return teil("dashboard/mitglieder.html", a, nach_abteilung=nach_abteilung,
                gesamt=len(personen), werte=werte,
                zeigt_werte=a.darf("leadership"))


#  Bewerbungen
def _bewerbungen_ansicht(a: Anmeldung, meldung=None, filter_status: str = "",
                         startpasswort=None, passwort_fuer=None):
    db, user = a.db, a.user
    abfrage = db.query(Application)
    if filter_status in ("neu", "in_pruefung", "angenommen", "abgelehnt"):
        abfrage = abfrage.filter(Application.status == filter_status)
    bewerbungen = abfrage.order_by(Application.created_at.desc()).all()

    zaehler = dict(db.query(Application.status, func.count(Application.id))
                   .group_by(Application.status).all())

    urteile, meine_urteile = {}, {}
    for urteil, person in (db.query(ApplicationReview, User)
                           .join(User, User.id == ApplicationReview.user_id).all()):
        urteile.setdefault(urteil.application_id, []).append((urteil, person))
        if urteil.user_id == user.id:
            meine_urteile[urteil.application_id] = urteil

    return teil("dashboard/bewerbungen.html", a, bewerbungen=bewerbungen,
                zaehler=zaehler, gesamt=sum(zaehler.values()),
                urteile=urteile, meine_urteile=meine_urteile,
                filter_status=filter_status,
                darf_entscheiden=a.darf("bewerbungen"),
                mail_moeglich=mail.versand_moeglich(),
                startpasswort=startpasswort, passwort_fuer=passwort_fuer,
                meldung=meldung)


@router.get("/bewerbungen")
def bewerbungen(status: str = "", a: Anmeldung = Depends(Anmeldung.pflicht)):
    if not darf_bewerbungen(a.user, a.db):
        a.verlange("bewerbungen")
    return _bewerbungen_ansicht(a, filter_status=status)


@router.post("/bewerbungen/{app_id}/urteil")
def bewerbung_urteil(app_id: int, bewertung: str = Form("3"),
                     notiz: str = Form(""), csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Einschaetzung einer Person zu einer Bewerbung.

    Bisher wurde per Chat abgestimmt - Wortmeldungen gingen unter, und wer
    spaeter dazukam, konnte nicht nachlesen, warum entschieden wurde.
    """
    if not darf_bewerbungen(a.user, a.db):
        a.verlange("bewerbungen")
    a.pruefe_csrf(csrf)
    db, user = a.db, a.user
    if not db.get(Application, app_id):
        return _bewerbungen_ansicht(a, fehler("Diese Bewerbung gibt es nicht mehr."))
    wert = max(1, min(5, zahl(bewertung, 3) or 3))
    vorhanden = db.query(ApplicationReview).filter(
        ApplicationReview.application_id == app_id,
        ApplicationReview.user_id == user.id).first()
    if vorhanden:
        vorhanden.bewertung = wert
        vorhanden.notiz = sauber(notiz)[:2000] or None
        vorhanden.updated_at = utcnow()
    else:
        db.add(ApplicationReview(application_id=app_id, user_id=user.id,
                                 bewertung=wert, notiz=sauber(notiz)[:2000] or None))
    db.commit()
    return _bewerbungen_ansicht(a, gut("Deine Einschätzung ist gespeichert."))


@router.post("/bewerbungen/{app_id}/status")
def bewerbung_status(app_id: int, status: str = Form(""),
                     konto_anlegen: str = Form(""), csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("bewerbungen")
    a.pruefe_csrf(csrf)
    db, user = a.db, a.user
    bewerbung = db.get(Application, app_id)
    if not bewerbung:
        return _bewerbungen_ansicht(a, fehler("Diese Bewerbung gibt es nicht mehr."))
    if status not in ("neu", "in_pruefung", "angenommen", "abgelehnt"):
        return _bewerbungen_ansicht(a, fehler("Diesen Stand gibt es nicht – bitte einen aus der Liste wählen."))

    vorher = bewerbung.status
    bewerbung.status = status
    protokoll.notiere(db, user.id, "bewerbung_status",
                      f"#{bewerbung.id} {vorher} → {status}")

    # Rueckmeldung an die bewerbende Person - es gibt kein Konto, deshalb ein
    # kleines Stellvertreter-Objekt.
    class _Empfaenger:
        id = None
        role = "member"
        department = "exekutive"
        vorname = bewerbung.vorname
        nachname = bewerbung.nachname
        email = bewerbung.email
        name = f"{bewerbung.vorname} {bewerbung.nachname}"

    text = {"angenommen": "Du bist dabei! Willkommen in der AG.",
            "abgelehnt": "Leider hat es diesmal nicht geklappt.",
            "in_pruefung": "Deine Bewerbung wird gerade angesehen.",
            "neu": "Deine Bewerbung liegt bei uns."}[status]
    if status in ("angenommen", "abgelehnt") and mail.versand_moeglich():
        mail.sende_vordruck(db, _Empfaenger(), "application_status", status=text)

    startpasswort = None
    if status == "angenommen" and konto_anlegen:
        adresse = email_normal(bewerbung.email)
        if db.query(User).filter(User.email == adresse).first():
            db.commit()
            return _bewerbungen_ansicht(a, warnung(
                "Stand geändert. Ein Konto mit dieser Adresse gibt es allerdings schon."))
        startpasswort = passwort_vorschlag()
        neu = User(vorname=bewerbung.vorname, nachname=bewerbung.nachname,
                   email=adresse,
                   telefonnummer=telefon_anzeige(bewerbung.telefonnummer)
                   or bewerbung.telefonnummer,
                   password_hash=passwort_hashen(startpasswort), role="member",
                   department=bewerbung.department or "exekutive", status="aktiv",
                   eintrittsdatum=date.today(), passwort_geaendert_am=None)
        db.add(neu)
        db.flush()
        if mail.versand_moeglich():
            mail.sende_vordruck(db, neu, "account_created", passwort=startpasswort)
        # Und der Bot begruesst die Person - das ist genau der Moment dafuer.
        whatsapp.willkommen_ausloesen(db, neu)
        db.commit()
        if whatsapp.modus() != "manuell":
            whatsapp.korb_anstossen()
        return _bewerbungen_ansicht(
            a, gut(f"{neu.name} ist aufgenommen und hat ein Konto."),
            startpasswort=startpasswort, passwort_fuer=neu.name)

    db.commit()
    return _bewerbungen_ansicht(a, gut(f"Stand auf „{status}“ geändert."))


@router.post("/bewerbungen/{app_id}/loeschen")
def bewerbung_loeschen(app_id: int, csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("bewerbungen")
    a.pruefe_csrf(csrf)
    bewerbung = a.db.get(Application, app_id)
    if bewerbung:
        papierkorb.hinein(a.db, "application", bewerbung, a.user.id,
                          f"{bewerbung.vorname} {bewerbung.nachname}")
        a.db.commit()
    return _bewerbungen_ansicht(a,
        papierkorb_hinweis("Die Bewerbung liegt im Papierkorb – 30 Tage lang "
                                "wiederherstellbar."))


#  Anwesenheit
def _anwesenheit_ansicht(a: Anmeldung, meldung=None):
    db = a.db
    eintraege = (db.query(Attendance, User)
                 .join(User, User.id == Attendance.user_id)
                 .order_by(Attendance.event_date.desc(), Attendance.id.desc())
                 .limit(200).all())
    # Quote je Person - die eigentliche Auskunft. Eine Liste von 200 Zeilen
    # beantwortet die Frage "wer ist eigentlich regelmaessig da" nicht.
    treffen_gesamt = db.query(func.count(Meeting.id)).scalar() or 0
    je_person = dict(db.query(Attendance.user_id, func.count(Attendance.id))
                     .group_by(Attendance.user_id).all())
    personen = db.query(User).filter(User.status == "aktiv").order_by(
        User.vorname).all()
    quoten = [{"person": p, "anzahl": je_person.get(p.id, 0),
               "quote": round(je_person.get(p.id, 0) / treffen_gesamt * 100)
                        if treffen_gesamt else 0}
              for p in personen]
    quoten.sort(key=lambda z: z["anzahl"], reverse=True)
    return teil("dashboard/anwesenheit.html", a, eintraege=eintraege,
                quoten=quoten, treffen_gesamt=treffen_gesamt, personen=personen,
                treffen=db.query(Meeting).order_by(Meeting.date.desc()).limit(30).all(),
                meldung=meldung)


@router.get("/anwesenheit")
def anwesenheit(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("attendance")
    return _anwesenheit_ansicht(a)


@router.post("/anwesenheit")
def anwesenheit_erfassen(personen: list = Form([]), art: str = Form("Treffen"),
                         wann: str = Form(""), treffen_id: str = Form(""),
                         notiz: str = Form(""), csrf: str = Form(""),
                         a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("attendance")
    a.pruefe_csrf(csrf)
    db = a.db
    tag = datum(wann) or date.today()
    ids = [zahl(p) for p in personen if zahl(p)]
    if not ids:
        return _anwesenheit_ansicht(a, fehler("Bitte mindestens eine Person ankreuzen."))
    neu = 0
    for person_id in ids:
        # Doppelte Erfassung am selben Tag zur selben Art abfangen.
        if db.query(Attendance).filter(Attendance.user_id == person_id,
                                       Attendance.event_date == tag,
                                       Attendance.event_type == art).first():
            continue
        eintrag = Attendance(user_id=person_id, event_type=sauber(art)[:80] or "Treffen",
                             event_date=tag, meeting_id=zahl(treffen_id),
                             notes=sauber(notiz)[:2000] or None)
        db.add(eintrag)
        db.flush()
        leistung.anwesenheit_erfasst(db, eintrag)
        neu += 1
    db.commit()
    leistung.anstossen(ids)
    # Jetzt steht fest, wer da war - also lassen sich die Zusagen zu diesem
    # Treffen abrechnen. Sonst geschaehe das erst nachts, und wer die Liste
    # eintraegt, saehe die Wirkung nicht.
    leistung.treffen_abrechnen()
    return _anwesenheit_ansicht(a, gut(f"{neu} Anwesenheit(en) erfasst."))


@router.post("/anwesenheit/{eintrag_id}/loeschen")
def anwesenheit_loeschen(eintrag_id: int, csrf: str = Form(""),
                         a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("attendance")
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(Attendance, eintrag_id)
    if eintrag:
        person_id = eintrag.user_id
        # Auch den Leistungsnachweis: das war eine Fehleingabe, keine Leistung.
        leistung.widerrufe(a.db, person_id, "anwesenheit", eintrag.id)
        a.db.delete(eintrag)
        a.db.commit()
        leistung.anstossen(person_id)
    return _anwesenheit_ansicht(a, gut("Eintrag entfernt."))


#  Leadership
@router.get("/leistung")
def leistungswerte(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("leadership")
    db = a.db
    zeilen = leistung.rangliste(db)
    kandidaten = (db.query(SuccessionCandidate, User)
                  .join(User, User.id == SuccessionCandidate.user_id)
                  .order_by(SuccessionCandidate.position,
                            SuccessionCandidate.ranking).all())
    return teil("dashboard/leistung.html", a, zeilen=zeilen,
                kandidaten=kandidaten,
                empfehlung_labels=leistung.EMPFEHLUNG_LABELS,
                gewichte=leistung.GEWICHTE,
                personen=db.query(User).filter(User.status == "aktiv")
                          .order_by(User.vorname).all(),
                darf_planen=a.darf("leadership_manage"),
                meldung=None)


@router.post("/leistung/neu-rechnen")
def leistung_neu(csrf: str = Form(""),
                 a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Vollabgleich von Hand anstossen.

    Normalerweise nicht noetig - das Scoring laeuft bei jedem Ereignis und
    einmal nachts. Der Knopf ist fuer den Fall, dass jemand nachsehen will,
    ob der Stand wirklich aktuell ist.
    """
    a.verlange("leadership")
    a.pruefe_csrf(csrf)
    anzahl = leistung.alle_neu_rechnen()
    db = a.db
    zeilen = leistung.rangliste(db)
    kandidaten = (db.query(SuccessionCandidate, User)
                  .join(User, User.id == SuccessionCandidate.user_id)
                  .order_by(SuccessionCandidate.position,
                            SuccessionCandidate.ranking).all())
    return teil("dashboard/leistung.html", a, zeilen=zeilen, kandidaten=kandidaten,
                empfehlung_labels=leistung.EMPFEHLUNG_LABELS,
                gewichte=leistung.GEWICHTE,
                personen=db.query(User).filter(User.status == "aktiv")
                          .order_by(User.vorname).all(),
                darf_planen=a.darf("leadership_manage"),
                meldung=gut(f"Werte für {anzahl} Konten neu berechnet."))


@router.post("/leistung/nachfolge")
def nachfolge(person: str = Form(""), position: str = Form(""),
              platz: str = Form(""), sicherheit: str = Form(""),
              ab: str = Form(""), notiz: str = Form(""),
              csrf: str = Form(""),
              a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("leadership_manage")
    a.pruefe_csrf(csrf)
    db = a.db
    person_id = zahl(person)
    pos = sauber(position)[:80]
    if not person_id or not pos:
        return leistungswerte(a)
    db.add(SuccessionCandidate(
        user_id=person_id, position=pos, ranking=zahl(platz),
        confidence=max(0, min(100, zahl(sicherheit, 50) or 50)),
        readiness_date=datum(ab), notes=sauber(notiz)[:2000] or None))
    db.commit()
    return leistungswerte(a)


@router.post("/leistung/nachfolge/{kandidat_id}/loeschen")
def nachfolge_loeschen(kandidat_id: int, csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("leadership_manage")
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(SuccessionCandidate, kandidat_id)
    if eintrag:
        a.db.delete(eintrag)
        a.db.commit()
    return leistungswerte(a)
