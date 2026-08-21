@echo off
REM ============================================================================
REM  Konfiguration der AG-Plattform V2 (VORLAGE)
REM ============================================================================
REM
REM  Diese Datei enthaelt keine echten Zugangsdaten und darf veroeffentlicht
REM  werden. Sie ist ein Nachschlagewerk: welche Werte es gibt und was sie tun.
REM
REM  Einrichtung:
REM    Normalerweise nichts zu tun. start.bat uebernimmt beim ersten Start die
REM    config.cmd aus Management-System-V1 - gleicher Sitzungsschluessel,
REM    gleicher Datenordner. Dadurch bleibt beim Umstieg alles, wie es war:
REM    niemand wird abgemeldet, niemand muss Benachrichtigungen neu einrichten.
REM
REM    Gibt es keine V1-Konfiguration, legt start.bat eine frische an.
REM ============================================================================

REM --- Sitzungsschluessel ------------------------------------------------------
REM  Verschluesselt die Anmelde-Cookies. Wer ihn kennt, kann sich als beliebige
REM  Person ausgeben - also niemals weitergeben.
REM  WICHTIG: Beim Umstieg von V1 denselben Wert behalten. Ein neuer Schluessel
REM  meldet alle ab.
REM  Neuen erzeugen ->  python -c "import secrets; print(secrets.token_hex(32))"
set "SECRET_KEY="

REM --- Erster Zugang -----------------------------------------------------------
REM  Wird nur benutzt, solange noch kein aktives CTO-Konto existiert.
set "DEFAULT_ADMIN_EMAIL=vorstand@ag.local"
set "DEFAULT_ADMIN_PASSWORD="

REM --- Datenordner -------------------------------------------------------------
REM  Wo Datenbank, Sicherungen und hochgeladene Dateien liegen. Relative
REM  Angaben zaehlen ab diesem Programmordner.
set "DATEN_DIR=../../daten"

REM --- Ports und Adressen ------------------------------------------------------
REM  Zwei Server: die oeffentliche Seite und das Dashboard. Das Sitzungs-Cookie
REM  gilt fuer beide, weil Cookies nicht nach Port getrennt werden.
set "WEBSITE_PORT=8000"
set "DASHBOARD_PORT=8001"
REM  SITE_URL steht in E-Mails, im Kalender-Abo und in den Suchmaschinen-Angaben.
set "SITE_URL=https://mvlg-wag.de"
REM  Nur setzen, wenn die Server hinter einem Proxy unter anderen Adressen
REM  erreichbar sind. Sonst leer lassen - dann werden sie aus den Ports gebildet.
set "WEBSITE_URL="
set "DASHBOARD_URL="
REM  Fuer welchen Namensbereich die Cookies gelten. Leer = automatisch:
REM  Liegen Website und Dashboard auf verschiedenen Namen derselben Domain
REM  (mvlg-wag.de und app.mvlg-wag.de), setzt die Anwendung von selbst
REM  ".mvlg-wag.de" - ohne das gilt die Anmeldung nur fuer den Namen, unter dem
REM  man sich angemeldet hat, und das Dashboard schickt einen sofort wieder zur
REM  Anmeldung. Nur ausfuellen, wenn es einen Grund gibt, davon abzuweichen.
set "COOKIE_DOMAIN="

REM --- Betrieb -----------------------------------------------------------------
REM  production erzwingt SECRET_KEY und HTTPS-Cookies.
set "APP_ENV=production"
REM  HTTPS_ONLY_COOKIES=false ist noetig, solange ueber http://localhost
REM  gearbeitet wird - sonst schickt der Browser das Cookie nicht zurueck und
REM  keine Anmeldung gelingt. Laeuft alles ueber https: true.
set "HTTPS_ONLY_COOKIES=true"
REM  Nur auf true, wenn wirklich ein Proxy davorhaengt (z.B. der Tunnel).
REM  Sonst koennte jeder seine IP-Adresse faelschen und die Anmeldebremse
REM  aushebeln.
set "TRUST_PROXY_HEADERS=true"
REM  HSTS zwingt Browser dauerhaft auf HTTPS - erst einschalten, wenn wirklich
REM  jede Adresse sauber ueber https erreichbar ist.
set "HSTS_ENABLED=true"
rem 180 Tage. Der Standard von einem Tag ist zu kurz: Er schuetzt nur,
rem wer die Seite taeglich besucht. Achtung, schwer rueckgaengig zu
rem machen - Browser merken sich die Angabe.
set "HSTS_MAX_AGE=15552000"
REM  Wie lange eine Anmeldung ohne Aktivitaet gilt und wie lange hoechstens.
set "SITZUNG_LEERLAUF_MINUTEN=480"
set "SITZUNG_HOECHSTDAUER_STUNDEN=24"
rem "Angemeldet bleiben" (Standard beim Anmelden): erst nach drei
rem Monaten ohne Aufruf ist Schluss, spaetestens nach einem halben Jahr.
rem Die kurzen Fristen darueber gelten nur, wenn jemand den Haken
rem beim Anmelden entfernt.
set "SITZUNG_DAUERHAFT_LEERLAUF_TAGE=90"
set "SITZUNG_DAUERHAFT_TAGE=180"

REM --- Cloudflare-Tunnel -------------------------------------------------------
REM  Nur auf einem einzigen Rechner einschalten. Zwei Rechner mit denselben
REM  Zugangsdaten teilen sich sonst den Datenverkehr der oeffentlichen Adresse -
REM  die Haelfte aller Besucher landet auf dem falschen PC.
set "TUNNEL_STARTEN=false"

REM --- E-Mail-Versand (optional) -----------------------------------------------
REM  Ohne SMTP_HOST laeuft alles weiter, nur ohne E-Mails - Meldungen erscheinen
REM  dann in der App und als Push.
REM  SMTP_PASSWORD ist der eigens erzeugte SMTP-Schluessel, nicht das Passwort
REM  des Kontos.
set "SMTP_HOST=smtp-relay.brevo.com"
set "SMTP_PORT=587"
set "SMTP_SECURITY=starttls"
set "SMTP_USER="
set "SMTP_PASSWORD="
set "SMTP_FROM=mail@example.de"
set "SMTP_FROM_NAME=Wirtschafts- & Investment-AG"
REM  Adresse, an die Antworten auf automatische Mails gehen.
set "MAIL_REPLY_TO=kontakt@example.de"

REM --- Push-Benachrichtigungen -------------------------------------------------
REM  ntfy.sh ist kostenlos, hat aber ein Tageskontingent. Ist es aufgebraucht,
REM  sieht man das im Dashboard unter Sicherheit bzw. Datenbank.
set "NTFY_BASE_URL=https://ntfy.sh"

REM --- Aufbewahrung ------------------------------------------------------------
REM  Wie lange Bewerbungen gespeichert bleiben. Personenbezogene Daten duerfen
REM  nur so lange liegen, wie der Zweck es verlangt - bei einer Bewerbung endet
REM  der mit der Entscheidung. 0 schaltet das Loeschen ab.
REM  Offene Bewerbungen werden nie automatisch geloescht.
REM set "BEWERBUNG_ABGELEHNT_TAGE=180"
REM set "BEWERBUNG_ANGENOMMEN_TAGE=365"

REM --- Auffangnetz bei Cloudflare ----------------------------------------------
REM  Ein kleiner Worker steht vor der Plattform und zeigt eine eigene Seite,
REM  wenn hier nichts antwortet - statt der englischen Cloudflare-Fehlerseite.
REM  Wer dort eine Meldung hinterlaesst, kann das nicht angemeldet tun; die
REM  Meldungen liegen deshalb beim Worker und werden hier abgeholt, sobald die
REM  Plattform wieder laeuft. Daraus werden echte Support-Tickets.
REM
REM  Einrichten: cloudflare/ANLEITUNG.md. Ohne diese beiden Werte passiert
REM  nichts - der Worker zeigt seine Seite auch dann, nur entstehen keine
REM  Tickets. Der Schluessel muss zeichengenau derselbe sein wie das Secret
REM  ABHOL_SCHLUESSEL im Worker.
REM set "AUSFALL_WORKER_URL=https://mvlg-wag.de"
REM set "AUSFALL_SCHLUESSEL="
REM set "AUSFALL_ABHOLUNG_MINUTEN=5"
set "DELIVERY_LOG_TAGE=30"

REM --- WhatsApp-Bot -------------------------------------------------------------
REM  Begruesst neue Mitglieder automatisch. Der Text ist im Dashboard aenderbar.
REM
REM  WHATSAPP_MODUS:
REM    web        EMPFOHLEN. Ein eigener Node-Dienst (whatsapp-web.js) haelt
REM               eine WhatsApp-Sitzung offen. Einmal per QR-Code im Dashboard
REM               koppeln, danach geht alles vollautomatisch an jede Nummer -
REM               ohne Business-Konto und ohne genehmigte Vorlagen.
REM               ACHTUNG: Das ist nicht die offizielle Schnittstelle.
REM               Automatisierung verstoesst gegen die Nutzungsbedingungen von
REM               WhatsApp; die Nummer kann gesperrt werden. Besser eine
REM               Zweitnummer der AG verwenden als eine private.
REM    manuell    Es wird nichts verschickt. Die Nachricht liegt fertig im
REM               Dashboard, ein Klick oeffnet WhatsApp mit vorgeschriebenem
REM               Text. Braucht kein Konto.
REM    cloud      Offizielle WhatsApp Cloud API von Meta. Braucht ein
REM               Business-Konto UND eine genehmigte Nachrichtenvorlage.
REM    callmebot  Kostenloser Umweg; jede Nummer braucht dort einen eigenen
REM               Schluessel. Fuer wechselnde Neuzugaenge unpraktisch.
set "WHATSAPP_MODUS=web"

REM  --- nur fuer WHATSAPP_MODUS=web ---
REM  Der Dienst laeuft nur auf 127.0.0.1 und niemals im Netz. Das Token
REM  schuetzt ihn gegen andere Programme auf demselben Rechner - ohne Token
REM  startet er gar nicht.
set "WHATSAPP_WEB_PORT=8099"
set "WHATSAPP_WEB_TOKEN="
REM  Welchen Browser der Dienst fernsteuert. Leer = automatisch suchen:
REM  erst ein selbst geholter Chromium, dann Chrome, dann Edge. Puppeteer laedt
REM  bewusst keinen eigenen Browser mehr herunter - der Download ist 200 MB und
REM  bricht in Schulnetzen gerne mittendrin ab, was jedes weitere "npm install"
REM  scheitern laesst.
set "WHATSAPP_BROWSER="
REM  Wo die Anmeldung liegt. Leer = Unterordner "whatsapp-sitzung" im
REM  Datenordner. Wird dieser Ordner geloescht, muss neu gekoppelt werden.
set "WHATSAPP_WEB_SITZUNG="

REM  --- nur fuer WHATSAPP_MODUS=cloud ---
REM  Aus dem Meta Business Manager -> WhatsApp -> API-Konfiguration.
REM  Das Token dort als DAUERHAFTES Systembenutzer-Token erzeugen; das
REM  Test-Token laeuft nach 24 Stunden ab und der Bot steht dann still.
set "WHATSAPP_TOKEN="
REM  Die "Telefonnummern-ID" der Absendernummer - eine lange Zahl, NICHT die
REM  Telefonnummer selbst.
set "WHATSAPP_NUMMER_ID="
REM  Name der von Meta genehmigten Nachrichtenvorlage. OHNE die kommt bei
REM  neuen Mitgliedern nichts an.
set "WHATSAPP_VORLAGE_NAME="
set "WHATSAPP_API_VERSION=v21.0"

REM  Landesvorwahl fuer Nummern, die mit 0 beginnen.
set "WHATSAPP_LANDESVORWAHL=49"
set "WHATSAPP_GRUPPE=https://chat.whatsapp.com/CvMbVpu81rF0QhsLLjz1Ms"
set "DISCORD_EINLADUNG=https://discord.gg/Y3zEEsD8Ec"
REM -----------------------------------------------------------------------------
REM --- Erinnerungen, Sicherungen, Scoring --------------------------------------
REM  Uhrzeit (deutsche Zeit) fuer die taeglichen Deadline-Erinnerungen.
set "REMINDER_HOUR=7"
set "REMINDERS_ENABLED=true"
set "BACKUPS_ENABLED=true"
set "BACKUP_INTERVAL_HOURS=12"
set "BACKUP_KEEP=2"
set "TRASH_RETENTION_DAYS=30"
REM  Wann der naechtliche Vollabgleich der Leistungswerte laeuft. Im Betrieb
REM  rechnet das Scoring ohnehin bei jedem Ereignis sofort nach.
set "SCORING_HOUR=3"
