# Monhip – Fortschritt

Was in welcher Version umgesetzt wurde, neueste zuerst. Neues kommt oben unter „Seit vX“ (bis zum nächsten Release),
immer mit festen Daten (TT.MM.JJJJ).

**Stand:** 30.10.2026 · **neuestes Release:** v1.4.5

---

## Seit v1.4.5
- 29.10.2026: Spracherkennung nur noch Deutsch oder Englisch – „Automatisch erkennen“ entfernt (ein gespeichertes
  „auto“ wird zu Deutsch).
- 29.10.2026: Wechsel der Oberflächensprache startet Monhip nach kurzem Hinweis (schon in der neuen Sprache) gleich in
  der neuen Sprache neu (`App.restart`, `i18n.tr_in`); läuft gerade eine Antwort, ein Download, eine Auswertung oder
  ein Teamwork-Raum, wird vorher gefragt – „Nein“ = gilt beim nächsten Start.

## v1.4.5 – 29.10.2026
- 29.10.2026: Rechtsklick-Menü (Ausschneiden, Kopieren, Einfügen, Alles markieren) in allen Eingabefeldern –
  Chatfeld, Einstellungen, Dialoge (`widgets.EditMenu`; Einfügen nimmt wie Strg+V auch Bilder und Dateien).
- 29.10.2026: „Stopp“ wirkt sofort – auch während das Modell noch einen langen Prompt einliest oder ein Befehl läuft:
  die Verbindung zum Server wird getrennt (`backend._cancel_on`), Befehle samt Unterprozessen beendet (`Agent._run`),
  andere Werkzeuge kehren sofort zurück (`agent._execute`), Rückfragen danach gelten als abgelehnt.
- 29.10.2026: Flüssigeres Scrollen im Chat (Schritte nach der vergangenen Zeit und mit genauem Windows-Zeitgeber –
  vorher abwechselnd 8 und 24 ms) und Ziehen am Fensterrand (breitere Kachelbilder für die runden Ecken, große
  verdeckte Rahmen als `tk.Frame`): bei 2600 px Fensterbreite 34 → 19 ms je Schritt.
- 29.10.2026: Neues Werkzeug „Programme bedienen“ (Einstellungen → Werkzeuge, Standard aus, nur mit Bildverständnis,
  nie im Teamwork; neues Modul `app/steuerung.py`): `fenster_liste`/`fenster_bedienen` – ein gewähltes Fenster per
  Tastatur, Text, Maus und Mausrad steuern (Tasten als Scancode, auch für Spiele) und danach ein Bild davon sehen.
  Fragt je Fenster, bricht ab, sobald ein anderes Fenster vorn ist; Konsolen, Explorer, Einstellungen, Task-Manager
  und Anmeldefenster sind gesperrt. Klickstellen relativ zum Bild (0–1000) – so trifft das Bildmodell deutlich besser
  als mit Pixeln. Mit echtem Modell getestet (kleines Spiel gelöst, Knopf getroffen, Konsole abgelehnt).

## v1.4.4 – 29.10.2026
- Diese Datei auf den Fortschritt je Version gekürzt (Zukünftige Aufgaben und Grundstruktur gestrichen).
- Alle Commits einheitlich „Update - vX“ mit der neuesten Version, auch die alten (bei jeder Version umbenannt); was
  geändert wurde, steht nur noch hier.
- 29.10.2026: Einheitliche Icons aus der Windows-Icon-Schrift (Segoe Fluent Icons, unter Windows 10 Segoe MDL2
  Assets) statt gemischter Sonderzeichen und Emojis – Seitenleisten, Kopfzeile, Eingabe, Chatverlauf, Teamwork
  (neues Modul `app/icons.py`). Schrift der Oberfläche zentral in `themes.FAMILY` (bleibt „Segoe UI“). Start rund
  280 ms schneller.
- 29.10.2026: Umschalter „Chat | Teamwork“ mit gleicher Schrift für beide Seiten (sprang vorher zwischen fett und
  normal), „Raum beitreten“ mit Personen-Icon statt langem Pfeil; Icons der Seitenleiste auf der Höhe des Texts (saßen
  bei 10 pt 1,5 px zu hoch), Seitenleiste in „Windows-Standard“ jetzt auch 10 pt.
- 29.10.2026: Werkzeuggruppen einzeln abschaltbar (Einstellungen → Werkzeuge, Standard an; spart Kontext): Rechnen,
  Rückgängig, Arbeitsplan, Word/Excel/PowerPoint/PDF, Dateien ordnen & Speicher, PDFs & Bilder bearbeiten,
  Hintergrund-Prozesse, Dateien herunterladen, Zwischenablage (`agent.TOOL_GROUPS`; im Teamwork alle außer der
  Zwischenablage).
- 29.10.2026: Neue Werkzeuge: `create_pdf` (PDF aus Markdown ohne Word, neues Modul `app/pdfsatz.py` – Windows-Schriften
  als Teilmenge eingebettet), `download_file` (Datei aus dem Internet in einen freigegebenen Ordner, „aus dem
  Internet“ markiert, lokale Adressen gesperrt), `clipboard_read`/`clipboard_write` (Zwischenablage, Lesen fragt
  immer). Mit echtem Modell getestet.

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
