# Monhip – Fortschritt und Absprachen

Gemeinsame Arbeitsliste für alle, die an Monhip mitarbeiten – Menschen und KI-Modelle (Claude, ChatGPT/Codex,
Gemini, lokale Modelle …). Sie soll verhindern, dass zwei gleichzeitig an derselben Stelle arbeiten, Erledigtes
noch einmal gebaut oder eine getroffene Entscheidung wieder umgeworfen wird. Ausführliche Entwicklernotizen führt
der Projektinhaber lokal; diese Datei ist der gemeinsame Auszug daraus. `AGENTS.md` (liest Codex von selbst) verweist
hierher.

**Stand:** 28.10.2026 · **neuestes Release:** v1.4.2 · Ziehen am Fensterrand 3–4-mal so flüssig – auf Basis von
v1.4.1 (Kontextgröße frei einstellbar, schnellere Antworten in langen Chats, PowerShell-Hinweise für die KI), v1.4
(19 neue Agenten-Werkzeuge) und v1.3 (Deutsch und Englisch für die Oberfläche).

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
| – | zurzeit nichts | – | – |

---

## 3. Als Nächstes / Ideen

Reihenfolge offen – vor dem Start unter „In Arbeit“ eintragen.

- **Tests mit echten Modellen** (bisher meist mit nachgestelltem llama-server): Zusammenfassen und „Kontext voll“
  im Chat und im Teamwork, Experten-Modus mit einem großen echten Ordner und einem dicken Scan, KI-Austausch im
  Teamwork.
- **Teamwork zwischen zwei echten Rechnern** (z. B. über Tailscale) – bisher nur mit zwei Instanzen auf einem PC.
- **Werkzeuge, Schritt 2:** Datei herunterladen, Zwischenablage, PDF erzeugen.
- **Agenten-Werkzeuge (v1.4) nachschärfen:**
  - Mit einem kleinen Modell (7–14B) testen – dafür sind sie gedacht, getestet wurde nur mit Qwen3.6-35B-A3B.
  - Eigene Schalter je Werkzeuggruppe (z. B. Git, Aufräumen, Programmieren): alle Häkchen an kosten ~2 600 Tokens
    zusätzlich; `rechnen` sollte immer an bleiben.
  - Knopf „Rückgängig“ unter einer Antwort, laufende Hintergrund-Prozesse in der Oberfläche anzeigen.
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
- Oberfläche und Meldungen wahlweise auf Deutsch oder Englisch; Code-Kommentare auf Deutsch.
- Oberflächensprache beim ersten Start ohne gespeicherte Auswahl aus der Windows-Anzeigesprache erkennen:
  Deutsch → Deutsch, Englisch und alle anderen Sprachen → Englisch. Manuelle Auswahl in den Einstellungen hat
  Vorrang, wird in `config.json` als `ui_language` gespeichert und gilt ab dem nächsten Programmstart.
- Oberflächensprache, Spracherkennung und Modell-Prompts bleiben unabhängig. Keine Übersetzung von Nutzerdaten,
  Dateipfaden oder internen Teamwork-Kennungen. Kein neuer Installer- oder Update-Code in Monhip.
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
- **Den Kontext stellt jeder selbst ein** (Einstellungen → Laden, Standard 16 384 Tokens) – keine Automatik und keine
  Vorschläge; „auto“ wurde in v1.4.1 auf Wunsch des Projektinhabers wieder entfernt. Auslagern in den
  Arbeitsspeicher ist in Ordnung.
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
  Das Textfeld hat eine **feste Breite** (`fixed_column`, liegt per `place` mittig) – nicht wieder an die
  Fensterbreite koppeln: jedes Pixel beim Ziehen am Fensterrand brach sonst Chat und Teamwork-Verlauf neu um.
- **`themes.no_resize_redraw()` nicht entfernen:** Tk legt seine Windows-Fensterklassen „TkTopLevel“/„TkChild“ mit
  `CS_HREDRAW|CS_VREDRAW` an – Windows zeichnet dann bei jedem Zieh-Schritt alle Bedienelemente neu, auch
  unveränderte. Die Funktion (aus `ThemeManager.present`) nimmt die beiden Stile weg; Tk zeichnet Geändertes selbst.
- **Anfang des Prompts stabil halten:** llama.cpp rechnet bei der nächsten Anfrage nur ab der ersten geänderten
  Stelle neu. Im System-Prompt deshalb nichts, was sich laufend ändert – keine Uhrzeit (`agent.date_line()` = nur
  Datum; die Uhrzeit hängt `_api_message` fest an jede Nutzernachricht), keine Laufzeiten, keine Zähler. Mit der
  Uhrzeit im Prompt las das Modell bei jeder Nachricht die ganze Unterhaltung neu ein (8 700 Tokens: 5,6 s statt 0,2 s).
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
- **Oberflächentexte** immer über `tr('…')` mit festem deutschem Text und englischem Eintrag in `i18n_en.py`
  (alphabetisch sortiert, gleiche Platzhalter; `tests/test_i18n.py` prüft das). Werte als Platzhalter
  (`tr('{0} Bilder bearbeiten?', n)`). Was das Modell liest (Prompts, Werkzeug-Beschreibungen und -Ergebnisse,
  Fehlermeldungen ans Modell), bleibt deutsch. Die Sprache steht fest, bevor `agent` geladen wird (`LABELS`).
- **Agent-Sicherheit:** Dateizugriffe nur über `Agent._path()` (freigegebene Ordner), schreibende Aktionen über
  `_ok()` bestätigen, Löschen nur in den Papierkorb, `open_path` startet keine Programme oder Skripte.
  Bildschirmfotos, Hochladen und Teilen fragen immer – auch nach „Alle erlauben“; ebenso Push, Pull Request und
  `speicher_analysieren` außerhalb der Freigaben. Vor jeder Datei-Änderung sichert `_sichern` den alten Stand für den
  Checkpoint der Antwort (auch neu angelegte Ordner darüber).
- **Teamwork-Sicherheit:** Anfragen sind HMAC-signiert, der Schlüssel geht nie übers Netz; Werkzeugaktionen der
  eigenen KI im Raum immer mit Bestätigung; an andere gehen nur Werkzeug-Kopfzeilen, nie Ergebnisse; nach außen nie
  volle Pfade (verraten den Benutzernamen); Gäste führen beim Gastgeber nie Befehle aus.
- **llama-server und Hintergrund-Prozesse** hängen an einem Windows-Job-Objekt (sterben mit dem Programm, auch bei
  einem Absturz); Starten und Stoppen des Servers unter `_start_lock`, `stop(proc)` beendet nur den eigenen Prozess.
- **Hilfsmodule der Werkzeuge** (`rechner`, `gitwork`, `checkpoints` …) importieren `agent` nicht (Zirkelimport);
  jedes hat eine eigene Fehlerklasse, die in `agent.MODEL_ERRORS` steht.
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
| `backend.py` | `LlamaServer` (Start/Stopp mit `-c` aus den Einstellungen, `/props`, Streaming, `count_tokens`), `ContextFull` |
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
| `i18n.py`, `i18n_en.py` | Erkennung und gespeicherte Wahl der Oberflächensprache, deutsche Originaltexte und englischer Katalog |
| `rechner.py` | Werkzeug `rechnen`: exakt mit Brüchen, sicher über `ast` (kein `eval`), Prozent, Statistik, Einheiten, Datum, Zinsen |
| `gitwork.py` | Git und GitHub für den Agenten (ohne Terminal-Rückfragen, Token aus dem Git Credential Manager, Pull Requests über die API) |
| `checkpoints.py` | Alter Stand vor Datei-Änderungen, ein Checkpoint je Antwort; Rückgängig (`checkpoint_zurueck`) |
| `prozesse.py` | Hintergrund-Prozesse (Webserver, `npm run dev` …): starten, Ausgabe lesen, samt Unterprozessen stoppen |
| `ordnen.py`, `speicher.py` | Viele Dateien in einem Schritt verschieben/umbenennen (ganz oder gar nicht), Speicherplatz analysieren |
| `pdfwerk.py`, `bildwerk.py` | PDFs zusammenfügen/aufteilen/drehen in reinem Python; Bilder verkleinern/umwandeln/drehen über PowerShell |
| `arbeitsplan.py`, `anweisungen.py` | Arbeitsplan des Modells; `MONHIP.md`/`AGENTS.md`/`CLAUDE.md` der freigegebenen Ordner in den System-Prompt |

**Nutzerdaten (nie ins Repo):** `config.json`, `gedaechtnis.json`, `erinnerungen.json`, `chats/`, `modelle/`,
`raeume/`, `sicherungen/`, `server/`, `checkpoints/`, `__pycache__/`.

---

## 7. Testen

- **Tests, die Fenster öffnen oder ein Modell auf die Grafikkarte laden, vorher ankündigen.** Reine Datei- und
  Kompiliertests sind unproblematisch.
- Schnellcheck vom Repo-Ordner aus: `py -m compileall -q app` (den entstehenden `__pycache__/` nicht committen).
- Sprach- und Regressionstests: `py -m unittest discover -s tests -v`. Die zwei GUI-Tests brauchen einen Bildschirm
  (unter Linux z. B. Xvfb über `DISPLAY`); ohne Bildschirm werden sie ausdrücklich übersprungen. GUI-Tests laufen
  in getrennten Prozessen mit temporären Einstellungen und Nutzerdaten. Kein echtes KI-Modell erforderlich.
  Die Tests der Agenten-Werkzeuge (`test_rechner.py`, `test_gitwork.py`, `test_checkpoints.py` …) sind Skripte: Sie
  laufen bei `discover` beim Laden mit („alle …-Tests bestanden“) und einzeln mit `py tests/test_<name>.py`.
- Agenten-Werkzeuge ohne Nutzerdaten testen: `checkpoints.DIR` auf einen Testordner, `agent._recycle` durch ein
  Verschieben in einen Testordner ersetzen (sonst echter Papierkorb), Git mit eigener `GIT_CONFIG_GLOBAL` und einem
  lokalen `git init --bare` als Remote; `gitwork.token()` nicht aufrufen (liest das echte GitHub-Token).
- Ohne echte Nutzerdaten testen: `CONFIG_FILE` in `monhip.py`, `chats.CHAT_DIR`, `memory.FILE`, `reminders.FILE`,
  im Teamwork `app.app_dir` und `roomui.CACHE_DIR` auf Testordner umbiegen.
- Ohne Modell: `run_conversation` bzw. `agent.chat_turn` durch Fakes ersetzen oder einen nachgestellten llama-server
  verwenden (`ThreadingHTTPServer` mit `/props`, `/tokenize` und `/v1/chat/completions` als SSE). Startoptionen des
  Servers: nachgemachte `llama-server.bat` → Python-Skript, das `sys.argv` in eine Datei schreibt und `/health` und
  `/props` beantwortet.
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

### v1.4.2 – 28.10.2026
- 28.10.2026 · Projektinhaber + Claude · **Ziehen am Fensterrand 3–4-mal so flüssig:** Ursache waren Tks
  Windows-Fensterklassen mit `CS_HREDRAW|CS_VREDRAW` – bei jeder Größenänderung zeichnete Windows alle Bedienelemente
  neu (auch die verdeckte Teamwork-Ebene und die Seitenleiste). Neu: `themes.no_resize_redraw()`. Gemessen (langer
  Chat + Teamwork-Verlauf, 8-px-Schritte im 60-Hz-Takt): breiter/schmaler 83 → 22 ms je Schritt, schmaler als die
  Spalte 109 → 39 ms, Höhe 87 → 29 ms. Getestet: nach 9 Zieh-Arten und im Einstellungsfenster pixelgleich mit einem
  komplett neu gezeichneten Fenster (Dunkel, Hell, Windows-Standard), alle Testdateien grün, vom Projektinhaber mit
  der Maus geprüft. Offen: ~7 ms für die runden Ecken; im schmalen Fenster bricht der Chat neu um (~16 ms).
- 28.10.2026 · Projektinhaber + Claude · **`AGENTS.md` angelegt:** Codex liest sie von selbst; sie verweist auf diese
  Datei und nennt die wichtigsten Regeln. Nur Doku, ohne Tag/Release.

### v1.4.1 – 27.10.2026
- 27.10.2026 · Projektinhaber + Claude · **Kontext „auto“ samt Vorschlag entfernt** (Wunsch des Projektinhabers: jeder
  stellt das Kontextfenster selbst ein, wie früher). Reiter „Laden“: einfaches Feld „Kontext (Tokens)“, Standard
  16 384; der Server bekommt immer `-c <Zahl>`. Weg sind die Berechnung über `llama-fit-params`, die Vorschlagszeile mit
  „Übernehmen“ und 17 englische Texte dazu. Geblieben ist nur `-fitt` (1 GB + Größe der mmproj-Datei, nur bei neuerer
  llama.cpp) – betrifft die Verteilung der Schichten auf die Grafikkarte, nie den Kontext. Ein gespeichertes „auto“
  wird beim Start zu 16 384, eine gespeicherte Zahl bleibt; ein Tippfehler beim Speichern behält die bisherige Zahl.
  Getestet: alle Testdateien, Startoptionen mit nachgemachtem Server (ältere/neuere llama.cpp, mmproj, `-ngl`,
  Extra-Argumente, Pfad mit Leerzeichen), alte Einstellungen („auto“, fehlt, leer, Zahl als Text …), Fenster Deutsch
  und Englisch inkl. Laden über die Oberfläche. Nicht mit echtem Modell geladen.
- 27.10.2026 · Projektinhaber + Claude · **Schneller und flüssiger:** Die Uhrzeit stand minutengenau im System-Prompt –
  llama.cpp las deshalb bei jeder Nachricht die ganze Unterhaltung neu ein (gemessen mit Qwen3.6-35B-A3B Q4: 8 700
  Tokens 5,6 s statt 0,2 s, wächst mit dem Chat). Jetzt nur das Datum im Prompt, die Uhrzeit fest an jeder
  Nutzernachricht; Hintergrund-Prozesse ohne Laufzeit. Ziehen am Fensterrand: das Chat-Textfeld hat eine feste Breite
  und die verdeckte Ebene (Chat bzw. Teamwork) folgt erst beim Umschalten – langer Chat 184 → 59 ms je Schritt (so viel
  wie ein leerer), schmales Fenster 101 → 48 ms. Gegen v1.2 gemessen: Start, Streamen, langer Chat, Modus- und
  Designwechsel unverändert. Getestet: alle Testdateien, 97 Prüfungen am Agenten, Fenstertest Deutsch/Englisch
  (zweite Frage mit vorgestellter Uhr: Prompt-Anfang Zeichen für Zeichen gleich), Spalte mit Bildschirmfotos in allen
  drei Designs. Offen: ~55 ms je Zieh-Schritt bleiben (Tk zeichnet alle Bedienelemente neu).
- 27.10.2026 · Projektinhaber + Claude · **PowerShell-Hinweise und knappere Werkzeug-Texte:** Der Befehls-Prompt sagt
  dem Modell `;` statt `&&`, `py` statt `python` (nur wenn `py` da ist) und `Invoke-WebRequest -UseBasicParsing` bzw.
  `curl.exe` – mit Qwen3.6-35B-A3B bei je 6 Aufgaben 7 von 13 Befehlen fehlgeschlagen → 0 von 9. Beschreibungen der
  19 neuen Werkzeuge gestrafft: 3 068 → 2 571 Tokens (−16 %); `dateien_ordnen` legt fehlende Zielordner selbst an
  (sagt das jetzt auch). Getestet mit echtem Modell: Git 3/3, Ordnen 3/3; `plan_setzen` wird seither benutzt.

### v1.4 – 27.10.2026
- 27.10.2026 · Projektinhaber + Claude · 19 Agenten-Werkzeuge (Paket eines Mitwirkenden, als Patch übergeben) auf
  Basis von v1.3: `rechnen`; Git & GitHub (8 Werkzeuge, eigenes Häkchen „Git & GitHub“, Push und Pull Request fragen
  immer); Checkpoints und Rückgängig; Arbeitsplan; Hintergrund-Prozesse; Dateien ordnen; Speicher analysieren; PDFs
  und Bilder bearbeiten; Projekt-Anweisungen aus `MONHIP.md`/`AGENTS.md`/`CLAUDE.md`. Beim Einbau behoben: leere
  Ordner nach dem Rückgängigmachen, Ursprung von Verschiebungen nicht gegen die Freigaben geprüft, Hintergrund-Prozesse
  überlebten einen Absturz (jetzt Job-Objekt), `core.fsmonitor` eines fremden Repositorys hätte bei `git status` ein
  Programm gestartet, Rechner hing bei Riesen-Wurzelexponenten, `produkt` umging die Größengrenze; mit echtem Modell
  gefunden: Rückgängig doppelt bzw. mit der eigenen Nummer (holte die Änderungen zurück), Zielordner mit Leerzeichen
  („ PDFs“). Alle sichtbaren Texte übersetzt (59 Einträge), Texte fürs Modell bleiben deutsch.
  Getestet unter Windows/Python 3.13: alle Testdateien (`discover`: 17 Tests + 7 Werkzeug-Skripte), 97 Prüfungen am
  Agenten (echte Word-/Edge-PDFs, Handyfoto mit EXIF, echtes Git mit lokalem Remote, Prozesskette, Absturz mit/ohne
  Job-Objekt), Fenstertest Deutsch und Englisch, mit Qwen3.6-35B-A3B Q4_K_M: Rechnen, Anweisungen, Rückgängig,
  Prozesse, Ordnen, Speicher, PDFs, Bilder und Git wählt das Modell von selbst richtig. Offen: `plan_setzen` nutzte
  das Modell nie (0/4); echter Pull Request, `git_clone` von GitHub und die Anmeldung über den Credential Manager
  ungetestet; nicht mit kleinen Modellen getestet.
- 27.10.2026 · Auftraggeber + Codex · README vollständig ins Englische übersetzt, Inhalt und Aufbau beibehalten.
  Geprüft: unveränderte Codeblöcke, Inline-Code/Dateipfade, Links, Überschriften- und Listenstruktur, Tabellenzeilen
  und Versionsangaben; `git diff --check`. Keine Anwendungstests (reine Dokumentationsänderung). Der ausstehende
  inhaltliche README-Abgleich bleibt offen; der parallele Arbeitseintrag des Projektinhabers bleibt erhalten.

### v1.3 – 27.10.2026 (`caf2f94`)
- 27.10.2026 · Auftraggeber + Codex · Sprachupdate v1.3 veröffentlicht: 664 englische Oberflächentexte, Deutsch
  bleibt erhalten; automatische Erkennung beim ersten Start, gespeicherte Auswahl unter Einstellungen →
  Darstellung → Oberflächensprache (wirksam nach Neustart). Modell-Prompts, Nutzerdaten und Protokollwerte bleiben
  unverändert. Getestet: 17 Tests mit Python 3.13 und Tk 8.6/Xvfb, einschließlich beider Oberflächen, Sprachwechsel,
  alter Konfiguration, Windows-Spracherkennung mit simulierten Sprachkennungen, echter lokaler Teamwork-Verbindung,
  Aufgabenstatus und schreibgeschütztem Projektordner; Syntaxprüfung und zeilenendengerechte Formatprüfung.
  Veröffentlichung geprüft: Tag `v1.3`, neuestes reguläres GitHub-Release (kein Entwurf, kein Vorab-Release),
  vollständiges Quellarchiv bytegenau mit dem Tag verglichen; dieselben 17 Tests bestehen auch aus dem
  heruntergeladenen Archiv. Offen: echter Windows-Installer und echte KI-Modelle hier nicht getestet.

### Zwischen v1.2 und v1.3
- 27.10.2026 · Auftraggeber + Codex · Versehentlich geleerte README exakt aus `db18120` wiederhergestellt.
  Getestet: bytegenauer Vergleich mit der ursprünglichen Fassung und `git diff --check`; keine Anwendungstests
  (reine Dokumentationsänderung). Offen: die unter „Als Nächstes“ genannten README-Ergänzungen bleiben unverändert ausstehend.
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
- Kontextanzeige, automatisches Zusammenfassen, „Kontext voll“ mitten in der Antwort, Kontext „auto“ (in v1.4.1
  wieder entfernt).
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
  entlang der Kette erkannt. Der System-Prompt der eigenen KI enthält Teilnehmer, Teamstand und Aufgaben – ändert sich
  davon etwas, liest llama.cpp den Raumverlauf bei der nächsten Antwort neu ein (Abhilfe: diese Teile ans Ende).
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
- **Agenten-Werkzeuge (v1.4):** Checkpoints erfassen weder Befehle (`run_command`, Prozesse) noch Git noch den
  Teamwork-Projektordner; Sicherungen liegen in `checkpoints/` (30 Stück, Dateien über 50 MB nur vermerkt).
  `arbeitstage` kennt keine Feiertage. PDF: Lesezeichen und Formularfelder gehen verloren, verschlüsselte PDFs nicht.
  Bilder: kein HEIC/WebP, bei animierten GIFs nur das erste Bild. Höchstens 5 Hintergrund-Prozesse. Im Teamwork
  bekommen KIs mit „Dateien“/„Befehle“ die neuen Werkzeuge mit (alle Aktionen werden dort ohnehin bestätigt), Git nicht.
