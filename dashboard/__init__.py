"""Das Dashboard - Port 8001.

Eigener Server, damit sich die Verwaltung getrennt haerten, getrennt neu
starten und im Ernstfall getrennt abschalten laesst. Angemeldet wird ueber
die Website; das Sitzungs-Cookie gilt fuer beide, weil Cookies nicht nach
Port getrennt werden.
"""
