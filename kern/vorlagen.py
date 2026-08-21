"""Jinja-Umgebung fuer beide Server.

Anders als in V1 liegen die Vorlagen als echte Dateien im Ordner "vorlagen"
und nicht als Zeichenketten im Quelltext. Damit hat der Editor Syntax-
hervorhebung, ein Fehler in einer Vorlage nennt Datei und Zeile, und niemand
muss mehr durch 6000 Zeilen HTML in einer .py-Datei scrollen.
"""

import json
import os

from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from kern import einstellungen as cfg
from kern.rechte import (
    ROLE_PRESETS_JSON, ROLE_PRESET_LABELS, abteilung_farbe, abteilung_label,
    abteilungen, hat_recht, label, rechte_von, zustaendige_abteilungen,
)
from kern.text import (
    datum_lang, esc, euro, heute_berlin, initialen, kuerzen, nach_berlin,
    prozent, relativ, telefon_anzeige, telefon_normal,
)

umgebung = Environment(
    loader=FileSystemLoader(cfg.VORLAGEN_DIR),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
    auto_reload=not cfg.IST_PRODUKTION,
)


def abteilungs_marken(user) -> Markup:
    """Die farbigen Abteilungs-Abzeichen hinter einem Namen."""
    teile = []
    for key in zustaendige_abteilungen(user):
        teile.append(
            f'<span class="marke abteilung" style="--marke:{esc(abteilung_farbe(key))}">'
            f'{esc(abteilung_label(key))}</span>')
    return Markup("".join(teile))


def abteilungs_marke(key: str) -> Markup:
    if not key:
        return Markup("")
    return Markup(
        f'<span class="marke abteilung" style="--marke:{esc(abteilung_farbe(key))}">'
        f'{esc(abteilung_label(key))}</span>')


umgebung.filters.update({
    "label": label,
    "berlin": nach_berlin,
    "relativ": relativ,
    "euro": euro,
    "kuerzen": kuerzen,
    "datum_lang": datum_lang,
    "abt_marken": abteilungs_marken,
    "abt_marke": abteilungs_marke,
    "initialen": lambda u: initialen(getattr(u, "vorname", ""), getattr(u, "nachname", "")),
    # Auch aeltere Eintraege sollen lesbar dastehen: "1636177263" wird zu
    # "+49 163 6177263", ohne dass die Datenbank angefasst wird.
    "telefon": telefon_anzeige,
    "telefon_link": lambda w: "tel:+" + telefon_normal(w) if w else "",
})
umgebung.globals.update({
    "hat_recht": hat_recht,
    "rechte_von": rechte_von,
    "abteilungen": abteilungen,
    "abteilung_label": abteilung_label,
    "abteilung_farbe": abteilung_farbe,
    "prozent": prozent,
    "heute": heute_berlin,
    "ROLLEN_VORLAGEN": ROLE_PRESET_LABELS,
    "ROLLEN_VORLAGEN_JSON": ROLE_PRESETS_JSON,
    "SITE_URL": cfg.SITE_URL,
    "WEBSITE_URL": cfg.WEBSITE_URL,
    "DASHBOARD_URL": cfg.DASHBOARD_URL,
    # Laufen beide unter derselben Adresse? Davon haengt ab, ob Push einmal
    # oder zweimal angemeldet werden muss.
    "gleicher_ursprung": cfg.GLEICHER_URSPRUNG,
    "WHATSAPP_GRUPPE": cfg.WHATSAPP_GRUPPE,
    "DISCORD_EINLADUNG": cfg.DISCORD_EINLADUNG,
    "json_dump": lambda wert: Markup(json.dumps(wert, ensure_ascii=False)),
})


#  Stylesheet-Fassungen
#  Im Dateinamen steckt eine Pruefsumme des Inhalts: aendert sich das CSS,
#  aendert sich die Adresse und der Browser holt es neu - solange es gleich
#  bleibt, fragt er gar nicht erst nach. Deshalb darf die Aufbewahrungsdauer
#  auf ein Jahr stehen.
def _fingerabdruck(pfad: str) -> str:
    import hashlib
    try:
        with open(pfad, "rb") as datei:
            return hashlib.sha256(datei.read()).hexdigest()[:10]
    except OSError:
        return "0"


_ABDRUECKE = {}          # Pfad -> (Aenderungszeit, Groesse, Pruefsumme)


def statisch(relativer_pfad: str) -> str:
    """Adresse einer statischen Datei samt Fassungsnummer.

    Die Pruefsumme wird gemerkt und nur neu gebildet, wenn sich Datum oder
    Groesse der Datei geaendert haben. Vorher wurde sie ausserhalb des
    Produktivbetriebs bei JEDEM Seitenaufbau neu berechnet - acht Dateien,
    155 KB lesen und hashen, rund eine Millisekunde pro Seite, fuer nichts.
    Ein stat() kostet einen Bruchteil davon und ist genauso richtig: Wer eine
    CSS-Datei aendert, aendert ihr Datum.
    """
    gemerkt = _ABDRUECKE.get(relativer_pfad)
    # Im Produktivbetrieb aendern sich die Dateien zwischen zwei Starts nicht.
    # Einmal gerechnet genuegt - kein Zugriff auf die Platte mehr.
    if gemerkt and cfg.IST_PRODUKTION:
        return f"/statisch/{relativer_pfad}?v={gemerkt[1]}"

    voll = os.path.join(cfg.STATISCH_DIR, relativer_pfad)
    try:
        angaben = os.stat(voll)
        kennung = (angaben.st_mtime_ns, angaben.st_size)
    except OSError:
        kennung = None
    if gemerkt and kennung is not None and gemerkt[0] == kennung:
        return f"/statisch/{relativer_pfad}?v={gemerkt[1]}"
    marke = _fingerabdruck(voll)
    _ABDRUECKE[relativer_pfad] = (kennung, marke)
    return f"/statisch/{relativer_pfad}?v={marke}"


umgebung.globals["statisch"] = statisch


def zeige(name: str, request=None, **inhalt) -> HTMLResponse:
    """Eine Vorlage rendern.

    Der CSP-Nonce wird automatisch mitgegeben: jedes <script> in einer Vorlage
    traegt nonce="{{ nonce }}", nur damit laesst der Browser es laufen. So
    kommt die Anwendung ohne 'unsafe-inline' fuer Skripte aus - in V1 stand es
    noch in der Richtlinie und machte den Schutz gegen eingeschleustes
    JavaScript weitgehend wirkungslos.
    """
    if request is not None:
        inhalt.setdefault("nonce", getattr(request.state, "nonce", ""))
        inhalt.setdefault("request", request)
        # Adressen passend zum Aufruf: Wer ueber localhost hereinkommt, soll
        # in den Verweisen auch auf localhost bleiben - sonst springt man
        # beim Testen auf die Live-Seite. Siehe cfg.adressen_fuer().
        website, dash = cfg.adressen_fuer(request)
        inhalt.setdefault("WEBSITE_URL", website)
        inhalt.setdefault("DASHBOARD_URL", dash)
    inhalt.setdefault("nonce", "")
    return HTMLResponse(umgebung.get_template(name).render(**inhalt))


def text(name: str, **inhalt) -> str:
    """Nur den gerenderten Text - fuer Teilstuecke, die woanders eingesetzt
    werden (htmx-Antworten, E-Mail-Rumpf)."""
    return umgebung.get_template(name).render(**inhalt)
