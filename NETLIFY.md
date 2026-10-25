# Statische Website und Bewerbungen

Die Quelldateien der öffentlichen Website liegen in `wag-koblenz/dist`.
Ausgeliefert werden sie auf `mvlg-wag.de` direkt vom Cloudflare Worker; ein
Netlify-Projekt oder Netlify-Deployment ist dafür nicht erforderlich. Der
Worker wird aus den Dateien dieses Verzeichnisses gebaut:

```
python werkzeuge/auffangnetz_bauen.py
cd cloudflare
npx wrangler deploy
```

Die öffentliche Seite funktioniert unabhängig vom Plattform-Backend. Das
Kontaktformular öffnet einen E-Mail-Entwurf. Bewerbungen sendet der Browser
direkt an `https://mvlg-wag.de/__ausfall/bewerben`; der Worker speichert sie
in Cloudflare KV, auch wenn Website- und Dashboard-Server nicht erreichbar
sind. Sobald das Backend wieder läuft, holt es die Bewerbungen alle fünf
Minuten ab, trägt sie in der Bewerbungsverwaltung ein und bestätigt sie erst
dann beim Worker. Ohne Backend-Konfiguration bleiben sie höchstens 28 Tage in
KV.

Damit das automatische Abholen funktioniert, müssen auf dem Backend
`AUSFALL_WORKER_URL=https://mvlg-wag.de` und das Worker-Secret
`AUSFALL_SCHLUESSEL` in `config.cmd` gesetzt sein. Die Plattform muss nach dem
Eintragen neu gestartet werden.

Das Management-System benötigt wegen Datenbank, Sitzungen, Hintergrundjobs,
Kalender-Abos und WhatsApp einen zustandsbehafteten Server und wird deshalb
nicht als Netlify-Funktion veröffentlicht. Die Landingpage verlinkt Mitglieder
weiterhin auf `https://app.mvlg-wag.de`; persönliche Kalender-Abos werden von
diesem Server unter `/dashboard/kalender/<token>.ics` ausgeliefert.

Der Cloudflare Worker enthält dieselben Dateien aus `wag-koblenz/dist` als
laufende Website, nicht nur als Ausfallkopie. Nach Änderungen an der Website
muss vor dem Worker-Deployment `python werkzeuge/auffangnetz_bauen.py` laufen.
