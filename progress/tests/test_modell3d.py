"""3D-Modelle aus Bildern: GLB lesen, als STL für den 3D-Druck schreiben (Z oben, Höhe in mm, auf der Platte), die
eigenständige Ansicht für den Browser, die Wahl des passenden trellis.cpp-Pakets je Grafikkarte, der Download-Plan,
der Fortschritt aus der Ausgabe von trellis-cli und – mit einem nachgestellten trellis-cli – Erzeugen, Fehler und
Abbrechen: python -m unittest discover -s progress/tests -p test_modell3d.py"""

import base64
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import zlib
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import i18n  # noqa: E402
import galerie  # noqa: E402
import modell3d  # noqa: E402
import trellis  # noqa: E402


def png(w: int = 8, h: int = 8) -> bytes:
    rows = b"".join(b"\0" + bytes((x * 30) % 256 for x in range(w * 3)) for _ in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def box_glb(size=(1.0, 2.0, 0.5), node: dict | None = None) -> bytes:
    """Quader (Breite x, Höhe y, Tiefe z – glTF: Y oben) mit Normalen, UVs, uint32-Indizes und PNG-Textur, wie ihn
    trellis.cpp aufbaut (ein Knoten, ein Netz, ein Material)."""
    sx, sy, sz = (v / 2 for v in size)
    corners = [(x * sx, y * sy, z * sz) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    pos = [c for p in corners for c in p]
    nrm = [c for p in corners for c in (p[0] / sx / 3 ** .5, p[1] / sy / 3 ** .5, p[2] / sz / 3 ** .5)]
    uv = [0.0, 0.0] * 8
    idx = [i for a, b, c, d in quads for i in (a, b, c, a, c, d)]
    parts = [struct.pack(f"<{len(pos)}f", *pos), struct.pack(f"<{len(nrm)}f", *nrm), struct.pack(f"<{len(uv)}f", *uv),
             struct.pack(f"<{len(idx)}I", *idx), png()]
    views, blob = [], b""
    for p in parts:
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(p)})
        blob += p + b"\0" * (-len(p) % 4)
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [node or {"mesh": 0}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3,
                                       "material": 0, "mode": 4}]}],
           "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
           "textures": [{"source": 0}], "images": [{"bufferView": 4, "mimeType": "image/png"}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3"},
                         {"bufferView": 1, "componentType": 5126, "count": 8, "type": "VEC3"},
                         {"bufferView": 2, "componentType": 5126, "count": 8, "type": "VEC2"},
                         {"bufferView": 3, "componentType": 5125, "count": len(idx), "type": "SCALAR"}],
           "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    j = json.dumps(doc).encode()
    j += b" " * (-len(j) % 4)
    return (b"glTF" + struct.pack("<II", 2, 28 + len(j) + len(blob)) + struct.pack("<II", len(j), 0x4E4F534A) + j
            + struct.pack("<II", len(blob), 0x004E4942) + blob)


def stl_triangles(data: bytes) -> list[tuple]:
    n = struct.unpack_from("<I", data, 80)[0]
    return [struct.unpack_from("<12f", data, 84 + 50 * i) for i in range(n)]


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name)
        i18n._language = "de"

    def tearDown(self):
        self.dir.cleanup()

    def test_stl_for_printing_z_up_height_in_mm_on_the_plate(self):
        glb = self.path / "quader.glb"
        glb.write_bytes(box_glb((1.0, 2.0, 0.5)))  # 1 breit, 2 hoch (Y), 0,5 tief
        size = modell3d.to_stl(glb, self.path / "quader.stl", height_mm=80)
        self.assertEqual([round(v, 3) for v in size], [40.0, 20.0, 80.0])  # Breite × Tiefe × Höhe
        data = (self.path / "quader.stl").read_bytes()
        tris = stl_triangles(data)
        self.assertEqual(len(tris), 12)
        self.assertEqual(len(data), 84 + 50 * 12)
        xs = [t[3 + 3 * k] for t in tris for k in range(3)]
        ys = [t[4 + 3 * k] for t in tris for k in range(3)]
        zs = [t[5 + 3 * k] for t in tris for k in range(3)]
        self.assertAlmostEqual(min(zs), 0, places=4)      # steht auf der Platte
        self.assertAlmostEqual(max(zs), 80, places=4)     # glTF-Höhe (Y) ist jetzt Z
        self.assertAlmostEqual(min(xs), -20, places=4)    # mittig
        self.assertAlmostEqual(max(ys) - min(ys), 20, places=4)
        for t in tris:  # Normalen haben die Länge 1
            self.assertAlmostEqual(sum(c * c for c in t[:3]), 1, places=4)

    def test_node_transform_counts(self):
        glb = self.path / "gross.glb"
        glb.write_bytes(box_glb((1.0, 1.0, 1.0), {"mesh": 0, "scale": [2, 3, 4], "translation": [5, 0, 0]}))
        info = modell3d.stats(glb)
        self.assertEqual(info["triangles"], 12)
        self.assertEqual([round(v, 4) for v in info["size"]], [2.0, 4.0, 3.0])  # Breite, Tiefe, Höhe

    def test_broken_files_are_reported(self):
        bad = self.path / "kaputt.glb"
        bad.write_bytes(b"kein glTF")
        with self.assertRaises(ValueError):
            modell3d.to_stl(bad, self.path / "x.stl")
        with self.assertRaises(ValueError):
            modell3d.to_stl(self.path / "x.stl" if False else self._glb(), self.path / "x.stl", height_mm=0)
        self.assertFalse((self.path / "x.stl").exists())

    def _glb(self) -> Path:
        glb = self.path / "ok.glb"
        glb.write_bytes(box_glb())
        return glb

    def test_viewer_page_contains_the_model_and_is_safe(self):
        glb = self._glb()
        page = modell3d.viewer_html(glb, "Stuhl </script><script>alert(1)</script>")
        self.assertIn(base64.b64encode(glb.read_bytes()).decode("ascii"), page)
        self.assertNotIn("<script>alert(1)", page)        # Titel kann die Seite nicht kapern
        self.assertIn("Stuhl &lt;/script&gt;", page)        # im <title> maskiert
        self.assertIn("webgl2", page)
        self.assertEqual(page.count("</script>"), 1)       # nur das Ende des eigenen Skripts
        out = modell3d.write_viewer(glb, self.path / "ansicht" / "seite.html", "Stuhl")
        self.assertTrue(out.is_file())

    def test_gallery_keeps_model_next_to_image_and_recycles_both(self):
        gallery = galerie.Gallery(self.path / "bilder")
        glb = self._glb()
        item = gallery.add_model(png(), glb, {"prompt": "Stuhl", "width": 8, "height": 8})
        model = gallery.model_path(item)
        self.assertEqual(model.stem, Path(item["file"]).stem)
        self.assertFalse(glb.exists())  # verschoben, nicht kopiert
        self.assertEqual(galerie.Gallery(self.path / "bilder").find(item["file"])["model3d"], model.name)
        self.assertIsNone(gallery.model_path({"file": "a.png", "model3d": "../fremd.glb"}))  # nur im eigenen Ordner
        with mock.patch.object(galerie.plattform, "recycle", side_effect=lambda p: Path(p).unlink()):
            gallery.remove(item)
        self.assertFalse(model.exists())
        self.assertFalse(gallery.path(item).exists())


RELEASE = {"tag_name": "v0.8.1", "assets": [
    {"name": f"trellis-{kind}-{system}", "size": 100, "browser_download_url": f"https://example.invalid/{kind}-{system}",
     "digest": "sha256:" + "0" * 64}
    for kind in ("cuda", "cuda12", "vulkan", "rocm") for system in ("windows-x64.zip", "linux-x64.tar.gz")]}


class Engine(unittest.TestCase):
    def pick(self, vendor, cuda, cc, linux=False, release=RELEASE):
        with mock.patch.object(trellis.platform, "machine", return_value="AMD64"):
            kind, asset = trellis._pick(release, vendor, cuda, cc, linux=linux)
        return kind, asset["name"] if asset else None

    def test_package_fits_driver_and_card(self):
        self.assertEqual(self.pick("nvidia", (13, 0), (8, 9)), ("cuda", "trellis-cuda-windows-x64.zip"))
        self.assertEqual(self.pick("nvidia", (12, 8), (8, 9)), ("vulkan", "trellis-vulkan-windows-x64.zip"))
        self.assertEqual(self.pick("nvidia", (12, 2), (6, 1), linux=True), ("cuda12", "trellis-cuda12-linux-x64.tar.gz"))
        self.assertEqual(self.pick("nvidia", (13, 1), None), ("vulkan", "trellis-vulkan-windows-x64.zip"))
        self.assertEqual(self.pick("amd", None, None, linux=True), ("vulkan", "trellis-vulkan-linux-x64.tar.gz"))
        no_cuda = {"tag_name": "v1", "assets": [a for a in RELEASE["assets"] if "-cuda-" not in a["name"]]}
        self.assertEqual(self.pick("nvidia", (13, 0), (12, 0), release=no_cuda)[0], "vulkan")  # experimentell, fehlt
        with mock.patch.object(trellis.platform, "machine", return_value="ARM64"):
            self.assertEqual(trellis._pick(RELEASE, "intel", None, None), ("", None))

    def test_plan_lists_program_and_weights_of_the_variant(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(trellis, "SERVER_DIR", Path(d) / "server"), \
                mock.patch.object(trellis, "MODEL_DIR", Path(d) / "3d"), \
                mock.patch.object(trellis.downloads, "get_json", return_value=[RELEASE]), \
                mock.patch.object(trellis.downloads, "head_size", return_value=1000), \
                mock.patch.object(trellis.llamacpp, "detect_gpu", return_value=("amd", "Radeon", None)), \
                mock.patch.object(trellis.platform, "machine", return_value="x86_64"), \
                mock.patch.object(trellis.plattform, "which", return_value=None):
            p = trellis.plan("q8")
            self.assertEqual(p["target"].name, "trellis-0.8.1-vulkan")
            self.assertEqual(len(p["program"]), 1)
            self.assertEqual(p["program"][0][3], "0" * 64)  # Prüfsumme aus dem Release
            self.assertEqual(len(p["weights"]), len(trellis.FILES))
            self.assertTrue(all("/resolve/main/q8/" in w[1] for w in p["weights"]))
            self.assertEqual(p["size"], 100 + 1000 * len(trellis.FILES))
            self.assertTrue(all("/resolve/main/q8/" not in url for _, url in trellis.model_files("f16")))
            self.assertFalse(trellis.ready("q8"))
            for dest, _ in trellis.model_files("q8"):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"x")
            self.assertTrue(trellis.model_ready("q8"))
            self.assertEqual(trellis.variant_key(None), "q8")
            self.assertEqual(trellis.plan("q8")["weights"], [])

    def test_progress_from_the_output(self):
        lines = ["[trellis] generating model with seed 7", "[1/6] preprocess in.png (BiRefNet bg removal, 1024 cascade)",
                 "[2/6] DINOv3 conditioning", "[3/6] sparse-structure flow + decode",
                 "      [flow] [....................]  0/12    0.0s  starting    ",
                 "      [flow] [#####...............]  3/12    9.1s  ~27s left   ",
                 "      [flow] 12 steps, 24 forwards, 36.0s",
                 "[4/7] shape SLAT flow (LR 512 -> upsample -> HR 1024 cascade, max_tok=49152)",
                 "      [flow] [##########..........]  6/12   40.0s  ~40s left   ",
                 "[5/7] FlexiDualGrid shape decode -> mesh @res1024", "[6/7] texture SLAT flow + PBR decode",
                 "[7/7] write out.glb"]
        state, seen = {}, []
        for line in lines:
            if trellis.parse_progress(line, state):
                seen.append(trellis.fraction(state))
        self.assertEqual(state["stage"], 7)
        self.assertEqual(seen, sorted(seen))  # nur vorwärts
        self.assertGreater(seen[-1], 0.9)
        st = {}
        trellis.parse_progress("      [flow] [#####...............]  3/12    9.1s  ~27s left   ", st)
        self.assertEqual((st["step"], st["steps"], st["eta"]), (3, 12, 27))
        self.assertTrue(trellis.stage_name(4))


@unittest.skipIf(sys.platform == "win32", "nachgestelltes trellis-cli als Skript – unter Windows bräuchte es eine .exe")
class FakeCli(unittest.TestCase):
    """trellis.generate mit einem Skript an Stelle von trellis-cli: Fortschritt, Ergebnis, Fehler, Abbrechen."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name)
        self.models = self.path / "3d"
        for dest, _ in [(self.models / "q8" / name, "") for name in trellis.FILES]:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"x")
        (self.path / "in.png").write_bytes(png())
        self.glb = box_glb()
        patches = [mock.patch.object(trellis, "MODEL_DIR", self.models)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.dir.cleanup()

    def cli(self, body: str) -> Path:
        exe = self.path / "trellis-cli"
        exe.write_text("#!" + sys.executable + "\n" + textwrap.dedent(body), encoding="utf-8")
        exe.chmod(0o755)
        return exe

    def run_cli(self, body: str, stop=None):
        exe = self.cli(body)
        states, log = [], []
        out = self.path / "arbeit" / "modell.glb"
        out.parent.mkdir(exist_ok=True)
        with mock.patch.object(trellis, "find_cli", return_value=exe):
            result = trellis.generate("q8", self.path / "in.png", out, 1024, 7, stop or threading.Event(),
                                      states.append, log.append)
        return result, states, log

    def test_progress_and_result(self):
        (self.path / "fertig.glb").write_bytes(self.glb)
        result, states, log = self.run_cli(f"""
            import shutil, sys
            args = sys.argv[1:]
            assert args[args.index("--res") + 1] == "1024" and "--require-gpu" in args
            assert args[args.index("--models") + 1].endswith("q8")
            for line in ["[1/6] preprocess", "[3/6] sparse-structure flow + decode",
                         "      [flow] [##..................]  2/12    3.0s  ~15s left", "[7/7] write"]:
                print(line, flush=True)
            shutil.copy({str(self.path / 'fertig.glb')!r}, args[args.index("-o") + 1])
        """)
        self.assertTrue(result.is_file())
        self.assertEqual(modell3d.stats(result)["triangles"], 12)
        self.assertEqual([s["stage"] for s in states], [1, 3, 3, 7])
        self.assertEqual(states[2]["step"], 2)
        self.assertTrue(log[0].startswith("> "))  # Befehlszeile im Server-Log

    def test_error_message_reaches_the_user(self):
        with self.assertRaises(RuntimeError) as cm:
            self.run_cli("""
                import sys
                print("[1/6] preprocess", flush=True)
                print("ggml_vulkan: error: out of memory allocating 18 GB", flush=True)
                sys.exit(3)
            """)
        self.assertIn("out of memory", str(cm.exception))
        self.assertIn("3", str(cm.exception))

    def test_stop_cancels_quickly(self):
        stop = threading.Event()
        threading.Timer(0.5, stop.set).start()
        t0 = time.monotonic()
        with self.assertRaises(trellis.Cancelled):
            self.run_cli("""
                import time
                print("[1/6] preprocess", flush=True)
                time.sleep(60)
            """, stop=stop)
        self.assertLess(time.monotonic() - t0, 10)


if __name__ == "__main__":
    unittest.main()
