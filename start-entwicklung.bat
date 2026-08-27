@echo off
cd /d "%~dp0"

REM ============================================================================
REM  Lokale Entwicklung
REM
REM  Laeuft mit UND ohne config.cmd:
REM
REM    * Ist eine config.cmd da, wird sie gelesen. Alles, was Entwicklung und
REM      Betrieb gemeinsam haben - Mailvordruecke, WhatsApp-Modus, ntfy - ist
REM      damit da, ohne es hier zweimal zu pflegen.
REM    * Ist keine da, startet der Rechner trotzdem. Wer das Projekt frisch
REM      auscheckt, soll nicht erst Geheimnisse besorgen muessen, um die Seite
REM      einmal zu sehen.
REM
REM  In BEIDEN Faellen werden danach die Werte ueberschrieben, bei denen
REM  Entwicklung und Betrieb auseinandergehen muessen: eigene Datenbank,
REM  eigene Ports, kein Mailversand, kein Auffangnetz. Diese Zeilen stehen
REM  deshalb NACH dem Aufruf von config.cmd - die letzte Zuweisung gewinnt.
REM ============================================================================

pip install -r requirements.txt

if exist "%~dp0config.cmd" (
  call "%~dp0config.cmd"
  set "KONFIG_HERKUNFT=config.cmd"
) else (
  set "KONFIG_HERKUNFT=Standardwerte (keine config.cmd gefunden)"
)

REM  Sagt server.py, dass die Konfiguration bereits eingelesen ist. Ohne diese
REM  Zeile liest server.py config.cmd ein zweites Mal - und weil "set VAR=" in
REM  cmd eine Variable LOESCHT statt sie zu leeren, kaemen genau die Werte
REM  zurueck, die unten mit Absicht geleert werden: Produktionsdatenbank,
REM  Mailversand, Auffangnetz. Die Entwicklung liefe dann auf den Livedaten.
set "KONFIG_GELESEN=1"

REM --- Ab hier gilt Entwicklung, egal was in der config.cmd stand -----------

REM Eigene lokale SQLite-Datenbank statt Supabase/Produktionsdatenbank.
set "DATEN_DIR=%~dp0daten-entwicklung"
set "DATABASE_URL="

REM Andere Ports als der Produktivbetrieb (8000/8001).
set "WEBSITE_PORT=8010"
set "DASHBOARD_PORT=8011"
set "WEBSITE_URL=http://localhost:8010"
set "DASHBOARD_URL=http://localhost:8011"
set "SITE_URL=http://localhost:8010"
set "COOKIE_DOMAIN="

REM Lokale Sicherheits- und Betriebswerte.
set "APP_ENV=development"
set "SECRET_KEY=entwicklung-nicht-fuer-produktivbetrieb"
set "HTTPS_ONLY_COOKIES=false"
set "TRUST_PROXY_HEADERS=false"
set "HSTS_ENABLED=false"

REM Nichts, was nach draussen geht: keine Mails an echte Adressen, keine
REM Meldungen ans Auffangnetz, keine Sicherungen der Entwicklungsdatenbank.
set "SMTP_HOST="
set "REMINDERS_ENABLED=false"
set "BACKUPS_ENABLED=false"
set "AUSFALL_WORKER_URL="
set "AUSFALL_SCHLUESSEL="
set "WHATSAPP_MODUS=manuell"

echo.
echo Lokale Entwicklung:
echo   Konfiguration: %KONFIG_HERKUNFT%
echo   Website:   http://localhost:8010
echo   Dashboard: http://localhost:8011
echo   Daten:     %DATEN_DIR%
echo.
echo Die Produktionsinstanz auf Port 8000/8001 bleibt unveraendert.
echo.

start "AG-Entwicklung Website" cmd /k "cd /d "%~dp0" && python server.py website --neuladen"
start "AG-Entwicklung Dashboard" cmd /k "cd /d "%~dp0" && python server.py dashboard --neuladen"

REM fertig
