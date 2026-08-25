@echo off
cd /d "%~dp0"

REM ============================================================================
REM  Lokale Entwicklung
REM
REM  Dieser Starter benutzt absichtlich NICHT config.cmd. Die dort eingetragenen
REM  Produktionswerte wuerden sonst die Live-Datenbank und die Live-Ports
REM  verwenden. Entwicklung und Betrieb koennen dadurch gleichzeitig laufen.
REM ============================================================================

pip install -r requirements.txt

REM Eigene lokale SQLite-Datenbank statt Supabase/Produktionsdatenbank.
set "DATEN_DIR=%~dp0daten-entwicklung"
set "DATABASE_URL="

REM Andere Ports als der Produktivbetrieb (8000/8001).
set "WEBSITE_PORT=8010"
set "DASHBOARD_PORT=8011"
set "WEBSITE_URL=http://localhost:8010"
set "DASHBOARD_URL=http://localhost:8011"

REM Lokale Sicherheits- und Betriebswerte.
set "APP_ENV=development"
set "SECRET_KEY=entwicklung-nicht-fuer-produktivbetrieb"
set "HTTPS_ONLY_COOKIES=false"
set "TRUST_PROXY_HEADERS=false"
set "HSTS_ENABLED=false"
set "SMTP_HOST="
set "REMINDERS_ENABLED=false"
set "BACKUPS_ENABLED=false"
set "AUSFALL_WORKER_URL="
set "AUSFALL_SCHLUESSEL="
set "WHATSAPP_MODUS=manuell"

echo Lokale Entwicklung:
echo   Website:   http://localhost:8010
echo   Dashboard: http://localhost:8011
echo   Daten:     %DATEN_DIR%
echo.
echo Die Produktionsinstanz auf Port 8000/8001 bleibt unveraendert.
echo.

start "AG-Entwicklung Website" cmd /k "cd /d "%~dp0" && python server.py website --neuladen"
start "AG-Entwicklung Dashboard" cmd /k "cd /d "%~dp0" && python server.py dashboard --neuladen"

REM fertig
