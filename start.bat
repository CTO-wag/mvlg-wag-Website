@echo off
setlocal EnableDelayedExpansion
title AG-Plattform V2

REM ============================================================================
REM  Startet die AG-Plattform V2 - und richtet sie beim ersten Mal selbst ein.
REM
REM  Zwei Server:
REM     Website    Port 8000   oeffentliche Seite und Anmeldung
REM     Dashboard  Port 8001   die Verwaltung
REM
REM  Aufruf:
REM    start.bat           Betrieb: beide Server mit Wiederanlauf, Tunnel
REM    start.bat lokal     nur zum Ausprobieren, ohne Wiederanlauf
REM    start.bat pruefen   einrichten und die Testsuite laufen lassen
REM    start.bat neu       Einrichtung erzwingen, dann lokal starten
REM ============================================================================

set "PROJEKT=%~dp0"
cd /d "%PROJEKT%"

if /i "%~1"=="_website" goto :serverschleife_website
if /i "%~1"=="_dashboard" goto :serverschleife_dashboard
if /i "%~1"=="_whatsapp" goto :serverschleife_whatsapp

set "ERZWINGEN=0"
set "NURPRUEFEN=0"
set "PRODUKTION=1"
if /i "%~1"=="neu" set "ERZWINGEN=1" & set "PRODUKTION=0"
if /i "%~1"=="pruefen" set "NURPRUEFEN=1" & set "ERZWINGEN=1" & set "PRODUKTION=0"
if /i "%~1"=="lokal" set "PRODUKTION=0"

echo.
echo  ====================================================================
echo    Wirtschafts- ^& Investment-AG  ^|  Management-System V2
echo  ====================================================================

REM =========================================================== Python finden
set "PY="
set "PYSKRIPT=import hashlib,os,sys;h=lambda p: hashlib.sha256(open(p,'rb').read()).hexdigest()[:16] if os.path.exists(p) else '-';print(str(int(sys.version_info>=(3,10)))+' '+str(sys.version_info[0])+'.'+str(sys.version_info[1])+' '+h(sys.argv[1]))"
for /f "tokens=1-3" %%a in ('python -c "!PYSKRIPT!" "%PROJEKT%requirements.txt" 2^>nul') do (
    set "PY=python" & set "PYOK=%%a" & set "PYVER=%%b" & set "REQ_NEU=%%c"
)
if not defined PY (
    for /f "tokens=1-3" %%a in ('py -3 -c "!PYSKRIPT!" "%PROJEKT%requirements.txt" 2^>nul') do (
        set "PY=py -3" & set "PYOK=%%a" & set "PYVER=%%b" & set "REQ_NEU=%%c"
    )
)
if not defined PY (
    echo.
    echo   Python fehlt.
    echo.
    echo   Bitte von https://www.python.org/downloads/ installieren und dabei
    echo   "Add python.exe to PATH" ankreuzen. Danach dieses Fenster schliessen
    echo   und start.bat erneut aufrufen - der PATH wirkt erst in neuen Fenstern.
    echo.
    pause
    exit /b 1
)
if not "!PYOK!"=="1" (
    echo.
    echo   Python !PYVER! ist zu alt - gebraucht wird mindestens 3.10.
    echo.
    pause
    exit /b 1
)

REM ==================================================== Konfiguration
REM  Beim Umstieg von V1 wird deren config.cmd uebernommen. Das ist die
REM  entscheidende Stelle: mit demselben SECRET_KEY bleiben alle angemeldet,
REM  mit demselben DATEN_DIR laeuft dieselbe Datenbank weiter. Wer hier eine
REM  frische Konfiguration erzeugte, haette am naechsten Morgen eine leere
REM  Plattform und keine Ahnung, wo die Daten geblieben sind.
if not exist "%PROJEKT%config.cmd" (
    if exist "%PROJEKT%..\Management-System-V1\config.cmd" (
        echo  [Einrichtung] config.cmd von V1 uebernommen.
        echo                Gleicher Schluessel, gleiche Daten - niemand muss
        echo                sich neu anmelden oder etwas neu einrichten.
        copy /y "%PROJEKT%..\Management-System-V1\config.cmd" "%PROJEKT%config.cmd" >nul
    ) else (
        echo  [Einrichtung] Neue config.cmd wird angelegt...
        for /f "delims=" %%k in ('%PY% -c "import secrets;print(secrets.token_hex(32))"') do set "NEUKEY=%%k"
        for /f "delims=" %%k in ('%PY% -c "import secrets,string;a=string.ascii_letters+string.digits;print('AG'+''.join(secrets.choice(a) for _ in range(14)))"') do set "NEUPASS=%%k"
        call :schreibe_config
        set "NEUE_CONFIG=1"
    )
)
call "%PROJEKT%config.cmd"

REM ============================================ Python-Pakete (nur bei Bedarf)
call :datenordner_bestimmen
if not exist "%STAND%" mkdir "%STAND%" >nul 2>nul
set "REQ_ALT="
if exist "%STAND%\.pakete-v2" set /p REQ_ALT=<"%STAND%\.pakete-v2"
if "%ERZWINGEN%"=="1" set "REQ_ALT="
if not "!REQ_NEU!"=="!REQ_ALT!" (
    echo  [Einrichtung] Python-Pakete werden installiert...
    %PY% -m pip install --quiet --disable-pip-version-check --upgrade pip >nul 2>nul
    %PY% -m pip install --disable-pip-version-check -r "%PROJEKT%requirements.txt" >"%TEMP%\ag-pip.log" 2>&1
    if errorlevel 1 (
        echo        FEHLGESCHLAGEN. Die letzten Zeilen:
        powershell -NoProfile -Command "Get-Content '%TEMP%\ag-pip.log' -Tail 8 | ForEach-Object { '        ' + $_ }"
        echo.
        pause
        exit /b 1
    )
    > "%STAND%\.pakete-v2" echo !REQ_NEU!
    echo        fertig.
)

REM ==================================================== Datenbank pruefen
echo  [Einrichtung] Datenbank pruefen und auf V2 bringen...
%PY% -c "import sys; sys.path.insert(0,'.'); from kern.migration import migriere; migriere(); from kern.datenbank import SessionLocal; from kern.modelle import User; db=SessionLocal(); print('        bereit -', db.query(User).count(), 'Konto(en).'); db.close()"
if errorlevel 1 (
    echo        FEHLGESCHLAGEN - die Anwendung liess sich nicht laden.
    echo.
    pause
    exit /b 1
)

if defined NEUE_CONFIG (
    >  "%PROJEKT%ERSTE-ANMELDUNG.txt" echo Erste Anmeldung an der AG-Plattform V2
    >> "%PROJEKT%ERSTE-ANMELDUNG.txt" echo --------------------------------------
    >> "%PROJEKT%ERSTE-ANMELDUNG.txt" echo Adresse:  http://localhost:8000/login
    >> "%PROJEKT%ERSTE-ANMELDUNG.txt" echo E-Mail:   %DEFAULT_ADMIN_EMAIL%
    >> "%PROJEKT%ERSTE-ANMELDUNG.txt" echo Passwort: %DEFAULT_ADMIN_PASSWORD%
    >> "%PROJEKT%ERSTE-ANMELDUNG.txt" echo.
    >> "%PROJEKT%ERSTE-ANMELDUNG.txt" echo Passwort nach der ersten Anmeldung unter "Mein Konto" aendern
    >> "%PROJEKT%ERSTE-ANMELDUNG.txt" echo und diese Datei danach loeschen.
    echo.
    echo    ERSTE ANMELDUNG
    echo      Adresse:  http://localhost:8000/login
    echo      E-Mail:   %DEFAULT_ADMIN_EMAIL%
    echo      Passwort: %DEFAULT_ADMIN_PASSWORD%
    echo      ^(steht auch in ERSTE-ANMELDUNG.txt^)
)

REM ==================================================== nur pruefen
if "%NURPRUEFEN%"=="1" (
    echo.
    echo  [Pruefen] Testsuite laeuft...
    %PY% -m unittest discover -s tests -t . >"%TEMP%\ag-tests.log" 2>&1
    if errorlevel 1 (
        echo        FEHLGESCHLAGEN:
        powershell -NoProfile -Command "Select-String -Path '%TEMP%\ag-tests.log' -Pattern '^(FAIL|ERROR):|^Ran |^FAILED' | ForEach-Object { '        ' + $_.Line }"
    ) else (
        powershell -NoProfile -Command "Select-String -Path '%TEMP%\ag-tests.log' -Pattern '^Ran ' | ForEach-Object { '        ' + $_.Line + ' - alle bestanden.' }"
    )
    echo.
    pause
    exit /b 0
)

REM ==================================== WhatsApp-Dienst (nur bei MODUS=web)
REM  Ein Node-Beiwagen mit whatsapp-web.js. Er haelt eine WhatsApp-Sitzung
REM  offen; gekoppelt wird einmalig per QR-Code im Dashboard.
if /i "%WHATSAPP_MODUS%"=="web" (
    where node >nul 2>nul
    if errorlevel 1 (
        echo  [WhatsApp] Node.js fehlt - der Bot bleibt aus.
        echo             Von https://nodejs.org installieren, dann start.bat
        echo             erneut aufrufen. Alles andere laeuft ohne Node.
        set "WA_START=0"
    ) else (
        if not exist "%PROJEKT%whatsapp-dienst\node_modules" (
            echo  [WhatsApp] Node-Pakete werden installiert. Das dauert beim
            echo             ersten Mal ein paar Minuten. Ein eigener
            echo             Browser wird NICHT geladen - der Dienst
            echo             steuert Chrome oder Edge fern.
            pushd "%PROJEKT%whatsapp-dienst"
            call npm install --no-audit --no-fund >"%TEMP%\ag-npm.log" 2>&1
            if errorlevel 1 (
                echo        FEHLGESCHLAGEN. Die letzten Zeilen:
                powershell -NoProfile -Command "Get-Content '%TEMP%\ag-npm.log' -Tail 10 | ForEach-Object { '        ' + $_ }"
                set "WA_START=0"
            ) else (
                echo        fertig.
                set "WA_START=1"
            )
            popd
        ) else (
            set "WA_START=1"
        )
    )
) else (
    set "WA_START=0"
)

REM =============================================================== Starten
echo.
if "%WA_START%"=="1" (
    start "AG-WhatsApp" cmd /k ""%~f0" _whatsapp"
    echo  [Start] WhatsApp-Dienst auf Port %WHATSAPP_WEB_PORT%.
    echo          Kopplung per QR-Code im Dashboard unter "WhatsApp-Bot".
)
if "%PRODUKTION%"=="1" (
    start "AG-Website (Dauerbetrieb)"   cmd /k ""%~f0" _website"
    start "AG-Dashboard (Dauerbetrieb)" cmd /k ""%~f0" _dashboard"
    echo  [Start] Website auf Port 8000 und Dashboard auf Port 8001, mit Wiederanlauf.
) else (
    start "AG-Website"   cmd /k "cd /d "%PROJEKT%" && call config.cmd && %PY% server.py website"
    start "AG-Dashboard" cmd /k "cd /d "%PROJEKT%" && call config.cmd && %PY% server.py dashboard"
    echo  [Start] Website auf Port 8000 und Dashboard auf Port 8001.
)

REM  Der Tunnel bleibt aus, solange er nicht ausdruecklich eingeschaltet ist.
REM  Zwei Rechner mit denselben Tunnel-Zugangsdaten teilen sich den Verkehr
REM  der oeffentlichen Adresse - die Haelfte aller Besucher landet dann auf
REM  dem falschen PC.
if /i "%TUNNEL_STARTEN%"=="true" (
    if exist "%USERPROFILE%\.cloudflared\config.yml" (
        where cloudflared >nul 2>nul
        if errorlevel 1 (
            echo  [Tunnel] cloudflared ist nicht installiert - uebersprungen.
        ) else (
            start "Cloudflare" cmd /k "cloudflared tunnel run mvlg-wag"
            echo  [Start] Cloudflare-Tunnel.
        )
    ) else (
        echo  [Tunnel] Keine Zugangsdaten in %%USERPROFILE%%\.cloudflared gefunden.
    )
) else (
    echo  [Tunnel] Aus. Einschalten mit  set "TUNNEL_STARTEN=true"  in config.cmd.
)

echo.
echo  ====================================================================
echo    Website:    http://localhost:8000
echo    Dashboard:  http://localhost:8001
echo  ====================================================================
echo.
echo    Angemeldet wird ueber die Website. Das Sitzungs-Cookie gilt fuer
echo    beide Server - Cookies werden nicht nach Port getrennt.
echo.
echo    Zum Beenden die geoeffneten Fenster schliessen.
echo.
endlocal
goto :eof


REM ============================================================================
REM  Wiederanlaufschleifen
REM
REM  Faellt ein Server aus, startet er nach kurzer Pause neu. Jeder Neustart
REM  landet mit Zeitstempel im Protokoll - sonst merkt niemand, dass etwas
REM  nicht stimmt. Bricht er dagegen fuenfmal hintereinander binnen Sekunden
REM  ab, ist das kein Ausfall, sondern ein Fehler: dann haelt die Schleife an
REM  und laesst die Meldung stehen, statt sie im Sekundentakt wegzuscrollen.
REM ============================================================================
:serverschleife_website
set "WELCHER=website"
set "TITEL=AG-Website"
goto :serverschleife
:serverschleife_dashboard
set "WELCHER=dashboard"
set "TITEL=AG-Dashboard"
goto :serverschleife

REM  Der WhatsApp-Beiwagen laeuft in einer eigenen Schleife: er stuerzt
REM  haeufiger ab als die Server (Chromium, wackelige Netzverbindung), und
REM  jeder Absturz wuerde sonst den Bot bis zum naechsten Neustart lahmlegen.
:serverschleife_whatsapp
setlocal EnableDelayedExpansion
set "PROJEKT=%~dp0"
call "%PROJEKT%config.cmd"
call :datenordner_bestimmen
if not defined WHATSAPP_WEB_SITZUNG set "WHATSAPP_WEB_SITZUNG=%STAND%\whatsapp-sitzung"
set "LOG=%STAND%\server-whatsapp.log"
title AG-WhatsApp - Dauerbetrieb
:wa_lauf
for /f "delims=" %%z in ('python -c "import datetime;print(datetime.datetime.now().strftime('%%Y-%%m-%%d %%H:%%M:%%S'))" 2^>nul') do set "ZEIT=%%z"
echo [!ZEIT!] WhatsApp-Dienst startet.>> "%LOG%"
pushd "%PROJEKT%whatsapp-dienst"
node dienst.js
popd
echo.
echo   WhatsApp-Dienst beendet. Neustart in 10 Sekunden - Fenster schliessen bricht ab.
timeout /t 10 /nobreak >nul
goto :wa_lauf

:serverschleife
setlocal EnableDelayedExpansion
set "PROJEKT=%~dp0"
call "%PROJEKT%config.cmd"
call :datenordner_bestimmen
set "LOG=%STAND%\server-%WELCHER%.log"
set "PY="
for /f "delims=" %%p in ('python -c "print(1)" 2^>nul') do if "%%p"=="1" set "PY=python"
if not defined PY set "PY=py -3"
set "SCHNELL=0"
title %TITEL% - Dauerbetrieb

:lauf
for /f "delims=" %%z in ('%PY% -c "import datetime;print(datetime.datetime.now().strftime('%%Y-%%m-%%d %%H:%%M:%%S'))"') do set "ZEIT=%%z"
echo [!ZEIT!] %WELCHER% startet.>> "%LOG%"
for /f "delims=" %%s in ('%PY% -c "import time;print(int(time.time()))"') do set "VORHER=%%s"
pushd "%PROJEKT%"
%PY% server.py %WELCHER%
popd
for /f "delims=" %%s in ('%PY% -c "import time;print(int(time.time()))"') do set "NACHHER=%%s"
set /a LIEF=NACHHER-VORHER
for /f "delims=" %%z in ('%PY% -c "import datetime;print(datetime.datetime.now().strftime('%%Y-%%m-%%d %%H:%%M:%%S'))"') do set "ZEIT=%%z"
echo [!ZEIT!] %WELCHER% beendet nach !LIEF! s.>> "%LOG%"
if !LIEF! LSS 10 (set /a SCHNELL+=1) else (set "SCHNELL=0")
if !SCHNELL! GEQ 5 (
    echo.
    echo   %TITEL% ist fuenfmal hintereinander sofort abgebrochen.
    echo   Das ist kein Ausfall, sondern ein Fehler - die Meldung steht oben.
    echo   Protokoll: %LOG%
    echo.
    echo [!ZEIT!] Abbruch: fuenf Sofortabbrueche hintereinander.>> "%LOG%"
    pause
    endlocal
    exit /b 1
)
echo.
echo   Beendet. Neustart in 5 Sekunden - Fenster schliessen bricht ab.
%PY% -c "import time;time.sleep(5)"
goto :lauf


REM ============================================================================
REM  Bestimmt, wo die Daten liegen. Muss nach dem Einlesen von config.cmd
REM  aufgerufen werden - vorher ist DATEN_DIR noch nicht bekannt.
REM
REM  Das pushd macht relative Angaben ("..\..\daten") am Programmordner fest.
REM  Die Zeile davor entfernt Anfuehrungszeichen aus dem Wert: wer
REM      set DATEN_DIR="D:\AG-Daten"
REM  schreibt statt der hier ueblichen Form, haette sie sonst mitten im Pfad.
REM  Die Anwendung wirft sie ebenfalls weg; beide muessen zum selben Ordner
REM  kommen.
REM ============================================================================
:datenordner_bestimmen
set "STAND=%PROJEKT%..\daten"
if not defined DATEN_DIR goto :eof
set "ROH=%DATEN_DIR%"
set ROH=!ROH:"=!
if not defined ROH goto :eof
pushd "%PROJEKT%"
for %%d in ("!ROH!") do set "STAND=%%~fd"
popd
goto :eof


REM ============================================================================
REM  Schreibt eine frische config.cmd. Bewusst als Unterprogramm und nicht in
REM  einem if-Block: die Eingabeaufforderung liest einen Klammerblock am Stueck
REM  ein und verschluckt dabei Klammern im Text.
REM ============================================================================
:schreibe_config
set "C=%PROJEKT%config.cmd"
>  "%C%" echo @echo off
>> "%C%" echo REM ==========================================================================
>> "%C%" echo REM  Konfiguration der AG-Plattform V2 - von start.bat angelegt.
>> "%C%" echo REM
>> "%C%" echo REM  Schreibweise:  set "NAME=Wert"   - Anfuehrungszeichen aussen herum,
>> "%C%" echo REM  damit Sonderzeichen ankommen und keine Leerzeichen ans Ende geraten.
>> "%C%" echo REM
>> "%C%" echo REM  ACHTUNG: Hier stehen Zugangsdaten im Klartext. Nicht weitergeben,
>> "%C%" echo REM  nicht auf GitHub hochladen.
>> "%C%" echo REM ==========================================================================
>> "%C%" echo.
>> "%C%" echo REM --- Sitzungsschluessel: nicht mehr aendern --------------------------------
>> "%C%" echo REM  Sonst werden bei jedem Neustart alle Anmeldungen ungueltig.
>> "%C%" echo set "SECRET_KEY=!NEUKEY!"
>> "%C%" echo.
>> "%C%" echo REM --- Erster Zugang ---------------------------------------------------------
>> "%C%" echo set "DEFAULT_ADMIN_EMAIL=vorstand@ag.local"
>> "%C%" echo set "DEFAULT_ADMIN_PASSWORD=!NEUPASS!"
>> "%C%" echo.
>> "%C%" echo REM --- Datenordner ----------------------------------------------------------
>> "%C%" echo REM  Leer = der Ordner "daten" neben diesem Programmordner. Relative
>> "%C%" echo REM  Angaben zaehlen ab dem Programmordner.
>> "%C%" echo set "DATEN_DIR=../../daten"
>> "%C%" echo.
>> "%C%" echo REM --- Betrieb --------------------------------------------------------------
>> "%C%" echo set "SITE_URL=http://localhost:8000"
>> "%C%" echo set "WEBSITE_PORT=8000"
>> "%C%" echo set "DASHBOARD_PORT=8001"
>> "%C%" echo REM  HTTPS_ONLY_COOKIES=false ist noetig, solange ueber http://localhost
>> "%C%" echo REM  gearbeitet wird - sonst schickt der Browser das Cookie nicht zurueck.
>> "%C%" echo set "HTTPS_ONLY_COOKIES=false"
>> "%C%" echo REM  Nur auf true, wenn wirklich ein Proxy davorhaengt (z.B. der Tunnel).
>> "%C%" echo set "TRUST_PROXY_HEADERS=false"
>> "%C%" echo set "HSTS_ENABLED=false"
>> "%C%" echo REM  development = Testbetrieb. Fuer den echten Betrieb: production.
>> "%C%" echo set "APP_ENV=development"
>> "%C%" echo.
>> "%C%" echo REM --- Cloudflare-Tunnel -----------------------------------------------------
>> "%C%" echo set "TUNNEL_STARTEN=false"
>> "%C%" echo.
>> "%C%" echo REM --- E-Mail-Versand (optional) ---------------------------------------------
>> "%C%" echo set "SMTP_HOST="
>> "%C%" echo set "SMTP_PORT=587"
>> "%C%" echo set "SMTP_SECURITY=starttls"
>> "%C%" echo set "SMTP_USER="
>> "%C%" echo set "SMTP_PASSWORD="
>> "%C%" echo set "SMTP_FROM="
>> "%C%" echo set "SMTP_FROM_NAME=Wirtschafts- & Investment-AG"
>> "%C%" echo set "MAIL_REPLY_TO="
>> "%C%" echo.
>> "%C%" echo REM --- Push-Benachrichtigungen (ntfy) ----------------------------------------
>> "%C%" echo set "NTFY_BASE_URL=https://ntfy.sh"
>> "%C%" echo set "DELIVERY_LOG_TAGE=30"
>> "%C%" echo.
>> "%C%" echo REM --- WhatsApp-Bot ----------------------------------------------------------
>> "%C%" echo REM  manuell   = nichts wird verschickt, das Dashboard bietet einen
>> "%C%" echo REM              fertigen Link zum Antippen (Vorgabe, geht immer)
>> "%C%" echo REM  callmebot = kostenlos, je Nummer ein Schluessel
>> "%C%" echo REM  cloud     = offizielle WhatsApp Cloud API von Meta
>> "%C%" echo set "WHATSAPP_MODUS=manuell"
>> "%C%" echo set "WHATSAPP_TOKEN="
>> "%C%" echo set "WHATSAPP_NUMMER_ID="
>> "%C%" echo set "WHATSAPP_LANDESVORWAHL=49"
>> "%C%" echo.
>> "%C%" echo REM --- Erinnerungen und Sicherungen ------------------------------------------
>> "%C%" echo set "REMINDER_HOUR=7"
>> "%C%" echo set "REMINDERS_ENABLED=true"
>> "%C%" echo set "BACKUPS_ENABLED=true"
>> "%C%" echo set "BACKUP_INTERVAL_HOURS=12"
>> "%C%" echo set "BACKUP_KEEP=2"
>> "%C%" echo set "TRASH_RETENTION_DAYS=30"
>> "%C%" echo set "SCORING_HOUR=3"
>> "%C%" echo.
goto :eof
