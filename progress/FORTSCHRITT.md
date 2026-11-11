# Monhip – Fortschritt

Was in welcher Version neu ist, neueste zuerst. Neues kommt oben unter „Seit vX“ (bis zum nächsten Release).

## Grundsatz
- **Linux:** Jede Neuerung gibt es auch für Linux. Systemabhängiges gehört nach `app/plattform.py` bzw. in einen
  Linux-Zweig; braucht Linux ein Systempaket, steht es in der Paketliste der README und im Paket. Geht etwas unter
  Linux nicht oder anders, steht das hier.
- **Tests:** Neue Funktionen bekommen Tests, die auf Windows und Linux laufen (bei jedem Push auf GitHub).
- **Kurz halten:** Je Neuerung ein Stichpunkt mit Datum (TT.MM.JJJJ), höchstens zwei Zeilen – was neu ist, nicht wie
  es gebaut ist. Keine Messwerte, Namen, Pfade oder Hardware-Angaben.
- **Commits** heißen nur „Update - vX“. **Release-Texte** nennen die Neuerungen kurz, in wenigen Sätzen.
- **Ordner im Repository:** `Monhip.pyw`, `app/`, `README.md`, `installer/` (nur `Monhip-Setup.exe` und
  `monhip_<Version>_all.deb`) und `progress/` (diese Datei, `tests/`, `tools/`). Die Quellen der Installer bleiben
  auf dem Entwicklungsrechner.
