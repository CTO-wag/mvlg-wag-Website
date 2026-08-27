"""E-Mail-Versand samt Vordrucken.

Ohne SMTP_HOST laeuft alles weiter, nur ohne E-Mails - Meldungen erscheinen
dann in der App und als Push. Das ist Absicht: der Mailversand darf nie zur
Voraussetzung dafuer werden, dass die Plattform benutzbar ist.

Die Vordrucke stehen in der Datenbank (Tabelle email_templates, unveraendert
aus V1) und sind im Dashboard aenderbar. Die Vorgaben hier unten greifen nur,
wenn ein Vordruck fehlt - bereits angepasste Texte bleiben also erhalten.
"""

import os
import smtplib
import ssl as ssl_modul
import threading
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from kern import einstellungen as cfg
from kern import werte
from kern.datenbank import sitzung
from kern.modelle import EmailTemplate, User
from kern.protokoll import zustellung
from kern.text import esc, sauber

LOGO_DATEI = os.path.join(cfg.STATISCH_DIR, "bilder", "logo-mail.png")
LOGO_KENNUNG = "ag-logo"


def versand_moeglich() -> bool:
    return bool(cfg.SMTP_HOST and cfg.SMTP_FROM)


#  Vordrucke
#  (Schluessel, Betreff, Text, Beschreibung, Platzhalter). Die Beschreibung
#  steht im Dashboard ueber dem Feld - in V1 musste man raten, wann ein
#  Vordruck ueberhaupt benutzt wird.
VORDRUCKE = {
    "application_received": (
        "Deine Bewerbung ist bei uns angekommen",
        "Hallo {vorname},\n\n"
        "danke für deine Bewerbung bei der Wirtschafts- & Investment-AG. "
        "Wir haben sie erhalten.\n\n"
        "Wie es weitergeht: Der Vorstand sieht sich jede Bewerbung in Ruhe an. "
        "Du bekommst in der Regel innerhalb von zwei Wochen eine Rückmeldung "
        "von uns, in jedem Fall aber eine.\n\n"
        "Bis dahin musst du nichts weiter tun.\n\n"
        "Viele Grüße\nDer Vorstand der Wirtschafts- & Investment-AG",
        "Geht sofort raus, wenn jemand das Bewerbungsformular abschickt.",
        ("vorname", "nachname", "abteilung"),
    ),
    "application_status": (
        "Deine Bewerbung: {status}",
        "Hallo {vorname},\n\n"
        "zu deiner Bewerbung bei der Wirtschafts- & Investment-AG gibt es "
        "einen neuen Stand:\n\n{status}\n\n"
        "Bei einer Zusage bekommst du gleich im Anschluss eine zweite E-Mail "
        "mit deinen Zugangsdaten für unser Dashboard.\n\n"
        "Hast du Fragen dazu? Schreib uns über das Kontaktformular auf unserer "
        "Website - wir antworten dir persönlich.\n\n"
        "Viele Grüße\nDer Vorstand der Wirtschafts- & Investment-AG",
        "Geht raus, sobald der Vorstand den Stand einer Bewerbung ändert.",
        ("vorname", "nachname", "status"),
    ),
    "account_created": (
        "Willkommen in der AG - dein Zugang zum Dashboard",
        "Hallo {vorname},\n\n"
        "herzlich willkommen bei der Wirtschafts- & Investment-AG. Für dich "
        "ist jetzt ein Zugang zu unserem internen Dashboard eingerichtet.\n\n"
        "Dort findest du deine Aufgaben, die nächsten AG-Termine, Nachrichten "
        "vom Vorstand und alles Weitere an einer Stelle.\n\n"
        "Deine Zugangsdaten:\n\nE-Mail: {email}\nPasswort: {passwort}\n\n"
        "Anmelden: {login_url}\n\n"
        "Bitte ändere das Passwort gleich nach der ersten Anmeldung unter "
        "„Mein Konto“.\n\n"
        "Viele Grüße\nDer Vorstand der Wirtschafts- & Investment-AG",
        "Geht an neue Mitglieder, sobald ihr Konto angelegt wurde.",
        ("vorname", "nachname", "email", "passwort", "login_url"),
    ),
    "password_reset": (
        "Neues Passwort für dein AG-Konto",
        "Hallo {vorname},\n\n"
        "für dein Konto bei der Wirtschafts- & Investment-AG wurde ein neues "
        "Passwort angefordert.\n\n"
        "Mit diesem Link kannst du es setzen. Er gilt {minuten} Minuten und "
        "funktioniert nur ein einziges Mal:\n\n{link}\n\n"
        "Warst du das nicht, musst du nichts tun. Dein bisheriges Passwort "
        "bleibt gültig, und ohne diese E-Mail kann niemand den Link benutzen.\n\n"
        "Viele Grüße\nDer Vorstand der Wirtschafts- & Investment-AG",
        "Der Link aus „Passwort vergessen“.",
        ("vorname", "link", "minuten"),
    ),
    "email_change": (
        "Bitte bestätige deine neue E-Mail-Adresse",
        "Hallo {vorname},\n\n"
        "du möchtest die Adresse deines AG-Kontos auf diese hier ändern. "
        "Mit einem Klick wird sie gültig:\n\n{link}\n\n"
        "Der Link gilt {stunden} Stunden. Bis dahin bleibt deine alte Adresse "
        "in Kraft - du sperrst dich also nicht versehentlich aus.\n\n"
        "Viele Grüße\nDer Vorstand der Wirtschafts- & Investment-AG",
        "Bestätigung, wenn jemand seine eigene Adresse ändert.",
        ("vorname", "link", "stunden"),
    ),
    "notification": (
        "{titel}",
        "Hallo {vorname},\n\n{text}\n\n"
        "Zum Dashboard: {dashboard_url}\n\n"
        "Du bekommst diese Nachricht, weil in deinem Konto Benachrichtigungen "
        "eingeschaltet sind. Du kannst das im Dashboard unter „Nachrichten“ "
        "jederzeit ändern.",
        "Der Rahmen für alle Benachrichtigungen, die zusätzlich per Mail gehen.",
        ("vorname", "titel", "text", "dashboard_url"),
    ),
    # Eigener Vordruck statt "notification": Wer ueber das Kontaktformular
    # schreibt, hat KEIN Konto. Der Benachrichtigungsrahmen haette ihm einen
    # Dashboard-Link geschickt und den Satz "weil in deinem Konto
    # Benachrichtigungen eingeschaltet sind" - beides Unsinn fuer jemanden
    # von aussen und ein guter Grund, die Mail fuer einen Irrlaeufer zu
    # halten.
    #
    # Die urspruengliche Frage steht mit darunter. Zwischen Absenden und
    # Antwort liegen leicht ein paar Tage; ohne sie weiss die Person nicht
    # mehr, worauf hier geantwortet wird.
    "contact_reply": (
        "Antwort auf deine Nachricht an die Wirtschafts- & Investment-AG",
        "Hallo {vorname},\n\n"
        "danke für deine Nachricht. Hier ist unsere Antwort:\n\n"
        "{antwort}\n\n"
        "Du kannst auf diese E-Mail einfach antworten - sie geht an eine "
        "Adresse, die gelesen wird.\n\n"
        "Viele Grüße\n{absender}\n"
        "Wirtschafts- & Investment-AG\n\n"
        "--- Deine Nachricht vom {datum} ---\n{frage}",
        "Die persönliche Antwort auf eine Anfrage über das Kontaktformular "
        "der Website. Wird im Dashboard unter „Nachrichten“ geschrieben.",
        ("vorname", "antwort", "frage", "datum", "absender"),
    ),
}

# Vordrucke, bei denen die persoenliche Abmeldung gilt. Bei allen anderen
# (Passwort, Adresswechsel, Zugangsdaten) waere ein "abbestellt" gefaehrlich -
# davon haengt der Zugang ab.
ABBESTELLBAR = frozenset({"notification"})


def vordrucke_anlegen() -> None:
    """Fehlende Vordrucke ergaenzen. Vorhandene bleiben unangetastet."""
    with sitzung() as db:
        vorhanden = {t.key for t in db.query(EmailTemplate.key).all()}
        for schluessel, (betreff, rumpf, _, _) in VORDRUCKE.items():
            if schluessel not in vorhanden:
                db.add(EmailTemplate(key=schluessel, subject=betreff, body=rumpf))
        db.commit()


class _Nachsichtig(dict):
    """Laesst unbekannte Platzhalter stehen statt abzustuerzen.

    Wer im Dashboard {vornmae} tippt, soll eine seltsame Mail bekommen - aber
    keinen Serverfehler, der den ganzen Vorgang abbricht.
    """

    def __missing__(self, schluessel):
        return "{" + schluessel + "}"


def fuelle(db, schluessel: str, **werte_) -> tuple:
    """(Betreff, Text) eines Vordrucks mit eingesetzten Werten."""
    vorlage = db.get(EmailTemplate, schluessel)
    if vorlage:
        betreff, rumpf = vorlage.subject, vorlage.body
    else:
        betreff, rumpf = VORDRUCKE.get(schluessel, ("{titel}", "{text}"))[:2]
    daten = _Nachsichtig(werte_)
    try:
        return betreff.format_map(daten), rumpf.format_map(daten)
    except Exception:                                        # pragma: no cover
        return betreff, rumpf


#  HTML-Rahmen
#  Tabellenlayout und Inline-Stil, weil Mailprogramme nichts anderes
#  zuverlaessig darstellen. Die Dunkelmodus-Regeln stehen zusaetzlich im
#  <style>-Block; wer sie ignoriert, sieht die helle Fassung.
_HELL = {"navy": "#0E2647", "text": "#18211F", "grau": "#66726D",
         "linie": "#E3E7EA", "grund": "#F4F6F4", "flaeche": "#FFFFFF",
         "amber": "#B7791F"}

_DUNKEL_CSS = """
@media (prefers-color-scheme: dark){
  body,.rahmen{background:#0A0F1A !important;}
  .karte{background:#131B2C !important;border-color:#2A3552 !important;}
  .text,.text *{color:#EDF0F7 !important;}
  .leise,.leise *{color:#9AA7C2 !important;}
  .trennlinie{border-color:#2A3552 !important;}
  a.knopf{background:#E8A83D !important;color:#0A0F1A !important;}
}
"""


def _absaetze(text: str) -> str:
    """Nackten Text in HTML-Absaetze giessen - Links werden anklickbar."""
    import re
    teile = []
    for absatz in (text or "").split("\n\n"):
        absatz = absatz.strip()
        if not absatz:
            continue
        sicher = esc(absatz).replace("\n", "<br>")
        sicher = re.sub(
            r"(https?://[^\s<]+)",
            r'<a href="\1" style="color:#B7791F;">\1</a>', sicher)
        teile.append(
            f'<p class="text" style="margin:0 0 16px;font-size:15px;'
            f'line-height:1.65;color:{_HELL["text"]};">{sicher}</p>')
    return "\n".join(teile)


def als_html(betreff: str, text: str, automatisch: bool = True,
             antwort_an: str = "") -> str:
    f = _HELL
    ziel = _antwortziel(antwort_an)
    fuss = " ".join(teil for teil in (
        "Diese Nachricht wurde automatisch verschickt." if automatisch else "",
        f"Antworten gehen an {esc(ziel)}." if ziel else "") if teil)
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{_DUNKEL_CSS}</style></head>
<body class="rahmen" style="margin:0;padding:0;background:{f['grund']};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:{f['grund']};padding:24px 12px;">
<tr><td align="center">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         class="karte" style="max-width:560px;background:{f['flaeche']};
         border:1px solid {f['linie']};border-radius:10px;overflow:hidden;">
    <!-- Kopfleiste: Wappen und Name auf Navy.
         Das Bild hat denselben Navy-Ton fest eingebaut (siehe
         werkzeuge/vorschaubild_bauen.py). Frueher hatte es einen weissen
         Hintergrund - in der Mail klebte damit ein weisser Kasten auf der
         blauen Leiste, im hellen wie im dunklen Modus. Transparenz waere der
         andere Weg, aber Mailprogramme tauschen im Dunkelmodus gern
         Hintergruende aus; ein Bild mit eigenem Grund sieht ueberall gleich
         aus. Der Name steht als Text daneben, nicht im Bild: so bleibt er
         lesbar, wenn jemand Bilder abgeschaltet hat. -->
    <tr><td style="background:{f['navy']};padding:18px 24px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td style="padding-right:14px;" valign="middle">
            <img src="cid:{LOGO_KENNUNG}" width="72" height="58"
                 alt="Wappen der Wirtschafts- und Investment-AG"
                 style="display:block;width:72px;height:58px;border:0;
                        background:{f['navy']};color:#FFFFFF;font-size:11px;">
          </td>
          <td valign="middle" style="font-family:Georgia,serif;">
            <div style="color:#FFFFFF;font-size:17px;font-weight:bold;
                        line-height:1.25;">Wirtschafts- &amp; Investment-AG</div>
            <div style="color:#C8D6E8;font-size:12px;line-height:1.4;
                        padding-top:2px;">Max-von-Laue-Gymnasium Koblenz</div>
          </td>
        </tr>
      </table>
    </td></tr>
    <tr><td style="padding:28px;">
      <h1 class="text" style="margin:0 0 18px;font-family:Georgia,serif;
          font-size:20px;line-height:1.3;color:{f['navy']};">{esc(betreff)}</h1>
      {_absaetze(text)}
    </td></tr>
    <tr><td class="trennlinie" style="border-top:1px solid {f['linie']};
        padding:18px 28px;">
      <p class="leise" style="margin:0;font-size:12px;line-height:1.6;
         color:{f['grau']};">
        Wirtschafts- &amp; Investment-AG · Schüler-AG des
        Max-von-Laue-Gymnasiums Koblenz<br>
        {fuss}
      </p>
    </td></tr>
  </table>
</td></tr></table></body></html>"""


def _antwortziel(antwort_an: str = "") -> str:
    """An wen eine Antwort auf diese Mail geht - oder "" fuer niemanden."""
    return sauber(antwort_an) or cfg.MAIL_REPLY_TO


def _fusszeile_text(automatisch: bool = True, antwort_an: str = "") -> str:
    zeilen = ["", "—",
              "Wirtschafts- & Investment-AG · Schüler-AG des "
              "Max-von-Laue-Gymnasiums Koblenz"]
    if automatisch:
        zeilen.append("Diese Nachricht wurde automatisch verschickt.")
    ziel = _antwortziel(antwort_an)
    if ziel:
        zeilen.append(f"Antworten gehen an {ziel}.")
    return "\n".join(zeilen)


#  Versand
def _zustellen(empfaenger: str, betreff: str, text: str,
               antwort_an: str = "", automatisch: bool = True) -> tuple:
    """(erfolg, Fehlermeldung). Blockiert - nie direkt aus einer Route rufen.

    `antwort_an` setzt Reply-To abweichend von der Vorgabe, `automatisch=False`
    laesst den Vermerk Auto-Submitted weg. Beides braucht die von Hand
    geschriebene Antwort auf eine Kontaktanfrage: Sie soll bei der Person
    landen, die sie geschrieben hat, und kein Mailprogramm soll sie als
    Maschinenpost behandeln - genau das unterdrueckt sonst die Abwesenheits-
    notiz, mit der jemand antworten wollte.
    """
    if not versand_moeglich():
        return False, "Kein SMTP-Server konfiguriert."

    nachricht = EmailMessage()
    nachricht["Subject"] = betreff
    nachricht["From"] = formataddr((cfg.SMTP_FROM_NAME, cfg.SMTP_FROM))
    nachricht["To"] = empfaenger
    nachricht["Date"] = formatdate(localtime=True)
    absenderdomain = cfg.SMTP_FROM.split("@")[-1] if "@" in cfg.SMTP_FROM else None
    nachricht["Message-ID"] = make_msgid(domain=absenderdomain)
    if _antwortziel(antwort_an):
        nachricht["Reply-To"] = _antwortziel(antwort_an)
    if automatisch:
        # Sagt Mailprogrammen, dass hier niemand mitliest - unterdrueckt
        # Abwesenheitsnotizen und Lesebestaetigungen. Bei einer von Hand
        # geschriebenen Antwort waere der Vermerk schlicht falsch.
        nachricht["Auto-Submitted"] = "auto-generated"

    nachricht.set_content(
        text + "\n" + _fusszeile_text(automatisch, antwort_an))
    nachricht.add_alternative(
        als_html(betreff, text, automatisch, antwort_an), subtype="html")

    if os.path.exists(LOGO_DATEI):
        try:
            with open(LOGO_DATEI, "rb") as datei:
                # An den HTML-Teil anhaengen, nicht an die Nachricht: sonst
                # zeigen manche Programme das Logo als lose Datei darunter.
                nachricht.get_payload()[1].add_related(
                    datei.read(), maintype="image", subtype="png",
                    cid=f"<{LOGO_KENNUNG}>", filename="logo.png")
        except OSError:
            pass

    try:
        if cfg.SMTP_SECURITY == "ssl":
            server = smtplib.SMTP_SSL(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=20)
        else:
            server = smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=20)
        with server:
            server.ehlo()
            if cfg.SMTP_SECURITY == "starttls":
                server.starttls(context=ssl_modul.create_default_context())
                server.ehlo()
            if cfg.SMTP_USER:
                server.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
            server.send_message(nachricht)
        return True, ""
    except Exception as problem:
        return False, f"{type(problem).__name__}: {problem}"[:300]


def sende(empfaenger: str, betreff: str, text: str, warten: bool = False,
          anlass: str = None, testmodus: bool = False,
          antwort_an: str = "", automatisch: bool = True) -> bool:
    """Verschickt eine Mail - normalerweise im Hintergrund.

    warten=True nur dort, wo das Ergebnis in derselben Antwort gebraucht wird
    (Testversand im Dashboard). Sonst haengt die Seite an der Antwortzeit des
    Mailservers, und die kann Sekunden betragen.
    """
    if testmodus:
        betreff = "[TEST] " + betreff
    if not versand_moeglich():
        zustellung("email", empfaenger, betreff, False,
                   "Kein SMTP-Server konfiguriert.", anlass)
        return False

    def arbeit():
        erfolg, fehler = _zustellen(empfaenger, betreff, text,
                                    antwort_an=antwort_an,
                                    automatisch=automatisch)
        zustellung("email", empfaenger, betreff, erfolg, fehler, anlass)
        if not erfolg:
            print(f"[E-Mail] an {empfaenger} fehlgeschlagen: {fehler}")
        return erfolg

    if warten:
        return arbeit()
    threading.Thread(target=arbeit, daemon=True, name="mailversand").start()
    return True


def sende_vordruck(db, empfaenger_user, schluessel: str, warten: bool = False,
                   antwort_an: str = "", automatisch: bool = True,
                   **daten) -> bool:
    """Vordruck fuellen und an eine Person schicken.

    Beachtet den Testmodus: Ist er an, gehen alle Mails nur an aktive Konten
    mit dem Recht "E-Mail-Vordrucke" - so laesst sich ein Ablauf ausprobieren,
    ohne dass die halbe AG Post bekommt.
    """
    if not empfaenger_user or not sauber(getattr(empfaenger_user, "email", "")):
        return False

    betreff, text = fuelle(
        db, schluessel,
        vorname=empfaenger_user.vorname, nachname=empfaenger_user.nachname,
        email=empfaenger_user.email, dashboard_url=cfg.DASHBOARD_URL,
        login_url=f"{cfg.WEBSITE_URL}/login", **daten)

    testmodus = werte.an_db(db, werte.EMAIL_TESTMODUS)
    if testmodus:
        from kern.rechte import hat_recht
        verwalter = (db.query(User).filter(User.status == "aktiv").all())
        empfaenger = []
        for person in verwalter:
            if hat_recht(person, "email_vorlagen", db) and sauber(person.email):
                if person.email not in empfaenger:
                    empfaenger.append(person.email)
        if not empfaenger:
            zustellung("email", empfaenger_user.email, betreff, False,
                       "Testmodus - kein Vordruck-Verwalter.", schluessel)
            return False
        ergebnisse = [
            sende(adresse, betreff, text, warten=warten,
                  anlass=schluessel, testmodus=True,
                  antwort_an=antwort_an, automatisch=automatisch)
            for adresse in empfaenger
        ]
        return any(ergebnisse)
    return sende(empfaenger_user.email, betreff, text, warten=warten,
                 anlass=schluessel, antwort_an=antwort_an,
                 automatisch=automatisch)


def pruefe_verbindung() -> tuple:
    """(gut, Meldung) - fuer die Systemuebersicht im Dashboard."""
    if not versand_moeglich():
        return False, "Kein SMTP-Server hinterlegt (Mails sind aus)."
    try:
        if cfg.SMTP_SECURITY == "ssl":
            server = smtplib.SMTP_SSL(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=8)
        else:
            server = smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=8)
        with server:
            server.ehlo()
            if cfg.SMTP_SECURITY == "starttls":
                server.starttls(context=ssl_modul.create_default_context())
                server.ehlo()
            if cfg.SMTP_USER:
                server.login(cfg.SMTP_USER, cfg.SMTP_PASSWORD)
        return True, f"Verbindung zu {cfg.SMTP_HOST} steht."
    except Exception as problem:
        return False, f"{type(problem).__name__}: {problem}"[:160]
