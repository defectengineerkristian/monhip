"""Tests für die Sprachausgabe (app/sprachausgabe.py: Markdown → vorlesbare Sätze, Download-Plan, Vorlesen mit Stopp)
und das Hochskalieren (app/hochskalieren.py: Plan, Fortschritt, 2× über 4×, Rückweg über den Prozessor) – ohne Netz,
ohne piper und ohne Grafikkarte: python -m unittest discover -s progress/tests -p test_sprachausgabe_hochskalieren.py"""

import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import downloads
import engines
import hochskalieren
import sprachausgabe as sa


def write_wav(path: Path, seconds: float = 0.05):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))


def write_png_head(path: Path, width: int, height: int):
    """Nur der Kopf einer PNG-Datei – genug für images.png_size."""
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height)
                     + b"\x08\x02\x00\x00\x00")


class Speakable(unittest.TestCase):
    MD = ("## Ergebnis\nHallo! Das ist **wichtig**: z. B. am 1. Mai um 14:30 Uhr. Siehe [die Doku](https://www.example.com/a).\n"
          "- Erster Punkt\n- Zweiter Punkt 🎉\n\n```python\nprint('x')\n```\n| A | B |\n|---|---|\n| 1 | 2 |\n"
          "Mehr unter https://github.com/x/y. Ende.")

    def test_markdown_becomes_clean_sentences(self):
        self.assertEqual(sa.speakable(self.MD), [
            "Ergebnis.", "Hallo!", "Das ist wichtig: z. B. am 1. Mai um 14:30 Uhr.", "Siehe die Doku.",
            "Erster Punkt.", "Zweiter Punkt.", "Codeblock ausgelassen.", "A, B.", "1, 2.",
            "Mehr unter github.com.", "Ende."])

    def test_code_note_follows_the_voice_language(self):
        self.assertEqual(sa.speakable("```\nx = 1\n```", "en"), ["Code block skipped."])

    def test_streaming_in_small_pieces_gives_the_same_sentences(self):
        for size in (1, 3, 7, 50):
            with self.subTest(size=size):
                stream = sa.SpeechStream("de")
                out = []
                for i in range(0, len(self.MD), size):
                    out += stream.feed(self.MD[i:i + size])
                out += stream.flush()
                self.assertEqual(out, sa.speakable(self.MD))

    def test_list_item_with_two_sentences_streams_like_the_whole(self):
        text = "- Erster Satz. Zweiter Teil\n## Titel. Mehr dazu\nEnde"
        stream = sa.SpeechStream("de")
        out = [s for ch in text for s in stream.feed(ch)] + stream.flush()
        self.assertEqual(out, sa.speakable(text))
        self.assertEqual(out, ["Erster Satz.", "Zweiter Teil.", "Titel.", "Mehr dazu.", "Ende"])

    def test_sentences_come_before_the_line_ends(self):
        stream = sa.SpeechStream("de")
        self.assertEqual(stream.feed("Erster Satz. Zweiter"), ["Erster Satz."])
        self.assertEqual(stream.feed(" Satz ist da."), [])  # Satzende erst sicher, wenn danach etwas folgt
        self.assertEqual(stream.feed("\n"), ["Zweiter Satz ist da."])

    def test_lowercase_after_a_dot_is_no_new_sentence(self):
        self.assertEqual(sa.speakable("Version 2. danach weiter. Gut."), ["Version 2. danach weiter.", "Gut."])

    def test_long_sentences_are_split_at_commas(self):
        long = ", ".join(["ein recht langer Teilsatz"] * 30) + "."
        parts = sa.speakable(long)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= sa.MAX_CHUNK + 1 for p in parts))
        self.assertEqual(" ".join(parts).replace(" ,", ","), long)

    def test_nothing_to_say(self):
        self.assertEqual(sa.speakable("---\n\n🎉🎉\n"), [])


class VoicesAndPlan(unittest.TestCase):
    def test_voice_and_speed_defaults(self):
        self.assertEqual(sa.voice_key("", "de"), "de_DE-thorsten-medium")
        self.assertEqual(sa.voice_key(None, "en"), "en_US-amy-medium")
        self.assertEqual(sa.voice_key("de_DE-kerstin-low", "en"), "de_DE-kerstin-low")
        self.assertEqual(sa.speed_value("fast"), 0.85)
        self.assertEqual(sa.speed_value("unbekannt"), 1.0)
        self.assertEqual(set(sa.speed_labels()), set(sa.SPEEDS))

    def test_voices_are_pinned_to_v1_with_checksums(self):
        for key in sa.VOICES:
            for dest, url, sha in sa.voice_files(key):
                self.assertIn("/resolve/v1.0.0/", url)
                self.assertTrue(url.endswith(dest.name))
                self.assertRegex(sha, r"^[0-9a-f]{64}$")

    def test_program_per_platform(self):
        self.assertEqual(sa.asset_name(windows=True), "piper_windows_amd64.zip")
        self.assertEqual(sa.asset_name(windows=False, machine="x86_64"), "piper_linux_x86_64.tar.gz")
        self.assertEqual(sa.asset_name(windows=False, machine="aarch64"), "piper_linux_aarch64.tar.gz")
        self.assertIsNone(sa.asset_name(windows=False, machine="riscv64"))

    def test_plan_without_network(self):
        release = {"tag_name": "2023.11.14-2", "assets": [
            {"name": sa.asset_name(), "browser_download_url": "https://example.invalid/p.zip", "size": 100}]}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(sa, "VOICE_DIR", Path(d)), \
                mock.patch.object(sa, "find_piper", return_value=None), \
                mock.patch.object(downloads, "get_json", return_value=release), \
                mock.patch.object(downloads, "head_size", return_value=50):
            p = sa.plan("de_DE-eva_k-x_low")
            self.assertEqual(p["target"].name, "piper-b202311142-cpu")
            self.assertEqual([w[0] for w in p["weights"]], ["de_DE-eva_k-x_low.onnx", "de_DE-eva_k-x_low.onnx.json"])
            self.assertEqual([w[4] for w in p["weights"]], list(sa.VOICES["de_DE-eva_k-x_low"]["sha256"]))
            self.assertEqual(p["size"], 200)
            for dest, _, _ in sa.voice_files("de_DE-eva_k-x_low"):
                dest.write_bytes(b"x")
            with mock.patch.object(sa, "find_piper", return_value=Path(d) / "piper"):
                self.assertEqual(sa.plan("de_DE-eva_k-x_low")["size"], 0)

    def test_weights_pass_their_checksum_to_the_download(self):
        calls = []
        with mock.patch.object(downloads, "fetch_one", side_effect=lambda *a, **k: calls.append(k) or 0):
            engines.install({"size": 0, "weights": [("a", "u", 1, Path("a"), "f" * 64), ("b", "u", 1, Path("b"))]},
                            Path("."), "x", None, None, threading.Event())
        self.assertEqual([c.get("sha256") for c in calls], ["f" * 64, None])


class FakePiper:
    """Statt piper: schreibt für jeden Satz eine kurze WAV-Datei."""

    def __init__(self, folder: Path, delay: float = 0.0):
        self.folder, self.delay, self.said = folder, delay, []

    def say(self, sentence):
        time.sleep(self.delay)
        self.said.append(sentence)
        path = self.folder / f"{len(self.said)}.wav"
        write_wav(path)
        return path


class FakeSound:
    SND_FILENAME = SND_ASYNC = SND_NODEFAULT = 0

    def __init__(self):
        self.played = []

    def PlaySound(self, path, _flags):
        self.played.append(Path(path).name if path else None)


class SpeakerTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.sound = FakeSound()
        patcher = mock.patch.object(sa, "winsound", self.sound)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.states, self.errors = [], []
        self.speaker = sa.Speaker(on_state=self.states.append, on_error=self.errors.append)
        self.addCleanup(self.speaker.shutdown)

    def wait_inactive(self, timeout=10):
        end = time.monotonic() + timeout
        while self.speaker.active and time.monotonic() < end:
            time.sleep(0.02)

    def test_reads_everything_in_order_and_reports_the_end(self):
        piper = FakePiper(self.dir)
        with mock.patch.object(sa.Speaker, "_get_piper", lambda _self: piper):
            self.speaker.say("Eins. Zwei. Drei.", "de_DE-thorsten-medium", tag="t")
            self.assertTrue(self.speaker.active)
            self.wait_inactive()
        self.assertEqual(piper.said, ["Eins.", "Zwei.", "Drei."])
        self.assertEqual([p for p in self.sound.played if p], ["1.wav", "2.wav", "3.wav"])
        self.assertEqual(self.states, [True, False])
        self.assertIsNone(self.speaker.tag)
        self.assertEqual(list(self.dir.glob("*.wav")), [])  # abgespielte Dateien sind weg
        self.assertEqual(self.errors, [])

    def test_stop_discards_the_rest(self):
        piper = FakePiper(self.dir, delay=0.2)
        with mock.patch.object(sa.Speaker, "_get_piper", lambda _self: piper):
            self.speaker.say("Eins. Zwei. Drei. Vier. Fünf.", "de_DE-thorsten-medium")
            time.sleep(0.3)
            self.speaker.stop()
            self.assertFalse(self.speaker.active)
            time.sleep(0.6)
        self.assertLess(len([p for p in self.sound.played if p]), 3)
        self.assertEqual(self.states, [True, False])

    def test_streaming_feed_flush_finish(self):
        piper = FakePiper(self.dir)
        with mock.patch.object(sa.Speaker, "_get_piper", lambda _self: piper):
            self.speaker.start("de_DE-thorsten-medium")
            for piece in ("Ich schau", " nach. ", "Moment"):
                self.speaker.feed(piece)
            self.speaker.flush()  # Antwortteil endet (Werkzeugaufruf)
            self.speaker.feed("Fertig: alles gut.")
            self.speaker.finish()
            self.wait_inactive()
        self.assertEqual(piper.said, ["Ich schau nach.", "Moment", "Fertig: alles gut."])

    def test_errors_end_reading_and_are_reported(self):
        def broken(_self):
            raise RuntimeError("piper fehlt")
        with mock.patch.object(sa.Speaker, "_get_piper", broken):
            self.speaker.say("Hallo.", "de_DE-thorsten-medium")
            self.wait_inactive()
        self.assertEqual(self.errors, ["piper fehlt"])
        self.assertFalse(self.speaker.active)


class Upscale(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_keys_sizes_and_sources(self):
        self.assertEqual(hochskalieren.key("art"), "art")
        self.assertEqual(hochskalieren.key("unbekannt"), hochskalieren.DEFAULT)
        self.assertEqual(hochskalieren.result_size(384, 256, 4), (1536, 1024))
        for up in hochskalieren.UPSCALERS.values():
            self.assertTrue(up["url"].startswith("https://github.com/xinntao/Real-ESRGAN/releases/download/"))
            self.assertRegex(up["sha256"], r"^[0-9a-f]{64}$")

    def test_plan_only_the_model_when_the_engine_is_there(self):
        with mock.patch.object(hochskalieren, "MODEL_DIR", self.dir), \
                mock.patch.object(hochskalieren, "find_cli", return_value=self.dir / "sd-cli"), \
                mock.patch.object(downloads, "head_size", return_value=0):
            p = hochskalieren.plan("art")
        self.assertEqual(p["program"], [])
        self.assertEqual(p["weights"][0][0], "RealESRGAN_x4plus_anime_6B.pth")
        self.assertEqual(p["weights"][0][4], hochskalieren.UPSCALERS["art"]["sha256"])
        self.assertEqual(p["size"], 17 * 2 ** 20)  # ohne Größe vom Server: die aus dem Katalog

    def test_plan_with_engine_download_drops_the_image_model(self):
        engine = {"tag": "master-1", "kind": "CUDA 12", "gpu": "", "target": self.dir / "sd-b1-cuda12",
                  "program": [("sd.zip", "u", 300, None)], "weights": [("riesig.gguf", "u", 9 * 10 ** 9, None)],
                  "runtime": None}
        with mock.patch.object(hochskalieren, "MODEL_DIR", self.dir), \
                mock.patch.object(hochskalieren, "find_cli", return_value=None), \
                mock.patch.object(hochskalieren.sdcpp, "plan", return_value=engine), \
                mock.patch.object(downloads, "head_size", return_value=1000):
            p = hochskalieren.plan("photo")
        self.assertEqual([w[0] for w in p["weights"]], ["RealESRGAN_x4plus.pth"])
        self.assertEqual(p["size"], 1300)

    def test_progress_counts_tiles_not_model_parts(self):
        script = ("import sys; o = sys.stdout.buffer; o.write(b'|=====| 702/702 - 9.0it/s\\r'); "
                  "o.write(b'[I] loading tensors completed\\n'); o.write(b'|==| 1/4 - 5it/s\\r|====| 4/4 - 5it/s\\r\\n')")
        seen = []
        code, _tail = hochskalieren._run([sys.executable, "-c", script], Path(sys.executable), threading.Event(),
                                         lambda d, n: seen.append((d, n)), None)
        self.assertEqual(code, 0)
        self.assertTrue(seen)
        self.assertTrue(all(total == 4 for _, total in seen))
        self.assertEqual(seen[-1], (4, 4))

    def test_stop_ends_the_program(self):
        stop = threading.Event()
        threading.Timer(0.3, stop.set).start()
        t0 = time.monotonic()
        with self.assertRaises(hochskalieren.Cancelled):
            hochskalieren._run([sys.executable, "-c", "import time; time.sleep(30)"], Path(sys.executable), stop,
                               None, None)
        self.assertLess(time.monotonic() - t0, 10)

    def fake_engine(self):
        (self.dir / "RealESRGAN_x4plus.pth").write_bytes(b"x")
        return (mock.patch.object(hochskalieren, "MODEL_DIR", self.dir),
                mock.patch.object(hochskalieren, "find_cli", return_value=self.dir / "sd-cli"))

    def test_two_times_is_four_times_then_shrunk(self):
        def run(args, *_a):
            write_png_head(Path(args[args.index("-o") + 1]), 1600, 1200)
            return 0, []

        fitted = []

        def fit(src, dst, w, h):
            fitted.append((w, h))
            write_png_head(dst, w, h)
            return w, h

        a, b = self.fake_engine()
        with a, b, mock.patch.object(hochskalieren, "_run", side_effect=run), \
                mock.patch.object(hochskalieren.images, "fit", side_effect=fit):
            out = self.dir / "out.png"
            self.assertEqual(hochskalieren.upscale("photo", self.dir / "in.png", out, 2, threading.Event()), (800, 600))
        self.assertEqual(fitted, [(800, 600)])
        self.assertEqual(sorted(p.name for p in self.dir.glob("*.png")), ["out.png"])  # kein 4×-Zwischenbild übrig

    def test_falls_back_to_the_processor(self):
        calls, cpu = [], []

        def run(args, *_a):
            calls.append(args)
            if "--backend" not in args:
                return 1, ["ggml_cuda: out of memory"]
            write_png_head(Path(args[args.index("-o") + 1]), 400, 400)
            return 0, []

        a, b = self.fake_engine()
        with a, b, mock.patch.object(hochskalieren, "_run", side_effect=run):
            size = hochskalieren.upscale("photo", self.dir / "in.png", self.dir / "out.png", 4, threading.Event(),
                                         on_cpu=lambda: cpu.append(True))
        self.assertEqual(size, (400, 400))
        self.assertEqual(cpu, [True])
        self.assertEqual(calls[1][-2:], ["--backend", "cpu"])

    def test_error_names_the_reason(self):
        a, b = self.fake_engine()
        with a, b, mock.patch.object(hochskalieren, "_run", return_value=(1, ["x", "error: model not supported"])):
            with self.assertRaisesRegex(RuntimeError, "model not supported"):
                hochskalieren.upscale("photo", self.dir / "in.png", self.dir / "out.png", 4, threading.Event())


if __name__ == "__main__":
    unittest.main()
