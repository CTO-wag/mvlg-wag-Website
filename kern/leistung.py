"""Leadership-Werte, vollautomatisch.

Jede Erledigung wird einmal in "leistungen" festgehalten und danach nicht
mehr angefasst - die Zeile ueberlebt Papierkorb und Loeschen. Wer
aufraeumt, verliert also keine Punkte. Gerechnet wird bei jedem Ereignis
und einmal nachts.

Fuenf Teilwerte, gewichtet: Zuverlaessigkeit 32, Aufgaben 26,
Anwesenheit 18, Projekte 14, Wettbewerbe 10.
"""

import threading
from datetime import timedelta

from kern.datenbank import sitzung
from kern.modelle import (
    Attendance, CompetitionParticipant, LeadershipScore, Leistung, Meeting,
    MeetingRueckmeldung, Project, ProjectTeamMember, Task, User,
)
from kern.text import utcnow

# Gewichte des Gesamtwerts. Summe 100.
GEWICHTE = {
    "zuverlaessigkeit": 32,
    "aufgaben": 26,
    "anwesenheit": 18,
    "projekte": 14,
    "wettbewerbe": 10,
}

# Ab wann ein Wert als "hoch" bzw. "aufstrebend" gilt.
SCHWELLE_HOCH = 75
SCHWELLE_AUFSTREBEND = 50

# Wie weit zurueck gerechnet wird. Was aelter ist, zaehlt nicht mehr voll -
# sonst traegt jemand seinen Einsatz aus der zehnten Klasse noch bis zum Abi
# vor sich her, waehrend ein Neuzugang nie aufholen kann.
FENSTER_TAGE = 240
HALBWERT_TAGE = 120


def _gewicht_nach_alter(zeitpunkt, jetzt) -> float:
    """Aeltere Leistungen zaehlen weniger - halbiert alle 120 Tage."""
    if not zeitpunkt:
        return 0.5
    tage = max(0.0, (jetzt - zeitpunkt).total_seconds() / 86400)
    return 0.5 ** (tage / HALBWERT_TAGE)


#  Leistungen festhalten
def vermerke(db, user_id: int, art: str, quelle_id, titel: str = "",
             punkte: int = 1, abteilung: str = None, zeitpunkt=None) -> bool:
    """Eine erbrachte Leistung eintragen. Doppelte werden still verschluckt.

    Kein commit: der Aufrufer speichert ohnehin, und ein eigenes commit
    mitten in seiner Transaktion wuerde einen halben Zustand festschreiben.
    """
    if not user_id:
        return False
    schon_da = db.query(Leistung.id).filter(
        Leistung.user_id == user_id, Leistung.art == art,
        Leistung.quelle_id == quelle_id).first()
    if schon_da:
        return False
    db.add(Leistung(user_id=user_id, art=art, quelle_id=quelle_id,
                    titel=(titel or "")[:200], abteilung=abteilung,
                    punkte=max(1, int(punkte)),
                    zeitpunkt=zeitpunkt or utcnow()))
    return True


def widerrufe(db, user_id: int, art: str, quelle_id) -> None:
    """Eine Leistung zuruecknehmen - nur fuer echte Irrtuemer.

    Gebraucht wird das, wenn eine Aufgabe versehentlich auf "erledigt" stand
    und wieder geoeffnet wird. Das Loeschen einer erledigten Aufgabe fuehrt
    ausdruecklich NICHT hierher - das ist der ganze Punkt.
    """
    db.query(Leistung).filter(
        Leistung.user_id == user_id, Leistung.art == art,
        Leistung.quelle_id == quelle_id).delete(synchronize_session=False)


def aufgabe_erledigt(db, task: Task) -> None:
    """Wird gerufen, sobald eine Aufgabe auf „erledigt“ geht."""
    if not task or not task.assignee_id:
        return
    # Puenktlichkeit steckt in den Punkten: vor der Frist gibt es mehr.
    punkte = 1
    if task.deadline and task.completed_at:
        if task.completed_at.date() <= task.deadline:
            punkte = 2
    if task.priority == "hoch":
        punkte += 1
    vermerke(db, task.assignee_id, "aufgabe", task.id, task.titel, punkte,
             task.task_department, task.completed_at)


def aufgabe_wieder_offen(db, task: Task) -> None:
    if task and task.assignee_id:
        widerrufe(db, task.assignee_id, "aufgabe", task.id)


def anwesenheit_erfasst(db, eintrag: Attendance) -> None:
    from datetime import datetime
    zeit = (datetime.combine(eintrag.event_date, datetime.min.time())
            if eintrag.event_date else eintrag.created_at)
    vermerke(db, eintrag.user_id, "anwesenheit", eintrag.id,
             eintrag.event_type, 1, None, zeit)


#  Zu- und Absagen zu Treffen
#  Nur EIN Fall bringt Punkte: zugesagt und dann auch da gewesen.
#
#    2   zugesagt und da gewesen           - Wort gehalten
#    1   zugesagt, Treffen noch nicht rum  - vorlaeufig, bis abgerechnet ist
#    0   zugesagt und nicht da gewesen     - der Eintrag faellt ersatzlos weg
#    0   abgesagt                          - kostet nichts, bringt nichts
#    0   gar nicht geantwortet             - es entsteht nie ein Eintrag
#
#  Warum die Absage nichts bringt, obwohl sie nuetzlich ist: Der Teilwert
#  heisst Anwesenheit. Wer acht Monate lang zuverlaessig absagt, war acht
#  Monate nicht da - ein Wert von 25 waere dafuer eine Falschaussage. Und
#  warum sie nichts kostet: Krank ist krank. Wer fuer Ehrlichkeit bestraft
#  wird, sagt beim naechsten Mal zu und kommt trotzdem nicht.
#
#  Die Ansage zaehlt damit trotzdem, und zwar als Voraussetzung: Ohne Zusage
#  gibt es diese Punkte auch dann nicht, wenn man erscheint. Anwesenheit
#  allein bleibt davon unberuehrt - die hat ihre eigene Zeile.
PUNKTE_WORT_GEHALTEN = 2
PUNKTE_ZUGESAGT = 1


def rueckmeldung_erfasst(db, eintrag: MeetingRueckmeldung) -> None:
    """Vorlaeufige Gutschrift, sobald jemand zusagt.

    Vorlaeufig, weil eine Zusage erst nach dem Treffen etwas wert ist. Sofort
    gutgeschrieben wird sie trotzdem: Ein Wert, der sich erst in zwei Wochen
    ruehrt, wird von niemandem mit der eigenen Handlung in Verbindung
    gebracht - und dann steuert er auch nichts.

    Wer seine Zusage in eine Absage aendert, verliert die Gutschrift wieder.
    """
    if not eintrag or not eintrag.user_id:
        return
    treffen = db.get(Meeting, eintrag.meeting_id)
    widerrufe(db, eintrag.user_id, "rueckmeldung", eintrag.meeting_id)
    if eintrag.antwort != "ja":
        return
    vermerke(db, eintrag.user_id, "rueckmeldung", eintrag.meeting_id,
             (treffen.title if treffen else "AG-Treffen"), PUNKTE_ZUGESAGT,
             None, _zeitpunkt_des_treffens(treffen, eintrag))


def _zeitpunkt_des_treffens(treffen, eintrag):
    """Gezaehlt wird zum Datum des Treffens, nicht zum Klickzeitpunkt.

    Sonst waere eine Zusage, die zwei Wochen vorher abgegeben wurde, im
    Zeitfenster aelter als das Treffen selbst - und eine Nachtragung Monate
    spaeter juenger als alles andere.
    """
    from datetime import datetime
    if treffen and treffen.date:
        return datetime.combine(treffen.date, datetime.min.time())
    return getattr(eintrag, "created_at", None) or utcnow()


def _war_da(db, treffen) -> set:
    """Wer bei diesem Treffen als anwesend eingetragen ist.

    Erst ueber die Verknuepfung, sonst ueber das Datum: Die Anwesenheitsliste
    kann von der Personenseite aus ohne Treffensbezug erfasst worden sein.
    """
    ids = {a.user_id for a in db.query(Attendance).filter(
        Attendance.meeting_id == treffen.id).all()}
    if not ids and treffen.date:
        ids = {a.user_id for a in db.query(Attendance).filter(
            Attendance.event_date == treffen.date).all()}
    return ids


def treffen_abrechnen(heute=None) -> int:
    """Vergangene Treffen einmalig verrechnen. Gibt die Anzahl zurueck.

    Der wichtige Teil ist, was hier NICHT passiert: Ein Treffen, zu dem
    niemand als anwesend eingetragen wurde, wird uebersprungen. Sonst haette
    eine vergessene Anwesenheitsliste zur Folge, dass alle, die zugesagt
    hatten, ihre Punkte verlieren - eine Strafe fuer das Versaeumnis eines
    anderen. Das Treffen bleibt dann offen und wird verrechnet, sobald die
    Liste nachgetragen ist.
    """
    from datetime import date
    heute = heute or date.today()
    verrechnet = 0
    betroffen = set()
    with sitzung() as db:
        offen = db.query(Meeting).filter(
            Meeting.date < heute,
            Meeting.leistung_verrechnet.is_(None)).all()
        for treffen in offen:
            anwesend = _war_da(db, treffen)
            if not anwesend:
                continue
            antworten = db.query(MeetingRueckmeldung).filter(
                MeetingRueckmeldung.meeting_id == treffen.id).all()
            zeit = _zeitpunkt_des_treffens(treffen, None)
            for antwort in antworten:
                widerrufe(db, antwort.user_id, "rueckmeldung", treffen.id)
                if antwort.antwort == "ja" and antwort.user_id in anwesend:
                    vermerke(db, antwort.user_id, "rueckmeldung", treffen.id,
                             treffen.title, PUNKTE_WORT_GEHALTEN, None, zeit)
                betroffen.add(antwort.user_id)
            treffen.leistung_verrechnet = heute
            verrechnet += 1
        db.commit()
    if betroffen:
        anstossen(list(betroffen))
    return verrechnet


def wettbewerb_erfasst(db, teilnahme: CompetitionParticipant) -> None:
    punkte = 1
    if teilnahme.placement:
        punkte = 4 if teilnahme.placement == 1 else (
            3 if teilnahme.placement <= 3 else 2)
    vermerke(db, teilnahme.user_id, "wettbewerb", teilnahme.id,
             teilnahme.team_name or "Teilnahme", punkte, None,
             teilnahme.created_at)


def projekt_mitarbeit(db, mitglied: ProjectTeamMember) -> None:
    leitend = (mitglied.role or "").strip().lower() in ("lead", "leitung", "leiter")
    vermerke(db, mitglied.user_id, "projekt", mitglied.id,
             mitglied.role or "Mitarbeit", 3 if leitend else 1, None,
             mitglied.joined_at)


#  Rechnen
def _teilwert(punkte: float, voll_bei: float) -> int:
    """Punkte in einen Wert von 0 bis 100 umrechnen.

    Bewusst nicht linear bis ins Unendliche: ab ``voll_bei`` ist die Skala
    ausgereizt. Sonst haette der Fleissigste immer 100 und alle anderen
    stuenden im Verhaeltnis dazu schlecht da, egal wie viel sie tun.
    """
    if voll_bei <= 0:
        return 0
    return max(0, min(100, round(punkte / voll_bei * 100)))


def werte_fuer(db, user_id: int) -> dict:
    """Alle Teilwerte einer Person - ohne zu speichern."""
    jetzt = utcnow()
    grenze = jetzt - timedelta(days=FENSTER_TAGE)

    leistungen = db.query(Leistung).filter(
        Leistung.user_id == user_id, Leistung.zeitpunkt >= grenze).all()

    gewichtet = {"aufgabe": 0.0, "anwesenheit": 0.0, "rueckmeldung": 0.0,
                 "wettbewerb": 0.0, "projekt": 0.0}
    for l in leistungen:
        if l.art in gewichtet:
            gewichtet[l.art] += l.punkte * _gewicht_nach_alter(l.zeitpunkt, jetzt)

    # Zuverlaessigkeit: Anteil des Uebernommenen, das auch fertig wurde.
    # Offene Aufgaben ohne Frist zaehlen nicht dagegen - sie sind vielleicht
    # einfach noch nicht dran.
    zugeteilt = db.query(Task).filter(Task.assignee_id == user_id).all()
    faellig = [t for t in zugeteilt
               if t.status == "erledigt" or (t.deadline and t.deadline < jetzt.date())]
    erledigt = [t for t in faellig if t.status == "erledigt"]
    ueberfaellig = [t for t in zugeteilt
                    if t.status != "erledigt" and t.deadline and t.deadline < jetzt.date()]

    if faellig:
        quote = len(erledigt) / len(faellig)
        # Wer nur zwei Aufgaben hatte, hat keine belastbare Quote. Deshalb
        # wird sie zur Mitte hin gezogen, bis genug Daten da sind.
        vertrauen = min(1.0, len(faellig) / 8)
        zuverlaessigkeit = round((quote * vertrauen + 0.5 * (1 - vertrauen)) * 100)
    else:
        # Noch nichts faellig gewesen: die Leistungshistorie entscheidet,
        # nicht eine erfundene Null.
        zuverlaessigkeit = 50 if gewichtet["aufgabe"] else 0
    # Jede ueberfaellige Aufgabe kostet spuerbar - genau darum geht es.
    zuverlaessigkeit = max(0, zuverlaessigkeit - len(ueberfaellig) * 8)

    aufgaben = _teilwert(gewichtet["aufgabe"], 18)
    # Anwesenheit, gehobene Fassung: Wer zusagt und dann auch kommt, steht
    # besser da als wer nur kommt. Gerechnet wird das ueber max() und nicht
    # als eine Summe mit groesserem Nenner - sonst waere der Wert JEDES
    # Mitglieds an dem Tag gesunken, an dem diese Zaehlung eingefuehrt wurde,
    # fuer ein Verhalten, das vorher niemand zeigen konnte. Die Ansage kann
    # den Wert also heben, nie senken.
    anwesenheit = max(
        _teilwert(gewichtet["anwesenheit"], 14),
        _teilwert(gewichtet["anwesenheit"] + gewichtet["rueckmeldung"], 30))
    wettbewerbe = _teilwert(gewichtet["wettbewerb"], 6)
    projekte = _teilwert(gewichtet["projekt"], 6)

    gesamt = round(
        (zuverlaessigkeit * GEWICHTE["zuverlaessigkeit"]
         + aufgaben * GEWICHTE["aufgaben"]
         + anwesenheit * GEWICHTE["anwesenheit"]
         + projekte * GEWICHTE["projekte"]
         + wettbewerbe * GEWICHTE["wettbewerbe"]) / 100)

    # Initiative: wie viel jemand selbst anstoesst, statt nur Zugeteiltes
    # abzuarbeiten. Ein eigener Wert, weil beides verschiedene Staerken sind.
    selbst_erstellt = db.query(Task).filter(
        Task.creator_id == user_id, Task.assignee_id != user_id,
        Task.created_at >= grenze).count()
    projektleitung = db.query(Project).filter(Project.lead_id == user_id).count()
    initiative = _teilwert(selbst_erstellt + projektleitung * 4, 14)

    if gesamt >= SCHWELLE_HOCH:
        stufe = "high"
    elif gesamt >= SCHWELLE_AUFSTREBEND:
        stufe = "emerging"
    else:
        stufe = "developing"

    return {
        "zuverlaessigkeit": zuverlaessigkeit,
        "aufgaben": aufgaben,
        "anwesenheit": anwesenheit,
        "wettbewerbe": wettbewerbe,
        "projekte": projekte,
        "initiative": initiative,
        "gesamt": gesamt,
        "stufe": stufe,
        "erledigt_gesamt": db.query(Leistung).filter(
            Leistung.user_id == user_id, Leistung.art == "aufgabe").count(),
        "ueberfaellig": len(ueberfaellig),
    }


def _empfehlungen(w: dict) -> str:
    """Wofuer sich jemand anbietet - als Komma-Liste wie in V1."""
    vor = []
    if w["gesamt"] >= SCHWELLE_HOCH and w["initiative"] >= 55:
        vor.append("board_member")
    if w["projekte"] >= 55 or w["initiative"] >= 60:
        vor.append("project_lead")
    if w["zuverlaessigkeit"] >= 80 and w["aufgaben"] >= 55:
        vor.append("coo")
    if w["anwesenheit"] >= 70 and w["gesamt"] >= SCHWELLE_AUFSTREBEND:
        vor.append("area_lead")
    if w["gesamt"] >= 85:
        vor.append("president")
    return ",".join(vor)


def speichere(db, user_id: int) -> LeadershipScore:
    """Werte neu rechnen und ablegen. Ohne commit.

    Die Zeile wird notfalls angelegt - und zwar so, dass zwei gleichzeitige
    Laeufe sich nicht ins Gehege kommen. Genau das passierte vorher: Wer zwei
    Aufgaben kurz hintereinander abhakt, stoesst zwei Hintergrundlaeufe an,
    beide finden keine Zeile, beide legen eine an, und der zweite scheitert
    an der Eindeutigkeitsregel. Der Wert blieb dann stehen.
    """
    from sqlalchemy.exc import IntegrityError

    w = werte_fuer(db, user_id)
    eintrag = db.query(LeadershipScore).filter(
        LeadershipScore.user_id == user_id).first()
    if not eintrag:
        eintrag = LeadershipScore(user_id=user_id)
        db.add(eintrag)
        try:
            db.flush()
        except IntegrityError:
            # Der andere Lauf war schneller - dann nehmen wir seine Zeile.
            db.rollback()
            eintrag = db.query(LeadershipScore).filter(
                LeadershipScore.user_id == user_id).first()
            if eintrag is None:                              # pragma: no cover
                raise
    # Die Spaltennamen stammen aus V1 und bleiben, damit bestehende Zeilen
    # weiterbenutzt werden koennen.
    eintrag.attendance_score = w["anwesenheit"]
    eintrag.task_completion_score = w["aufgaben"]
    eintrag.competition_score = w["wettbewerbe"]
    eintrag.project_activity_score = w["projekte"]
    eintrag.zuverlaessigkeit = w["zuverlaessigkeit"]
    eintrag.initiative = w["initiative"]
    eintrag.gesamt = w["gesamt"]
    eintrag.leadership_potential = w["stufe"]
    eintrag.recommended_for = _empfehlungen(w) or None
    eintrag.last_updated = utcnow()
    return eintrag


def alle_neu_rechnen() -> int:
    """Vollabgleich fuer alle aktiven Konten. Gibt die Anzahl zurueck."""
    with sitzung() as db:
        personen = db.query(User).filter(User.status == "aktiv").all()
        for person in personen:
            speichere(db, person.id)
        db.commit()
        return len(personen)


def anstossen(user_ids) -> None:
    """Werte im Hintergrund neu rechnen.

    Von den Routen aus aufzurufen, nachdem etwas passiert ist. Der Aufruf
    kehrt sofort zurueck - niemand wartet beim Abhaken einer Aufgabe darauf,
    dass ein Score fertig gerechnet ist.
    """
    ids = [i for i in (user_ids if isinstance(user_ids, (list, tuple, set))
                       else [user_ids]) if i]
    if not ids:
        return

    def arbeit():
        # Zwei Anlaeufe: Bei zwei gleichzeitigen Ereignissen kann SQLite die
        # Schreibsperre kurz verweigern. Ein zweiter Versuch nach einem
        # Augenblick genuegt dann - der Wert wuerde sonst veralten.
        for versuch in range(2):
            try:
                with sitzung() as db:
                    for user_id in ids:
                        speichere(db, user_id)
                    db.commit()
                return
            except Exception as problem:                     # pragma: no cover
                if versuch == 0:
                    time.sleep(0.4)
                    continue
                print(f"[Leistung] Neuberechnung fehlgeschlagen: {problem}")

    threading.Thread(target=arbeit, daemon=True, name="leistung").start()


#  Auswertung fuers Dashboard
def rangliste(db, nur_aktive: bool = True) -> list:
    """Alle Personen mit ihren Werten, der Beste zuerst."""
    abfrage = db.query(User)
    if nur_aktive:
        abfrage = abfrage.filter(User.status == "aktiv")
    personen = abfrage.all()
    stand = {s.user_id: s for s in db.query(LeadershipScore).all()}
    zeilen = []
    for person in personen:
        eintrag = stand.get(person.id)
        if not eintrag:
            eintrag = speichere(db, person.id)
            db.commit()
        zeilen.append({
            "person": person,
            "score": eintrag,
            "gesamt": eintrag.gesamt or 0,
            "empfehlungen": [e for e in (eintrag.recommended_for or "").split(",") if e],
        })
    zeilen.sort(key=lambda z: z["gesamt"], reverse=True)
    return zeilen


def verlauf(db, user_id: int, monate: int = 6) -> list:
    """Erledigte Leistungen je Monat - fuer das kleine Diagramm im Profil."""
    from collections import OrderedDict
    from datetime import date
    heute = utcnow().date()
    kaesten = OrderedDict()
    jahr, monat = heute.year, heute.month
    for _ in range(monate):
        kaesten[(jahr, monat)] = 0
        monat -= 1
        if monat == 0:
            monat, jahr = 12, jahr - 1
    grenze = date(jahr, monat if monat else 1, 1)
    for l in db.query(Leistung).filter(
            Leistung.user_id == user_id,
            Leistung.zeitpunkt >= utcnow() - timedelta(days=monate * 31)).all():
        schluessel = (l.zeitpunkt.year, l.zeitpunkt.month)
        if schluessel in kaesten:
            kaesten[schluessel] += l.punkte
    from kern.text import MONATE
    return [(MONATE[m - 1][:3], wert) for (j, m), wert in reversed(kaesten.items())]


EMPFEHLUNG_LABELS = {
    "board_member": "Vorstandsposten",
    "project_lead": "Projektleitung",
    "president": "Vorsitz",
    "coo": "Operatives",
    "area_lead": "Abteilungsleitung",
}
