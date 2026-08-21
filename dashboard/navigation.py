"""Die Seitenleiste des Dashboards.

Sortiert nach Haeufigkeit der Nutzung, nicht nach Entstehungsreihenfolge:
oben steht, was im Alltag staendig gebraucht wird, unten die Verwaltung.

Neu gegenueber V1: an den Eintraegen stehen Zahlen, wo etwas wartet -
ungelesene Nachrichten, neue Bewerbungen, ueberfaellige Aufgaben, offene
Support-Anfragen. Vorher musste man jeden Bereich einmal aufmachen, um zu
sehen, ob dort etwas liegt.
"""

from datetime import date

from sqlalchemy import func

from kern.modelle import (
    Application, DirectMessageRecipient, SupportTicket, Task, WhatsAppNachricht,
)
from kern.rechte import (
    darf_bewerbungen, darf_ideensammlung, darf_redaktionsplan, rechte_von,
)


def zaehler(db, user, rechte) -> dict:
    """Alles, was irgendwo als Zahl erscheint - in wenigen Abfragen."""
    from kern.aufgaben import sichtbar_filter

    werte = {}

    werte["nachrichten"] = (db.query(func.count(DirectMessageRecipient.id))
                            .filter(DirectMessageRecipient.user_id == user.id,
                                    DirectMessageRecipient.read_at.is_(None))
                            .scalar() or 0)

    heute = date.today()
    werte["aufgaben"] = (db.query(func.count(Task.id))
                         .filter(sichtbar_filter(user, db),
                                 Task.status != "erledigt",
                                 Task.deadline.isnot(None),
                                 Task.deadline < heute)
                         .scalar() or 0)

    if darf_bewerbungen(user, db):
        werte["bewerbungen"] = (db.query(func.count(Application.id))
                                .filter(Application.status == "neu")
                                .scalar() or 0)

    if rechte.get("support_verwaltung"):
        werte["support"] = (db.query(func.count(SupportTicket.id))
                            .filter(SupportTicket.status == "offen")
                            .scalar() or 0)
    else:
        werte["support"] = 0

    if rechte.get("whatsapp_bot"):
        werte["whatsapp"] = (db.query(func.count(WhatsAppNachricht.id))
                             .filter(WhatsAppNachricht.status.in_(("offen", "bereit")))
                             .scalar() or 0)

    return {k: v for k, v in werte.items() if v}


def bereiche(db, user) -> list:
    """Die sichtbaren Bereiche als (kennung, name, adresse, gruppe)."""
    r = rechte_von(user, db)
    liste = []

    # Ohne Gruppentitel - der erste Eintrag fuer jede Rolle.
    liste.append(("uebersicht", "Übersicht", "/dashboard/uebersicht", ""))

    # -- Tagesgeschaeft: was in jeder Sitzung gebraucht wird ----------------
    if r["aufgaben_all"]:
        liste.append(("aufgaben", "Aufgaben", "/dashboard/aufgaben", "Tagesgeschäft"))
    else:
        liste.append(("aufgaben", "Meine Aufgaben", "/dashboard/aufgaben",
                      "Tagesgeschäft"))
    liste.append(("treffen", "AG-Treffen", "/dashboard/treffen", "Tagesgeschäft"))
    if darf_redaktionsplan(user, db) or darf_ideensammlung(user, db):
        liste.append(("redaktion", "Redaktionsplan", "/dashboard/redaktion",
                      "Tagesgeschäft"))
    liste.append(("kalender", "Kalender", "/dashboard/kalender", "Tagesgeschäft"))
    # Das Kassenbuch steht beim Tagesgeschaeft und nicht unter System: Belege
    # werden laufend eingetragen, nicht einmal im Halbjahr verwaltet.
    if r.get("finanzen"):
        liste.append(("kassenbuch", "Kassenbuch", "/dashboard/kassenbuch",
                      "Tagesgeschäft"))

    # -- Menschen: Bewerbungen zuerst, dort wartet jemand auf Antwort -------
    if darf_bewerbungen(user, db):
        liste.append(("bewerbungen", "Bewerbungen", "/dashboard/bewerbungen",
                      "Mitglieder"))
    if r["accounts_all"]:
        liste.append(("konten", "Konten", "/dashboard/konten", "Mitglieder"))
    if r["mitglieder_view"]:
        liste.append(("mitglieder", "Mitgliederliste", "/dashboard/mitglieder",
                      "Mitglieder"))
    if r["attendance"]:
        liste.append(("anwesenheit", "Anwesenheit", "/dashboard/anwesenheit",
                      "Mitglieder"))

    # -- Kommunikation: alles an einer Stelle statt an zweien ---------------
    liste.append(("nachrichten", "Nachrichten", "/dashboard/nachrichten",
                  "Kommunikation"))
    liste.append(("support", "Support", "/dashboard/support", "Kommunikation"))
    if r.get("email_vorlagen"):
        liste.append(("vordrucke", "E-Mail-Vordrucke", "/dashboard/vordrucke",
                      "Kommunikation"))
    if r.get("whatsapp_bot"):
        liste.append(("whatsapp", "WhatsApp-Bot", "/dashboard/whatsapp",
                      "Kommunikation"))

    # -- Foerderung: laeuft ueber Wochen, nicht ueber Stunden ---------------
    if r["projects"]:
        liste.append(("projekte", "Projekte", "/dashboard/projekte", "Förderung"))
    if r["competitions"]:
        liste.append(("wettbewerbe", "Wettbewerbe", "/dashboard/wettbewerbe",
                      "Förderung"))
    if r["leadership"]:
        liste.append(("leistung", "Leadership", "/dashboard/leistung", "Förderung"))

    # -- System: selten, aber wichtig - deshalb ganz unten ------------------
    if r["rollen"]:
        liste.append(("rollen", "Rollen & Rechte", "/dashboard/rollen", "System"))
    if r.get("seiteninhalte"):
        liste.append(("startseite", "Startseite", "/dashboard/startseite", "System"))
    if r["statistiken"]:
        liste.append(("statistiken", "Statistiken", "/dashboard/statistiken",
                      "System"))
    if r.get("sicherheit"):
        liste.append(("sicherheit", "Sicherheit", "/dashboard/sicherheit", "System"))
    if r["datenbank"]:
        liste.append(("datenbank", "Datenbank", "/dashboard/datenbank", "System"))
        liste.append(("papierkorb", "Papierkorb", "/dashboard/papierkorb", "System"))

    # "Mein Konto" steht bewusst nicht in der Leiste: der Bereich wird oben
    # ueber den eigenen Namen geoeffnet.
    return liste


def gruppiert(liste) -> list:
    """Nach Gruppen sortiert, Reihenfolge bleibt: [(gruppe, [eintraege])]."""
    reihenfolge, kaesten = [], {}
    for eintrag in liste:
        gruppe = eintrag[3]
        if gruppe not in kaesten:
            kaesten[gruppe] = []
            reihenfolge.append(gruppe)
        kaesten[gruppe].append(eintrag)
    # Ein Gruppentitel ueber einem einzigen Eintrag ist Unordnung, kein
    # Ordnungsmerkmal - er wird in der Vorlage weggelassen.
    return [(name, kaesten[name]) for name in reihenfolge]
