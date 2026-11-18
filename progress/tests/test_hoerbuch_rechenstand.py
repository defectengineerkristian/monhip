"""Tests für das Hörbuch (app/pdftext.py extract_lines, app/hoerbuchtext.py, app/hoerbuch.py) und den Rechenstand
langer Chats (app/rechenstand.py) – ohne Netz, ohne Grafikkarte, ohne audio.cpp und ffmpeg:
python -m unittest discover -s progress/tests -p test_hoerbuch_rechenstand.py"""

import json
import shutil
import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import hoerbuch
import hoerbuchtext as hbt
import pdftext
import rechenstand


def make_pdf(pages: list[list[tuple[float, float, float, str]]]) -> bytes:
    """Kleines PDF: je Seite [(x, y, Schriftgröße, Text)] in Helvetica (WinAnsi – Umlaute gehen)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    kids = []
    for lines in pages:
        stream = "".join("BT /F1 {0:g} Tf 1 0 0 1 {1:g} {2:g} Tm ({3}) Tj ET\n".format(
            size, x, y, text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)"))
            for x, y, size, text in lines).encode("cp1252")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 420 595] /Contents {len(objs)} 0 R "
                    "/Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + (obj if isinstance(obj, bytes) else obj.encode("latin-1")) + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def body(lines, top=540):
    return [(40, top - i * 15, 11, t) for i, t in enumerate(lines)]


HEAD = [(40, 575, 9, "Das Testbuch")]
BOOK = make_pdf([
    [(60, 400, 24, "Das Testbuch"), (60, 360, 14, "Eine Geschichte von Monhip")],
    [(40, 540, 18, "Inhalt"), (40, 510, 11, "Kapitel 1: Der Anfang . . . . . . . . . . 3"),
     (40, 495, 11, "Kapitel 2: Die Reise . . . . . . . . . . . 4"), (40, 480, 11, "Literatur . . . . . . . . . 6")],
    HEAD + [(40, 540, 18, "Kapitel 1: Der Anfang")] + body([
        "Als Anna am Morgen den Bahnhof betrat, lag noch Nebel über den",
        "Gleisen. Sie hatte kein Ver-",
        "ständnis für die Eile der anderen Reisenden¹ und blieb stehen.",
        "Dann ging sie weiter.",
        "Abbildung 1: Ein Bahnhof im Nebel",
        "Der Zug kam pünktlich, was z. B. im Winter selten ist, und sie",
        "stieg in den zweiten Wagen.",
    ], top=510) + [(40, 60, 8, "1 Gemeint sind die Pendler aus der Stadt."), (200, 30, 9, "3")],
    HEAD + body(["Im Abteil saß ein alter Mann mit einem Hut. „Wohin fahren Sie?“,", "fragte er freundlich.",
                 "„Nach Norden“, sagte Anna."]) + [(200, 30, 9, "4")],
    HEAD + [(40, 540, 18, "Kapitel 2: Die Reise")] + body([
        "Die Landschaft zog vorbei. Felder, Wälder und kleine Dörfer",
        "wechselten sich ab, bis am Abend das Meer zu sehen war."], top=510) + [(200, 30, 9, "5")],
    HEAD + [(40, 540, 18, "Literatur")] + body(["Müller, A. (2020): Reisen im Nebel. Berlin."], top=510)
    + [(200, 30, 9, "6")],
])


class PdfLines(unittest.TestCase):
    def test_lines_with_font_sizes(self):
        pages = pdftext.extract_lines(BOOK)
        self.assertEqual(len(pages), 6)
        self.assertEqual(pages[0], [("Das Testbuch", 24), ("Eine Geschichte von Monhip", 14)])
        self.assertIn(("1 Gemeint sind die Pendler aus der Stadt.", 8), pages[2])
        self.assertEqual(pages[2][-1], ("3", 9))

    def test_plain_text_unchanged(self):
        text, count = pdftext.extract(BOOK)
        self.assertEqual(count, 6)
        self.assertIn("Kapitel 2: Die Reise", text)


class Prepare(unittest.TestCase):
    def setUp(self):
        self.pages = pdftext.extract_lines(BOOK)
        self.book = hbt.prepare(self.pages, hbt.detect_language(self.pages))

    def test_only_the_real_text(self):
        book = self.book
        self.assertEqual(book["title"], "Das Testbuch")
        self.assertEqual([c["title"] for c in book["chapters"]], ["Kapitel 1: Der Anfang", "Kapitel 2: Die Reise"])
        first = book["chapters"][0]["paragraphs"]
        self.assertEqual(first[0], "Als Anna am Morgen den Bahnhof betrat, lag noch Nebel über den Gleisen. Sie hatte "
                                   "kein Verständnis für die Eile der anderen Reisenden und blieb stehen. Dann ging "
                                   "sie weiter.")
        self.assertIn("zum Beispiel", first[1])
        text = " ".join(p for c in book["chapters"] for p in c["paragraphs"])
        for gone in ("Abbildung", "Pendler", "Das Testbuch", "Müller", "Inhalt", "Eine Geschichte"):
            self.assertNotIn(gone, text)
        self.assertEqual(set(book["removed"]), {"Kopf- und Fußzeilen", "Inhaltsverzeichnis (Seiten)",
                                                "Bild- und Tabellenunterschriften", "Fußnoten",
                                                "Literatur, Register, Anhang (Seiten ab hier)",
                                                "Titelei vor dem ersten Kapitel"})
        self.assertEqual(book["chapters"][0]["pages"], (3, 4))

    def test_hyphenation(self):
        self.assertEqual(hbt._join("Ver-", "ständnis für"), "Verständnis für")
        self.assertEqual(hbt._join("per E-", "Mail"), "per E-Mail")
        self.assertEqual(hbt._join("Nord-", "und Süd"), "Nord- und Süd")
        self.assertEqual(hbt._join("Satz", "weiter"), "Satz weiter")

    def test_clean_line(self):
        self.assertEqual(hbt.clean_line("Siehe S. 12, vgl. [3] und https://www.example.com/x²."),
                         "Siehe Seite 12, vergleiche und example.com.")
        self.assertEqual(hbt.clean_line("Eine Fläche von 20 m²"), "Eine Fläche von 20 Quadratmeter")

    def test_language_and_selection(self):
        self.assertEqual(hbt.detect_language([[("The man and the dog went to the park, and it was fun.", 11)]]),
                         "en")
        self.assertEqual(hbt.detect_language(self.pages), "de")
        chapters = [{}] * 6
        self.assertEqual(hbt.select(chapters, ""), list(range(6)))
        self.assertEqual(hbt.select(chapters, "1-2,5-"), [0, 1, 4, 5])
        with self.assertRaises(ValueError):
            hbt.select(chapters, "abc")
        with self.assertRaises(ValueError):
            hbt.select(chapters, "9")

    def test_without_headings_parts_are_cut(self):
        text = "Ein Satz, der eine ganz normale Zeile Fließtext füllt und weitergeht."
        pages = [[(text, 11)] * 40 for _ in range(30)]
        with mock.patch.object(hbt, "PART_CHARS", 20_000):
            book = hbt.prepare(pages)
        self.assertGreater(len(book["chapters"]), 2)
        self.assertEqual(book["chapters"][0]["title"], "Teil 1")

    def test_overview_for_the_model(self):
        text = hbt.overview(self.book, [1])
        self.assertIn("2 Kapitel", text)
        self.assertIn("1. Kapitel 1: Der Anfang", text)
        self.assertIn("(nicht ausgewählt)", text)
        self.assertIn("Weggelassen:", text)


def write_wav(path: Path, seconds: float = 0.2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00\x00" * int(24000 * seconds))


class Render(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.model = self.dir / "modell.gguf"
        self.model.write_bytes(b"x")
        self.book = {"title": "Buch", "chapters": [
            {"title": "Kapitel 1: Start", "paragraphs": ["Absatz eins.", "Absatz zwei."]},
            {"title": "Kapitel 2: Ende", "paragraphs": ["Nur ein Absatz."]}]}

    def test_segments_and_names(self):
        segs = hoerbuch.segments({"title": "Kapitel 1", "paragraphs": ["a" * 900, "b" * 900, "Satz. " * 400]},
                                 max_chars=1000)
        self.assertEqual(segs[0], "Kapitel 1.")
        self.assertTrue(all(len(s) <= 1000 for s in segs))
        self.assertEqual("".join(segs[1:]).replace("\n", "").replace(" ", ""),
                         ("a" * 900 + "b" * 900 + "Satz. " * 400).replace(" ", ""))
        self.assertEqual(hoerbuch.file_name(3, 'Kapitel 3: Wer? Was/Wie "jetzt"'), "03 – Kapitel 3 Wer Was Wie jetzt.mp3")
        self.assertEqual(hoerbuch.file_name(12, ""), "12.mp3")

    def test_voices(self):
        self.assertEqual(hoerbuch.voice_args("aiden", "de")[:4], ["--task", "tts", "--speaker", "aiden"])
        design = hoerbuch.voice_args("erzaehlerin", "en")
        self.assertEqual(design[:2], ["--task", "vdes"])
        self.assertIn("female", design[3])
        self.assertEqual(hoerbuch.voice_key("gibtsnicht"), hoerbuch.DEFAULT_VOICE)
        for key, v in hoerbuch.VOICES.items():
            self.assertIn(v["variant"], hoerbuch.MODELS)
            self.assertRegex(hoerbuch.MODELS[v["variant"]][2], r"^[0-9a-f]{64}$")

    def test_render_writes_chapters_and_resumes(self):
        spoken, encoded = [], []

        def speak(exe, model, voice, language, src, out, sizes, stop, done, total, on_progress, log):
            for key in sorted(sizes):
                write_wav(out / f"{key}.wav")
                done += sizes[key]
                on_progress(done)
            spoken.append(sorted(p.read_text(encoding="utf-8") for p in src.glob("*.txt")))
            return done

        def encode(ffmpeg, wavs, silence, target, title, album, track, tracks, stop):
            encoded.append((target.name, title, album, track, tracks, len(wavs)))
            target.write_bytes(b"mp3")

        progress = []
        with mock.patch.object(hoerbuch, "find_cli", return_value=self.dir / "cli"), \
                mock.patch.object(hoerbuch, "find_ffmpeg", return_value=self.dir / "ffmpeg"), \
                mock.patch.object(hoerbuch, "model_path", return_value=self.model), \
                mock.patch.object(hoerbuch, "_speak", side_effect=speak), \
                mock.patch.object(hoerbuch, "_encode", side_effect=encode):
            out = self.dir / "Hörbuch"
            res = hoerbuch.render(self.book, [0, 1], out, "aiden", "de", threading.Event(),
                                  lambda d, n, nr, t: progress.append((d, n, nr)))
            self.assertEqual([f.name for f in res["files"]], ["01 – Kapitel 1 Start.mp3", "02 – Kapitel 2 Ende.mp3"])
            self.assertEqual(encoded[0][1:], ("Kapitel 1: Start", "Buch", 1, 2, 2))
            self.assertEqual(spoken[0], ["Absatz eins.\nAbsatz zwei.", "Kapitel 1: Start."])
            self.assertEqual(progress[-1][0], progress[-1][1])  # am Ende 100 %
            self.assertAlmostEqual(res["seconds"], 0.2 * 4 + hoerbuch.PAUSE_SECONDS * 2, places=2)
            again = hoerbuch.render(self.book, [0, 1], out, "aiden", "de", threading.Event())
            self.assertEqual(again["skipped"], 2)
            self.assertEqual(len(spoken), 2)  # nichts neu gesprochen

    def test_render_needs_the_engine(self):
        with mock.patch.object(hoerbuch, "find_cli", return_value=None):
            with self.assertRaises(RuntimeError):
                hoerbuch.render(self.book, [0], self.dir, "aiden", "de", threading.Event())

    def test_pick_builds(self):
        assets = {n: {"name": n} for n in ("audio-v0.9.5-bin-windows-x64-cuda12.4.zip",
                                           "audio-v0.9.5-bin-windows-x64-cuda13.3.zip",
                                           "audio-v0.9.5-bin-windows-x64-cpu.zip",
                                           "audio-v0.9.5-bin-ubuntu-x64-vulkan.tar.gz",
                                           "audio-v0.9.5-bin-ubuntu-x64-cpu.tar.gz")}
        with mock.patch.object(hoerbuch.plattform, "WINDOWS", True):
            self.assertEqual(hoerbuch._pick(assets, "nvidia", (13, 4))[0], "cuda13.3")
            self.assertEqual(hoerbuch._pick(assets, "nvidia", (12, 8))[0], "cuda12.4")
            self.assertEqual(hoerbuch._pick(assets, "amd", None)[0], "cpu")
        with mock.patch.object(hoerbuch.plattform, "WINDOWS", False), \
                mock.patch.object(hoerbuch.platform, "machine", return_value="x86_64"):
            self.assertEqual(hoerbuch._pick(assets, "amd", None)[0], "vulkan")
            self.assertEqual(hoerbuch._pick(assets, "", None)[0], "cpu")
        self.assertEqual(hoerbuch._version("v0.9.5"), 905)
        self.assertEqual(hoerbuch._version("v1.12.0"), 11200)


class FakeServer:
    def __init__(self, base="http://127.0.0.1:1"):
        self.base_url = base
        self.last = {"model": "m.gguf", "ctx": 8192, "mmproj": None, "extra": ""}

    def is_running(self):
        return True


class ChatState(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        patcher = mock.patch.object(rechenstand, "DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_save(self, n):
        def action(base, headers, act, chat_id, timeout=120):
            if act == "save":
                (self.dir / f"{chat_id}.bin").write_bytes(b"x" * 10)
                return {"n_saved": n}
            return {"n_restored": n}
        return mock.patch.object(rechenstand, "_slot_action", side_effect=action)

    def test_save_and_restore(self):
        server = FakeServer()
        with self.fake_save(9000):
            self.assertEqual(rechenstand.save(server, "20261118-000340-9441", 9500), 9000)
            meta = json.loads((self.dir / "20261118-000340-9441.json").read_text(encoding="utf-8"))
            self.assertEqual((meta["model"], meta["ctx"], meta["tokens"]), ("m.gguf", 8192, 9000))
            self.assertEqual(rechenstand.restore(server, "20261118-000340-9441"), 9000)
            other = FakeServer()
            other.last = {**server.last, "ctx": 4096}  # anderer Kontext: nicht laden, aber behalten
            self.assertEqual(rechenstand.restore(other, "20261118-000340-9441"), 0)
            self.assertTrue((self.dir / "20261118-000340-9441.bin").is_file())

    def test_short_chats_and_foreign_slots_are_not_kept(self):
        server = FakeServer()
        with self.fake_save(9000):
            self.assertEqual(rechenstand.save(server, "kurz", 100), 0)
        with self.fake_save(1200):  # auf dem Platz lag inzwischen eine andere, kurze Anfrage
            self.assertEqual(rechenstand.save(server, "lang", 9000), 0)
        self.assertEqual(list(self.dir.iterdir()), [])
        self.assertEqual(rechenstand.save(server, "../böse", 9000), 0)

    def test_prune_keeps_the_newest(self):
        import os
        import time
        for i, name in enumerate(("alt", "mittel", "neu")):
            (self.dir / f"{name}.bin").write_bytes(b"x" * 100)
            (self.dir / f"{name}.json").write_text("{}", encoding="utf-8")
            t = time.time() - 100 + i * 10
            os.utime(self.dir / f"{name}.bin", (t, t))
        (self.dir / "halb.bin").write_bytes(b"x")  # ohne .json
        rechenstand.prune(max_bytes=250)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ["mittel.bin", "mittel.json", "neu.bin", "neu.json"])


if __name__ == "__main__":
    unittest.main()
