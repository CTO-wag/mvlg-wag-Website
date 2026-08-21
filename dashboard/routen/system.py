"""Rollen, Abteilungen, Startseite, Kassenbuch, Datenbank, Papierkorb, Sicherheit."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, inspect

from dashboard.hilfen import (
    als_csv, Anmeldung, datum, fehler, gut, info, papierkorb_hinweis, teil, zahl,
    warnung,
)
from kern import inhalte, kasse, papierkorb, protokoll, sicherung, zustand
from kern import einstellungen as cfg
from kern.datenbank import Base, engine
from kern.modelle import (
    ActivityLog, Anmeldeversuch, Buchung, Budget, Dauerauftrag, Department,
    Inhalt, Role, TrashItem, User, UserSession,
)
from kern.rechte import (
    CTO_KERNRECHTE, DEPT_FEATURES, DEPT_PERM_KEYS, PERM_KEYS, PERM_LABELS,
    ROLE_PRESETS, abteilung_label, abteilungen, cache_verwerfen, perm_gruppen,
    rang_von, rollen,
)
from kern.text import betrag_in_cent, euro, kuerzen, sauber, schluessel_normal, utcnow

router = APIRouter(prefix="/dashboard")


#  Rollen und Abteilungen
def _rollen_ansicht(a: Anmeldung, meldung=None):
    db = a.db
    rollen_zeilen = db.query(Role).order_by(Role.rang.desc(), Role.key).all()
    belegung = dict(db.query(User.role, func.count(User.id))
                    .group_by(User.role).all())
    abt_belegung = dict(db.query(User.department, func.count(User.id))
                        .group_by(User.department).all())
    gruppen = perm_gruppen()
    # Wie viele Rechte je Gruppe an sind - die Zahl oben auf der Karte.
    stand = {}
    for rolle in rollen_zeilen:
        stand[rolle.key] = {
            name: (sum(1 for k, _, _ in eintraege if getattr(rolle, k, 0)),
                   len(eintraege))
            for name, eintraege in gruppen}
    return teil("dashboard/rollen.html", a,
                rollen_zeilen=rollen_zeilen, belegung=belegung,
                abt_belegung=abt_belegung,
                abteilungen_liste=abteilungen(nur_aktive=False),
                gruppen=gruppen, stand=stand,
                kernrechte=CTO_KERNRECHTE,
                dept_features=DEPT_FEATURES,
                perm_labels=PERM_LABELS,
                vorlagen=ROLE_PRESETS, mein_rang=rang_von(a.user),
                meldung=meldung)


@router.get("/rollen")
def rollen_bereich(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("rollen")
    return _rollen_ansicht(a)


@router.post("/rollen")
def rolle_anlegen(schluessel: str = Form(""), name: str = Form(""),
                  rang: str = Form("20"), beschreibung: str = Form(""),
                  csrf: str = Form(""),
                  a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("rollen")
    a.pruefe_csrf(csrf)
    key = schluessel_normal(schluessel)[:40]
    label_ = sauber(name)[:80]
    if not key or not label_:
        return _rollen_ansicht(a, fehler("Kennung und Name werden gebraucht."))
    if a.db.get(Role, key):
        return _rollen_ansicht(a, fehler(f"Die Kennung „{key}“ gibt es schon."))
    neuer_rang = max(0, min(rang_von(a.user), zahl(rang, 20) or 20))
    a.db.add(Role(key=key, label=label_, rang=neuer_rang,
                  beschreibung=sauber(beschreibung)[:500] or None,
                  **{p: 0 for p in PERM_KEYS}))
    a.db.commit()
    cache_verwerfen()
    return _rollen_ansicht(a, gut(
        f"Rolle „{label_}“ angelegt – noch ohne Rechte. Die vergibst du unten."))


@router.post("/rollen/{key}/aendern")
def rolle_aendern(key: str, name: str = Form(""), rang: str = Form(""),
                  beschreibung: str = Form(""), rechte: list = Form([]),
                  csrf: str = Form(""),
                  a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("rollen")
    a.pruefe_csrf(csrf)
    rolle = a.db.get(Role, key)
    if not rolle:
        return _rollen_ansicht(a, fehler("Diese Rolle gibt es nicht mehr."))
    # Man kann keine Rolle bearbeiten, die über einem selbst steht.
    if (rolle.rang or 0) > rang_von(a.user):
        return _rollen_ansicht(a, fehler(
            "Diese Rolle steht über deiner eigenen – das darfst du nicht ändern."))

    if sauber(name):
        rolle.label = sauber(name)[:80]
    rolle.beschreibung = sauber(beschreibung)[:500] or None
    neuer_rang = zahl(rang)
    if neuer_rang is not None:
        rolle.rang = max(0, min(rang_von(a.user), neuer_rang))

    gewaehlt = set(rechte)
    for perm in PERM_KEYS:
        setattr(rolle, perm, 1 if perm in gewaehlt else 0)
    # Dem CTO bleiben die Kernrechte - sonst sperrt sich die AG aus ihrer
    # eigenen Verwaltung aus und kommt nicht mehr hinein.
    if rolle.key == "cto":
        for perm in CTO_KERNRECHTE:
            setattr(rolle, perm, 1)
    protokoll.notiere(a.db, a.user.id, "rolle_geaendert", rolle.key)
    a.db.commit()
    cache_verwerfen()
    return _rollen_ansicht(a, gut(f"Rechte für „{rolle.label}“ gespeichert."))


@router.post("/rollen/{key}/loeschen")
def rolle_loeschen(key: str, csrf: str = Form(""),
                   a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("rollen")
    a.pruefe_csrf(csrf)
    rolle = a.db.get(Role, key)
    if not rolle:
        return _rollen_ansicht(a, fehler("Diese Rolle gibt es nicht mehr."))
    if rolle.protected:
        return _rollen_ansicht(a, fehler(
            "Diese Rolle ist geschützt – an ihr hängt die Grundordnung der AG."))
    belegt = a.db.query(func.count(User.id)).filter(User.role == key).scalar() or 0
    if belegt:
        return _rollen_ansicht(a, fehler(
            f"{belegt} Konto/Konten haben diese Rolle. Erst umtragen, dann löschen."))
    a.db.delete(rolle)
    a.db.commit()
    cache_verwerfen()
    return _rollen_ansicht(a, gut("Rolle gelöscht."))


@router.post("/abteilungen")
def abteilung_anlegen(schluessel: str = Form(""), name: str = Form(""),
                      farbe: str = Form("#4A5568"),
                      beschreibung: str = Form(""), csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("rollen")
    a.pruefe_csrf(csrf)
    key = schluessel_normal(schluessel)[:30]
    label_ = sauber(name)[:60]
    if not key or not label_:
        return _rollen_ansicht(a, fehler("Kennung und Name werden gebraucht."))
    if a.db.get(Department, key):
        return _rollen_ansicht(a, fehler(f"Die Kennung „{key}“ gibt es schon."))
    letzte = a.db.query(func.coalesce(func.max(Department.reihenfolge), 0)).scalar() or 0
    neu = Department(key=key, label=label_, farbe=_farbe_pruefen(farbe),
                     beschreibung=sauber(beschreibung)[:500] or None,
                     reihenfolge=letzte + 10)
    for feld in DEPT_PERM_KEYS:
        setattr(neu, feld, 0)
    a.db.add(neu)
    a.db.commit()
    cache_verwerfen()
    return _rollen_ansicht(a, gut(f"Abteilung „{label_}“ angelegt."))


def _farbe_pruefen(wert: str, ersatz: str = "#4A5568") -> str:
    """Nur echte Hex-Farben durchlassen - der Wert landet in einem style-Attribut."""
    import re
    text = sauber(wert)
    return text if re.fullmatch(r"#[0-9A-Fa-f]{6}", text) else ersatz


@router.post("/abteilungen/{key}/aendern")
def abteilung_aendern(key: str, name: str = Form(""), farbe: str = Form(""),
                      beschreibung: str = Form(""), aktiv: str = Form(""),
                      funktionen: list = Form([]), csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("rollen")
    a.pruefe_csrf(csrf)
    abteilung = a.db.get(Department, key)
    if not abteilung:
        return _rollen_ansicht(a, fehler("Diese Abteilung gibt es nicht mehr."))
    if sauber(name):
        abteilung.label = sauber(name)[:60]
    abteilung.farbe = _farbe_pruefen(farbe, abteilung.farbe)
    abteilung.beschreibung = sauber(beschreibung)[:500] or None
    if not abteilung.geschuetzt:
        abteilung.aktiv = 1 if aktiv else 0
    gewaehlt = set(funktionen)
    for feld in DEPT_PERM_KEYS:
        setattr(abteilung, feld, 1 if feld in gewaehlt else 0)
    a.db.commit()
    cache_verwerfen()
    return _rollen_ansicht(a, gut(f"Abteilung „{abteilung.label}“ gespeichert."))


@router.post("/abteilungen/{key}/loeschen")
def abteilung_loeschen(key: str, csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("rollen")
    a.pruefe_csrf(csrf)
    abteilung = a.db.get(Department, key)
    if not abteilung:
        return _rollen_ansicht(a, fehler("Diese Abteilung gibt es nicht mehr."))
    if abteilung.geschuetzt:
        return _rollen_ansicht(a, fehler(
            "Die Exekutive lässt sich nicht löschen – an ihr hängt die "
            "Zuständigkeit jeder Vorstandsrolle."))
    belegt = a.db.query(func.count(User.id)).filter(User.department == key).scalar() or 0
    if belegt:
        return _rollen_ansicht(a, fehler(
            f"{belegt} Person(en) sind in dieser Abteilung. Erst umtragen."))
    a.db.delete(abteilung)
    a.db.commit()
    cache_verwerfen()
    return _rollen_ansicht(a, gut("Abteilung gelöscht."))


#  Startseite bearbeiten
def _startseite_ansicht(a: Anmeldung, meldung=None):
    return teil("dashboard/startseite.html", a,
                bereiche=inhalte.BEREICHE,
                bloecke=inhalte.alle_bloecke(a.db),
                farben=inhalte.FARBVORSCHLAEGE,
                mit_zeitraum=inhalte.MIT_ZEITRAUM,
                mit_text=inhalte.MIT_TEXT,
                mit_farbe=inhalte.MIT_FARBE,
                meldung=meldung)


@router.get("/startseite")
def startseite(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("seiteninhalte")
    return _startseite_ansicht(a)


@router.post("/startseite")
def block_anlegen(bereich: str = Form(""), titel: str = Form(""),
                  text: str = Form(""), farbe: str = Form(""),
                  zeitraum: str = Form(""), ergebnis: str = Form(""),
                  csrf: str = Form(""),
                  a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("seiteninhalte")
    a.pruefe_csrf(csrf)
    if bereich not in inhalte.BEREICHE:
        return _startseite_ansicht(a, fehler("Diesen Bereich gibt es nicht."))
    titel_ = sauber(titel)[:160]
    if not titel_:
        return _startseite_ansicht(a, fehler("Ohne Titel geht es nicht."))
    inhalte.anlegen(a.db, bereich, titel_, sauber(text)[:2000],
                    _farbe_pruefen(farbe, ""), sauber(zeitraum)[:60],
                    sauber(ergebnis)[:120], a.user.id)
    a.db.commit()
    inhalte.verwerfen()
    hinweis = ("Eintrag hinzugefügt – er steht ab sofort auf der Startseite."
               if bereich != "portfolio" else
               "Eintrag hinzugefügt. Die Sektion „Unsere Arbeit“ erscheint "
               "damit auf der Startseite.")
    return _startseite_ansicht(a, gut(hinweis))


@router.post("/startseite/{block_id}/aendern")
def block_aendern(block_id: int, titel: str = Form(""), text: str = Form(""),
                  farbe: str = Form(""), zeitraum: str = Form(""),
                  ergebnis: str = Form(""), aktiv: str = Form(""),
                  csrf: str = Form(""),
                  a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("seiteninhalte")
    a.pruefe_csrf(csrf)
    block = a.db.get(Inhalt, block_id)
    if not block:
        return _startseite_ansicht(a, fehler("Diesen Block gibt es nicht mehr."))
    if sauber(titel):
        block.titel = sauber(titel)[:160]
    block.text = sauber(text)[:2000] or None
    block.farbe = _farbe_pruefen(farbe, "") or None
    block.zeitraum = sauber(zeitraum)[:60] or None
    block.ergebnis = sauber(ergebnis)[:120] or None
    block.aktiv = 1 if aktiv else 0
    block.geaendert_von = a.user.id
    block.updated_at = utcnow()
    a.db.commit()
    inhalte.verwerfen()
    return _startseite_ansicht(a, gut("Gespeichert."))


@router.post("/startseite/{block_id}/verschieben")
def block_verschieben(block_id: int, richtung: str = Form("1"),
                      csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("seiteninhalte")
    a.pruefe_csrf(csrf)
    inhalte.verschieben(a.db, block_id, zahl(richtung, 1) or 1)
    a.db.commit()
    inhalte.verwerfen()
    return _startseite_ansicht(a)


@router.post("/startseite/{block_id}/loeschen")
def block_loeschen(block_id: int, csrf: str = Form(""),
                   a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("seiteninhalte")
    a.pruefe_csrf(csrf)
    block = a.db.get(Inhalt, block_id)
    if block:
        a.db.delete(block)
        a.db.commit()
        inhalte.verwerfen()
    return _startseite_ansicht(a, gut("Block entfernt."))


#  Kassenbuch
def _kasse_ansicht(a: Anmeldung, meldung=None, monate_zurueck: int = 6,
                   formular_offen: bool = False):
    db = a.db
    von = date.today() - timedelta(days=monate_zurueck * 31)
    buchungen = (db.query(Buchung).filter(Buchung.datum >= von)
                 .order_by(Buchung.datum.desc(), Buchung.id.desc()).all())
    from kern import diagramme
    verlaufsdaten = kasse.monate(buchungen, monate_zurueck)
    return teil("dashboard/kassenbuch.html", a,
                formular_offen=formular_offen,
                buchungen=buchungen[:120],
                statistik=kasse.statistik(db, buchungen),
                verlauf=verlaufsdaten,
                ausgaben_diagramm=diagramme.balken(
                    kasse.nach_kategorie(buchungen, True), 5,
                    lambda w: euro(w)),
                einnahmen_diagramm=diagramme.balken(
                    kasse.nach_kategorie(buchungen, False), 2,
                    lambda w: euro(w)),
                budgets=kasse.budget_uebersicht(db),
                auftraege=db.query(Dauerauftrag).order_by(
                    Dauerauftrag.aktiv.desc(),
                    Dauerauftrag.naechste_faelligkeit).all(),
                faellig=kasse.faellige_auftraege(db),
                kategorien=kasse.kategorie_vorschlaege(db),
                rhythmen=kasse.RHYTHMEN,
                abteilungen_wahl=[x["key"] for x in abteilungen()],
                darf_buchen=a.darf("finanzen_verwalten"),
                meldung=meldung)


@router.get("/kassenbuch")
def kassenbuch(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("finanzen")
    return _kasse_ansicht(a)


@router.post("/kassenbuch")
def buchung_anlegen(zweck: str = Form(""), betrag: str = Form(""),
                    richtung: str = Form("aus"), kategorie: str = Form(""),
                    abteilung: str = Form(""), wann: str = Form(""),
                    beleg: str = Form(""), notiz: str = Form(""),
                    csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("finanzen_verwalten")
    a.pruefe_csrf(csrf)
    zweck_ = sauber(zweck)[:200]
    cent = betrag_in_cent(betrag)
    if not zweck_:
        return _kasse_ansicht(a, fehler("Wofür war das? Bitte einen Zweck angeben."))
    if cent is None or cent == 0:
        return _kasse_ansicht(a, fehler(
            "Der Betrag ist nicht lesbar. Beispiele: 12,50 oder 1.234,56"))
    # Vorzeichen kommt aus der Richtung, nicht aus der Eingabe - sonst gibt es
    # zwei Stellen, an denen ein Vorzeichenfehler entstehen kann.
    cent = abs(cent) if richtung == "ein" else -abs(cent)

    a.db.add(Buchung(datum=datum(wann) or date.today(), zweck=zweck_,
                     betrag_cent=cent,
                     kategorie=kasse.kategorie_saeubern(kategorie),
                     abteilung=abteilung or None,
                     beleg=sauber(beleg)[:60] or None,
                     notiz=sauber(notiz)[:2000] or None,
                     erfasser_id=a.user.id))
    protokoll.notiere(a.db, a.user.id, "buchung", f"{euro(cent)} · {kuerzen(zweck_, 80)}")
    a.db.commit()
    # Nach einem Wettbewerbstag bucht man mehrere Belege hintereinander -
    # das Formular bleibt deshalb offen stehen.
    return _kasse_ansicht(a, gut(f"{euro(cent)} gebucht. Neuer Stand: "
                                 f"{euro(kasse.stand(a.db))}."),
                          formular_offen=True)


@router.post("/kassenbuch/{buchung_id}/stornieren")
def buchung_stornieren(buchung_id: int, csrf: str = Form(""),
                       a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("finanzen_verwalten")
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(Buchung, buchung_id)
    if eintrag:
        papierkorb.hinein(a.db, "buchung", eintrag, a.user.id,
                          f"{euro(eintrag.betrag_cent)} · {eintrag.zweck}")
        protokoll.notiere(a.db, a.user.id, "buchung_storniert", f"#{buchung_id}")
        a.db.commit()
    return _kasse_ansicht(a,
        papierkorb_hinweis("Buchung storniert – sie liegt im Papierkorb und "
                       "lässt sich zurückholen."))


@router.post("/kassenbuch/budget")
def budget_anlegen(abteilung: str = Form(""), bezeichnung: str = Form(""),
                   betrag: str = Form(""), von: str = Form(""),
                   bis: str = Form(""), csrf: str = Form(""),
                   a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("finanzen_verwalten")
    a.pruefe_csrf(csrf)
    cent = betrag_in_cent(betrag)
    von_, bis_ = datum(von), datum(bis)
    if not sauber(bezeichnung) or cent is None or cent <= 0:
        return _kasse_ansicht(a, fehler("Bezeichnung und ein Betrag über null werden gebraucht."))
    if not von_ or not bis_ or bis_ < von_:
        return _kasse_ansicht(a, fehler("Der Zeitraum stimmt nicht."))
    a.db.add(Budget(abteilung=abteilung or "exekutive",
                    bezeichnung=sauber(bezeichnung)[:120],
                    von=von_, bis=bis_, betrag_cent=cent))
    a.db.commit()
    return _kasse_ansicht(a, gut("Budget angelegt."))


@router.post("/kassenbuch/budget/{budget_id}/loeschen")
def budget_loeschen(budget_id: int, csrf: str = Form(""),
                    a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("finanzen_verwalten")
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(Budget, budget_id)
    if eintrag:
        a.db.delete(eintrag)
        a.db.commit()
    return _kasse_ansicht(a, gut("Budget gelöscht."))


@router.post("/kassenbuch/dauerauftrag")
def dauerauftrag_anlegen(zweck: str = Form(""), betrag: str = Form(""),
                         richtung: str = Form("ein"),
                         kategorie: str = Form(""), abteilung: str = Form(""),
                         rhythmus: str = Form("monatlich"),
                         start: str = Form(""), csrf: str = Form(""),
                         a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("finanzen_verwalten")
    a.pruefe_csrf(csrf)
    cent = betrag_in_cent(betrag)
    beginn = datum(start) or date.today()
    if not sauber(zweck) or cent is None or cent == 0:
        return _kasse_ansicht(a, fehler("Zweck und Betrag werden gebraucht."))
    cent = abs(cent) if richtung == "ein" else -abs(cent)
    a.db.add(Dauerauftrag(
        zweck=sauber(zweck)[:200], betrag_cent=cent,
        kategorie=kasse.kategorie_saeubern(kategorie),
        abteilung=abteilung or None,
        rhythmus=rhythmus if rhythmus in kasse.RHYTHMUS_MONATE else "monatlich",
        start_datum=beginn, naechste_faelligkeit=beginn,
        angelegt_von=a.user.id))
    a.db.commit()
    return _kasse_ansicht(a, gut(
        "Dauerauftrag angelegt. Fällige Buchungen werden beim nächsten Lauf "
        "automatisch angelegt – auch rückwirkend."))


@router.post("/kassenbuch/dauerauftrag/{auftrag_id}/umschalten")
def dauerauftrag_umschalten(auftrag_id: int, csrf: str = Form(""),
                            a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("finanzen_verwalten")
    a.pruefe_csrf(csrf)
    auftrag = a.db.get(Dauerauftrag, auftrag_id)
    if auftrag:
        auftrag.aktiv = 0 if auftrag.aktiv else 1
        a.db.commit()
    return _kasse_ansicht(a, gut("Dauerauftrag umgeschaltet."))


@router.post("/kassenbuch/dauerauftrag/{auftrag_id}/loeschen")
def dauerauftrag_loeschen(auftrag_id: int, csrf: str = Form(""),
                          a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("finanzen_verwalten")
    a.pruefe_csrf(csrf)
    auftrag = a.db.get(Dauerauftrag, auftrag_id)
    if auftrag:
        a.db.delete(auftrag)
        a.db.commit()
    return _kasse_ansicht(a, gut("Dauerauftrag gelöscht. Bereits angelegte "
                                 "Buchungen bleiben stehen."))


@router.post("/kassenbuch/dauerauftraege-ausfuehren")
def dauerauftraege_jetzt(csrf: str = Form(""),
                         a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("finanzen_verwalten")
    a.pruefe_csrf(csrf)
    anzahl = kasse.dauerauftraege_ausfuehren(a.db, erfasser_id=a.user.id)
    a.db.commit()
    return _kasse_ansicht(a, gut(f"{anzahl} Buchung(en) angelegt.")
                          if anzahl else info("Nichts fällig."))


@router.get("/kassenbuch/export.csv")
def kasse_export(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("finanzen")
    zeilen = [(b.datum.isoformat(), b.zweck, f"{b.betrag_cent / 100:.2f}".replace(".", ","),
               b.kategorie, abteilung_label(b.abteilung) if b.abteilung else "",
               b.beleg or "", b.erfasser.name if b.erfasser else "", b.notiz or "")
              for b in a.db.query(Buchung).order_by(Buchung.datum).all()]
    return als_csv(zeilen, ["Datum", "Zweck", "Betrag", "Kategorie", "Abteilung",
                            "Beleg", "Erfasst von", "Notiz"], "kassenbuch.csv")


#  Datenbank
def _modelle() -> dict:
    return {t.name: t for t in Base.metadata.sorted_tables}


@router.get("/datenbank")
def datenbank(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("datenbank")
    db = a.db
    kacheln = []
    vorhandene = set(inspect(engine).get_table_names())
    for name, tabelle in sorted(_modelle().items()):
        if name not in vorhandene:
            continue
        try:
            anzahl = db.execute(func.count().select().select_from(tabelle)).scalar()
        except Exception:
            anzahl = 0
        kacheln.append({"name": name, "anzahl": anzahl,
                        "titel": name.replace("_", " ").title()})
    kacheln.sort(key=lambda k: (-k["anzahl"], k["name"]))
    aktivitaet = (db.query(ActivityLog, User)
                  .outerjoin(User, User.id == ActivityLog.user_id)
                  .order_by(ActivityLog.created_at.desc()).limit(50).all())
    return teil("dashboard/datenbank.html", a, kacheln=kacheln,
                aktivitaet=aktivitaet, zustand=zustand.pruefen(db),
                meldung=None)


@router.get("/datenbank/tabelle/{name}")
def datenbank_tabelle(name: str, seite: int = 0,
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("datenbank")
    tabelle = _modelle().get(name)
    if tabelle is None:
        return teil("dashboard/datenbank_tabelle.html", a, tabelle=name,
                    spalten=[], zeilen=[], seite=0, mehr=False,
                    meldung=fehler("Diese Tabelle gibt es nicht."))
    # Passwoerter und Token gehoeren auch dem Vorstand nicht vor die Augen.
    # Sie stehen zwar nur als Prüfwert da, aber angezeigt werden müssen sie
    # deshalb noch lange nicht.
    verborgen = {"password_hash", "token_hash", "auth", "p256dh", "totp_secret"}
    spalten = [s.name for s in tabelle.columns]
    pro_seite = 50
    abfrage = tabelle.select().limit(pro_seite + 1).offset(max(0, seite) * pro_seite)
    ergebnis = a.db.execute(abfrage).fetchall()
    mehr = len(ergebnis) > pro_seite
    zeilen = []
    for zeile in ergebnis[:pro_seite]:
        werte = []
        for spalte, wert in zip(spalten, zeile):
            if spalte in verborgen and wert:
                werte.append("••• verborgen •••")
            else:
                werte.append("" if wert is None else str(wert))
        zeilen.append(werte)
    return teil("dashboard/datenbank_tabelle.html", a, tabelle=name,
                spalten=spalten, zeilen=zeilen, seite=max(0, seite), mehr=mehr,
                meldung=None)


@router.post("/datenbank/protokoll-leeren")
def protokoll_leeren(csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("aktivitaetslog_loeschen")
    a.pruefe_csrf(csrf)
    anzahl = a.db.query(ActivityLog).delete(synchronize_session=False)
    a.db.commit()
    return datenbank(a)


#  Papierkorb und Sicherungen
def _papierkorb_ansicht(a: Anmeldung, meldung=None):
    return teil("dashboard/papierkorb.html", a,
                eintraege=papierkorb.inhalt(a.db),
                arten=papierkorb.MODELLE,
                sicherungen=sicherung.vorhandene(),
                frist=cfg.TRASH_RETENTION_DAYS,
                meldung=meldung)


@router.get("/papierkorb")
def papierkorb_bereich(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("datenbank")
    return _papierkorb_ansicht(a)


@router.post("/papierkorb/{eintrag_id}/wiederherstellen")
def wiederherstellen(eintrag_id: int, csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("datenbank")
    a.pruefe_csrf(csrf)
    geklappt, text = papierkorb.zurueck(a.db, eintrag_id)
    if geklappt:
        a.db.commit()
        return _papierkorb_ansicht(a, gut(text))
    a.db.rollback()
    return _papierkorb_ansicht(a, fehler(text))


@router.post("/papierkorb/{eintrag_id}/endgueltig")
def endgueltig_loeschen(eintrag_id: int, csrf: str = Form(""),
                        a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("datenbank")
    a.pruefe_csrf(csrf)
    if papierkorb.endgueltig(a.db, eintrag_id):
        a.db.commit()
    return _papierkorb_ansicht(a, gut("Endgültig entfernt."))


@router.post("/papierkorb/leeren")
def papierkorb_leeren(csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("datenbank")
    a.pruefe_csrf(csrf)
    anzahl = a.db.query(TrashItem).delete(synchronize_session=False)
    a.db.commit()
    return _papierkorb_ansicht(a, gut(f"{anzahl} Eintrag/Einträge endgültig entfernt."))


@router.post("/papierkorb/sicherung")
def sicherung_anlegen(csrf: str = Form(""),
                      a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("datenbank")
    a.pruefe_csrf(csrf)
    name = sicherung.erstelle()
    return _papierkorb_ansicht(a, gut(f"Sicherung angelegt: {name}") if name
                               else info("Innerhalb dieser Minute gibt es schon eine."))


@router.post("/papierkorb/sicherung/{name}/einspielen")
def sicherung_einspielen(name: str, bestaetigung: str = Form(""),
                         csrf: str = Form(""),
                         a: Anmeldung = Depends(Anmeldung.pflicht)):
    """Eine Sicherung zurueckspielen - der gefaehrlichste Knopf im System.

    Deshalb dreifach abgesichert: das Recht "datenbank", ein abgetipptes
    Wort statt eines blossen Klicks, und ein Protokolleintrag. Ein
    versehentlicher Klick wuerde die Arbeit von Tagen zurueckdrehen.
    """
    a.verlange("datenbank")
    a.pruefe_csrf(csrf)
    if sauber(bestaetigung).upper() != "EINSPIELEN":
        return _papierkorb_ansicht(a, fehler(
            "Zum Bestätigen bitte EINSPIELEN in das Feld tippen. Nichts "
            "wurde verändert."))
    geklappt, meldung = sicherung.einspielen(name)
    if not geklappt:
        return _papierkorb_ansicht(a, fehler(meldung))
    # Der Protokolleintrag landet in der EINGESPIELTEN Datenbank - dort
    # gehoert er auch hin: Wer sie spaeter ansieht, soll erkennen, dass sie
    # eingespielt wurde und von wem.
    protokoll.notiere(a.db, a.user.id, "sicherung_eingespielt", name)
    a.db.commit()
    return _papierkorb_ansicht(a, warnung(meldung))


@router.get("/papierkorb/sicherung/{name}")
def sicherung_holen(name: str, a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("datenbank")
    pfad = sicherung.pfad_von(name)
    if not pfad:
        return Response("Nicht gefunden", status_code=404, media_type="text/plain")
    return FileResponse(pfad, filename=name, media_type="application/octet-stream")


#  Sicherheit
@router.get("/sicherheit")
def sicherheit(a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("sicherheit")
    db = a.db
    seit = utcnow() - timedelta(days=14)

    versuche = (db.query(Anmeldeversuch)
                .order_by(Anmeldeversuch.created_at.desc()).limit(60).all())
    fehlversuche = (db.query(func.count(Anmeldeversuch.id))
                    .filter(Anmeldeversuch.erfolg == 0,
                            Anmeldeversuch.created_at >= seit).scalar() or 0)
    # Adressen mit auffällig vielen Fehlversuchen - das ist die Zahl, wegen
    # der man überhaupt hier hereinschaut.
    auffaellig = (db.query(Anmeldeversuch.ip_address, func.count(Anmeldeversuch.id))
                  .filter(Anmeldeversuch.erfolg == 0,
                          Anmeldeversuch.created_at >= seit)
                  .group_by(Anmeldeversuch.ip_address)
                  .having(func.count(Anmeldeversuch.id) >= 5)
                  .order_by(func.count(Anmeldeversuch.id).desc()).limit(10).all())

    sitzungen = (db.query(UserSession, User)
                 .join(User, User.id == UserSession.user_id)
                 .filter(UserSession.revoked == 0)
                 .order_by(UserSession.last_active.desc()).limit(60).all())

    konten = db.query(User).filter(User.status == "aktiv").all()
    ohne_2fa = [k for k in konten if not k.totp_aktiv]
    altes_passwort = [k for k in konten if not k.passwort_geaendert_am
                      or k.passwort_geaendert_am < utcnow() - timedelta(days=365)]
    gesperrt = [k for k in konten if k.locked_until and k.locked_until > utcnow()]

    from kern.sicherheit import geraet_beschreiben
    return teil("dashboard/sicherheit.html", a,
                versuche=versuche, fehlversuche=fehlversuche,
                geraet_name=geraet_beschreiben,
                auffaellig=auffaellig, sitzungen=sitzungen,
                ohne_2fa=ohne_2fa, altes_passwort=altes_passwort,
                gesperrt=gesperrt, konten_gesamt=len(konten),
                sicherungen=sicherung.vorhandene()[:5],
                zustand=zustand.pruefen(db),
                einstellungen=cfg.zusammenfassung(),
                meldung=None)


@router.post("/sicherheit/sitzung/{sid}/beenden")
def sitzung_beenden_fremd(sid: str, csrf: str = Form(""),
                          a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("sicherheit")
    a.pruefe_csrf(csrf)
    eintrag = a.db.get(UserSession, sid)
    if eintrag:
        eintrag.revoked = 1
        protokoll.notiere(a.db, a.user.id, "sitzung_beendet",
                          f"Konto #{eintrag.user_id}")
        a.db.commit()
    return sicherheit(a)


@router.post("/sicherheit/konto/{konto_id}/entsperren")
def konto_entsperren(konto_id: int, csrf: str = Form(""),
                     a: Anmeldung = Depends(Anmeldung.pflicht)):
    a.verlange("sicherheit")
    a.pruefe_csrf(csrf)
    person = a.db.get(User, konto_id)
    if person:
        person.locked_until = None
        person.failed_logins = 0
        a.db.commit()
    return sicherheit(a)
