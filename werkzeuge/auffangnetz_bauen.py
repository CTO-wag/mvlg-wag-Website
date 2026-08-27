"""Baut cloudflare/eingebettet.js - alles, was die Notfassung mitbringen muss.

Warum es diese Datei gibt
-------------------------
Das Auffangnetz (cloudflare/worker.js) soll aussehen wie die echte Startseite.
Es steht aber am Rand des Netzes und laeuft genau dann, wenn der Server nicht
antwortet - es kann sich also kein Stylesheet, keine Schrift und kein Bild
holen. Alles muss in der Worker-Datei stehen.

Von Hand gepflegt liefe das nach dem zweiten Feinschliff an der Seite
auseinander: Die echte Seite waere neu, die Notfassung noch die von vorletztem
Jahr - und ausgerechnet in dem Moment sichtbar, in dem man es am wenigsten
gebrauchen kann. Deshalb wird der eingebettete Teil erzeugt, nicht getippt.

    python werkzeuge/auffangnetz_bauen.py

Danach ausrollen:

    cd cloudflare && npx wrangler deploy

Was hier eingesammelt wird
--------------------------
* statisch/stil/basis.css und website.css - eins zu eins, unveraendert.
* Die Schriften als data:-Adressen. Nur "latin", nicht "latin-ext": Deutsche
  Umlaute stehen in latin, und latin-ext waere noch einmal so viel.
* Wappen, Logo und Favicon.
* Das Quiz - Fragen und Auswertung. Es rechnet ohnehin im Browser; ohne
  Server fehlt ihm also nichts, und die Notfassung kommt ohne Luecke aus.
* Die vier pflegbaren Bloecke der Startseite (Vorteile, Stufen, Aktivitaeten,
  Portfolio) aus der Datenbank - wenn eine erreichbar ist. Sonst bleibt der
  Stand aus der vorhandenen eingebettet.js erhalten; erst wenn es auch den
  nicht gibt, greifen die Vorgaben unten.

Der Aufbau der Seite steht NICHT hier, sondern in worker.js. Diese Datei
liefert nur die Zutaten - so bleibt lesbar, was das Auffangnetz tut.
"""

import base64
import json
import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
PROGRAMM = os.path.dirname(HIER)
sys.path.insert(0, PROGRAMM)

# Muss VOR jedem Import aus kern/ passieren: kern/einstellungen.py liest die
# Umgebung beim Import, danach kommt nichts mehr an. Ohne diese Zeile liefe
# das Bauen auf einer leeren SQLite-Datei statt auf der Datenbank, in der die
# gepflegten Startseiten-Bloecke wirklich stehen - und die Notfassung zeigte
# die Vorgabetexte.
from kern.konfig import einlesen as _konfig_einlesen        # noqa: E402
KONFIG_QUELLE = _konfig_einlesen()

STATISCH = os.path.join(PROGRAMM, "statisch")
ZIEL = os.path.join(PROGRAMM, "cloudflare", "eingebettet.js")

# Nur die Schnitte, die basis.css und website.css wirklich benutzen. Jeder
# weitere waere ein Anhang von rund 60 KB fuer Zeichen, die nie erscheinen.
SCHRIFTEN = [
    ("IBM Plex Sans", 400, "ibm-plex-sans-400-latin.woff2"),
    ("IBM Plex Sans", 500, "ibm-plex-sans-500-latin.woff2"),
    ("IBM Plex Sans", 600, "ibm-plex-sans-600-latin.woff2"),
    ("Space Grotesk", 500, "space-grotesk-500-latin.woff2"),
    ("Space Grotesk", 600, "space-grotesk-600-latin.woff2"),
    ("Space Grotesk", 700, "space-grotesk-700-latin.woff2"),
    ("IBM Plex Mono", 400, "ibm-plex-mono-400-latin.woff2"),
]

STILDATEIEN = ["stil/basis.css", "stil/website.css"]

BILDER = {
    "WAPPEN": ("bilder/wappen.webp", "image/webp"),
    "LOGO": ("bilder/logo-klein.webp", "image/webp"),
    "FAVICON": ("bilder/favicon.png", "image/png"),
}

# Fallen zurueck, wenn weder Datenbank noch eine vorhandene eingebettet.js da
# sind. Wortgleich mit dem, was die Migration beim ersten Start eintraegt -
# eine frisch gebaute Notfassung zeigt also dasselbe wie eine frische
# Plattform.
VORGABEN = {
    "vorteile": [
        {"titel": "Wie Märkte, Zinsen und Risiko wirklich zusammenhängen"},
        {"titel": "Ein eigenes Projekt von der Idee bis zur Präsentation"},
        {"titel": "Auftritte bei echten Wettbewerben"},
        {"titel": "Verantwortung, die man dir nicht wieder abnimmt"},
        {"titel": "Leute, die dasselbe interessiert"},
    ],
    "stufen": [
        {"titel": "Mitglied",
         "text": "Du bist dabei, arbeitest mit und lernst, wie die AG "
                 "funktioniert."},
        {"titel": "Eigene Aufgaben",
         "text": "Du übernimmst Dinge, die wirklich jemand braucht – und "
                 "bringst sie zu Ende."},
        {"titel": "Projektleitung",
         "text": "Du führst ein Team durch ein eigenes Projekt."},
        {"titel": "Core-Team",
         "text": "Du entscheidest mit, wohin die AG geht."},
    ],
    "angebot": [],
    "portfolio": [],
}

# Nur der Notnagel: Die echte Liste steht in der Datenbank und wird im
# Dashboard gepflegt - dort ist sie inzwischen laenger als diese hier. Die
# Exekutive fehlt mit Absicht, in die bewirbt man sich nicht.
VORGABE_ABTEILUNGEN = [
    {"key": "tech", "label": "Tech"},
    {"key": "marketing", "label": "Marketing"},
    {"key": "recruitment", "label": "Recruitment"},
]


def _lesen(pfad: str) -> bytes:
    with open(pfad, "rb") as datei:
        return datei.read()


def _als_daten(pfad: str, typ: str) -> str:
    return f"data:{typ};base64," + base64.b64encode(_lesen(pfad)).decode("ascii")


def schriften_css() -> str:
    """@font-face-Regeln mit eingebetteten Schriftdateien."""
    teile = []
    for familie, gewicht, datei in SCHRIFTEN:
        pfad = os.path.join(STATISCH, "schrift", datei)
        if not os.path.exists(pfad):
            print(f"  ! Schrift fehlt, wird uebersprungen: {datei}")
            continue
        adresse = _als_daten(pfad, "font/woff2")
        teile.append(
            "@font-face{font-family:'%s';font-style:normal;font-weight:%d;"
            "font-display:swap;src:url(%s) format('woff2');}"
            % (familie, gewicht, adresse))
    return "\n".join(teile)


def stil_css() -> str:
    """basis.css und website.css hintereinander, unveraendert.

    Kein Zusammenstreichen und kein Entfernen von Kommentaren: Was hier
    ankommt, soll Zeile fuer Zeile das sein, was die echte Seite benutzt.
    Ein Optimierer waere eine zweite Stelle, an der sich das Aussehen
    unterscheiden koennte.
    """
    teile = []
    for name in STILDATEIEN:
        pfad = os.path.join(STATISCH, name)
        teile.append(f"/* --- {name} --- */")
        teile.append(_lesen(pfad).decode("utf-8"))
    return "\n".join(teile)


def abteilungen():
    """Wonach sich im Bewerbungsformular auswaehlen laesst.

    Steht in der Datenbank, nicht im Quelltext. Bis hierher war die Liste im
    Worker von Hand gepflegt - und lag prompt daneben: "Unsicher" gab es im
    echten Formular seit einer Weile, in der Notfassung nie.
    """
    try:
        from kern.rechte import bewerbbare_abteilungen
        return [{"key": a["key"], "label": a["label"]}
                for a in bewerbbare_abteilungen()]
    except Exception as problem:
        print(f"  i Abteilungen nicht lesbar ({type(problem).__name__}).")
        return None


def quiz_fragen():
    """Die Quizfragen - oder None, wenn sich das Modul nicht laden laesst.

    Sie stehen als feste Liste im Quelltext, nicht in der Datenbank. Es reicht
    also, das Modul zu importieren; laeuft dabei etwas schief, bleibt der
    Stand aus der vorhandenen eingebettet.js.
    """
    try:
        from website.routen.oeffentlich import QUIZ_FRAGEN
        return [{"frage": f["frage"], "optionen": list(f["optionen"]),
                 "richtig": f["richtig"]} for f in QUIZ_FRAGEN]
    except Exception as problem:
        print(f"  i Quizfragen nicht lesbar ({type(problem).__name__}).")
        return None


def bloecke_aus_datenbank():
    """Die pflegbaren Startseiten-Bloecke - oder None, wenn keine DB da ist."""
    try:
        from kern import inhalte
        daten = {}
        for bereich in ("vorteile", "stufen", "angebot", "portfolio"):
            daten[bereich] = [
                {k: v for k, v in block.items()
                 if k in ("titel", "text", "farbe", "zeitraum", "ergebnis") and v}
                for block in inhalte.bloecke(bereich)
            ]
        if not daten["vorteile"] and not daten["stufen"]:
            return None
        return daten
    except Exception as problem:
        print(f"  i Keine Datenbank erreichbar ({type(problem).__name__}) - "
              f"Inhalte werden nicht aufgefrischt.")
        return None


def _aus_datei(name: str, klammern: str = "{}"):
    """Ein bereits gebauter Wert aus der vorhandenen eingebettet.js.

    Damit kostet ein Bauen ohne Datenbank nichts: Was diesmal nicht zu holen
    war, bleibt so stehen, wie es war - statt auf die Vorgaben zurueckzufallen
    und die gepflegten Texte still zu verlieren.
    """
    if not os.path.exists(ZIEL):
        return None
    text = _lesen(ZIEL).decode("utf-8")
    auf, zu = klammern
    treffer = re.search(r"export const %s = (\%s.*?\%s);\n" % (name, auf, zu),
                        text, re.S)
    if not treffer:
        return None
    try:
        return json.loads(treffer.group(1))
    except ValueError:
        return None


def bauen() -> None:
    print("Auffangnetz bauen …")
    print(f"  Konfiguration: {KONFIG_QUELLE or 'keine (Umgebung wie sie ist)'}")
    inhalte = (bloecke_aus_datenbank() or _aus_datei("INHALTE") or VORGABEN)
    fragen = quiz_fragen() or _aus_datei("QUIZ_FRAGEN", "[]") or []
    faecher = (abteilungen() or _aus_datei("ABTEILUNGEN", "[]")
               or VORGABE_ABTEILUNGEN)

    stil = stil_css()
    schriften = schriften_css()
    quiz_js = _lesen(os.path.join(STATISCH, "js", "quiz.js")).decode("utf-8")
    bilder = {name: _als_daten(os.path.join(STATISCH, pfad), typ)
              for name, (pfad, typ) in BILDER.items()}

    kopf = (
        "/* ERZEUGT - nicht von Hand aendern.\n"
        " *\n"
        " * Gebaut von werkzeuge/auffangnetz_bauen.py aus statisch/. Aenderungen\n"
        " * hier gehen beim naechsten Lauf verloren; wer das Aussehen der\n"
        " * Notfassung aendern will, aendert die echte Seite und baut neu:\n"
        " *\n"
        " *     python werkzeuge/auffangnetz_bauen.py\n"
        " *\n"
        " * Enthalten sind das Stylesheet der oeffentlichen Seite, die Schriften,\n"
        " * Wappen, Logo, Favicon und die im Dashboard gepflegten Bloecke der\n"
        " * Startseite. Alles als Text, weil ein Worker keine zweite Datei\n"
        " * nachladen kann - der Server, von dem sie kaeme, ist der ausgefallene.\n"
        " */\n\n")

    zeilen = [kopf]
    zeilen.append("export const SCHRIFTEN = " + json.dumps(schriften) + ";\n\n")
    zeilen.append("export const STIL = " + json.dumps(stil) + ";\n\n")
    for name in ("WAPPEN", "LOGO", "FAVICON"):
        zeilen.append(f"export const {name} = "
                      + json.dumps(bilder[name]) + ";\n\n")
    zeilen.append("export const ABTEILUNGEN = "
                  + json.dumps(faecher, ensure_ascii=False, indent=2) + ";\n\n")
    zeilen.append("export const QUIZ_JS = " + json.dumps(quiz_js) + ";\n\n")
    zeilen.append("export const QUIZ_FRAGEN = "
                  + json.dumps(fragen, ensure_ascii=False, indent=2) + ";\n\n")
    zeilen.append("export const INHALTE = "
                  + json.dumps(inhalte, ensure_ascii=False, indent=2) + ";\n")

    text = "".join(zeilen)
    with open(ZIEL, "w", encoding="utf-8", newline="\n") as datei:
        datei.write(text)

    groesse = len(text.encode("utf-8"))
    print(f"  Stylesheet : {len(stil):>9,} Zeichen")
    print(f"  Schriften  : {len(schriften):>9,} Zeichen "
          f"({len(SCHRIFTEN)} Schnitte)")
    for name in ("WAPPEN", "LOGO", "FAVICON"):
        print(f"  {name:<11}: {len(bilder[name]):>9,} Zeichen")
    print(f"  Quiz       : {len(fragen)} Fragen, "
          f"{len(quiz_js):,} Zeichen Auswertung")
    print("  Abteilungen: " + ", ".join(a["label"] for a in faecher))
    print(f"  Inhalte    : " + ", ".join(
        f"{len(v)}× {k}" for k, v in inhalte.items()))
    print(f"  -> {os.path.relpath(ZIEL, PROGRAMM)} "
          f"({groesse / 1024:.0f} KB)")
    if groesse > 900 * 1024:
        print("  ! Ueber 900 KB. Cloudflare nimmt Worker bis 1 MB (nach "
              "Kompression) - vor dem Ausrollen pruefen.")


if __name__ == "__main__":
    bauen()
