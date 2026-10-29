# Monhip – Fortschritt

Was in welcher Version umgesetzt wurde, neueste zuerst. Neues kommt oben unter „Seit vX“ (bis zum nächsten Release),
immer mit festen Daten (TT.MM.JJJJ).

**Stand:** 29.10.2026 · **neuestes Release:** v1.4.3

---

## Seit v1.4.3
- Diese Datei auf den Fortschritt je Version gekürzt (Zukünftige Aufgaben und Grundstruktur gestrichen).
- Alle Commits einheitlich „Update - v1.4.3“, auch die alten (umbenannt); was geändert wurde, steht nur noch hier.
- 29.10.2026: Einheitliche Icons aus der Windows-Icon-Schrift (Segoe Fluent Icons, unter Windows 10 Segoe MDL2
  Assets) statt gemischter Sonderzeichen und Emojis – Seitenleisten, Kopfzeile, Eingabe, Chatverlauf, Teamwork
  (neues Modul `app/icons.py`). Schrift der Oberfläche zentral in `themes.FAMILY` (bleibt „Segoe UI“). Start rund
  280 ms schneller.

## v1.4.3 – 29.10.2026
- Teamwork: eigene KI hat immer alle Werkzeuge; Fenster „Erlaubnis“ mit drei Stufen (Alles erlauben, Eingeschränkt,
  Strikt).
- Teamwork-Seitenleiste nur noch Knöpfe, „Projektordner“ als Knopf, „Raum schließen“ fest unten über „Einstellungen“.
- Kontextmenüs im Design (kein heller Rahmen mehr), sauber runde Ecken am Umschalter „Chat | Teamwork“.
- Commits heißen nur noch nach der Version; `AGENTS.md` wieder entfernt.

## v1.4.2 – 28.10.2026
- Ziehen am Fensterrand 3–4-mal so flüssig (`themes.no_resize_redraw`).

## v1.4.1 – 27.10.2026
- Kontext wieder frei einstellbar (Automatik „auto“ entfernt).
- Antworten in langen Chats beginnen viel schneller (keine Uhrzeit mehr im System-Prompt).
- Flüssigeres Ziehen (feste Chat-Spalte); PowerShell-Hinweise für die KI, knappere Werkzeug-Texte.

## v1.4 – 27.10.2026
- 19 Agenten-Werkzeuge: rechnen, Git & GitHub, Checkpoints/Rückgängig, Arbeitsplan, Hintergrund-Prozesse, Dateien
  ordnen, Speicher analysieren, PDFs und Bilder bearbeiten, Projekt-Anweisungen (`MONHIP.md`/`AGENTS.md`/`CLAUDE.md`).
- README auf Englisch.

## v1.3 – 27.10.2026
- Oberfläche auf Deutsch und Englisch (erkennt die Windows-Sprache, Auswahl in den Einstellungen).
- Experten-Modus: eingescannte PDFs bis 500 Seiten, Abschrift Seite für Seite fortsetzbar.
- README ausführlich, diese Datei angelegt.

## v1.2 – 25.10.2026
- Teamwork: KI wartet nach @Name auf die Antworten der anderen KIs und macht dann selbst weiter.

## v1.1 – 25.10.2026
- Teamwork: Kontextanzeige und Zusammenfassen, Hauptauftrag (`@main`), Arbeitsstand, Aufgabenliste, Teamstand,
  `ki_fragen`, „Alle KIs stoppen“.
- Größeres Startfenster, scrollbare Seitenleiste; schnellerer Moduswechsel und Beitritt zu langen Räumen.

## v1.0 – 25.10.2026
- Experten-Modus: Ordner mit vielen Dokumenten auswerten (Zusammenfassungen, Volltextindex, Scans per Bildverständnis).

## Vor v1.0
- Chat-Oberfläche mit Chatliste, Einstellungen, drei Designs; eigene Chatansicht (Markdown, Denkprozess, Werkzeuge).
- Eigener llama.cpp-Download, Modelle in `modelle/` – unabhängig von LM Studio.
- Agent: freigegebene Ordner, Word/Excel/PowerPoint, PowerShell/Python, Websuche, Gedächtnis, Erinnerungen,
  Bildschirmfoto.
- Bilder verstehen, Drag & Drop, Spracherkennung (whisper.cpp), Nachrichten bearbeiten (Fassungen) und zitieren.
- Kontextanzeige, automatisches Zusammenfassen, „Kontext voll“ mitten in der Antwort.
- Teamwork: Räume übers Netz, @Name/@alle, Dateien teilen, gemeinsamer Projektordner.
- Separater Installer (eigenes Programm, nicht in diesem Repo).
