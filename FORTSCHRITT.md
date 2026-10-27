# Monhip – Fortschritt und Absprachen

Gemeinsame Arbeitsliste für alle, die an Monhip mitarbeiten – Menschen und KI-Modelle (Claude, ChatGPT/Codex,
Gemini, lokale Modelle …). Sie soll verhindern, dass zwei gleichzeitig an derselben Stelle arbeiten, Erledigtes
noch einmal gebaut oder eine getroffene Entscheidung wieder umgeworfen wird. Ausführliche Entwicklernotizen führt
der Projektinhaber lokal; diese Datei ist der gemeinsame Auszug daraus.

**Stand:** 27.10.2026 · **neuestes Release:** v1.2 · der Hauptzweig enthält zusätzlich die Scan-Erweiterung im
Experten-Modus (ohne Release) und die ausführliche README.

---

## 1. So arbeiten wir mit dieser Datei

**Für alle – Menschen und KIs:**

1. **Vor dem Start** `git pull` und diese Datei lesen – mindestens „In Arbeit“, „Entscheidungen“ und „Regeln für
   den Code“.
2. **Eintragen, bevor es losgeht:** eine Zeile unter „In Arbeit“ (wer, was, welche Dateien, seit wann), committen
   und pushen – erst dann anfangen. Wer zuerst eingetragen hat, hat die Dateien.
3. **Dateien, die jemand anders unter „In Arbeit“ stehen hat, nicht ändern** – vorher absprechen.
4. **Fertig:** Zeile unter „In Arbeit“ löschen, oben im Verlauf eintragen (was, wie getestet, was offen ist),
   „Als Nächstes“ und „Offen“ nachziehen – im selben Commit wie die Änderung selbst.
5. **Abgebrochen oder pausiert:** Zeile mit kurzer Notiz stehen lassen („pausiert seit …“) oder zurück nach
   „Als Nächstes“.
6. **Neue Entscheidungen des Projektinhabers** sofort unter „Entscheidungen“ festhalten.
7. **Immer ein festes Datum** (TT.MM.JJJJ), nie „gestern“ oder „nächste Woche“.

**Zusätzlich für KI-Modelle:**

- Nur das ändern, worum dein Mensch gebeten hat. Aufräumen oder Umbauen nebenbei vorher fragen.
- Committen und pushen nur nach ausdrücklichem OK eines Menschen; Releases (Tag + GitHub-Release) nur nach OK des
  Projektinhabers.
- Bei „Wer“ Mensch **und** Modell angeben (z. B. „Max + Claude“), damit klar ist, wen man fragt.
- Widerspricht diese Datei dem Code, gilt der Code – Datei korrigieren und das im Verlauf erwähnen.

---

## 2. In Arbeit

| Wer (Mensch + Modell) | Was | Dateien | Seit |
|---|---|---|---|
| Auftraggeber + Codex | Versehentlich geleerte README exakt aus `db18120` wiederherstellen | `README.md`, `FORTSCHRITT.md` | 27.10.2026 |

---

## 3. Als Nächstes / Ideen

Reihenfolge offen – vor dem Start unter „In Arbeit“ eintragen.

- **Tests mit echten Modellen** (bisher meist mit nachgestelltem llama-server): Zusammenfassen und „Kontext voll“
  im Chat und im Teamwork, Experten-Modus mit einem großen echten Ordner und einem dicken Scan, KI-Austausch im
  Teamwork.
- **Teamwork zwischen zwei echten Rechnern** (z. B. über Tailscale) – bisher nur mit zwei Instanzen auf einem PC.
- **Werkzeuge, Schritt 2:** Datei herunterladen, Zwischenablage, PDF erzeugen.
- **Experten-Modus:** „Auswertung löschen“ in der Oberfläche (Ergebnisse bleiben bisher unter `chats/experten/`).
- **Bildbereich „Chat | Teamwork | Bilder“** (besprochen, noch nicht begonnen; vorher andere Optimierungen):
  - Eigener dritter Bereich statt im Chat, weil Sprach- und Bildmodell nicht gleichzeitig in 16 GB Grafikspeicher
    passen – Wechsel in den Bereich = Sprachmodell nach kurzer Rückfrage entladen, Bildmodell laden.
  - Aufbau: links Galerie (wie die Chatliste), Mitte große Vorschau, unten Beschreibung + schmale Leiste (Format,
    Qualität, „Neue Variante“), Fortschrittsbalken.
  - Technik: stable-diffusion.cpp (github.com/leejet/stable-diffusion.cpp), nur `sd-cli.exe` als Subprozess
    (Job-Objekt), eingebunden wie whisper.cpp in `speech.py` (eigenes Modul, Download über `downloads.py`, Reiter in
    den Einstellungen). Modell Qwen-Image 2.1 (GGUF Q8_0, Text-Encoder Qwen3-VL-8B, VAE der Fassung 2.1, für
    Bearbeiten zusätzlich die mmproj; zusammen ~15 GB). Programm-Auswahl wie in `llamacpp.plan()`: CUDA (+ cudart)
    → Vulkan → CPU.
  - Ablage ohne Installer-Änderung: `server/sd-<build>-<art>/`, `modelle/bild/`, erzeugte Bilder unter `chats/`.
  - **Zuerst messen** (Zeit und Grafikspeicher bei 1024 × 1024, mit und ohne geladenes Sprachmodell), Flags vorher
    mit `sd-cli --help` am echten Programm prüfen.
- **Video** (nach dem Bildbereich, erst nach einer Messung): gleiche Technik, zweiter Reiter „Bild | Video“,
  Einstieg mit Wan 2.2 TI2V 5B. Tkinter spielt keine Videos ab → Vorschaubild zeigen, im Windows-Player öffnen.
- **Kleinere Reserve beim Laden** (`backend.fit_margin`) testen: bei der Messung am 26.10.2026 blieben ~1,7 GB
  Grafikspeicher frei. Ohne den Kontext zu verkleinern (siehe Entscheidungen).
- **README abgleichen:** dort steht „beispielsweise Python 3.12“, Projekt und Installer nutzen Python 3.13; die
  Tabelle „Lokale Daten“ nennt `raeume/` und `sicherungen/` noch nicht.

---

## 4. Entscheidungen

Vom Projektinhaber so festgelegt – nicht ohne Rücksprache ändern und nicht wieder vorschlagen.

**Grundsätzliches**
- Nur die Python-Standardbibliothek (Python 3.13), keine pip-Pakete.
- **Unabhängig von LM Studio:** keine LM-Studio-Pfade oder -Backends. llama.cpp kommt in den eigenen Ordner
  `server/` (Download direkt von github.com/ggml-org/llama.cpp), Modelle nach `modelle/`. Auch kein Ollama.
- **Kein Installer- oder Update-Code in Monhip.** Der Installer ist ein eigenständiges Programm (C#, nicht in
  diesem Repo).
- Oberfläche, Meldungen und Code-Kommentare auf Deutsch.
- Name „Monhip“; der Gruppenchat heißt „Teamwork“ (interne Namen `room*`/`RoomMode` und Einstellungen `room_*`
  bleiben).

**Oberfläche**
- Chats löschen **ohne Rückfrage und endgültig** (kein Papierkorb).
- Knapp halten: keine Tipps und Erklärtexte in den Einstellungen; die Teamwork-Seitenleiste zeigt nur die
  Funktionen selbst, Einzelheiten erst beim Anklicken.
- Experten-Modus **ohne Emojis** (professionell); vorhandene Emojis an anderen Stellen bleiben vorerst.
- Ergebnisse des Experten-Modus liegen unter `chats/experten/` (dadurch bleibt der Installer unverändert).

**Teamwork**
- **Keine Bremse** für KI-Ketten – KIs dürfen sich beliebig oft ansprechen; dafür kann jeder Mensch „Alle KIs
  stoppen“.
- Den Hauptauftrag (`@main`) legen nur Menschen fest; Änderungen erscheinen **nicht** im Verlauf. KIs lesen ihn nur.
- Spricht eine KI andere KIs mit @Name an, wartet sie auf deren Antworten und macht danach von selbst weiter.

**Modelle und Leistung**
- Kontext: Auslagern in den Arbeitsspeicher ist in Ordnung (Kontext „auto“ mit Untergrenze 32 768 Tokens).
- **„Grafikkarte zuerst“** (kleinerer Kontext und quantisierter Kontextspeicher für etwas mehr Tempo) ist nicht
  gewünscht – das Kontextfenster soll nicht kleiner werden. Größter Hebel bei langsamen Antworten ist die
  Modellfassung: Q4_K_M statt Q8_0 war in der Messung fast doppelt so schnell.

**GitHub**
- Commits **ohne** „Co-Authored-By“-Zeile.
- Ein Programm-Update, das bei installierten Fassungen ankommen soll, braucht ein Release mit Versionsnummer; die
  Nummer stimmt der Projektinhaber ab.

---

## 5. Regeln für den Code

Die wichtigsten Stolpersteine – fast jede Regel hier steht da, weil ihr Bruch schon einmal etwas kaputt gemacht hat.

- **Tk nur im Tk-Thread.** Laden, Chatten und Downloads laufen in Threads; von dort nur über
  `self.background(work, done)` bzw. `self.ui(fn, *args)` zurück. Tk-Variablen vor dem Thread auslesen. Aus einer
  ctypes-Fensterprozedur nie Tkinter aufrufen (führte zum Absturz bei Drag & Drop).
- **Das Chat-Textfeld nie per `configure` ändern** (`state`, `cursor` …) – Tk vermisst dann den ganzen Verlauf neu.
  Der Schreibschutz läuft über den Bindtag `ChatReadOnly`, Farben über `tag_configure`. In `chatview.py` nur
  innerhalb `with self._edit():` schreiben; wegen der Slots im Teamwork nie fest „end-1c“, sondern `self._at`.
- **Designs:** klassische tk-Widgets und Fenster registrieren (`theme.register_text/list/combo/menu/window`),
  sonst bleiben sie hell. Neue Farbschlüssel in beiden Paletten, Chatfarben (`"chat"`) in allen drei Designs.
  Runde Ecken: undurchsichtige Bilder mit 64-px-Mitte, keine Halbtransparenz (sonst 16 s statt 1,8 s Start).
- **Meldungen** nur über `dialogs.showinfo/showerror/askyesno/askstring`, nie `tkinter.messagebox`. Neue Fenster
  mit `dialogs.window(…)` anlegen, fertig aufbauen, mit `dialogs.present(…)` zeigen. Kein `scrolledtext`, sondern
  `widgets.scrolled()`; Listen über `App._listbox()`.
- **Einstellungen** neu über `DEFAULTS` in `monhip.py`. `config.json` nie überschreiben und nie hochladen (kann
  einen API-Schlüssel enthalten).
- **Pfade:** Der Code liegt in `app/`, Nutzerdaten daneben im Hauptordner – deshalb zeigen `APP_DIR`, `CHAT_DIR`,
  `SERVER_DIR`, `memory.FILE` und `reminders.FILE` auf `Path(__file__).resolve().parent.parent`.
- **Agent-Sicherheit:** Dateizugriffe nur über `Agent._path()` (freigegebene Ordner), schreibende Aktionen über
  `_ok()` bestätigen, Löschen nur in den Papierkorb, `open_path` startet keine Programme oder Skripte.
  Bildschirmfotos, Hochladen und Teilen fragen immer – auch nach „Alle erlauben“.
- **Teamwork-Sicherheit:** Anfragen sind HMAC-signiert, der Schlüssel geht nie übers Netz; Werkzeugaktionen der
  eigenen KI im Raum immer mit Bestätigung; an andere gehen nur Werkzeug-Kopfzeilen, nie Ergebnisse; nach außen nie
  volle Pfade (verraten den Benutzernamen); Gäste führen beim Gastgeber nie Befehle aus.
- **llama-server:** hängt an einem Windows-Job-Objekt (stirbt mit dem Programm); Starten und Stoppen unter
  `_start_lock`, `stop(proc)` beendet nur den eigenen Prozess.
- **Skalierung:** Fenster- und Seitenleistenbreiten mit `self.ui_scale` multiplizieren.
- **Neue Nutzerdaten-Ordner** müssen auch im Installer eingetragen werden (sonst überschreibt oder löscht ein Update
  sie) → mit dem Projektinhaber absprechen.

---

## 6. Aufbau (Kurzüberblick)

Start über `Monhip.pyw` (hängt `app/` an `sys.path` und führt `app/monhip.py` aus; Fehler sieht man nur beim Start
mit `py Monhip.pyw`).

| Datei in `app/` | Inhalt |
|---|---|
| `monhip.py` | Klasse `App`: gesamte Oberfläche und Ablauf, `DEFAULTS`/`load_config`/`save_config`, `VERSION` |
| `chatview.py` | `ChatView`: Chatverlauf in einem `tk.Text` (Sprechblasen, Markdown, Denk-/Werkzeugblöcke, Kärtchen, Bearbeiten, Zitat) |
| `markdown_lite.py` | Markdown-Helfer für Chatansicht und Office-Dateien |
| `backend.py` | `LlamaServer` (Start/Stopp, `/props`, Streaming, `count_tokens`, Kontext „auto“ über `llama-fit-params`), `ContextFull` |
| `context.py` | Kontext messen, ältere Unterhaltung zusammenfassen, „Kontext voll“ mitten in der Antwort (`Window`) |
| `agent.py` | Werkzeuge der KI (Dateien, Office, Befehle, Web, Bilder, Gedächtnis, Erinnerungen, Teamwork, Experte) und Werkzeugschleife `run_conversation` |
| `experte.py` | Experten-Modus: Ordner auswerten (`Job`), Volltextindex (SQLite FTS5), `Library` für die Werkzeuge |
| `llamacpp.py`, `speech.py`, `downloads.py` | llama.cpp- bzw. whisper.cpp-Download passend zur Grafikkarte, Spracherkennung, gemeinsame Download-Hilfen |
| `documents.py`, `pdftext.py`, `office.py` | Dokumente lesen (PDF, Office, OpenDocument, RTF, Text), eigener PDF-Leser, Word/Excel/PowerPoint schreiben |
| `images.py`, `filedrop.py` | Bilder, Bildschirmfotos, Zwischenablage; Drag & Drop (Windows) |
| `room.py`, `roomui.py`, `projekt.py` | Teamwork: Netzwerk (Gastgeber/Teilnehmer), Oberfläche und eigene KI im Raum, gemeinsamer Projektordner |
| `chats.py`, `memory.py`, `reminders.py` | Chats speichern, Gedächtnis, Erinnerungen |
| `themes.py`, `dialogs.py`, `widgets.py` | Designs und runde Ecken, Meldungen und Fenster-Grundgerüst, eigene Bedienelemente |
| `web.py`, `projects.py` | Websuche und Seitenabruf, Projektvorlagen |

**Nutzerdaten (nie ins Repo):** `config.json`, `gedaechtnis.json`, `erinnerungen.json`, `chats/`, `modelle/`,
`raeume/`, `sicherungen/`, `server/`, `__pycache__/`.

---

## 7. Testen

- **Tests, die Fenster öffnen oder ein Modell auf die Grafikkarte laden, vorher ankündigen.** Reine Datei- und
  Kompiliertests sind unproblematisch.
- Schnellcheck vom Repo-Ordner aus: `py -m compileall -q app` (den entstehenden `__pycache__/` nicht committen).
- Ohne echte Nutzerdaten testen: `CONFIG_FILE` in `monhip.py`, `chats.CHAT_DIR`, `memory.FILE`, `reminders.FILE`,
  im Teamwork `app.app_dir` und `roomui.CACHE_DIR` auf Testordner umbiegen.
- Ohne Modell: `run_conversation` bzw. `agent.chat_turn` durch Fakes ersetzen oder einen nachgestellten llama-server
  verwenden (`ThreadingHTTPServer` mit `/props`, `/tokenize` und `/v1/chat/completions` als SSE).
- Teamwork in einem Prozess: App als Gastgeber (`app.room.create(…)` auf 127.0.0.1), ein zweiter `room.RoomClient`
  als Gast.
- Im Verlauf immer auch angeben, **was nicht** getestet ist (z. B. „nicht mit echtem Modell“, „nicht zwischen zwei
  Rechnern“).

---

## 8. GitHub, Versionen, Zeilenenden

- **Es gibt keine `.gitignore`** (am 26.10.2026 gelöscht). Deshalb nur einzelne Dateien aufnehmen
  (`git add <datei>`), nie `git add -A` oder `git add .`, und vorher `git status --untracked-files=all` prüfen.
- **Vor jedem Commit `git pull`.** Wer in einem Arbeitsordner ohne Git entwickelt und Dateien in den Klon kopiert:
  erst `git pull`, dann kopieren, dann `git diff` ansehen – zeigt der Diff Änderungen, die man nicht selbst gemacht
  hat, überschreibt man gerade die Arbeit eines anderen.
- Vor dem Hochladen nach Namen, Benutzerpfaden, Schlüsseln, Mail- und IP-Adressen durchsuchen.
- **Zeilenenden** sind je Datei verschieden (`git ls-files --eol`, `core.autocrlf=true`). Zeigt `git diff --stat`
  eine ganze Datei als geändert, hat sie ihr Zeilenende gewechselt → auf das bisherige zurückstellen.
- **Versionen:** `VERSION` in `app/monhip.py` erhöhen, Commit-Text „v1.3 – <ein Satz>“, dann:

  ```sh
  git tag -a v1.3 -m "v1.3"
  git push origin main v1.3
  gh release create v1.3 --verify-tag --title "v1.3" --notes "<derselbe Satz>"
  ```

  1.0.1 für Fehlerbehebungen, 1.1 für Neues – die Nummer mit dem Projektinhaber abstimmen.
- **Ohne neues Release kommt ein Commit bei installierten Fassungen nicht an:** Der Installer richtet sich nach dem
  neuesten Release und tauscht bei einem Update die Dateien aus dem Repo aus (Nutzerdaten bleiben).

---

## 9. Verlauf

Neueste zuerst. Neue Einträge oben im Abschnitt „Seit …“:
`- TT.MM.JJJJ · Wer · Was · getestet: … · offen: …`

### Seit v1.2 (ohne Release)
- 27.10.2026 · Projektinhaber + Claude · Diese Datei angelegt (gemeinsamer Auszug aus den lokalen Entwicklernotizen).
- 27.10.2026 · README ausführlich: Funktionen, Voraussetzungen, Start aus dem Quellcode, lokale Daten
  (`db18120`, `e6e3514`).
- 26.10.2026 · Experten-Modus: eingescannte PDFs bis 500 statt 30 Seiten, in Blöcken zu 10 Seiten gerendert,
  Abschrift Seite für Seite gemerkt (nach Stopp/Absturz geht es bei der nächsten offenen Seite weiter), Fortschritt
  je Seite (`90ebc13`) · getestet mit nachgestelltem Server und echtem Rendern · offen: echtes Modell, großer Scan.
- 26.10.2026 · Nur gemessen: wenig Grafikkarten-Last bei großen MoE-Modellen liegt an den in den Arbeitsspeicher
  ausgelagerten Experten (Q8_0 auf 16 GB); Ergebnis siehe Entscheidungen.

### v1.2 – 25.10.2026 (`7179705`)
- Teamwork: Spricht eine KI andere KIs mit @Name an, wartet sie (nicht blockierend) auf deren Antworten und macht
  danach von selbst weiter.

### v1.1 – 25.10.2026 (`fc43d6d`)
- Teamwork: Kontextanzeige und Zusammenfassen wie im normalen Chat (Zusammenfassungen bleiben auf dem eigenen
  Rechner), Füllstand je KI in der Teilnehmerliste.
- Teamwork: Hauptauftrag (`@main`) und Arbeitsstand je KI.
- Teamwork: KI-Austausch – Aufgabenliste, Teamstand, `ki_fragen`, „Alle KIs stoppen“; Bremse entfernt.
- Fenstergrößen (Start 1320 × 980, Seitenleiste scrollt), Seitenleiste ohne Kurztexte, schneller: Moduswechsel und
  Beitritt zu langen Räumen.

### v1.0 – 25.10.2026 (`c0e0467`)
- Experten-Modus: Ordner mit vielen Dokumenten auswerten (Zusammenfassung je Datei, Volltextindex, Gesamtüberblick,
  Scans über Bildverständnis), Werkzeuge zum Suchen und Lesen mit Datei- und Seitenangabe. Erste Versionsnummer.

### Vor v1.0 (Oktober 2026)
- Grundgerüst: Chat-Oberfläche mit Chatliste und Einstellungsfenster, Designs Dunkel/Hell/Windows-Standard, eigene
  Chatansicht (Markdown, Denkprozess, Werkzeugblöcke, flüssige Ausgabe), runde Ecken.
- Agent-Werkzeuge: freigegebene Ordner, Word/Excel/PowerPoint, Projektvorlagen, PowerShell/Python, Websuche;
  Gedächtnis, Erinnerungen, Bilder ansehen, Bildschirmfoto; `read_file`/`fetch_url` abschnittsweise.
- Eigener llama.cpp-Download (unabhängig von LM Studio), Modellordner `modelle/`, Job-Objekt gegen verwaiste
  Server, Wettlauf beim Entladen/Laden behoben.
- Bilder anhängen und verstehen (mmproj), Drag & Drop (Absturz behoben), Einfügen mit Strg+V.
- Nachrichten kopieren, bearbeiten (mit Fassungen ‹ 2/3 ›) und zitieren.
- Spracherkennung mit whisper.cpp (Diktat, Audiodateien als Anhang).
- Kontextanzeige, automatisches Zusammenfassen, „Kontext voll“ mitten in der Antwort, Kontext „auto“.
- Teamwork: Räume übers Netz, @Name/@alle, Dateien teilen, gemeinsamer Projektordner, KIs übertragen und teilen
  Dateien, Räume löschen.
- Leistung: Schreibschutz ohne `configure`, runde Ecken ohne Halbtransparenz, Chatliste und Teamwork-Neuaufbau
  beschleunigt.
- Umbenennung Modell-Studio → Monhip, Programmsymbol, separater Installer.

---

## 10. Offen / bekannte Grenzen

- **Kaum mit echten Modellen getestet:** Zusammenfassen, „Kontext voll“, Experten-Modus und die KIs im Teamwork
  wurden meist mit einem nachgestellten Server geprüft.
- **Teamwork:** nicht zwischen zwei echten Rechnern getestet; ohne VPN unverschlüsselt (nur signiert); geteilte
  Dateien liegen nur beim Gastgeber; Hoch- und Herunterladen ohne Fortschrittsanzeige, höchstens 100 MB; KIs können
  sich endlos ansprechen (dann „Alle KIs stoppen“); Warten nach @KI ohne Zeitlimit; Rückfragen im Kreis werden nur
  entlang der Kette erkannt.
- **Lange Chats:** eine einzelne riesige Runde wird nicht zusammengefasst, eine Zusammenfassung kann Einzelheiten
  verlieren; im Teamwork fällt weg, was älter als zwei Kontextlängen ist.
- **Experten-Modus:** höchstens 5000 Dateien je Ordner und 500 Seiten je Scan (je Seite ~15–40 s), Bilddateien im
  Ordner werden nicht ausgewertet, immer nur eine Auswertung und nur solange Monhip läuft, Volltextsuche ohne
  Bedeutungssuche, noch kein „Auswertung löschen“.
- **Dokumente und Bilder:** keine verschlüsselten PDFs; PDF erzeugen nur über Word; kein WebP/TIFF/HEIC;
  EXIF-Drehung wird nicht beachtet; Bildschirmfotos nur vom Hauptbildschirm.
- **Markdown-Anzeige** bewusst einfach: keine verschachtelten Zitate, kein LaTeX, Code-Hervorhebung zeilenweise.
- **Spracherkennung:** keine Live-Mitschrift, kein Opus/M4A (bräuchte ffmpeg), auf AMD/Intel nur über den
  Prozessor; ein echtes Mikrofon-Diktat ist noch nicht getestet.
- **Gedächtnis und Erinnerungen** nur im normalen Chat; Erinnerungen nur, solange Monhip läuft, keine Wiederholungen.
