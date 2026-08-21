# Sicherheitslücken melden

Wenn du eine Lücke findest, melde sie bitte, bevor sie öffentlich wird:

**cto@tech.mvlg-wag.de**

Dieselbe Adresse steht in `/.well-known/security.txt`.

Wir sind eine Schüler-AG, kein Unternehmen mit Bereitschaftsdienst. Wir
antworten aber innerhalb einer Woche.

## Hilfreich sind

- was du gemacht hast, Schritt für Schritt
- was dabei herauskam
- ob du an Daten gekommen bist, die dir nicht gehören

Im Zweifel lieber melden. Eine Fehlmeldung kostet uns fünf Minuten.

## Was wir zusagen

Wir zeigen dich nicht an, solange du nicht mehr getan hast als nötig, um die
Lücke zu belegen. Auf Wunsch nennen wir dich beim Beheben – oder
ausdrücklich nicht. Geld können wir nicht bieten.

## Besonders schützenswert

Die Anwendung verwaltet Namen, E-Mail-Adressen und Telefonnummern von
Schülerinnen und Schülern, teilweise minderjährig. Alles, was daran kommt,
hat Vorrang.

## Schon vorhanden

Damit du nicht suchst, was es nicht gibt:

- Passwörter als bcrypt-Hash
- TOTP als zweiter Faktor, mit Ersatzcodes
- CSRF-Token an jedem Formular, an die Sitzung gebunden
- CSP mit Nonce je Anfrage, kein `unsafe-inline` für Skripte
- HSTS, `X-Frame-Options: DENY`, `nosniff`
- Sitzungen an ein Gerätemerkmal gebunden, einzeln beendbar
- Anmeldeversuche begrenzt, Konten danach vorübergehend gesperrt
- Rechte an Rollen, nicht an einzelnen Konten
