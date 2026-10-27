# Monhip

Monhip ist eine Desktop-Anwendung für lokale KI-Modelle. Sie verbindet einen Chat mit
Dokumentanalyse, Werkzeugen für die Arbeit am eigenen Rechner und einem Teamwork-Modus,
in dem Menschen und ihre lokalen KI-Assistenten zusammenarbeiten können.

Die Sprachmodelle werden im GGUF-Format über [llama.cpp](https://github.com/ggml-org/llama.cpp)
auf dem eigenen Rechner ausgeführt. Die Oberfläche ist in Python mit Tkinter geschrieben
und überwiegend deutschsprachig. Der aktuelle Funktionsumfang ist auf Windows ausgerichtet.

## Funktionen

### Mit lokalen Modellen chatten

- GGUF-Modelle aus dem Ordner `modelle/` oder aus zusätzlich ausgewählten Ordnern laden.
- Eine passende llama.cpp-Version direkt aus der Anwendung herunterladen und aktualisieren;
  je nach Hardware stehen CPU- und GPU-Varianten zur Verfügung.
- Antworten während der Erzeugung mitlesen und frühere Chats lokal speichern und wieder öffnen.
- System-Prompt, Temperatur, Antwortlänge, Kontextgröße und GPU-Layers einstellen.
- Den belegten Kontext verfolgen und ältere Gesprächsteile bei Bedarf automatisch
  zusammenfassen lassen, um längere Unterhaltungen fortzuführen.

### Dokumente und Bilder einbeziehen

Monhip kann Dokumente als Chat-Anhänge lesen, damit das Modell Fragen dazu beantworten oder
Inhalte zusammenfassen kann. Unterstützt werden unter anderem:

- PDF-Dateien mit auslesbarem Text;
- Word-, Excel- und PowerPoint-Dateien im modernen Office-Format (`.docx`, `.xlsx`, `.pptx`);
- OpenDocument-Dateien (`.odt`, `.ods`, `.odp`), RTF und HTML;
- Text-, Markdown-, CSV-, JSON-, XML- und Quellcodedateien.

Mit einem Modell mit Bildverständnis und einer passenden `mmproj`-Datei lassen sich auch
PNG-, JPG-, BMP- und GIF-Bilder im Chat besprechen. Optional kann die KI nach Bestätigung
Bildschirmfotos anfordern. Die Bildfunktionen setzen entsprechende Modellfähigkeiten voraus.

### Dokumentensammlungen im Experten-Modus auswerten

Der Experten-Modus erschließt einen ganzen Dokumentordner als Wissensquelle für die KI:

- Dokumente einzeln oder bei langen Inhalten abschnittsweise zusammenfassen;
- einen durchsuchbaren Volltextindex und einen Gesamtüberblick erstellen;
- gezielt nach Informationen suchen und einzelne Seiten oder Abschnitte nachlesen;
- eine Auswertung pausieren und fortsetzen sowie geänderte Dateien erneut auswerten.

Eingescannte PDFs können über das Bildverständnis eines geeigneten Modells seitenweise
gelesen werden. Die dafür benötigte PDF-Darstellung verwendet Windows-Funktionen. Ergebnisse
werden separat unter `chats/experten/` gespeichert; die Quelldokumente bleiben unverändert.

### Die KI als Agent einsetzen

Über zuschaltbare Werkzeuge kann das Modell Aufgaben ausführen, die über eine reine
Textantwort hinausgehen:

- Dateien und Ordner in freigegebenen Verzeichnissen lesen, durchsuchen und bearbeiten;
- Word-Dokumente, Excel-Tabellen und PowerPoint-Präsentationen erstellen;
- Programmierprojekte aus Vorlagen anlegen und mit vorhandenen Entwicklungswerkzeugen arbeiten;
- PowerShell- und Python-Befehle ausführen, sofern diese Funktion freigegeben ist;
- im Web suchen und Webseiten als Text abrufen;
- Notizen als chatübergreifendes Gedächtnis speichern und Erinnerungen anlegen.

In den Einstellungen werden Arbeitsordner, zusätzliche freigegebene Ordner und verfügbare
Werkzeuge festgelegt. Die Option „Jede Aktion bestätigen“ lässt Werkzeugaufrufe vor der
Ausführung bestätigen. Welche Aufgaben zuverlässig gelingen, hängt auch vom gewählten
Modell und dessen Unterstützung für Werkzeugaufrufe ab.

Die Websuche verwendet DuckDuckGo oder optional die Brave Search API. Für Brave wird ein
eigener API-Schlüssel benötigt.

### Sprache lokal in Text umwandeln

Mit [whisper.cpp](https://github.com/ggml-org/whisper.cpp) lassen sich Mikrofonaufnahmen und
Audiodateien lokal transkribieren. Die Anwendung kann das benötigte Programm und ein
Spracherkennungsmodell herunterladen. Die Mikrofonaufnahme verwendet Windows-Schnittstellen.

### Im Team zusammenarbeiten

Im Teamwork-Modus erstellt ein Teilnehmer einen Raum auf seinem Rechner. Andere treten
über einen Einladungscode bei; ihre Rechner müssen den Gastgeber über das Netzwerk erreichen können.

- Menschen und ihre KI-Assistenten schreiben in einen gemeinsamen Gruppenchat.
- Mit `@Name` oder `@alle` lassen sich KI-Assistenten ansprechen.
- Ein gemeinsamer Hauptauftrag und eine Aufgabenliste unterstützen die Zusammenarbeit.
- Dateien und ein vom Gastgeber freigegebener Projektordner können gemeinsam genutzt werden.
- Jeder Teilnehmer legt fest, welche Werkzeuge die eigene KI im Raum verwenden darf.
- Laufende KI-Antworten können einzeln oder für den ganzen Raum gestoppt werden.

Jede KI verwendet das auf ihrem jeweiligen Rechner geladene Modell. Der Raum wird vom
Gastgeber betrieben und benötigt einen erreichbaren Netzwerkzugang zu diesem Rechner.

## Voraussetzungen

- **Windows** für den vorgesehenen vollständigen Desktop-Funktionsumfang. Teile der Oberfläche
  und Dokumentverarbeitung lassen sich unter anderen Betriebssystemen ausführen; Downloader,
  Mikrofonaufnahme, Bildverarbeitung und weitere Integrationen verwenden jedoch Windows-Technik.
- **Python mit Tkinter**, beispielsweise Python 3.12, zum Starten aus dem Quellcode.
  Der Python-Code verwendet die Standardbibliothek; separate pip-Pakete sind derzeit nicht deklariert.
- **Ein GGUF-Sprachmodell und llama.cpp** für KI-Antworten. Modelldateien sind nicht im
  Repository enthalten. Arbeitsspeicher, Grafikspeicher und Geschwindigkeit hängen von Modell
  und Einstellungen ab.
- **Optionale Zusatzmodelle** für Bildverständnis und Spracherkennung sowie gegebenenfalls
  weitere Entwicklungswerkzeuge für Programmieraufgaben.

## Start aus dem Quellcode

1. Das Repository klonen oder herunterladen und Python mit Tkinter bereitstellen.
2. Im Repository-Ordner die Anwendung starten:

   ```sh
   python Monhip.pyw
   ```

3. Unter **Einstellungen → Laden** über **„llama.cpp herunterladen / aktualisieren“**
   den Modellserver einrichten.
4. Ein geeignetes `.gguf`-Modell im Ordner `modelle/` ablegen oder unter
   **Einstellungen → Modelle** einen weiteren Modellordner hinzufügen.
5. Das Modell in der Oberfläche auswählen und **„▶ Laden“** anklicken. Nach dem Laden
   kann der erste Chat beginnen.
6. Bei Bedarf unter **Einstellungen → Werkzeuge** zusätzliche Funktionen und Arbeitsordner
   freigeben. Spracherkennung wird separat unter **Einstellungen → Sprache** eingerichtet.

Die Modellberechnung läuft lokal. Downloads, Websuche und Seitenabrufe benötigen
Internetzugriff; der Teamwork-Modus überträgt geteilte Inhalte an die beteiligten Rechner.

## Oberflächensprache

Seit Version 1.3 lässt sich unter **Einstellungen → Darstellung → Oberflächensprache**
zwischen **Deutsch** und **English** wählen. Die Auswahl wird gespeichert und beim nächsten
Start von Monhip angewendet.

Beim ersten Start ohne gespeicherte Sprachauswahl erkennt Monhip die Systemsprache automatisch:
Bei Deutsch erscheint die Oberfläche auf Deutsch, bei Englisch und allen anderen Sprachen auf
Englisch. Unter Windows wird dafür die Windows-Anzeigesprache verwendet. Eine später manuell
gewählte Sprache hat Vorrang vor der Systemsprache.

Die Oberflächensprache ist unabhängig von der Spracherkennung und dem System-Prompt des
KI-Modells. Eigene Nachrichten, Modellantworten, Dokumentinhalte und gespeicherte Namen werden
durch den Sprachwechsel nicht übersetzt oder verändert.

## Lokale Daten und Projektaufbau

Monhip legt Einstellungen und Nutzungsdaten neben dem Startprogramm ab:

| Pfad | Inhalt |
| --- | --- |
| `Monhip.pyw` | Einstiegspunkt zum Starten der Anwendung |
| `app/` | Oberfläche, Modellanbindung, Agentenwerkzeuge und weitere Python-Module |
| `config.json` | Einstellungen der Anwendung |
| `modelle/` | Lokale GGUF-Modelle und Modelle für die Spracherkennung |
| `server/` | Heruntergeladene llama.cpp- und whisper.cpp-Programme |
| `chats/` | Gespeicherte Unterhaltungen, angehängte Bilder und Experten-Auswertungen |
| `gedaechtnis.json` | Chatübergreifende Notizen der KI |
| `erinnerungen.json` | Gespeicherte Erinnerungen |

Die Datenordner und Einstellungsdateien entstehen bei der Nutzung. Eigene Chats, Modelle,
Einstellungen und Zugangsschlüssel gehören zu den lokalen Nutzungsdaten und sollten beim
Veröffentlichen von Quellcode nicht mit hochgeladen werden.
