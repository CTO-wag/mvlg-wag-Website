"""Kassenbuch: Buchungen, Budgets, Dauerauftraege.

Betraege stehen ueberall als ganze Cent - siehe kern/text.py. Vorzeichen
statt einer Spalte „Art“: eine Einnahme ist positiv, eine Ausgabe negativ.
Damit ist der Kassenstand schlicht die Summe, und es gibt keine zweite
Stelle, an der sich ein Vorzeichenfehler verstecken kann.
"""

from calendar import monthrange
from datetime import date

from sqlalchemy import func

from kern.modelle import Buchung, Budget, Dauerauftrag
from kern.rechte import LABELS, abteilung_label
from kern.text import sauber

# Vorschlaege, keine Vorschrift: das Eingabefeld nimmt jeden Text an. Eine
# feste Liste geht bei einer AG nie auf - irgendwann kommt "Trikots" oder
# "Startgeld Planspiel", und dann landet alles unter Sonstiges.
KATEGORIEN = ("mitgliedsbeitrag", "sponsoring", "verkauf", "material",
              "veranstaltung", "fahrtkosten", "sonstiges")
MAX_KATEGORIE = 40

RHYTHMEN = (("monatlich", "Monatlich", 1),
            ("quartalsweise", "Alle 3 Monate", 3),
            ("halbjaehrlich", "Halbjährlich", 6),
            ("jaehrlich", "Jährlich", 12))
RHYTHMUS_MONATE = {k: m for k, _, m in RHYTHMEN}

# Obergrenze fuer das Nachholen. Ein Dauerauftrag von 2019, den niemand
# beendet hat, soll nicht auf einen Schlag 80 Buchungen erzeugen.
MAX_NACHHOLEN = 120


def kategorie_saeubern(eingabe: str) -> str:
    """Bekannte Vorschlaege auf ihren Schluessel zuruecckfuehren.

    Sonst stehen „Material & Druck“ und „material“ als zwei Kategorien
    nebeneinander in der Statistik - genau dafuer ist die Liste da.
    """
    text = sauber(eingabe)[:MAX_KATEGORIE].strip()
    if not text:
        return "sonstiges"
    klein = text.casefold()
    for schluessel in KATEGORIEN:
        if klein == schluessel or klein == LABELS.get(schluessel, "").casefold():
            return schluessel
    return text


def kategorie_vorschlaege(db) -> list:
    benutzt = [k for (k,) in db.query(Buchung.kategorie).distinct().all() if k]
    benutzt += [k for (k,) in db.query(Dauerauftrag.kategorie).distinct().all() if k]
    alle = list(KATEGORIEN) + sorted(set(benutzt) - set(KATEGORIEN))
    return [(k, LABELS.get(k, k)) for k in alle]


def stand(db) -> int:
    return db.query(func.coalesce(func.sum(Buchung.betrag_cent), 0)).scalar() or 0


def monate(buchungen, anzahl: int = 6) -> list:
    """Einnahmen und Ausgaben je Monat, aelteste zuerst."""
    from collections import OrderedDict
    heute = date.today()
    kaesten = OrderedDict()
    jahr, monat = heute.year, heute.month
    for _ in range(anzahl):
        kaesten[(jahr, monat)] = {"ein": 0, "aus": 0}
        monat -= 1
        if monat == 0:
            monat, jahr = 12, jahr - 1
    for b in buchungen:
        schluessel = (b.datum.year, b.datum.month)
        if schluessel not in kaesten:
            continue
        if b.betrag_cent >= 0:
            kaesten[schluessel]["ein"] += b.betrag_cent
        else:
            kaesten[schluessel]["aus"] += -b.betrag_cent
    from kern.text import MONATE
    return [(f"{MONATE[m - 1][:3]} {str(j)[2:]}", w["ein"], w["aus"])
            for (j, m), w in reversed(kaesten.items())]


def monate_addieren(start: date, anzahl: int) -> date:
    """Datum um Monate verschieben - der Monatstag bleibt, soweit es geht.

    Ohne diese Sorgfalt wandert ein Auftrag, der am 31. faellig ist, im
    Februar auf den 28. und bliebe dort fuer immer.
    """
    monat_gesamt = start.month - 1 + anzahl
    jahr = start.year + monat_gesamt // 12
    monat = monat_gesamt % 12 + 1
    tag = min(start.day, monthrange(jahr, monat)[1])
    return date(jahr, monat, tag)


def budget_uebersicht(db, stichtag: date = None) -> list:
    """Je Budget: was zur Verfuegung steht, was verbraucht ist."""
    stichtag = stichtag or date.today()
    zeilen = []
    for budget in db.query(Budget).order_by(Budget.von.desc()).all():
        ausgaben = db.query(func.coalesce(func.sum(Buchung.betrag_cent), 0)).filter(
            Buchung.abteilung == budget.abteilung,
            Buchung.datum >= budget.von, Buchung.datum <= budget.bis,
            Buchung.betrag_cent < 0).scalar() or 0
        verbraucht = -ausgaben
        zeilen.append({
            "budget": budget,
            "abteilung_label": abteilung_label(budget.abteilung),
            "verbraucht": verbraucht,
            "rest": budget.betrag_cent - verbraucht,
            "anteil": min(100, round(verbraucht / budget.betrag_cent * 100))
                      if budget.betrag_cent else 0,
            "laeuft": budget.von <= stichtag <= budget.bis,
            "vorbei": budget.bis < stichtag,
        })
    return zeilen


def faellige_auftraege(db, stichtag: date = None) -> list:
    stichtag = stichtag or date.today()
    return (db.query(Dauerauftrag)
            .filter(Dauerauftrag.aktiv == 1,
                    Dauerauftrag.naechste_faelligkeit <= stichtag)
            .order_by(Dauerauftrag.naechste_faelligkeit).all())


def dauerauftraege_ausfuehren(db, stichtag: date = None, erfasser_id=None) -> int:
    """Faellige wiederkehrende Buchungen anlegen - auch rueckwirkend.

    Die Faelligkeit laeuft so lange weiter, bis sie in der Zukunft liegt.
    Dadurch holt ein Rechner, der wochenlang aus war, alle verpassten
    Buchungen nach, statt genau eine anzulegen. Gerechnet wird dabei immer
    vom START aus, nicht von der vorigen Faelligkeit - sonst wandert ein
    Auftrag vom 31. im Februar dauerhaft auf den 28.
    """
    stichtag = stichtag or date.today()
    angelegt = 0
    for auftrag in faellige_auftraege(db, stichtag):
        schritte = RHYTHMUS_MONATE.get(auftrag.rhythmus, 1)
        schutz = 0
        while auftrag.naechste_faelligkeit <= stichtag and schutz < MAX_NACHHOLEN:
            db.add(Buchung(
                datum=auftrag.naechste_faelligkeit, zweck=auftrag.zweck,
                betrag_cent=auftrag.betrag_cent, kategorie=auftrag.kategorie,
                abteilung=auftrag.abteilung, erfasser_id=erfasser_id,
                dauerauftrag_id=auftrag.id,
                notiz="Automatisch aus dem Dauerauftrag."))
            auftrag.ausfuehrungen = (auftrag.ausfuehrungen or 0) + 1
            auftrag.letzte_ausfuehrung = auftrag.naechste_faelligkeit
            auftrag.naechste_faelligkeit = monate_addieren(
                auftrag.start_datum, auftrag.ausfuehrungen * schritte)
            angelegt += 1
            schutz += 1
    return angelegt


def statistik(db, buchungen) -> dict:
    einnahmen = sum(b.betrag_cent for b in buchungen if b.betrag_cent > 0)
    ausgaben = -sum(b.betrag_cent for b in buchungen if b.betrag_cent < 0)
    return {
        "einnahmen": einnahmen,
        "ausgaben": ausgaben,
        "saldo": einnahmen - ausgaben,
        "anzahl": len(buchungen),
        "stand": stand(db),
    }


def nach_kategorie(buchungen, nur_ausgaben: bool = True) -> list:
    summen = {}
    for b in buchungen:
        if nur_ausgaben and b.betrag_cent >= 0:
            continue
        if not nur_ausgaben and b.betrag_cent < 0:
            continue
        summen[b.kategorie] = summen.get(b.kategorie, 0) + abs(b.betrag_cent)
    return sorted(((LABELS.get(k, k), w) for k, w in summen.items()),
                  key=lambda z: z[1], reverse=True)
