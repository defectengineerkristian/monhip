"""Tests für den Bereich „Bilder“ ohne echte Bild-Engine und ohne Netz: Auswahl der Programm-Zips, installierte
Programme und Modelle, Bildmodelle zur Wahl (Teile, fehlende Dateien, Größe beim Bearbeiten), Download-Plan,
Aufträge an einen nachgebauten sd-server (Fortschritt, Abbruch, Fehler, Vorlage zum Bearbeiten), Galerie (Ablage,
eingebettete Erzeugungsdaten, Löschen) und „Beschreibung verbessern“:
python -m unittest discover -s progress/tests -p test_bilder.py"""

import base64
import http.server
import json
import os
import struct
import sys
import tempfile
import threading
import unittest
import zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import backend
import bilder
import galerie
import sdcpp

# Dateien des Releases master-1060-0b3b98d (Stand 08.11.2026)
ASSETS = ["cudart-sd-bin-win-cu12-x64.zip", "sd-master-0b3b98d-bin-Darwin-macOS-26.7.2-arm64.zip",
          "sd-master-0b3b98d-bin-Linux-Ubuntu-24.04-x86_64-rocm-10.1.0.zip",
          "sd-master-0b3b98d-bin-Linux-Ubuntu-26.04-x86_64-vulkan.zip",
          "sd-master-0b3b98d-bin-Linux-Ubuntu-26.04-x86_64.zip", "sd-master-0b3b98d-bin-win-cpu-x64.zip",
          "sd-master-0b3b98d-bin-win-cuda12-x64.zip", "sd-master-0b3b98d-bin-win-rocm-10.1.0-x64.zip",
          "sd-master-0b3b98d-bin-win-vulkan-x64.zip"]
RELEASE = {"tag_name": "master-1060-0b3b98d", "draft": False,
           "assets": [{"name": n, "browser_download_url": f"https://example.invalid/{n}", "size": 1000 + i}
                      for i, n in enumerate(ASSETS)]}


def png_with_text(chunks: list[tuple[bytes, bytes]]) -> bytes:
    """Kleinste gültige PNG-Datei (1 × 1) mit Textblöcken vor den Bilddaten."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
    for kind, data in chunks:
        out += chunk(kind, data)
    return out + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b"")


class PickAndInstalled(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(sdcpp.platform, "machine", return_value="AMD64")
        patcher.start()
        self.addCleanup(patcher.stop)

    def names(self, vendor, cuda, linux, gpu="", runtime=True):
        with mock.patch.object(sdcpp, "_rocm_available", return_value=runtime):
            kind, assets = sdcpp._pick(RELEASE, vendor, cuda, linux=linux, gpu=gpu)
        return kind, [a["name"] for a in assets]

    def test_windows_choices(self):
        self.assertEqual(self.names("nvidia", (13, 0), False),
                         ("cuda12", ["sd-master-0b3b98d-bin-win-cuda12-x64.zip", "cudart-sd-bin-win-cu12-x64.zip"]))
        self.assertEqual(self.names("nvidia", (11, 8), False)[0], "vulkan")   # Treiber zu alt für CUDA 12
        self.assertEqual(self.names("nvidia", None, False)[0], "vulkan")      # ohne nvidia-smi
        self.assertEqual(self.names("amd", None, False), ("vulkan", ["sd-master-0b3b98d-bin-win-vulkan-x64.zip"]))
        self.assertEqual(self.names("", None, False), ("cpu", ["sd-master-0b3b98d-bin-win-cpu-x64.zip"]))

    def test_rx9070xt_prefers_bundled_windows_rocm_and_keeps_vulkan_fallback(self):
        self.assertEqual(self.names("amd", None, False, "AMD Radeon RX 9070 XT"),
                         ("rocm", ["sd-master-0b3b98d-bin-win-rocm-10.1.0-x64.zip"]))
        self.assertEqual(self.names("amd", None, False, "AMD Radeon RX 7900 XTX")[0], "vulkan")
        without_rocm = {**RELEASE, "assets": [a for a in RELEASE["assets"] if "rocm" not in a["name"]]}
        self.assertEqual(sdcpp._pick(without_rocm, "amd", None, linux=False,
                                    gpu="AMD Radeon RX 9070 XT")[0], "vulkan")
        self.assertEqual(self.names("amd", None, True, "AMD Radeon RX 9070 XT")[0], "vulkan")
        self.assertEqual(self.names("amd", None, False, "AMD Radeon RX 9070 XT", runtime=False)[0], "rocm")

    def test_installed_rocm_is_preferred_and_vulkan_remains_selectable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for folder in ("sd-b1068-rocm", "sd-b1068-vulkan", "sd-b1069-rocm.part"):
                (root / folder).mkdir()
                (root / folder / sdcpp.SERVER_EXE).write_bytes(b"")
                if "rocm" in folder:
                    for dll in sdcpp.rocm_runtime.REQUIRED:
                        (root / folder / dll).write_bytes(b"dll")
            with mock.patch.object(sdcpp, "SERVER_DIR", root), \
                    mock.patch.object(sdcpp.plattform, "which", return_value=None):
                self.assertEqual(sdcpp.find_server(), root / "sd-b1068-rocm" / sdcpp.SERVER_EXE)
                self.assertEqual(sdcpp.find_server("vulkan"), root / "sd-b1068-vulkan" / sdcpp.SERVER_EXE)

    def test_linux_choices(self):
        self.assertEqual(self.names("nvidia", (13, 0), True),
                         ("vulkan", ["sd-master-0b3b98d-bin-Linux-Ubuntu-26.04-x86_64-vulkan.zip"]))
        self.assertEqual(self.names("", None, True), ("cpu", ["sd-master-0b3b98d-bin-Linux-Ubuntu-26.04-x86_64.zip"]))

    def test_other_processors_get_nothing(self):
        with mock.patch.object(sdcpp.platform, "machine", return_value="aarch64"):
            self.assertEqual(sdcpp._pick(RELEASE, "nvidia", (13, 0), linux=True), ("", []))

    def test_find_server_prefers_cuda_and_skips_unfinished(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for folder in ("sd-b1060-vulkan", "sd-b1000-cpu", "sd-b1050-cuda12", "sd-b1070-rocm", "sd-b1070-cuda12.part",
                           "llama-b1-bin-win-cpu-x64"):
                (root / folder).mkdir()
                (root / folder / sdcpp.SERVER_EXE).write_bytes(b"")
                if "rocm" in folder:
                    for dll in sdcpp.rocm_runtime.REQUIRED:
                        (root / folder / dll).write_bytes(b"dll")
            with mock.patch.object(sdcpp, "SERVER_DIR", root), mock.patch.object(sdcpp.plattform, "which",
                                                                                  return_value=None):
                self.assertEqual(sdcpp.find_server(), root / "sd-b1050-cuda12" / sdcpp.SERVER_EXE)
                (root / "sd-b1050-cuda12" / sdcpp.SERVER_EXE).unlink()
                self.assertEqual(sdcpp.find_server(), root / "sd-b1070-rocm" / sdcpp.SERVER_EXE)
                (root / "sd-b1070-rocm" / sdcpp.SERVER_EXE).unlink()
                self.assertEqual(sdcpp.find_server(), root / "sd-b1060-vulkan" / sdcpp.SERVER_EXE)

    def test_model_files_ready_and_plan(self):
        pick = sdcpp._pick
        with tempfile.TemporaryDirectory() as d:
            models, servers = Path(d) / "bild", Path(d) / "server"
            with mock.patch.object(sdcpp, "MODEL_DIR", models), mock.patch.object(sdcpp, "SERVER_DIR", servers), \
                    mock.patch.object(sdcpp.llamacpp, "detect_gpu", return_value=("nvidia", "RTX", (13, 0))), \
                    mock.patch.object(sdcpp.downloads, "get_json", return_value=[RELEASE]), \
                    mock.patch.object(sdcpp.downloads, "head_size", return_value=500), \
                    mock.patch.object(sdcpp.plattform, "WINDOWS", True), \
                    mock.patch.object(sdcpp, "_pick", side_effect=lambda r, v, c, **kw: pick(r, v, c, linux=False, **kw)):
                files = sdcpp.model_files("flux2-klein-4b-q8")
                self.assertEqual([role for role, _, _ in files], ["diffusion-model", "llm", "vae"])
                self.assertTrue(all(dest.parent == models / "FLUX.2-klein-4B" for _, dest, _ in files))
                self.assertIn("huggingface.co/Comfy-Org/Flux-2-Klein-4B/resolve/main/split_files/vae/", files[2][2])
                self.assertFalse(sdcpp.model_ready("flux2-klein-4b-q8"))
                p = sdcpp.plan("flux2-klein-4b-q8")
                self.assertEqual(p["target"], servers / "sd-b1060-cuda12")
                self.assertEqual(len(p["program"]), 2)
                self.assertEqual(len(p["weights"]), 3)
                self.assertEqual(p["size"], sum(x[2] for x in p["program"]) + 3 * 500)
                # vorhandene Dateien fehlen im Plan, das installierte Programm auch
                files[0][1].parent.mkdir(parents=True)
                for _, dest, _ in files[:2]:
                    dest.write_bytes(b"x")
                (servers / "sd-b1060-cuda12").mkdir(parents=True)
                (servers / "sd-b1060-cuda12" / sdcpp.SERVER_EXE).write_bytes(b"")
                p = sdcpp.plan("flux2-klein-4b-q8")
                self.assertEqual(p["program"], [])
                self.assertEqual([w[0] for w in p["weights"]], ["flux2-vae.safetensors"])
                # die kleine Fassung teilt sich den Bildkodierer
                self.assertEqual(sdcpp.model_files("flux2-klein-4b-q4")[2][1], files[2][1])
        self.assertEqual(sdcpp.model_key("gibt-es-nicht"), sdcpp.DEFAULT_MODEL)

    def test_rocm_update_reuses_models_and_keeps_the_checksum(self):
        pick = sdcpp._pick
        release = {**RELEASE, "assets": [dict(a) for a in RELEASE["assets"]]}
        for asset in release["assets"]:
            asset["digest"] = "sha256:" + "a" * 64
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(sdcpp, "MODEL_DIR", Path(d) / "models"), \
                mock.patch.object(sdcpp, "SERVER_DIR", Path(d) / "server"), \
                mock.patch.object(sdcpp.plattform, "WINDOWS", True), \
                mock.patch.object(sdcpp.plattform, "which", return_value=None), \
                mock.patch.object(sdcpp, "_rocm_available", return_value=True), \
                mock.patch.object(sdcpp.llamacpp, "detect_gpu", return_value=("amd", "AMD Radeon RX 9070 XT", None)), \
                mock.patch.object(sdcpp, "_pick", side_effect=lambda r, v, c, **kw: pick(r, v, c, linux=False, **kw)), \
                mock.patch.object(sdcpp.downloads, "get_json", return_value=[release]), \
                mock.patch.object(sdcpp.downloads, "head_size", side_effect=AssertionError("models already present")):
            for _, dest, _ in sdcpp.model_files("qwen-image-2.1-turbo"):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"model")
            # Die bestehende Vulkan-Installation allein darf ein explizites Engine-Update nicht abkürzen.
            vulkan = sdcpp.SERVER_DIR / "sd-b1060-vulkan" / sdcpp.SERVER_EXE
            vulkan.parent.mkdir(parents=True)
            vulkan.write_bytes(b"engine")
            plan = sdcpp.plan("qwen-image-2.1-turbo")
            self.assertEqual(plan["kind"], "ROCm")
            self.assertEqual(plan["rocm_version"], "10.1.0")
            self.assertEqual(plan["target"], sdcpp.SERVER_DIR / "sd-b1060-rocm")
            self.assertEqual(plan["weights"], [])
            self.assertEqual(len(plan["program"]), 1)
            self.assertEqual(plan["program"][0][3], "a" * 64)
            self.assertTrue(vulkan.exists())

    def test_default_and_already_installed_model(self):
        """Standard ist Qwen-Image 2.1 – wer nie gewählt hat und schon FLUX.2 hat, behält es, bis Qwen da ist."""
        self.assertEqual(sdcpp.DEFAULT_MODEL, "qwen-image-2.1-turbo")
        self.assertEqual(next(iter(sdcpp.MODELS)), sdcpp.DEFAULT_MODEL)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(sdcpp, "MODEL_DIR", Path(d)):
            self.assertEqual(sdcpp.model_key(None), sdcpp.DEFAULT_MODEL)
            for _, dest, _ in sdcpp.model_files("flux2-klein-4b-q8"):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"x")
            self.assertEqual(sdcpp.model_key(None), "flux2-klein-4b-q8")
            self.assertEqual(sdcpp.model_key("flux2-klein-4b-q4"), "flux2-klein-4b-q4")  # gewählt bleibt gewählt
            for _, dest, _ in sdcpp.model_files("qwen-image-2.1-turbo"):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"x")
            self.assertEqual(sdcpp.model_key(None), sdcpp.DEFAULT_MODEL)


class Catalog(unittest.TestCase):
    """Bildmodelle zur Wahl: jedes aus Bildmodell, Textverständnis und VAE; Qwen-Image zusätzlich mit dem
    Bildverständnis des Textmodells (fürs Bearbeiten)."""

    def test_every_model_has_its_parts(self):
        for key, m in sdcpp.MODELS.items():
            with self.subTest(key=key):
                roles = [role for role, _, _ in m["files"]]
                self.assertEqual({"diffusion-model", "llm", "vae"} - set(roles), set())
                self.assertEqual(len(roles), len(set(roles)))
                self.assertTrue(m["license"] and m["gb"] > 0 and m["align"] in (16, 32))
        roles = [role for role, _, _ in sdcpp.MODELS["qwen-image-2.1-turbo"]["files"]]
        self.assertIn("llm_vision", roles)
        self.assertEqual(len(sdcpp.MODELS["qwen-image-2.1-turbo"]["sigmas"]), 9)  # 8 Schritte

    def test_missing_files_and_plan_without_engine_update(self):
        with tempfile.TemporaryDirectory() as d:
            models, servers = Path(d) / "bild", Path(d) / "server"
            (servers / "sd-b1060-cuda12").mkdir(parents=True)
            (servers / "sd-b1060-cuda12" / sdcpp.SERVER_EXE).write_bytes(b"")
            with mock.patch.object(sdcpp, "MODEL_DIR", models), mock.patch.object(sdcpp, "SERVER_DIR", servers), \
                    mock.patch.object(sdcpp.downloads, "get_json", side_effect=AssertionError("kein GitHub")), \
                    mock.patch.object(sdcpp.downloads, "head_size", return_value=700):
                key = "qwen-image-2.1-turbo"
                self.assertAlmostEqual(sdcpp.missing_gb(key), sdcpp.MODELS[key]["gb"])
                files = sdcpp.model_files(key)
                files[0][1].parent.mkdir(parents=True)
                files[0][1].write_bytes(b"x")
                self.assertAlmostEqual(sdcpp.missing_gb(key), sdcpp.MODELS[key]["gb"] * 3 / 4)
                p = sdcpp.plan(key, update=False)  # Bild-Engine ist da: nur fehlende Modelldateien, GitHub unberührt
                self.assertEqual(p["program"], [])
                self.assertEqual([w[0] for w in p["weights"]], [dest.name for _, dest, _ in files[1:]])
                self.assertEqual(p["size"], 3 * 700)
                for _, dest, _ in files:
                    dest.write_bytes(b"x")
                self.assertTrue(sdcpp.ready(key))
                self.assertEqual(sdcpp.missing_gb(key), 0)

    def test_edit_size_keeps_aspect_and_alignment(self):
        self.assertEqual(sdcpp.edit_size(1024, 1024, "flux2-klein-4b-q8"), (1024, 1024))
        w, h = sdcpp.edit_size(1920, 1080, "qwen-image-2.1-turbo")
        self.assertEqual((w % 32, h % 32), (0, 0))
        self.assertAlmostEqual(w / h, 16 / 9, delta=0.05)
        self.assertAlmostEqual(w * h, sdcpp.EDIT_AREA, delta=sdcpp.EDIT_AREA * 0.05)
        w, h = sdcpp.edit_size(640, 480, "flux2-klein-4b-q4")  # kleine Vorlage: Ergebnis trotzdem etwa 1 MP
        self.assertEqual((w % 16, h % 16), (0, 0))
        self.assertGreater(w * h, 900_000)
        self.assertEqual(sdcpp.edit_size(8000, 100), (2048, 256))  # Grenzen


class Compatibility(unittest.TestCase):
    """Der bestätigte Vergleichspfad muss beim echten Prozessstart ankommen, ohne globale Variablen zu ändern."""

    def launch(self, key="qwen-image-2.1-turbo", mode="auto", folder="sd-b1068-vulkan",
               gpu=("amd", "AMD Radeon RX 9070 XT", None), windows=True, finder=None):
        setting = {"mode": mode}
        server = sdcpp.ImageServer(lambda _t: None, lambda: setting["mode"])
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.stdout = []
        with mock.patch.object(sdcpp, "find_server", side_effect=finder,
                               return_value=Path("/server") / folder / sdcpp.SERVER_EXE), \
                mock.patch.object(sdcpp, "model_ready", return_value=True), \
                mock.patch.object(sdcpp, "_free_port", return_value=54416), \
                mock.patch.object(sdcpp, "_request", return_value={"state": "ready"}), \
                mock.patch.object(backend, "_end_with_app", return_value=True), \
                mock.patch.object(sdcpp.plattform, "WINDOWS", windows), \
                mock.patch.object(sdcpp.rocm_runtime, "missing", return_value=[]), \
                mock.patch.object(sdcpp.rocm_runtime, "probe", return_value=None), \
                mock.patch.object(sdcpp.llamacpp, "detect_gpu", return_value=gpu), \
                mock.patch.object(sdcpp.plattform, "popen", return_value=proc) as popen:
            server.start(key, threading.Event())
        return server, setting, popen.call_args.args[0], popen.call_args.kwargs["env"]

    def test_reported_hardware_uses_the_verified_profile(self):
        inherited = dict(os.environ)
        server, setting, args, env = self.launch()
        self.assertTrue(server.compatibility_active)
        self.assertTrue(server.ready_for("qwen-image-2.1-turbo"))
        for flag, value in (("--backend", "vae=cpu"), ("--flash-attn", "off"), ("--conv-direct", "off"),
                            ("--model-args", "qwen_image_2_1_prefix_cache=false")):
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertEqual([float(v) for v in args[args.index("--sigmas") + 1].split(",")],
                         [1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0.0])
        self.assertEqual({name: env[name] for name in sdcpp.QWEN_VULKAN_COMPAT_ENV},
                         {name: "1" for name in sdcpp.QWEN_VULKAN_COMPAT_ENV})
        self.assertTrue(dict(os.environ) == inherited, "Parent environment changed")
        # Eine Einstellungsänderung darf nicht still mit dem bereits geladenen Modus weiterrechnen.
        setting["mode"] = "normal"
        self.assertFalse(server.ready_for("qwen-image-2.1-turbo"))
        server.stop()
        self.assertFalse(server.compatibility_active)

    def test_normal_mode_and_other_configurations_keep_their_fast_path(self):
        cases = [
            {"mode": "normal"},
            {"key": "flux2-klein-4b-q8", "mode": "compatible"},
            {"folder": "sd-b1068-cuda12"},
            {"folder": "sd-b1068-rocm"},
            {"folder": "sd-b1069-vulkan"},
            {"windows": False},
            {"gpu": ("nvidia", "NVIDIA RTX", (13, 0))},
            {"gpu": ("amd", "AMD Radeon RX 7900 XTX", None)},
            {"gpu": ("intel", "Intel Arc", None)},
        ]
        with mock.patch.dict(os.environ, {"GGML_VK_DISABLE_FUSION": "inherited"}):
            for case in cases:
                with self.subTest(case=case):
                    server, _, args, env = self.launch(**case)
                    self.assertFalse(server.compatibility_active)
                    self.assertNotIn("--backend", args)
                    self.assertNotIn("--flash-attn", args)
                    self.assertEqual(env["GGML_VK_DISABLE_FUSION"], "inherited")
                    for name in sdcpp.QWEN_VULKAN_COMPAT_ENV:
                        self.assertEqual(env.get(name), os.environ.get(name))

    def test_explicit_compatibility_works_on_other_builds(self):
        server, _, _, _ = self.launch(mode="compatible", folder="sd-b1069-vulkan", windows=False)
        self.assertTrue(server.compatibility_active)
        self.assertTrue(server.ready_for("qwen-image-2.1-turbo"))

    def test_nvidia_cuda_keeps_gpu_optimizations_for_all_image_models(self):
        for key in sdcpp.MODELS:
            with self.subTest(model=key):
                server, _, args, env = self.launch(key=key, folder="sd-b1068-cuda12",
                                                   gpu=("nvidia", "NVIDIA GeForce RTX 4090", (13, 0)))
                self.assertTrue(server.ready_for(key))
                self.assertFalse(server.compatibility_active)
                for flag in ("--backend", "--flash-attn", "--conv-direct", "--model-args"):
                    self.assertNotIn(flag, args)
                for name in sdcpp.QWEN_VULKAN_COMPAT_ENV:
                    self.assertEqual(env.get(name), os.environ.get(name))

    def test_native_engine_and_verified_vulkan_fallback_can_both_be_used(self):
        finder = sdcpp.find_server
        with tempfile.TemporaryDirectory() as d, mock.patch.object(sdcpp, "SERVER_DIR", Path(d)):
            for folder in ("sd-b1068-rocm", "sd-b1068-vulkan"):
                exe = Path(d) / folder / sdcpp.SERVER_EXE
                exe.parent.mkdir()
                exe.write_bytes(b"engine")
            server, _, args, env = self.launch(finder=finder)
            self.assertEqual(Path(args[0]).parent.name, "sd-b1068-rocm")
            self.assertFalse(server.compatibility_active)
            # Installation eines neuen Programms beendet keinen laufenden Auftrag, verlangt danach aber Neuladen.
            server.require_reload()
            self.assertTrue(server.is_running())
            self.assertFalse(server.ready_for("qwen-image-2.1-turbo"))
            fallback, _, args, _ = self.launch(mode="compatible", finder=finder)
            self.assertEqual(Path(args[0]).parent.name, "sd-b1068-vulkan")
            self.assertTrue(fallback.compatibility_active)
            self.assertEqual(args[args.index("--backend") + 1], "vae=cpu")


# ---------------------------------------------------------------- nachgebauter sd-server

class FakeSd(http.server.BaseHTTPRequestHandler):
    jobs: dict = {}
    fail = False

    def log_message(self, *args):
        pass

    def _send(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/sdcpp/v1/img_gen":
            jid = f"job_{len(self.jobs)}"
            self.jobs[jid] = {"body": body, "polls": 0, "cancel": False}
            self._send(202, {"id": jid, "status": "queued"})
        elif self.path.endswith("/cancel"):
            self.jobs[self.path.split("/")[-2]]["cancel"] = True
            self._send(200, {"cancel_requested": True})
        else:
            self._send(404, {"error": "unbekannt"})

    def do_GET(self):
        job = self.jobs.get(self.path.rsplit("/", 1)[-1])
        if not job:
            self._send(404, {"error": "unbekannt"})
            return
        job["polls"] += 1
        body = job["body"]
        steps, count = body["sample_params"]["sample_steps"], body["batch_count"]
        n = job["polls"]
        if job["cancel"]:
            self._send(200, {"status": "cancelled", "error": {"code": "cancelled"}})
        elif self.fail:
            self._send(200, {"status": "failed", "error": {"code": "generation_failed", "message": "kaputt"}})
        elif n <= steps * count:
            preview = {"pass": (n - 1) // steps + 1, "step": (n - 1) % steps + 1, "total_steps": steps,
                       "b64_json": base64.b64encode(f"vorschau{n}".encode()).decode()}
            self._send(200, {"status": "generating", "preview": preview})
        else:
            images = [{"index": i, "b64_json": base64.b64encode(f"bild{i}".encode()).decode()}
                      for i in reversed(range(count))]
            self._send(200, {"status": "completed", "result": {"output_format": "png", "images": images}})


class Generate(unittest.TestCase):
    def setUp(self):
        FakeSd.jobs, FakeSd.fail = {}, False
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeSd)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.server = sdcpp.ImageServer(lambda t: None)
        self.server.port, self.server.model = self.httpd.server_address[1], "flux2-klein-4b-q8"
        self.server.proc = mock.Mock(poll=lambda: None)

    def test_two_images_with_progress_and_parameters(self):
        seen = []
        pngs = self.server.generate("eine Katze", 832, 1216, 2, 42, threading.Event(),
                                    lambda d, t, img: seen.append((d, t, img)), poll=0.01)
        self.assertEqual(pngs, [b"bild0", b"bild1"])  # nach Index geordnet
        body = FakeSd.jobs["job_0"]["body"]
        self.assertEqual((body["prompt"], body["width"], body["height"], body["seed"], body["batch_count"]),
                         ("eine Katze", 832, 1216, 42, 2))
        self.assertEqual(body["sample_params"]["sample_steps"], 4)
        self.assertEqual(body["sample_params"]["guidance"]["txt_cfg"], 1.0)
        done = [d for d, _, _ in seen]
        self.assertEqual(done, sorted(done))
        self.assertEqual(seen[-1][:2], (8, 8))
        self.assertIn(b"vorschau1", [img for _, _, img in seen])

    def test_edit_sends_the_reference_image(self):
        self.server.model = "qwen-image-2.1-turbo"
        pngs = self.server.generate("mach den Himmel rot", 1344, 768, 1, 7, threading.Event(), poll=0.01,
                                    refs=[b"\x89PNG vorlage"])
        self.assertEqual(pngs, [b"bild0"])
        body = FakeSd.jobs["job_0"]["body"]
        self.assertEqual([base64.b64decode(r) for r in body["ref_images"]], [b"\x89PNG vorlage"])
        self.assertEqual(body["sample_params"]["sample_steps"], 8)
        self.assertEqual(body["sample_params"]["custom_sigmas"], sdcpp.MODELS["qwen-image-2.1-turbo"]["sigmas"])
        # ohne Vorlage keine ref_images, FLUX.2 ohne festen Zeitplan
        self.server.model = "flux2-klein-4b-q8"
        self.server.generate("x", 1024, 1024, 1, 1, threading.Event(), poll=0.01)
        body = FakeSd.jobs["job_1"]["body"]
        self.assertNotIn("ref_images", body)
        self.assertNotIn("custom_sigmas", body["sample_params"])

    def test_stop_cancels_the_job(self):
        stop = threading.Event()
        with self.assertRaises(sdcpp.Cancelled):
            self.server.generate("x", 1024, 1024, 1, 1, stop, lambda *a: stop.set(), poll=0.01)
        self.assertTrue(FakeSd.jobs["job_0"]["cancel"])

    def test_failure_message(self):
        FakeSd.fail = True
        with self.assertRaisesRegex(RuntimeError, "kaputt"):
            self.server.generate("x", 1024, 1024, 1, 1, threading.Event(), poll=0.01)

    def test_engine_gone(self):
        self.server.proc = mock.Mock(poll=lambda: 1)
        with self.assertRaises(RuntimeError):
            self.server.generate("x", 1024, 1024, 1, 1, threading.Event(), poll=0.01)


# ---------------------------------------------------------------- Galerie

class Gallery(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))

    def test_png_text_and_parameters(self):
        params = b"a red fox in the snow\nSteps: 4, Sampler: euler, CFG scale: 1.0, Seed: 1234, Size: 832x1216"
        itxt = b"Kommentar\x00\x00\x00\x00\x00" + "Füchse".encode()
        data = png_with_text([(b"tEXt", b"parameters\x00" + params), (b"iTXt", itxt)])
        (self.dir / "a.png").write_bytes(data)
        text = galerie.png_text(self.dir / "a.png")
        self.assertEqual(text["Kommentar"], "Füchse")
        info = galerie.parse_parameters(text["parameters"])
        self.assertEqual(info, {"prompt": "a red fox in the snow", "seed": 1234, "width": 832, "height": 1216})

    def test_add_reload_adopt_and_remove(self):
        g = galerie.Gallery(self.dir)
        self.assertEqual(g.items, [])
        first = g.add(png_with_text([]), {"prompt": "eins", "width": 1, "height": 1, "seed": 5})
        second = g.add(png_with_text([]), {"prompt": "zwei"})
        self.assertNotEqual(first["file"], second["file"])  # gleiche Sekunde: eigener Name
        self.assertEqual([e["prompt"] for e in g.items], ["zwei", "eins"])
        # von Hand hineinkopiert: kommt mit den eingebetteten Daten dazu
        (self.dir / "0000 alt.png").write_bytes(png_with_text([(b"tEXt", b"parameters\x00ein Haus\nSteps: 4")]))
        g2 = galerie.Gallery(self.dir)
        self.assertEqual(len(g2.items), 3)
        adopted = g2.find("0000 alt.png")
        self.assertEqual((adopted["prompt"], adopted["width"], adopted["height"]), ("ein Haus", 1, 1))
        self.assertEqual(json.loads((self.dir / "bilder.json").read_text(encoding="utf-8"))[0]["file"],
                         g2.items[0]["file"])
        # Löschen: Papierkorb (hier nachgebildet), Eintrag und Vorschau weg
        g2.thumb(first).parent.mkdir(parents=True, exist_ok=True)
        g2.thumb(first).write_bytes(b"x")
        with mock.patch.object(galerie.plattform, "recycle", side_effect=lambda p: p.unlink()):
            g2.remove(g2.find(first["file"]))
        self.assertIsNone(g2.find(first["file"]))
        self.assertFalse((self.dir / first["file"]).exists())
        self.assertFalse(g2.thumb(first).exists())
        # fehlende Datei: Eintrag verschwindet beim Laden
        (self.dir / second["file"]).unlink()
        self.assertEqual([e["file"] for e in galerie.Gallery(self.dir).items], ["0000 alt.png"])

    def test_broken_index_is_rebuilt(self):
        (self.dir / "b.png").write_bytes(png_with_text([]))
        (self.dir / "bilder.json").write_text("{kaputt", encoding="utf-8")
        self.assertEqual([e["file"] for e in galerie.Gallery(self.dir).items], ["b.png"])


# ---------------------------------------------------------------- Beschreibung verbessern

class Improve(unittest.TestCase):
    def test_reply_is_cleaned(self):
        class Llama(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                Llama.req = req
                body = json.dumps({"choices": [{"message": {
                    "content": "<think>hm</think>„A cozy cabin in a snowy forest at dusk.“"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Llama)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            out = bilder.improve_prompt(f"http://127.0.0.1:{httpd.server_address[1]}", "  Hütte im Schnee ")
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assertEqual(out, "A cozy cabin in a snowy forest at dusk.")
        self.assertEqual(Llama.req["messages"][1]["content"], "Hütte im Schnee")
        self.assertFalse(Llama.req["chat_template_kwargs"]["enable_thinking"])

    def test_short(self):
        font = mock.Mock(measure=lambda s: len(s) * 10)
        self.assertEqual(bilder.short("kurz", font, 100), "kurz")
        self.assertEqual(bilder.short("ein  sehr\nlanger Text", font, 80), "ein seh…")

    def test_first_image_of_dropped_files(self):
        with tempfile.TemporaryDirectory() as d:
            text, photo = Path(d) / "notiz.txt", Path(d) / "Foto.JPG"
            text.write_text("x")
            photo.write_bytes(b"\xff\xd8")
            self.assertEqual(bilder.first_image([str(text), str(Path(d) / "fehlt.png"), str(photo)]), photo)
            self.assertIsNone(bilder.first_image([str(text)]))


if __name__ == "__main__":
    unittest.main()
