# Monhip – Fortschritt

Gemeinsame Arbeitsliste für alle Menschen und KI-Modelle, die an Monhip mitarbeiten. Wer mit einer KI arbeitet, lässt
sie zuerst diese Datei lesen. Alle Absprachen stehen nur hier (keine `AGENTS.md` o. Ä.).

**Stand:** 29.10.2026 · **neuestes Release:** v1.4.3

**Ablauf:**
- `git pull`, diese Datei lesen.
- Aufgabe unter 1. markieren: „**in Arbeit:** Wer (Mensch + Modell), seit TT.MM.JJJJ“ – committen, pushen, dann erst
  anfangen. Was jemand anders in Arbeit hat, nicht anfassen.
- Fertig: Eintrag unter 1. löschen, unter 2. kurz eintragen – im selben Commit wie die Änderung.
- Immer feste Daten (TT.MM.JJJJ). Widerspricht diese Datei dem Code, gilt der Code – Datei korrigieren.

---

## 1. Zukünftige Aufgaben

- **Mit echten Modellen testen:** Zusammenfassen und „Kontext voll“ (Chat und Teamwork), Experten-Modus mit großem
  Ordner und dickem Scan, KI-Austausch und Erlaubnis-Stufen im Teamwork (bisher meist mit nachgestelltem Server).
- **Teamwork zwischen zwei echten Rechnern** testen (z. B. über Tailscale) – bisher nur auf einem PC.
- **Teamwork schneller:** Teilnehmer, Teamstand und Aufgaben aus dem System-Prompt ans Ende verschieben (z. B. an die
  auslösende Nachricht) – sonst liest llama.cpp bei jeder Änderung den ganzen Raumverlauf neu ein.
- **Werkzeuge, Schritt 2:** Datei herunterladen, Zwischenablage, PDF erzeugen.
- **Agenten-Werkzeuge (v1.4):** mit kleinem Modell (7–14B) testen; Schalter je Werkzeuggruppe (alle an ≈ 2 600 Tokens,
  `rechnen` immer an); Knopf „Rückgängig“ unter einer Antwort; laufende Hintergrund-Prozesse anzeigen.
- **Experten-Modus:** „Auswertung löschen“ in der Oberfläche.
- **Reserve beim Laden** (`backend.fit_margin`) kleiner testen – ~1,7 GB Grafikspeicher blieben frei. Kontext dabei
  nicht verkleinern.
- **README abgleichen:** Python 3.13 statt 3.12; `raeume/`, `sicherungen/`, `checkpoints/` unter „Lokale Daten“.
- **Bildbereich „Chat | Teamwork | Bilder“** (besprochen, nicht begonnen):
  - stable-diffusion.cpp (`sd-cli.exe` als Unterprozess, eingebunden wie whisper.cpp), Modell Qwen-Image 2.1 (~15 GB).
  - Beim Wechsel Sprachmodell entladen (beide passen nicht gleichzeitig in 16 GB).
  - Links Galerie, Mitte Vorschau, unten Beschreibung; Ablage `server/`, `modelle/bild/`, `chats/` (Installer bleibt).
  - Zuerst messen: Zeit und Grafikspeicher bei 1024 × 1024.
- **Video** (nach dem Bildbereich): gleiche Technik, Reiter „Bild | Video“, Einstieg Wan 2.2 TI2V 5B.

---

## 2. Umgesetzte Aufgaben

Neueste Version zuerst. Commits ohne eigenes Release kommen unter „Seit …“.

### Seit v1.4.3
- Diese Datei in drei Teile gegliedert (Zukünftige Aufgaben, Umgesetzte Aufgaben, Grundstruktur).
- Alle Commits einheitlich „Update - v1.4.3“, auch die alten (umbenannt); was geändert wurde, steht nur noch hier.

### v1.4.3 – 29.10.2026
- Teamwork: eigene KI hat immer alle Werkzeuge; Fenster „Erlaubnis“ mit drei Stufen (Alles erlauben, Eingeschränkt,
  Strikt).
- Teamwork-Seitenleiste nur noch Knöpfe, „Projektordner“ als Knopf, „Raum schließen“ fest unten über „Einstellungen“.
- Kontextmenüs im Design (kein heller Rahmen mehr), sauber runde Ecken am Umschalter „Chat | Teamwork“.
- Commits heißen nur noch nach der Version; `AGENTS.md` wieder entfernt.

### v1.4.2 – 28.10.2026
- Ziehen am Fensterrand 3–4-mal so flüssig (`themes.no_resize_redraw`).

### v1.4.1 – 27.10.2026
- Kontext wieder frei einstellbar (Automatik „auto“ entfernt).
- Antworten in langen Chats beginnen viel schneller (keine Uhrzeit mehr im System-Prompt).
- Flüssigeres Ziehen (feste Chat-Spalte); PowerShell-Hinweise für die KI, knappere Werkzeug-Texte.

### v1.4 – 27.10.2026
- 19 Agenten-Werkzeuge: rechnen, Git & GitHub, Checkpoints/Rückgängig, Arbeitsplan, Hintergrund-Prozesse, Dateien
  ordnen, Speicher analysieren, PDFs und Bilder bearbeiten, Projekt-Anweisungen (`MONHIP.md`/`AGENTS.md`/`CLAUDE.md`).
- README auf Englisch.

### v1.3 – 27.10.2026
- Oberfläche auf Deutsch und Englisch (erkennt die Windows-Sprache, Auswahl in den Einstellungen).
- Experten-Modus: eingescannte PDFs bis 500 Seiten, Abschrift Seite für Seite fortsetzbar.
- README ausführlich, diese Datei angelegt.

### v1.2 – 25.10.2026
- Teamwork: KI wartet nach @Name auf die Antworten der anderen KIs und macht dann selbst weiter.

### v1.1 – 25.10.2026
- Teamwork: Kontextanzeige und Zusammenfassen, Hauptauftrag (`@main`), Arbeitsstand, Aufgabenliste, Teamstand,
  `ki_fragen`, „Alle KIs stoppen“.
- Größeres Startfenster, scrollbare Seitenleiste; schnellerer Moduswechsel und Beitritt zu langen Räumen.

### v1.0 – 25.10.2026
- Experten-Modus: Ordner mit vielen Dokumenten auswerten (Zusammenfassungen, Volltextindex, Scans per Bildverständnis).

### Vor v1.0
- Chat-Oberfläche mit Chatliste, Einstellungen, drei Designs; eigene Chatansicht (Markdown, Denkprozess, Werkzeuge).
- Eigener llama.cpp-Download, Modelle in `modelle/` – unabhängig von LM Studio.
- Agent: freigegebene Ordner, Word/Excel/PowerPoint, PowerShell/Python, Websuche, Gedächtnis, Erinnerungen,
  Bildschirmfoto.
- Bilder verstehen, Drag & Drop, Spracherkennung (whisper.cpp), Nachrichten bearbeiten (Fassungen) und zitieren.
- Kontextanzeige, automatisches Zusammenfassen, „Kontext voll“ mitten in der Antwort.
- Teamwork: Räume übers Netz, @Name/@alle, Dateien teilen, gemeinsamer Projektordner.
- Separater Installer (eigenes Programm, nicht in diesem Repo).

---

## 3. Grundstruktur

### Aufbau
- Windows, Python 3.13, **nur Standardbibliothek**, Oberfläche mit Tkinter.
- Start: `Monhip.pyw` → hängt `app/` an `sys.path`, führt `app/monhip.py` aus (Fehler sieht man nur mit
  `py Monhip.pyw`).
- Code nur in `app/`. Nutzerdaten daneben im Hauptordner, **nie ins Repo:** `config.json`, `gedaechtnis.json`,
  `erinnerungen.json`, `chats/`, `modelle/`, `raeume/`, `server/`, `checkpoints/`, `sicherungen/`.
- Das Sprachmodell läuft in einem eigenen `llama-server.exe` (llama.cpp, in `server/`), Monhip spricht ihn über HTTP an.

### Bereiche (Dateien in `app/`)
- **Oberfläche** – `monhip.py`: Klasse `App` (Fenster, Ablauf, Einstellungen `DEFAULTS`, `VERSION`).
- **Chatansicht** – `chatview.py`, `markdown_lite.py`: ganzer Verlauf in einem `tk.Text`.
- **Aussehen** – `themes.py`, `widgets.py`, `dialogs.py`: Designs, runde Ecken, Bedienelemente, Meldungen, Fenster.
- **Sprachen** – `i18n.py`, `i18n_en.py`: `tr()`, deutsche Texte als Schlüssel, englischer Katalog.
- **Modell** – `backend.py`, `llamacpp.py`, `downloads.py`: Server starten/stoppen, Streaming, llama.cpp-Download.
- **Kontext** – `context.py`: messen, ältere Unterhaltung zusammenfassen, „Kontext voll“.
- **Agent** – `agent.py`: alle Werkzeuge, Rückfragen, Werkzeugschleife `run_conversation`.
- **Werkzeug-Helfer** – `rechner`, `gitwork`, `checkpoints`, `prozesse`, `ordnen`, `speicher`, `pdfwerk`, `bildwerk`,
  `arbeitsplan`, `anweisungen`, `office`, `projects`, `web` (importieren `agent` nicht).
- **Dateien lesen** – `documents.py`, `pdftext.py`, `images.py`, `filedrop.py`.
- **Teamwork** – `room.py` (Netzwerk), `roomui.py` (Raum-Oberfläche, eigene KI), `projekt.py` (Projektordner).
- **Weitere** – `experte.py` (Experten-Modus), `chats.py`, `memory.py`, `reminders.py`, `speech.py` (Spracherkennung).

### Grundregeln (Entscheidungen des Projektinhabers – nicht ohne Rücksprache ändern)
- Unabhängig von LM Studio und Ollama; kein Installer- oder Update-Code in Monhip.
- Den Kontext stellt jeder selbst ein – keine Automatik, kein „Grafikkarte zuerst“.
- Chats löschen ohne Rückfrage; Oberfläche knapp, ohne Erklärtexte; Experten-Modus ohne Emojis.
- Teamwork: keine Bremse für KI-Ketten (dafür „Alle KIs stoppen“); Hauptauftrag legen nur Menschen fest; die eigene KI
  hat alle Werkzeuge, die Erlaubnis-Stufe bestimmt die Rückfragen.
- Oberfläche Deutsch/Englisch über `tr()`; alles, was das Modell liest, bleibt deutsch.

### Regeln für den Code
- Tk nur im Tk-Thread (`self.background`, `self.ui`); aus ctypes-Fensterprozeduren nie Tkinter aufrufen.
- Chat-Textfeld nie per `configure` ändern; feste Spaltenbreite; `themes.no_resize_redraw()` nicht entfernen.
- Meldungen über `dialogs`, neue Fenster über `dialogs.window/present`, Kontextmenüs über `widgets.PopupMenu`, Rand
  über `rounded(…, outline=)` in einem Stück; klassische tk-Widgets im Design registrieren.
- Nichts laufend Wechselndes (Uhrzeit, Zähler) in den System-Prompt – sonst liest llama.cpp alles neu ein.
- Agent: Dateien nur über `Agent._path()`, Änderungen über `_ok()`, Löschen nur in den Papierkorb; nach außen nie
  volle Pfade.
- Teamwork: Anfragen HMAC-signiert, der Schlüssel geht nie übers Netz; Gäste führen beim Gastgeber nie Befehle aus; an
  andere gehen nur Werkzeug-Kopfzeilen, nie Ergebnisse.
- Jeder neue Oberflächentext braucht einen englischen Eintrag in `i18n_en.py` (sortiert, gleiche Platzhalter).
- llama-server und Hintergrund-Prozesse hängen an einem Job-Objekt (enden mit dem Programm).
- Neue Einstellungen über `DEFAULTS`; `config.json` nie überschreiben oder hochladen; neue Nutzerdaten-Ordner mit dem
  Projektinhaber absprechen (Installer).

### GitHub und Testen
- Keine `.gitignore`: nur einzelne Dateien `git add <datei>`, vorher `git pull`; Zeilenenden je Datei beibehalten.
- **Alle Commits heißen einheitlich „Update - vX“** mit der neuesten Version (z. B. „Update - v1.4.3“), egal welche
  Dateien sie ändern, ohne „Co-Authored-By“. Was geändert wurde, steht nur in dieser Datei.
- Bei jeder neuen Version werden auch alle älteren Commits auf „Update - vX“ umbenannt (Inhalt, Autor und Datum
  bleiben; Force-Push von `main` und allen Tags). Danach in jedem Klon: `git fetch origin`, `git fetch --tags --force`,
  `git reset --keep origin/main` – eigene, noch nicht hochgeladene Commits vorher sichern.
- Pushen nur mit OK, Releases nur mit OK des Projektinhabers.
- Release: `VERSION` in `app/monhip.py` erhöhen → alle Commits umbenennen (siehe oben) → `git tag -a vX -m "vX"` →
  `git push origin main vX` →
  `gh release create vX --verify-tag --title "vX" --notes "<ein Satz>"`. Ohne Release kommt nichts beim Nutzer an.
- Tests: `py -m unittest discover -s tests -v`. Tests mit Fenster oder Grafikkarte vorher ankündigen; Nutzerdaten-Pfade
  im Test auf Testordner umbiegen.
