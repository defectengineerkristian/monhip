"""Sicherheitsprüfungen: Teamwork-Server (Länge, Signatur, Wiederholungen, Uploads), Pfade vom Gastgeber beim Gast,
PowerShell-Zeichenketten, Webabruf (private Adressen, Gzip-Bombe), API-Schlüssel des eigenen llama-servers,
Dateisuche über Verknüpfungen, Prüfsummen und abgerissene Downloads, PNG-Metadaten der Galerie:
python -m unittest discover -s progress/tests -p test_sicherheit.py"""

import gzip
import hashlib
import http.server
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import agent  # noqa: E402
import backend  # noqa: E402
import downloads  # noqa: E402
import galerie  # noqa: E402
import images  # noqa: E402
import plattform  # noqa: E402
import room  # noqa: E402
import web  # noqa: E402


def _raw(port: int, request: bytes) -> bytes:
    """Rohe HTTP-Anfrage an 127.0.0.1:port → erste Zeile der Antwort."""
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(request)
        data = b""
        while b"\r\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
    return data.split(b"\r\n", 1)[0]


class RoomServerHardening(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.server = room.RoomServer("Test", room.new_key(), bind="127.0.0.1", port=0, store=self.dir / "r.json")
        self.server.start()
        self.client = room.RoomClient("127.0.0.1", self.server.port, self.server.key,
                                      {"name": "Anna", "ai": "Ki-Anna", "client": "c1"}, lambda *_: None)
        self.client.join()

    def tearDown(self):
        self.client.leave()
        self.server.stop()

    def _signed(self, path: str, body: bytes) -> bytes:
        ts = str(int(time.time()))
        sig = room.sign(self.server.key, "POST", path, ts, body)
        return (f"POST {path} HTTP/1.1\r\nHost: x\r\nContent-Length: {len(body)}\r\nX-MS-Zeit: {ts}\r\n"
                f"X-MS-Signatur: {sig}\r\n\r\n").encode() + body

    def test_negative_length_is_rejected(self):
        # früher: rfile.read(-1) – las ohne Grenze bis zum Ende der Verbindung, noch vor der Signaturprüfung
        line = _raw(self.server.port, b"POST /api/post HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n\r\nxx")
        self.assertIn(b" 400 ", line)

    def test_replayed_request_is_rejected(self):
        body = json.dumps({"member": self.client.member, "kind": "human", "text": "Hallo"}).encode()
        request = self._signed("/api/post?_r=einmalig123", body)
        self.assertIn(b" 200 ", _raw(self.server.port, request))
        self.assertIn(b" 409 ", _raw(self.server.port, request))  # dieselbe mitgeschnittene Anfrage noch einmal

    def test_older_clients_without_request_id_still_work(self):
        body = json.dumps({"member": self.client.member, "kind": "human", "text": "Hallo"}).encode()
        self.assertIn(b" 200 ", _raw(self.server.port, self._signed("/api/post", body)))

    def test_json_must_be_an_object(self):
        self.assertIn(b" 400 ", _raw(self.server.port, self._signed("/api/post", b"[1, 2]")))

    def test_upload_with_wrong_key_is_rejected(self):
        ts = str(int(time.time()))
        line = _raw(self.server.port, (f"POST /api/upload HTTP/1.1\r\nHost: x\r\nContent-Length: 4\r\nX-MS-Zeit: {ts}\r\n"
                                       "X-MS-Signatur: 00\r\n\r\nabcd").encode())
        self.assertIn(b" 401 ", line)

    def test_upload_and_download_stream_from_disk(self):
        src = self.dir / "gross.bin"
        src.write_bytes(os.urandom(3 * 1024 * 1024 + 5))
        up = self.client.upload(src, "gross.bin")
        self.assertTrue(room.valid_file_id(up["id"]))
        self.assertEqual((up["size"], up["sha256"]), (src.stat().st_size, hashlib.sha256(src.read_bytes()).hexdigest()))
        self.client.download(up["id"], self.dir / "zurueck.bin")
        self.assertEqual((self.dir / "zurueck.bin").read_bytes(), src.read_bytes())

    def test_member_fields_are_cleaned(self):
        self.client.update_member(busy="ja", ai_ready=1, tools=["kein", "dict"], model="M" * 500)
        m = self.server.members[self.client.member]
        self.assertEqual((m["busy"], m["ai_ready"], m["tools"], len(m["model"])), (True, True, {}, 80))


class GuestPaths(unittest.TestCase):
    """Daten vom Gastgeber werden beim Gast zu Dateinamen – ein fremder Gastgeber darf nicht daneben schreiben."""

    def test_file_ids(self):
        self.assertTrue(room.valid_file_id("0123456789abcdef01234567"))
        for bad in ("../../Startup/x", "0123456789abcdef0123456/", "", None, 5, "0123456789ABCDEF01234567"):
            self.assertFalse(room.valid_file_id(bad), bad)

    def test_cache_paths_refuse_foreign_ids(self):
        import roomui
        with self.assertRaises(ValueError):
            roomui.RoomMode._cache_path({"id": "../../../AppData/x", "name": "a.bat"})
        with self.assertRaises(ValueError):
            roomui.RoomMode._thumb_path({"id": "..\\..\\x"})
        ok = roomui.RoomMode._cache_path({"id": "a" * 24, "name": "bild.PNG"})
        self.assertEqual((ok.parent, ok.name), (roomui.CACHE_DIR, "a" * 24 + ".png"))

    def test_project_tree_from_host(self):
        tree = agent.Agent._host_tree
        self.assertEqual(tree({"kind": "dir", "base": "src", "files": [["src/a.py", 3], ["src/b/c.txt", 0]]}),
                         ("dir", "src", [("src/a.py", 3), ("src/b/c.txt", 0)]))
        self.assertEqual(tree({"kind": "file", "base": "a.txt", "files": [["a.txt", 1]]})[0], "file")
        for bad in ({"kind": "dir", "base": ".", "files": [["../../.bashrc", 1]]},
                    {"kind": "dir", "base": "src", "files": [["andere/x", 1]]},
                    {"kind": "dir", "base": ".", "files": [["/etc/passwd", 1]]},
                    {"kind": "dir", "base": ".", "files": [["a\\..\\..\\x", 1]]},
                    {"kind": "dir", "base": ".", "files": [["C:/x", 1]]},
                    {"kind": "dir", "base": ".", "files": [["a.txt", -5]]},
                    {"kind": "file", "base": "../x", "files": [["../x", 1]]},
                    {"kind": "file", "base": "a.txt", "files": [["b.txt", 1]]},
                    {"kind": "?", "base": ".", "files": []}):
            with self.assertRaises(agent.ToolError, msg=bad):
                tree(bad)


class PowerShellStrings(unittest.TestCase):
    def test_all_single_quote_kinds_are_doubled(self):
        # PowerShell beendet '…' auch an ‘ ’ ‚ ‛ – „x’; calc; ’“ führte sonst Code aus
        self.assertEqual(plattform.ps_quote("Don’t ‚so‘ it's ‛x"), "'Don’’t ‚‚so‘‘ it''s ‛‛x'")
        self.assertEqual(plattform.ps_quote(Path("C:/a b")), "'" + str(Path("C:/a b")) + "'")


class WebAccess(unittest.TestCase):
    def test_non_public_addresses(self):
        for address in ("127.0.0.1", "10.1.2.3", "192.168.1.1", "100.100.1.1", "169.254.169.254", "0.0.0.0",
                        "::1", "::ffff:127.0.0.1", "64:ff9b::7f00:1", "fe80::1", "fc00::1", "224.0.0.1"):
            self.assertTrue(web._blocked(address), address)
        for address in ("8.8.8.8", "93.184.215.14", "2606:4700::1111"):
            self.assertFalse(web._blocked(address), address)

    def test_gzip_bomb_is_capped(self):
        bomb = gzip.compress(b"\0" * (64 * 1024 * 1024))
        self.assertEqual(len(web._gunzip(bomb)), web.UNPACKED_MAX)
        self.assertEqual(web._gunzip(gzip.compress(b"Hallo Welt")), b"Hallo Welt")

    def test_connection_to_local_address_is_refused(self):
        # auch wenn die Prüfung des Namens vorher öffentlich ergab (DNS-Rebinding): verbunden wird nicht
        srv = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            no_proxy = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
            with mock.patch.dict(os.environ, no_proxy, clear=True):
                opener = web.urllib.request.build_opener(web._SafeRedirect, web._PublicHTTPHandler,
                                                         web._PublicHTTPSHandler)
                with self.assertRaises(OSError) as ctx:
                    opener.open(f"http://127.0.0.1:{srv.server_port}/", timeout=5)
            self.assertIn("blockiert", str(ctx.exception))
        finally:
            srv.shutdown()
            srv.server_close()


class _FakeLlama(http.server.BaseHTTPRequestHandler):
    """Wie llama-server mit --api-key: nur /health ohne Schlüssel."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if self.path == "/health" or self.headers.get("Authorization") == f"Bearer {backend.API_KEY}":
            return True
        self._send(401, b'{"error": {"message": "Invalid API Key"}}')
        return False

    def do_GET(self):
        if self._authorized():
            self._send(200, b'{"status": "ok"}' if self.path == "/health" else
                       b'{"default_generation_settings": {"n_ctx": 4096}, "modalities": {"vision": false}}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if not self._authorized():
            return
        if self.path == "/tokenize":
            self._send(200, json.dumps({"tokens": list(range(len(body["content"].split())))}).encode())
        elif not body.get("stream"):  # z. B. bilder.improve_prompt
            self._send(200, json.dumps({"choices": [{"message": {"content": "„Ein Leuchtturm“"}}]}).encode())
        else:
            chunks = [{"choices": [{"delta": {"content": "Hal"}}]}, {"choices": [{"delta": {"content": "lo"}}]}]
            sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
            self._send(200, sse.encode(), "text/event-stream")


class LocalModelServer(unittest.TestCase):
    def setUp(self):
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeLlama)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_requests_carry_the_key_and_bypass_proxies(self):
        # ein Proxy aus der Umgebung darf lokale Aufrufe nicht umleiten (Port 9 nimmt nichts an)
        with mock.patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9",
                                          "no_proxy": "", "NO_PROXY": ""}):
            self.assertEqual(backend.count_tokens(self.url, "eins zwei drei"), 3)
            server = backend.LlamaServer(lambda *_: None)
            self.assertEqual(server._props(1024, self.url), (False, 4096))
            text, calls, _ = backend.chat_turn(self.url, [{"role": "user", "content": "Hi"}], {}, None,
                                               threading.Event(), lambda *_: None)
        self.assertEqual((text, calls), ("Hallo", []))

    def test_improve_prompt_uses_the_key(self):
        import bilder  # „Beschreibung verbessern“ (v1.5) – ohne Schlüssel lehnte llama-server sie ab
        with mock.patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:9", "no_proxy": "", "NO_PROXY": ""}):
            self.assertEqual(bilder.improve_prompt(self.url, "Leuchtturm"), "Ein Leuchtturm")

    def test_image_server_requests_bypass_proxies(self):
        import sdcpp
        with mock.patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:9", "no_proxy": "", "NO_PROXY": ""}):
            self.assertEqual(sdcpp._request(self.url + "/health")["status"], "ok")

    def test_without_key_the_server_refuses(self):
        req = backend.urllib.request.Request(self.url + "/tokenize", data=b'{"content": "x"}',
                                             headers={"Content-Type": "application/json"})
        with self.assertRaises(backend.urllib.error.HTTPError) as ctx:
            backend._local.open(req, timeout=5)
        self.assertEqual(ctx.exception.code, 401)


class FileSearch(unittest.TestCase):
    def test_links_out_of_the_folder_are_not_read(self):
        with tempfile.TemporaryDirectory() as d:
            outside, base = Path(d) / "draussen", Path(d) / "projekt"
            outside.mkdir()
            (base / "sub").mkdir(parents=True)
            (outside / "geheim.txt").write_text("PASSWORT=xyz")
            (outside / "ordner").mkdir()
            (outside / "ordner" / "innen.txt").write_text("nichts")
            (base / "sub" / "a.txt").write_text("hier PASSWORT=gut")
            try:
                os.symlink(outside / "geheim.txt", base / "link.txt")
                os.symlink(outside / "ordner", base / "linkordner", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Verknüpfungen lassen sich hier nicht anlegen")
            found = agent.search_files(base, "*", "passwort")
            self.assertIn("sub/a.txt:1: hier PASSWORT=gut", found)
            self.assertNotIn("xyz", found)
            listing = agent.list_directory(base, 3)
            self.assertIn("[D] linkordner/", listing)
            self.assertNotIn("innen.txt", listing)  # Verknüpfungen auf Ordner werden nicht betreten

    def test_same_results_as_before(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            for rel in ("a.py", "x/b.py", "x/y/c.md", "node_modules/z.py", "x/.git/d.py", "Gross.PY"):
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_text("Zeile eins\nTreffer HIER\n" * 3)
            out = agent.search_files(base, "*.py", title="T").splitlines()  # Reihenfolge wie im Dateisystem
            self.assertEqual((out[0], sorted(out[1:])), ("Suche in T:", ["Gross.PY", "a.py", "x/b.py"]))
            out = agent.search_files(base, "x/*", "treffer", title="T").splitlines()
            self.assertEqual(out[0], "Suche in T:")
            self.assertEqual(sorted(out[1:]), sorted([f"x/b.py:{i}: Treffer HIER" for i in (2, 4, 6)]
                                                      + [f"x/y/c.md:{i}: Treffer HIER" for i in (2, 4, 6)]))

    def test_huge_text_files_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "riesig.log"
            with open(p, "wb") as f:
                f.truncate(agent.TEXT_FILE_MAX + 1)
            with self.assertRaises(agent.ToolError):
                agent._read_text_file(p)


class DownloadChecksum(unittest.TestCase):
    def test_wrong_checksum_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "programm.zip"
            src.write_bytes(b"Inhalt")
            good = hashlib.sha256(b"Inhalt").hexdigest()
            self.assertEqual(downloads.asset_sha256({"digest": f"sha256:{good.upper()}"}), good)
            self.assertIsNone(downloads.asset_sha256({"digest": None}))
            cancel = threading.Event()
            downloads.download(src.as_uri(), Path(d) / "ok.zip", lambda *_: None, cancel, sha256=good)
            with self.assertRaises(RuntimeError):
                downloads.download(src.as_uri(), Path(d) / "falsch.zip", lambda *_: None, cancel, sha256="0" * 64)


class _Flaky(http.server.BaseHTTPRequestHandler):
    """Liefert DATA, kennt Range; der erste Abruf reißt nach CUT Bytes ab (wie eine abgebrochene Verbindung)."""
    protocol_version = "HTTP/1.1"
    DATA = bytes(range(256)) * 4000
    CUT = 300_000
    calls: list = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        rng = self.headers.get("Range")
        start = int(rng.split("=")[1].split("-")[0]) if rng else 0
        type(self).calls.append(start)
        body = self.DATA[start:]
        self.send_response(206 if rng else 200)
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{len(self.DATA) - 1}/{len(self.DATA)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if len(type(self).calls) == 1:
            self.wfile.write(body[:self.CUT])
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_RDWR)
        else:
            self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.DATA)))
        self.end_headers()


class BrokenDownloads(unittest.TestCase):
    """http.client meldet einen Abriss nicht – die abgeschnittene Datei sah fertig aus und wurde nie neu geladen."""

    def setUp(self):
        _Flaky.calls = []
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Flaky)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/modell.gguf"
        self.dir = Path(tempfile.mkdtemp())
        no_proxy = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
        patcher = mock.patch.dict(os.environ, no_proxy, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_truncated_download_is_an_error(self):
        with self.assertRaises(ConnectionError):
            downloads.download(self.url, self.dir / "m.gguf", lambda *_: None, threading.Event())

    def test_broken_download_continues_where_it_stopped(self):
        dest = self.dir / "modell.gguf"
        with self.assertRaises(ConnectionError):
            downloads.fetch_files([(self.url, dest)], lambda *_: None, threading.Event())
        self.assertFalse(dest.exists())
        self.assertEqual(downloads.partial_size(dest), _Flaky.CUT)  # der Teil bleibt liegen
        downloads.fetch_files([(self.url, dest)], lambda *_: None, threading.Event())
        self.assertEqual(dest.read_bytes(), _Flaky.DATA)
        self.assertEqual(_Flaky.calls, [0, _Flaky.CUT])  # zweiter Abruf ab dem Abriss
        self.assertEqual(downloads.partial_size(dest), 0)

    def test_cancel_leaves_nothing(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(RuntimeError):
            downloads.fetch_one(self.url, self.dir / "x.gguf", lambda *_: None, cancel)
        self.assertEqual(list(self.dir.iterdir()), [])


class GalleryFiles(unittest.TestCase):
    @staticmethod
    def _chunk(kind: bytes, data: bytes) -> bytes:
        return len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")

    def test_compressed_text_is_capped(self):
        bomb = zlib.compress(b"A" * (32 * 1024 * 1024), 9)  # ~32 KB gepackt, 32 MB entpackt
        png = (b"\x89PNG\r\n\x1a\n" + b"".join(self._chunk(b"zTXt", b"k%d\0\0" % i + bomb) for i in range(100))
               + self._chunk(b"IEND", b""))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bombe.png"
            p.write_bytes(png)
            out = galerie.png_text(p)
        self.assertLessEqual(sum(map(len, out.values())), galerie.META_MAX)

    def test_metadata_is_still_read(self):
        png = (b"\x89PNG\r\n\x1a\n" + self._chunk(b"tEXt", b"parameters\0Haus\nSteps: 4, Seed: 42")
               + self._chunk(b"iTXt", b"x\0\x01\0\0\0" + zlib.compress("Grüße".encode())) + self._chunk(b"IEND", b""))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.png"
            p.write_bytes(png)
            self.assertEqual(galerie.png_text(p), {"parameters": "Haus\nSteps: 4, Seed: 42", "x": "Grüße"})

    def test_index_entries_stay_in_the_folder(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "bilder"
            folder.mkdir()
            (Path(d) / "wichtig.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (folder / "gut.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (folder / "bilder.json").write_text(json.dumps([{"file": "../wichtig.png"}, {"file": "gut.png"}]))
            g = galerie.Gallery(folder)
            self.assertEqual([e["file"] for e in g.items], ["gut.png"])  # Löschen träfe sonst ../wichtig.png

    def test_imagemagick_gets_a_fixed_format(self):
        bild = Path("/x/Bild.PNG")  # Pfad in der Schreibweise des Systems (unter Windows mit \)
        self.assertEqual(images._magick_input(bild), f"png:{bild}[0]")
        with self.assertRaises(ValueError):
            images._magick_input(Path("/x/bild.svg"))


class GalleryLabels(unittest.TestCase):
    def test_short_finds_the_same_cut_as_before(self):
        import bilder

        class Font:  # Zeichen unterschiedlich breit, wie in einer echten Schrift
            calls = 0

            def measure(self, text):
                Font.calls += 1
                return sum(4 + ord(ch) % 7 for ch in text)

        def old_short(text, font, width):
            line = " ".join((text or "").split())
            if font.measure(line) <= width:
                return line
            while line and font.measure(line + "…") > width:
                line = line[:-1]
            return line.rstrip() + "…"

        font = Font()
        texts = ["", "kurz", "a cinematic photo of an old lighthouse " * 30, "x" * 2000, "Wort  mit   Lücken " * 9]
        for width in (1, 30, 152, 400):
            for text in texts:
                self.assertEqual(bilder.short(text, font, width), old_short(text, font, width), (width, text[:20]))
        Font.calls = 0
        bilder.short("a cinematic photo of an old lighthouse " * 30, font, 152)
        self.assertLess(Font.calls, 20)  # vorher über tausend Messungen


if __name__ == "__main__":
    unittest.main()
