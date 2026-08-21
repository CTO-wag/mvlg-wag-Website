"""Leichte SVG-Diagramme ohne Bibliothek.

Zwei Formen genuegen fuer alles, was hier gebraucht wird: ein Balken fuer
Vergleiche und ein Ring fuer Anteile. Beide werden serverseitig erzeugt und
tragen keine Skripte - damit funktionieren sie auch, wenn JavaScript aus ist,
und sie kosten keine 200 KB Bibliothek fuer vier Balken.

Die Farben kommen aus dem Farbschema, damit die Diagramme im Dunkelmodus
mitwandern.
"""

from markupsafe import Markup

from kern.text import esc

FARBEN = ("var(--navy)", "var(--amber)", "var(--gruen)", "var(--blau)",
          "var(--lila)", "var(--rot)", "var(--gedaempft)")


def _leer(text: str = "Noch keine Daten") -> Markup:
    return Markup(f'<p class="meta">{esc(text)}</p>')


def balken(werte, farbe_index: int = 0, format_=None) -> Markup:
    """Waagerechte Balken: [(Name, Zahl), ...].

    Waagerecht und nicht senkrecht, weil die Namen sonst gedreht werden
    muessten - "Recruitment" quer gestellt liest niemand.
    """
    werte = [(str(n), z) for n, z in werte if z is not None]
    if not werte:
        return _leer()
    hoechster = max(z for _, z in werte) or 1
    farbe = FARBEN[farbe_index % len(FARBEN)]
    zeilen = []
    for name, zahl in werte:
        anteil = max(1.5, zahl / hoechster * 100)
        anzeige = format_(zahl) if format_ else str(zahl)
        zeilen.append(
            '<div class="balken-zeile">'
            f'<span class="balken-name">{esc(name)}</span>'
            f'<span class="balken" style="height:.55rem;">'
            f'<span style="width:{anteil:.1f}%;background:{farbe};"></span></span>'
            f'<b class="balken-zahl">{esc(anzeige)}</b>'
            "</div>")
    return Markup(
        '<div class="balken-diagramm">' + "".join(zeilen) + "</div>")


def ring(werte, groesse: int = 168, staerke: int = 26) -> Markup:
    """Ringdiagramm fuer Anteile: [(Name, Zahl), ...] samt Legende."""
    werte = [(str(n), z) for n, z in werte if z]
    if not werte:
        return _leer()
    gesamt = sum(z for _, z in werte)
    if not gesamt:
        return _leer()

    radius = (groesse - staerke) / 2
    umfang = 2 * 3.141592653589793 * radius
    mitte = groesse / 2
    versatz = 0.0
    kreise = []
    legende = []
    for nummer, (name, zahl) in enumerate(werte):
        farbe = FARBEN[nummer % len(FARBEN)]
        laenge = zahl / gesamt * umfang
        kreise.append(
            f'<circle cx="{mitte}" cy="{mitte}" r="{radius:.2f}" fill="none" '
            f'stroke="{farbe}" stroke-width="{staerke}" '
            f'stroke-dasharray="{laenge:.2f} {umfang - laenge:.2f}" '
            f'stroke-dashoffset="{-versatz:.2f}" />')
        versatz += laenge
        anteil = round(zahl / gesamt * 100)
        legende.append(
            f'<span><i class="legende-punkt" style="background:{farbe}"></i>'
            f"{esc(name)} · {zahl} ({anteil} %)</span>")

    return Markup(
        f'<svg class="diagramm" viewBox="0 0 {groesse} {groesse}" '
        f'width="{groesse}" height="{groesse}" role="img" '
        f'aria-label="Ringdiagramm mit {len(werte)} Anteilen">'
        # Startpunkt oben statt rechts - so liest man ein Tortendiagramm.
        f'<g transform="rotate(-90 {mitte} {mitte})">' + "".join(kreise) + "</g>"
        f'<text x="{mitte}" y="{mitte - 2}" text-anchor="middle" '
        f'class="wert" style="font-size:20px;">{gesamt}</text>'
        f'<text x="{mitte}" y="{mitte + 14}" text-anchor="middle" '
        f'style="font-size:10px;">gesamt</text>'
        "</svg>"
        f'<div class="diagramm-legende">{"".join(legende)}</div>')


def verlauf(werte, hoehe: int = 90) -> Markup:
    """Kleine Linie fuer eine Reihe ueber die Zeit: [(Beschriftung, Zahl), ...]."""
    werte = [(str(n), z or 0) for n, z in werte]
    if len(werte) < 2:
        return _leer()
    hoechster = max(z for _, z in werte) or 1
    breite = 100
    schritt = breite / (len(werte) - 1)
    punkte = " ".join(
        f"{i * schritt:.2f},{hoehe - (z / hoechster * (hoehe - 16)) - 8:.2f}"
        for i, (_, z) in enumerate(werte))
    beschriftung = " ".join(
        f'<text x="{i * schritt:.2f}" y="{hoehe - 1}" text-anchor="middle" '
        f'style="font-size:7px;">{esc(n)}</text>'
        for i, (n, _) in enumerate(werte))
    return Markup(
        f'<svg class="diagramm" viewBox="0 0 {breite} {hoehe}" '
        f'preserveAspectRatio="none" role="img" aria-label="Verlauf">'
        f'<polyline points="{punkte}" fill="none" stroke="var(--navy)" '
        'stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" '
        'vector-effect="non-scaling-stroke" />'
        f"{beschriftung}</svg>")
