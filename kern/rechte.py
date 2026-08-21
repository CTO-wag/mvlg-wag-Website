"""Rollen, Abteilungen und Rechte.

Die Rechtespalten werden aus FEATURE_PERMS an Role und Department
angehaengt, nicht von Hand aufgezaehlt. Eine zweite, handgepflegte Liste
war in V1 der Grund, warum das Anlegen einer Rolle zeitweise abbrach.
"""

import json
import threading

from sqlalchemy import Column, Integer

from kern.datenbank import SessionLocal
from kern.modelle import Department, Role, User, UserPermission

#  Alle einzeln schaltbaren Funktionen
#  (Schluessel, Anzeigename, Erklaerung). Die Erklaerung ist neu: in V1 stand
#  in der Rollenverwaltung nur "Accounts – Profildaten bearbeiten", und was das
#  genau erlaubt, wusste nur, wer den Quelltext kannte.
FEATURE_PERMS = (
    ("accounts_all", "Accounts verwalten",
     "Konten anlegen, Rolle, Abteilung und Status ändern, Passwörter setzen."),
    ("accounts_full_edit", "Accounts – Profildaten bearbeiten",
     "Name, E-Mail und Telefonnummer anderer Personen ändern."),
    ("bewerbungen", "Bewerbungen",
     "Bewerbungen lesen, annehmen, ablehnen und löschen."),
    ("aufgaben_all", "Aufgaben",
     "Aufgaben für andere anlegen und die Aufgaben der eigenen Abteilung führen."),
    ("aufgaben_alle_abteilungen", "Aufgaben – alle Abteilungen",
     "Über die eigene Abteilung hinaus in alle Abteilungen sehen."),
    ("rollen", "Rollen & Rechte",
     "Rollen anlegen, Rechte vergeben, Abteilungen pflegen."),
    ("rechte_personen", "Rechte einzelner Personen",
     "Einer einzelnen Person ein Recht zusätzlich geben oder entziehen."),
    ("datenbank", "Datenbank",
     "Rohdaten aller Tabellen einsehen."),
    ("aktivitaetslog_loeschen", "Datenbank – Protokoll löschen",
     "Das Aktivitätsprotokoll leeren."),
    ("mitglieder_view", "Mitgliederliste",
     "Die Liste aller Mitglieder mit Kontaktdaten sehen."),
    ("meetings_manage", "AG-Treffen",
     "Treffen anlegen, ändern und löschen, Protokolle schreiben und die "
     "Tagesordnung abhaken. Ohne dieses Recht kann man zu- und absagen und "
     "eigene Punkte eintragen - mehr nicht."),
    ("statistiken", "Statistiken",
     "Auswertungen über Aufgaben, Mitglieder und Bewerbungen."),
    ("nachrichten", "Nachrichten",
     "Das gemeinsame Postfach und die Kontaktanfragen der Website."),
    ("benachrichtigungen_admin", "Nachrichten an alle",
     "Rundnachrichten verschicken und die Zustellwege anderer einsehen."),
    ("support_verwaltung", "Support verwalten",
     "Alle Support-Anfragen sehen und beantworten."),
    ("attendance", "Anwesenheit",
     "Anwesenheit erfassen und auswerten."),
    ("competitions", "Wettbewerbe",
     "Wettbewerbe anlegen und Teilnahmen pflegen."),
    ("projects", "Projekte",
     "Projekte anlegen, Teams zusammenstellen, Fortschritt pflegen."),
    ("leadership", "Leadership-Werte",
     "Die automatisch errechneten Werte aller Mitglieder einsehen."),
    ("leadership_manage", "Leadership – Nachfolgeplanung",
     "Empfehlungen aussprechen und Nachfolgekandidaten festhalten."),
    ("email_vorlagen", "E-Mail-Vordrucke",
     "Betreff und Text der automatischen Mails ändern, Testmodus schalten."),
    ("whatsapp_bot", "WhatsApp-Bot",
     "Willkommenstext ändern und den Ausgangskorb verwalten."),
    ("seiteninhalte", "Startseite bearbeiten",
     "Die Sektion „Unsere Arbeit“ und andere Blöcke der Startseite pflegen."),
    ("kalender_verwalten", "Kalender",
     "Termine für andere oder für alle eintragen."),
    ("redaktion", "Redaktionsplan – alle Abteilungen",
     "Sonderfall: der Plan gehört normalerweise der Abteilung."),
    ("finanzen", "Kassenbuch – einsehen",
     "Kassenstand, Buchungen und Budgets ansehen."),
    ("finanzen_verwalten", "Kassenbuch – buchen",
     "Buchungen anlegen und stornieren, Budgets und Daueraufträge pflegen."),
    ("sicherheit", "Sicherheitsübersicht",
     "Anmeldeprotokoll, aktive Sitzungen aller Konten, Sicherungen."),
)
PERM_KEYS = tuple(k for k, _, _ in FEATURE_PERMS)
PERM_LABELS = {k: la for k, la, _ in FEATURE_PERMS}
PERM_HILFE = {k: h for k, _, h in FEATURE_PERMS}

# Funktionen, die an der ABTEILUNG haengen statt an der Rolle. Rollen gelten
# abteilungsuebergreifend - ueber sie laesst sich nicht sagen "Marketing darf
# den Redaktionsplan, Tech nicht".
DEPT_FEATURES = (
    ("redaktionsplan", "Redaktionsplan",
     "Beiträge mit Datum, Kanal und Verantwortlichem planen."),
    ("ideensammlung", "Ideensammlung",
     "Ideen ohne Datum sammeln. Ein Datum macht daraus einen Planeintrag."),
    ("bewerbungen_abteilung", "Bewerbungen sichten",
     "Alle Bewerbungen lesen und einschätzen. Entscheiden bleibt beim Vorstand."),
)
DEPT_FEATURE_KEYS = tuple(k for k, _, _ in DEPT_FEATURES)
DEPT_PERM_KEYS = DEPT_FEATURE_KEYS + PERM_KEYS

# Rechte, die der Rolle CTO nicht entzogen werden koennen. Bewusst wenige: es
# geht allein darum, sich aus einer Fehlkonfiguration wieder befreien zu
# koennen. Wer Rollenverwaltung und Kontenzugriff verliert, kommt an keines
# von beiden mehr heran.
CTO_KERNRECHTE = ("rollen", "accounts_all", "accounts_full_edit", "rechte_personen")

# Rechte nach Themen - 28 Kaestchen in einer Reihe liest niemand.
PERM_GRUPPEN_ROH = (
    ("Personen", ("accounts_all", "accounts_full_edit", "rechte_personen",
                  "bewerbungen", "mitglieder_view", "rollen")),
    ("Arbeit & Termine", ("aufgaben_all", "aufgaben_alle_abteilungen",
                          "meetings_manage", "kalender_verwalten", "attendance")),
    ("Kommunikation", ("nachrichten", "benachrichtigungen_admin",
                       "support_verwaltung", "email_vorlagen", "whatsapp_bot")),
    ("Programm", ("competitions", "projects", "leadership", "leadership_manage",
                  "redaktion")),
    ("Kasse", ("finanzen", "finanzen_verwalten")),
    ("System", ("datenbank", "aktivitaetslog_loeschen", "statistiken",
                "seiteninhalte", "sicherheit")),
)


def perm_gruppen():
    """Rechte nach Themen. Was in keiner Gruppe steht, landet unter „Weitere“ -
    ein neu hinzugefuegtes Recht darf nie unsichtbar bleiben."""
    vergeben = set()
    gruppen = []
    for name, keys in PERM_GRUPPEN_ROH:
        eintraege = [(k, PERM_LABELS[k], PERM_HILFE[k]) for k in keys if k in PERM_LABELS]
        vergeben.update(k for k, _, _ in eintraege)
        if eintraege:
            gruppen.append((name, eintraege))
    rest = [(k, PERM_LABELS[k], PERM_HILFE[k]) for k in PERM_KEYS if k not in vergeben]
    if rest:
        gruppen.append(("Weitere", rest))
    return gruppen


#  Rechtespalten an Role und Department haengen
#  Bewusst hier und nicht von Hand in modelle.py: eine zweite, handgepflegte
#  Liste laeuft frueher oder spaeter auseinander.
for _perm in PERM_KEYS:
    if not hasattr(Role, _perm):
        setattr(Role, _perm, Column(Integer, nullable=False, default=0))
    if not hasattr(Department, _perm):
        setattr(Department, _perm, Column(Integer, nullable=False, default=0))
del _perm


#  Vorbelegung
DEFAULT_ROLES = ("cto", "ceo", "coo", "cro", "cmo", "member")
CORE_ROLES = ("cto", "ceo", "coo")
ROLE_RANG = {"cto": 100, "ceo": 90, "coo": 80, "cro": 60, "cmo": 60, "member": 10}

_VOLL = {k: True for k in PERM_KEYS}


def _rolle(*aktiv):
    """Kurzschreibweise: nur die genannten Rechte sind an."""
    return {k: (k in aktiv) for k in PERM_KEYS}


PERMISSIONS = {
    # Der CTO bekommt bei einer frischen Anlage alles. Das ist die Rolle, die
    # das System einrichtet - fehlt ihr ein Recht, kann sie es sich zwar
    # selbst geben, muss aber erst darauf kommen. In einer bestehenden
    # Datenbank aendert das nichts: die Migration ueberschreibt gesetzte
    # Rechte nie, sie ergaenzt nur fehlende Spalten.
    "cto": _VOLL,
    "ceo": _rolle("bewerbungen", "aufgaben_all", "rollen", "mitglieder_view",
                  "meetings_manage", "nachrichten", "attendance", "competitions",
                  "projects", "leadership", "kalender_verwalten", "finanzen",
                  "finanzen_verwalten", "seiteninhalte"),
    "coo": _rolle("bewerbungen", "aufgaben_all", "rollen", "mitglieder_view",
                  "meetings_manage", "nachrichten", "attendance", "competitions",
                  "projects", "leadership", "kalender_verwalten", "finanzen"),
    "cro": _rolle("bewerbungen", "aufgaben_all", "meetings_manage", "nachrichten",
                  "finanzen"),
    "cmo": _rolle("aufgaben_all", "meetings_manage", "nachrichten", "finanzen",
                  "seiteninhalte"),
    "member": _rolle(),
}

ROLE_PRESETS = {
    "vollzugriff": dict(_VOLL),
    "abteilungsleiter": dict(PERMISSIONS["ceo"]),
    "nur_lesen": _rolle("datenbank", "mitglieder_view", "statistiken",
                        "nachrichten", "attendance", "competitions", "projects",
                        "leadership", "finanzen"),
    "zuruecksetzen": _rolle(),
}
ROLE_PRESET_LABELS = {
    "vollzugriff": "Vollzugriff", "abteilungsleiter": "Abteilungsleiter",
    "nur_lesen": "Nur lesen", "zuruecksetzen": "Alles aus",
}
ROLE_PRESETS_JSON = json.dumps(ROLE_PRESETS)

DEPARTMENT_DEFAULTS = (
    ("exekutive", "Exekutive", "#4A5568",
     "Vorstand und abteilungsübergreifende Aufgaben.", 10, 1, ()),
    ("tech", "Tech", "#2B6CB0",
     "Website, Dashboard und alles Technische.", 20, 0, ()),
    ("marketing", "Marketing", "#B83280",
     "Auftritt der AG, Social Media, Aushänge.", 30, 0,
     ("redaktionsplan", "ideensammlung")),
    ("recruitment", "Recruitment", "#B7791F",
     "Bewerbungen sichten und neue Mitglieder aufnehmen.", 40, 0,
     ("bewerbungen_abteilung",)),
)

ROLE_DEPARTMENT_SUGGESTION = {
    "cto": "tech", "ceo": "exekutive", "coo": "exekutive",
    "cro": "recruitment", "cmo": "marketing",
}
ROLE_DEPT_SUGGESTION_JSON = json.dumps(ROLE_DEPARTMENT_SUGGESTION)

LABELS = {
    "cto": "CTO", "ceo": "CEO", "coo": "COO", "cro": "CRO", "cmo": "CMO",
    "member": "Mitglied",
    "tech": "Tech", "marketing": "Marketing", "recruitment": "Recruitment",
    "exekutive": "Exekutive",
    "aktiv": "Aktiv", "inaktiv": "Inaktiv",
    "neu": "Neu", "in_pruefung": "In Prüfung", "angenommen": "Angenommen",
    "abgelehnt": "Abgelehnt",
    "offen": "Offen", "in_bearbeitung": "In Bearbeitung", "erledigt": "Erledigt",
    "beantwortet": "Beantwortet", "geschlossen": "Geschlossen",
    "niedrig": "Niedrig", "mittel": "Mittel", "hoch": "Hoch",
    "instagram": "Instagram", "aushang": "Aushang", "website": "Website",
    "newsletter": "Newsletter", "sonstiges": "Sonstiges",
    "idee": "Idee", "geplant": "Geplant", "in_arbeit": "In Arbeit",
    "veroeffentlicht": "Veröffentlicht",
    "planung": "Planung", "laufend": "Laufend", "abgeschlossen": "Abgeschlossen",
    "developing": "In Entwicklung", "emerging": "Aufstrebend", "high": "Hoch",
    "mitgliedsbeitrag": "Mitgliedsbeiträge", "sponsoring": "Sponsoring & Spenden",
    "verkauf": "Verkauf & Aktionen", "material": "Material & Druck",
    "veranstaltung": "Veranstaltungen", "fahrtkosten": "Fahrtkosten",
    "monatlich": "Monatlich", "quartalsweise": "Alle 3 Monate",
    "halbjaehrlich": "Halbjährlich", "jaehrlich": "Jährlich",
}


def label(wert) -> str:
    return LABELS.get(wert, wert if wert else "")


#  Zwischenspeicher
#  Rollen und Abteilungen werden bei jedem Seitenaufbau dutzendfach gebraucht,
#  aber selten geaendert. Beides liegt deshalb im Speicher und wird bei jeder
#  Aenderung verworfen. Die Sperre ist noetig, weil zwei Serverprozesse mit
#  mehreren Threads darauf zugreifen.
_sperre = threading.Lock()
_rollen_cache = None
_abteilungen_cache = None


def cache_verwerfen() -> None:
    global _rollen_cache, _abteilungen_cache
    with _sperre:
        _rollen_cache = None
        _abteilungen_cache = None


def rollen(nur_cache: bool = False) -> dict:
    """Alle Rollen als {key: {"label":..., "rang":..., "protected":..., perms}}."""
    global _rollen_cache
    if _rollen_cache is None:
        if nur_cache:
            return {}
        db = SessionLocal()
        try:
            daten = {}
            for r in db.query(Role).order_by(Role.rang.desc(), Role.key).all():
                eintrag = {k: bool(getattr(r, k, 0)) for k in PERM_KEYS}
                eintrag.update({"label": r.label, "rang": r.rang or 0,
                                "protected": bool(r.protected),
                                "beschreibung": r.beschreibung or ""})
                daten[r.key] = eintrag
                LABELS[r.key] = r.label
            if "member" not in daten:
                daten["member"] = dict(PERMISSIONS["member"],
                                       label="Mitglied", rang=10,
                                       protected=False, beschreibung="")
            with _sperre:
                _rollen_cache = daten
        except Exception:
            # Vor der ersten Migration gibt es die Tabelle noch nicht.
            return {k: dict(v, label=LABELS.get(k, k), rang=ROLE_RANG.get(k, 10),
                            protected=k in CORE_ROLES, beschreibung="")
                    for k, v in PERMISSIONS.items()}
        finally:
            db.close()
    return _rollen_cache


def abteilungen(nur_aktive: bool = True) -> list:
    """Alle Abteilungen als einfache dicts (keine ORM-Objekte - die waeren nach
    dem Schliessen der Sitzung unbrauchbar)."""
    global _abteilungen_cache
    if _abteilungen_cache is None:
        db = SessionLocal()
        try:
            _abteilungen_cache = [
                dict({"key": d.key, "label": d.label, "farbe": d.farbe,
                      "beschreibung": d.beschreibung or "",
                      "aktiv": bool(d.aktiv), "geschuetzt": bool(d.geschuetzt),
                      "reihenfolge": d.reihenfolge},
                     **{fk: bool(getattr(d, fk, 0)) for fk in DEPT_PERM_KEYS})
                for d in db.query(Department)
                            .order_by(Department.reihenfolge, Department.key).all()
            ]
            for a in _abteilungen_cache:
                LABELS[a["key"]] = a["label"]
        except Exception:
            return [dict({"key": k, "label": la, "farbe": f, "beschreibung": b,
                          "aktiv": True, "geschuetzt": bool(g), "reihenfolge": r},
                         **{fk: fk in funk for fk in DEPT_PERM_KEYS})
                    for k, la, f, b, r, g, funk in DEPARTMENT_DEFAULTS]
        finally:
            db.close()
    if nur_aktive:
        return [a for a in _abteilungen_cache if a["aktiv"]]
    return list(_abteilungen_cache)


def abteilungs_keys(nur_aktive: bool = True) -> tuple:
    return tuple(a["key"] for a in abteilungen(nur_aktive))


def abteilung(key: str):
    for a in abteilungen(nur_aktive=False):
        if a["key"] == key:
            return a
    return None


def abteilung_label(key: str) -> str:
    a = abteilung(key)
    return a["label"] if a else LABELS.get(key, key or "")


def abteilung_farbe(key: str) -> str:
    a = abteilung(key)
    return a["farbe"] if a else "#4A5568"


def bewerbbare_abteilungen() -> list:
    """Was im oeffentlichen Bewerbungsformular zur Wahl steht. Geschuetzte
    Abteilungen bleiben aussen vor - in die Exekutive bewirbt man sich nicht."""
    return [a for a in abteilungen() if not a["geschuetzt"]]


def rollen_keys() -> list:
    return list(rollen().keys())


#  Auswertung
def rolle_von(user) -> dict:
    return rollen().get(getattr(user, "role", ""), rollen().get("member", {}))


def rang_von(user) -> int:
    if not user:
        return 0
    return int(rolle_von(user).get("rang", 0) or 0)


def zustaendige_abteilungen(user) -> tuple:
    """Fuer welche Abteilungen jemand zustaendig ist.

    Vorstandsrollen sind immer zusaetzlich fuer die Exekutive zustaendig,
    Mitglieder nur fuer ihre eine Abteilung. Als Vorstandsrolle gilt, wer
    einen Rang oberhalb der Mitgliederschwelle hat - nicht mehr eine feste
    Liste von Rollennamen wie in V1, sonst zaehlt eine neu angelegte Rolle
    nicht mit.
    """
    if not user:
        return ()
    eigene = user.department or "exekutive"
    if rang_von(user) <= ROLE_RANG["member"]:
        return (eigene,)
    if eigene and eigene != "exekutive":
        return ("exekutive", eigene)
    return ("exekutive",)


_persoenliche_rechte_cache = {}


def persoenliche_rechte(db, user_id: int) -> dict:
    """Die Ausnahmen fuer genau diese Person: {perm: True/False}."""
    if not user_id:
        return {}
    zeilen = db.query(UserPermission).filter(
        UserPermission.user_id == user_id).all()
    return {z.perm: bool(z.wert) for z in zeilen if z.perm in PERM_KEYS}


def rechte_von(user, db=None) -> dict:
    """Alle wirksamen Rechte einer Person auf einmal.

    Fuer Stellen, die viele Rechte gleichzeitig brauchen (Navigation, Uebersicht).
    Ohne db werden die persoenlichen Ausnahmen aus dem am Objekt vermerkten
    Zwischenspeicher genommen - den setzt die Anmeldung beim Laden der Person.
    """
    ergebnis = {k: False for k in PERM_KEYS}
    if not user:
        return ergebnis
    rolle = rolle_von(user)
    for k in PERM_KEYS:
        if rolle.get(k):
            ergebnis[k] = True
    meine = set(zustaendige_abteilungen(user))
    for a in abteilungen():
        if a["key"] not in meine:
            continue
        for k in PERM_KEYS:
            if a.get(k):
                ergebnis[k] = True
    # Persoenliche Ausnahmen zuletzt - sie duerfen auch entziehen.
    eigene = getattr(user, "_rechte_ausnahmen", None)
    if eigene is None and db is not None:
        eigene = persoenliche_rechte(db, user.id)
        try:
            user._rechte_ausnahmen = eigene
        except Exception:                                    # pragma: no cover
            pass
    for k, wert in (eigene or {}).items():
        if k in ergebnis:
            ergebnis[k] = bool(wert)
    # Der CTO-Rolle koennen die Kernrechte nicht abhandenkommen - sonst sperrt
    # sich die AG aus ihrer eigenen Verwaltung aus.
    if user.role == "cto":
        for k in CTO_KERNRECHTE:
            ergebnis[k] = True
    return ergebnis


def hat_recht(user, perm: str, db=None) -> bool:
    if not user:
        return False
    return bool(rechte_von(user, db).get(perm, False))


def hat_abteilungsfunktion(user, feature: str) -> bool:
    """True, wenn eine der Abteilungen dieser Person die Funktion freigibt."""
    if not user or feature not in DEPT_PERM_KEYS:
        return False
    meine = set(zustaendige_abteilungen(user))
    return any(a["key"] in meine and a.get(feature) for a in abteilungen())


def darf_redaktionsplan(user, db=None) -> bool:
    return hat_recht(user, "redaktion", db) or hat_abteilungsfunktion(user, "redaktionsplan")


def darf_ideensammlung(user, db=None) -> bool:
    return hat_recht(user, "redaktion", db) or hat_abteilungsfunktion(user, "ideensammlung")


def darf_bewerbungen(user, db=None) -> bool:
    return hat_recht(user, "bewerbungen", db) or hat_abteilungsfunktion(user, "bewerbungen_abteilung")


def darf_person_bearbeiten(handelnder, ziel) -> bool:
    """Rangregel: eigenen Rang oder darunter, sich selbst immer.

    Damit kann jemand mit dem Recht "Accounts" nicht mehr den CTO umstellen.
    In V1 fehlte diese Schranke - das Recht galt fuer alle Konten gleich.
    """
    if not handelnder or not ziel:
        return False
    if handelnder.id == ziel.id:
        return True
    return rang_von(handelnder) >= rang_von(ziel)


def redaktions_abteilungen(user, db=None) -> list:
    if hat_recht(user, "redaktion", db):
        return abteilungen()
    meine = set(zustaendige_abteilungen(user))
    return [a for a in abteilungen()
            if a["key"] in meine and (a.get("redaktionsplan") or a.get("ideensammlung"))]


def personen_mit_recht(db, perm: str) -> list:
    """Alle aktiven Konten, die dieses Recht gerade besitzen.

    Fuer Benachrichtigungen an eine frei definierbare Gruppe ("wer Support
    verwaltet") statt an eine fest verdrahtete Rolle.
    """
    kandidaten = db.query(User).filter(User.status == "aktiv").all()
    ausnahmen = {}
    for z in db.query(UserPermission).filter(UserPermission.perm == perm).all():
        ausnahmen[z.user_id] = bool(z.wert)
    treffer = []
    for u in kandidaten:
        if u.id in ausnahmen:
            if ausnahmen[u.id]:
                treffer.append(u)
            continue
        if rolle_von(u).get(perm) or hat_abteilungsfunktion(u, perm):
            treffer.append(u)
    return treffer


#  Vorbelegung anlegen
def rollen_anlegen() -> None:
    """Standardrollen ergaenzen, vorhandene nicht ueberschreiben.

    Nur der Rang und der Schutz werden nachgezogen: beides ist neu in V2, und
    eine bestehende Datenbank haette dort sonst ueberall 0 stehen - womit
    niemand mehr irgendwen bearbeiten koennte.
    """
    db = SessionLocal()
    try:
        for key in DEFAULT_ROLES:
            vorhanden = db.get(Role, key)
            if vorhanden:
                if not vorhanden.rang:
                    vorhanden.rang = ROLE_RANG.get(key, 10)
                if key in CORE_ROLES:
                    vorhanden.protected = 1
                continue
            db.add(Role(
                key=key, label=LABELS.get(key, key),
                protected=1 if key in CORE_ROLES else 0,
                rang=ROLE_RANG.get(key, 10),
                **{p: int(PERMISSIONS[key].get(p, False)) for p in PERM_KEYS},
            ))
        # Rollen, die jemand selbst angelegt hat, brauchen auch einen Rang.
        for r in db.query(Role).filter((Role.rang == 0) | (Role.rang.is_(None))).all():
            r.rang = ROLE_RANG.get(r.key, 20)
        db.commit()
    finally:
        db.close()
    cache_verwerfen()


def abteilungen_anlegen() -> None:
    db = SessionLocal()
    try:
        vorhanden = {d.key for d in db.query(Department).all()}
        for key, la, farbe, besch, reihe, gesch, funk in DEPARTMENT_DEFAULTS:
            if key in vorhanden:
                continue
            neu = Department(key=key, label=la, farbe=farbe, beschreibung=besch,
                             reihenfolge=reihe, geschuetzt=gesch)
            for fk in DEPT_PERM_KEYS:
                setattr(neu, fk, 1 if fk in funk else 0)
            db.add(neu)
        db.commit()
    finally:
        db.close()
    cache_verwerfen()
