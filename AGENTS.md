# Hinweise für KI-Agenten (Codex und andere)

Dieses Repository ist **Monhip**: eine Windows-Desktop-App (Python 3.13 + Tkinter, nur Standardbibliothek), die lokale
GGUF-Sprachmodelle über llama.cpp lädt, mit ihnen chattet und sie als Agent arbeiten lässt.

## Zuerst lesen

**Vor jeder Arbeit `git pull` und [`FORTSCHRITT.md`](FORTSCHRITT.md) lesen** – mindestens „So arbeiten wir mit dieser
Datei“, „In Arbeit“, „Entscheidungen“ und „Regeln für den Code“. Dort steht, wer gerade woran arbeitet, was entschieden
ist, wie der Code aufgebaut ist und wie getestet wird. Diese Datei ist nur der Wegweiser; bei Widersprüchen gilt
`FORTSCHRITT.md` (und dort im Zweifel der Code).

## Das Wichtigste in Kürze

- **Vor dem Start** unter „In Arbeit“ eintragen (Mensch + Modell, z. B. „Max + Codex“, was, welche Dateien, Datum),
  committen und pushen – erst dann anfangen. Dateien, die dort jemand anders stehen hat, nicht ändern.
- **Fertig:** Zeile unter „In Arbeit“ löschen und oben im Verlauf eintragen – im selben Commit wie die Änderung.
- Nur das ändern, worum dein Mensch gebeten hat. Committen und pushen nur nach ausdrücklichem OK eines Menschen,
  Releases (Tag + GitHub-Release) nur nach OK des Projektinhabers.
- Nur die Python-Standardbibliothek, keine pip-Pakete. Code-Kommentare auf Deutsch; Oberflächentexte über `tr('…')`
  mit englischem Eintrag in `app/i18n_en.py`.
- Es gibt keine `.gitignore`: nur einzelne Dateien aufnehmen (`git add <datei>`), nie `git add -A` oder `git add .`.
- Commits ohne „Co-Authored-By“-Zeile; Zeilenenden je Datei beibehalten (`git ls-files --eol`).
- Tests: `py -m unittest discover -s tests -v` (einige Tests öffnen kurz Monhip-Fenster).
