"""Gemeinsamer Kern von Website und Dashboard.

Beide Server-Prozesse benutzen dieselben Module aus diesem Paket: dieselben
Modelle, dieselben Rechte, dieselbe Sicherheitsschicht. Damit kann es keine
zwei Auslegungen derselben Regel geben - genau der Fehler, den eine Trennung
in zwei Anwendungen sonst leicht einlaedt.
"""
