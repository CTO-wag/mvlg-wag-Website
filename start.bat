@echo off
cd /d "%~dp0"
echo Dependencies installieren...
python -m pip install --quiet -r requirements.txt
cd /d "%~dp0whatsapp-dienst" && call npm install --no-audit --no-fund

start "AG-Dashboard" cmd /k "cd /d "%~dp0" && call config.cmd && python server.py"
start "AG-WhatsApp"  cmd /k "cd /d "%~dp0" && call config.cmd && cd /d "%~dp0whatsapp-dienst" && node dienst.js"