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

**Stand:** 11.11.2026 · **neuestes Release:** v1.7.0

---

## Seit v1.7.0
- 11.11.2026: Einstellungen: „Laden“ und „System-Prompt“ stehen jetzt unter „Modelle“, das Modell wählst du dort
  aus einer Aufklappliste; neue Reihenfolge der Reiter, die bündig mit dem Rahmen enden.
- 11.11.2026: Bereich „Bilder“ und Bildeinstellungen ohne Hinweis- und Erklärtexte und Lizenzangaben; das
  Eingabefeld ist so groß wie im Chat.
- 11.11.2026: Das Design „Hell (Weiß/Violett)“ entfällt; wer es nutzte, bekommt das dunkle Design.

## v1.7.0 – 11.11.2026
- 11.11.2026: Qwen-Image 2.1 auf Grafikkarten ohne CUDA (AMD, Intel, Linux) mit eigener Modelldatei (GGUF) – dort
  kamen sonst nur Bildfetzen heraus; der Windows-Installer lädt sie ebenso.
- 11.11.2026: 3D-Bereich ohne Hinweistexte; das Einstellungsfenster wird so hoch, wie der längste Reiter es braucht.
- 11.11.2026: Programm-Downloads und Serverstart intern zusammengelegt (weniger doppelter Code).
- 11.11.2026: Die native Bild-Engine lädt unter Windows ihre vollständige passende Laufzeit mit geprüften
  Downloads automatisch nach; vorhandene Modelle werden weiterverwendet. Unter Linux bleibt die Auswahl gleich.
- 11.11.2026: Unvollständige Bild-Engines werden vor dem Start erkannt; fehlende Laufzeitbibliotheken führen
  zum vorhandenen Kompatibilitätsmodus statt zu einem Systemfehlerdialog.
- 11.11.2026: Für die betroffene Grafikkarte wird unter Windows die native Bild-Engine angeboten; vorhandene
  Modelle bleiben nutzbar, der bestätigte Kompatibilitätsmodus bleibt als Rückweg erhalten.
- 10.11.2026: Kompatibilitätsmodus gegen Farbrauschen mit Qwen-Image; für die bestätigte betroffene Kombination
  automatisch aktiv, in den Bildeinstellungen umschaltbar. Die Berechnung dauert damit länger.
- 10.11.2026: Der Ordner `Fortschritt/` heißt jetzt `progress/`.
- 10.11.2026: 3D-Modell auch aus einer Beschreibung: Monhip erzeugt erst ein passendes Bild und macht daraus das
  3D-Modell.
- 10.11.2026: 3D-Modelle aus einem Bild (Bereich „Bilder“ → „3D-Modell“, mit TRELLIS.2): im Browser ansehen,
  als STL für den 3D-Druck oder als GLB speichern.
- 10.11.2026: Benachrichtigung, wenn eine längere Antwort, ein Bild, eine Auswertung, ein Download oder ein Modell
  fertig ist oder eine Aktion auf Bestätigung wartet – nur, wenn Monhip im Hintergrund ist; abschaltbar.
- 08.11.2026: Repository aufgeräumt: Tests, Werkzeuge und diese Datei unter `Fortschritt/`, unter `installer/` nur noch
  die fertigen Installer; diese Datei gekürzt.
- 08.11.2026: Flüssigere Bedienung: Bilder springen nicht mehr in der Größe, Fortschritt und Seitenleiste „Quellen“
  gleiten, die Galerie blättert schneller.
- 08.11.2026: Durchsicht Bilder und Downloads: Galerie viel schneller, abgerissene Downloads werden fortgesetzt statt
  kaputt übernommen, weitere Härtungen.
- 08.11.2026: Sicherheitsdurchsicht: Teamwork, Webzugriffe, PowerShell-Aufrufe und Downloads gehärtet; llama-server
  nur noch mit Zugangsschlüssel.
- 08.11.2026: Schnellere Dateisuche.

## v1.6.0 – 08.11.2026
- 08.11.2026: Bilder bearbeiten: eigenes Bild wählen, hineinziehen oder einfügen und beschreiben, was sich ändern
  soll; Bildmodell wählen und laden wie im Chat, fehlende Teile lädt Monhip nach.
- 08.11.2026: Qwen-Image 2.1 Turbo ist das Standard-Bildmodell (nur nicht-kommerziell) und im Windows-Installer wählbar.
- 08.11.2026: Teamwork: Die KI erzeugt und bearbeitet auf Wunsch Bilder und teilt sie; reicht der Grafikspeicher
  nicht, fasst sie vorher zusammen und entlädt das Sprachmodell kurz.

## v1.5.1 – 08.11.2026
- 08.11.2026: Qwen3.8-Flash-Next als Alternative zu Qwen3.8-27B (Installer und „Herunterladen…“); aufgeteilte
  Modelle erscheinen als ein Eintrag.

## v1.5.0 – 08.11.2026
- 08.11.2026: Neuer Bereich „Bilder“: Bilder aus einer Beschreibung erzeugen, Galerie, „Beschreibung verbessern“.

## v1.4.8 – 08.11.2026
- 08.11.2026: Seitenleiste „Quellen & Recherche“ zeigt live, was die KI sucht und liest; Quellenangaben sind klickbar.
- 08.11.2026: Expertensuche verzeiht mehr (Wortformen, zusammengesetzte Wörter, Füllwörter).

## v1.4.7 – 05.11.2026
- 05.11.2026: Jupyter-Notebooks lesen, ändern, anlegen und ausführen.
- 04.11.2026: Fenster ziehen und lange Antworten flüssiger; Symbole auch unter Linux.
- 02.11.2026: Monhip läuft unter Linux (Paket .deb); Windows-Installer und .deb zu jedem Release.

## v1.4.6 – 30.10.2026
- 30.10.2026: Hinweise, wo man Bildschirmfotos und „Programme bedienen“ einschaltet; Sprachwechsel startet neu.

## v1.4.5 – 29.10.2026
- 29.10.2026: Rechtsklick-Menü in Eingabefeldern, „Stopp“ wirkt sofort, flüssigeres Scrollen.
- 29.10.2026: Neues Werkzeug „Programme bedienen“ (Fenster per Tastatur und Maus steuern).

## v1.4.4 – 29.10.2026
- 29.10.2026: Einheitliche Icons, Werkzeuggruppen abschaltbar, neue Werkzeuge (PDF, Download, Zwischenablage).

## v1.4.3 – 29.10.2026
- Teamwork: Erlaubnis in drei Stufen, aufgeräumte Seitenleiste.

## v1.4.2 – 28.10.2026
- Ziehen am Fensterrand deutlich flüssiger.

## v1.4.1 – 27.10.2026
- Kontext frei einstellbar; Antworten in langen Chats beginnen schneller.

## v1.4 – 27.10.2026
- 19 neue Agenten-Werkzeuge (u. a. Rechnen, Git, Rückgängig, Arbeitsplan, PDFs und Bilder bearbeiten).

## v1.3 – 27.10.2026
- Oberfläche auf Deutsch und Englisch; Experten-Modus liest eingescannte PDFs.

## v1.2 – 25.10.2026
- Teamwork: Die KI wartet nach @Name auf die Antworten anderer KIs.

## v1.1 – 25.10.2026
- Teamwork: Kontextanzeige, Hauptauftrag, Aufgabenliste, Teamstand, andere KIs fragen.

## v1.0 – 25.10.2026
- Experten-Modus: Ordner mit vielen Dokumenten auswerten.

## Vor v1.0
- Chat mit eigener Ansicht, eigener llama.cpp-Download, Agent (Dateien, Office, Befehle, Websuche, Gedächtnis,
  Erinnerungen), Bildverständnis, Spracherkennung und Teamwork-Räume.
