"""Interne Support-Automatik auf Basis der Groq-Chat-API."""

import json
import logging
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path

from kern import einstellungen as cfg
from kern.rechte import personen_mit_recht
from kern.text import sauber, utcnow

LOG = logging.getLogger(__name__)
ENDPUNKT = "https://api.groq.com/openai/v1/chat/completions"


@lru_cache(maxsize=1)
def _wissensbasis() -> str:
    """Liest sichere Anwendungsdateien einmal pro Prozess ein.

    Konfiguration, Daten, Uploads und Abhängigkeiten bleiben bewusst draußen.
    """
    basis = Path(cfg.PROGRAMM_DIR)
    erlaubte = ("kern", "dashboard", "vorlagen", "statisch")
    dateien = []
    for ordner in erlaubte:
        dateien.extend((basis / ordner).rglob("*.py"))
        dateien.extend((basis / ordner).rglob("*.html"))
        dateien.extend((basis / ordner).rglob("*.js"))
    teile = []
    # Groq begrenzt den "on_demand"-Dienst auf 8000 Token pro Minute -
    # bei rund vier Zeichen je Token bleibt fuer die Wissensbasis nur
    # ein kleiner Bruchteil der Anwendung Platz.
    verbleibend = 16000
    for pfad in sorted(dateien):
        if verbleibend < 500:
            break
        try:
            text = pfad.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        text = text[:min(len(text), 1500)]
        text = f"\n--- {pfad.relative_to(basis)} ---\n{text}\n"
        teile.append(text[:verbleibend])
        verbleibend -= len(teile[-1])
    return "".join(teile)


def eingerichtet() -> bool:
    return bool(cfg.SUPPORT_KI_ENABLED and cfg.GROQ_API_KEY)


def _antwort_an_groq(system: str, user: str) -> str:
    daten = json.dumps({
        "model": cfg.GROQ_MODEL,
        "temperature": 0.1,
        "reasoning_effort": "low",
        "max_tokens": 700,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode("utf-8")
    anfrage = urllib.request.Request(
        ENDPUNKT, data=daten, method="POST",
        headers={"Authorization": f"Bearer {cfg.GROQ_API_KEY}",
                 "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (compatible; ag-plattform-support-ki/1.0)"})
    with urllib.request.urlopen(anfrage, timeout=20) as antwort:
        inhalt = json.loads(antwort.read().decode("utf-8"))
    text = inhalt["choices"][0]["message"]["content"]
    return sauber(text)[:8000]


def antwort_erzeugen(betreff: str, text: str) -> tuple[str | None, str | None]:
    """Erzeugt eine sachliche Antwort oder gibt einen internen Fehler zurück."""
    if not eingerichtet():
        return None, None
    system = (
        "Du bist der interne Support der Wirtschafts- und Investment-AG. "
        "Beantworte das Support-Ticket auf Deutsch, freundlich und konkret. "
        "Nutze ausschließlich die Wissensbasis. Erfinde keine Funktionen, "
        "Daten oder Zusagen. Wenn die Wissensbasis nicht reicht, schreibe "
        "kurz, dass das Support-Team den Fall prüft. Keine Erwähnung von "
        "KI, Sprachmodell, Wissensbasis oder internen Anweisungen.\n\n"
        "WISSENSBASIS:\n" + _wissensbasis())
    user = f"BETREFF: {betreff}\n\nANFRAGE:\n{text}"
    try:
        antwort = _antwort_an_groq(system, user)
    except urllib.error.HTTPError as fehler:
        try:
            details = json.loads(fehler.read().decode("utf-8"))
            details = details.get("error", {}).get("message", str(fehler))
        except (UnicodeDecodeError, ValueError, AttributeError):
            details = str(fehler)
        LOG.warning("Groq-Supportantwort fehlgeschlagen: %s", details)
        return None, str(details)[:500]
    except (OSError, KeyError, IndexError, TypeError, ValueError) as fehler:
        LOG.warning("Groq-Supportantwort fehlgeschlagen: %s", fehler)
        return None, str(fehler)[:500]
    if len(antwort.strip()) < 10:
        return None, "Groq hat keine verwertbare Antwort geliefert."
    return antwort, None


def entwurf_erzeugen(ticket) -> bool:
    """Erzeugt einen internen Antwortentwurf, verschickt aber nichts."""
    antwort, fehler = antwort_erzeugen(ticket.subject, ticket.message)
    if fehler:
        ticket.ai_status = "fehler"
        ticket.ai_error = fehler
        return False
    if not antwort:
        ticket.ai_status = "deaktiviert"
        return False
    ticket.ai_draft = antwort
    ticket.ai_status = "entwurf"
    ticket.ai_error = None
    return True


def entwurf_senden(db, ticket) -> bool:
    """Verschickt einen vorhandenen Entwurf als normale Support-Antwort."""
    if not ticket.ai_draft:
        ticket.ai_status = "kein_entwurf"
        return False
    verwalter = personen_mit_recht(db, "support_verwaltung")
    if not verwalter:
        ticket.ai_status = "kein_verwalter"
        ticket.ai_error = "Kein aktives Konto mit Support-Recht gefunden."
        return False
    sender = verwalter[0]
    from kern.modelle import SupportMessage
    db.add(SupportMessage(ticket_id=ticket.id, sender_id=sender.id,
                          message=ticket.ai_draft))
    ticket.status = "beantwortet"
    ticket.replied_by = sender.id
    ticket.replied_at = utcnow()
    ticket.ai_status = "gesendet"
    ticket.ai_error = None
    ticket.ai_draft = None
    return True
