"""Teamwork – Netzwerkteil. RoomServer läuft beim Gastgeber (Teilnehmer, Nachrichten, nummerierte
Ereignisse, Long-Polling bis 20 s), RoomClient bei jedem Teilnehmer, auch beim Gastgeber.

Sicherheit: Jede Anfrage ist HMAC-SHA256-signiert (Methode, Pfad, Zeit, Inhalt), der Schlüssel geht nie über
das Netz. Teilnehmer schreiben nur eigene Nachrichten fort; Größe und Häufigkeit sind begrenzt. Der Server
reicht nur Chatnachrichten weiter – was eine KI tut, entscheidet allein ihr eigener Rechner.
"""

import base64
import hashlib
import hmac
import ipaddress
import itertools
import json
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import projekt

PROTOCOL = 1
DEFAULT_PORT = 47821
MAX_BODY = 4 * 1024 * 1024        # Bytes pro Anfrage
MAX_FILE = 100 * 1024 * 1024      # Bytes pro geteilter Datei (/api/upload)
MAX_ROOM_FILES = 2 * 1024 ** 3    # so viel speichert der Gastgeber an Dateien je Raum
MAX_TEXT = 600_000                # Zeichen pro Nachricht (inkl. angehängter Dokumente)
MAX_MESSAGES = 1500               # so viele Nachrichten behält der Gastgeber
POLL_WAIT = 20                    # Sekunden, die /api/events auf Neues wartet
OFFLINE_AFTER = 45                # ohne Abfrage so lange → offline
MAX_CLOCK_SKEW = 300              # erlaubte Zeitabweichung der Signatur (Sekunden)
NAME_RE = re.compile(r"^[A-Za-z0-9ÄÖÜäöüß._-]{2,24}$")


class RoomError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- Hilfsfunktionen

def new_key() -> str:
    return secrets.token_urlsafe(18)


def sign(key: str, method: str, path: str, ts: str, body: bytes) -> str:
    msg = f"{method}\n{path}\n{ts}\n".encode() + body
    return hmac.new(key.encode(), msg, hashlib.sha256).hexdigest()


def safe_file_name(name: str) -> str:
    """Dateiname ohne Pfad und ohne Zeichen, die Windows nicht erlaubt – für Anzeige und Speichern. Gespeichert
    wird beim Gastgeber nie unter diesem Namen, sondern unter einer zufälligen ID."""
    name = re.split(r"[\\/]", str(name or ""))[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(" .")
    stem = name.split(".")[0].upper()
    if stem in ("CON", "PRN", "AUX", "NUL") or re.fullmatch(r"(COM|LPT)\d", stem):
        name = "_" + name
    return name[:120] or "Datei"


def make_invite(host: str, port: int, key: str, room: str) -> str:
    """Einladungscode zum Weitergeben (enthält Adresse, Port, Raumname und Schlüssel)."""
    data = json.dumps({"v": PROTOCOL, "h": host, "p": port, "k": key, "r": room}, separators=(",", ":"))
    return "MSRAUM-" + base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")


def parse_invite(code: str) -> dict:
    code = "".join(code.split())
    if not code.startswith("MSRAUM-"):
        raise ValueError("Das ist kein gültiger Einladungscode (er beginnt mit „MSRAUM-“).")
    raw = code[7:] + "=" * (-len(code[7:]) % 4)
    try:
        d = json.loads(base64.urlsafe_b64decode(raw))
        return {"host": str(d["h"]), "port": int(d["p"]), "key": str(d["k"]), "room": str(d.get("r", "Raum"))}
    except (ValueError, KeyError, TypeError):
        raise ValueError("Der Einladungscode ist unvollständig oder beschädigt.") from None


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name or ""))


def mentions(text: str) -> set[str]:
    """Alle @Namen einer Nachricht (kleingeschrieben)."""
    return {m.lower() for m in re.findall(r"(?<![\w@])@([A-Za-z0-9ÄÖÜäöüß._-]{2,24})", text or "")}


def _tailscale_exe() -> str | None:
    exe = shutil.which("tailscale") or r"C:\Program Files\Tailscale\tailscale.exe"
    return exe if Path(exe).exists() else None


def tailscale_status(addrs: list[tuple[str, str]] | None = None) -> str:
    """"verbunden", "nicht verbunden" (installiert, aber z. B. nicht angemeldet) oder "" (nicht installiert).
    addrs: schon ermittelte local_addresses() – spart den zweiten Aufruf von „tailscale ip“."""
    if any(kind == "Tailscale" for _, kind in (local_addresses() if addrs is None else addrs)):
        return "verbunden"
    return "nicht verbunden" if _tailscale_exe() else ""


def local_addresses() -> list[tuple[str, str]]:
    """[(IPv4, Art)] der eigenen Netzwerkadressen – Tailscale (100.64.0.0/10) zuerst. Notfall-Adressen
    (169.254.x.x, z. B. von einem noch nicht angemeldeten Tailscale-Adapter) sind nicht erreichbar und fehlen."""
    ips = set()
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    exe = _tailscale_exe()
    if exe:
        try:
            r = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ips.update(x.strip() for x in r.stdout.split() if x.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    tailnet, out = ipaddress.ip_network("100.64.0.0/10"), []
    for ip in sorted(ips):
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.version != 4 or a.is_loopback or a.is_link_local:
            continue
        if a in tailnet:
            out.insert(0, (ip, "Tailscale"))
        else:
            out.append((ip, "Heimnetz" if a.is_private else "öffentlich"))
    return out


# ---------------------------------------------------------------- Gastgeber

class RoomServer:
    def __init__(self, room: str, key: str, bind: str = "0.0.0.0", port: int = DEFAULT_PORT,
                 store: Path | None = None):
        self.room, self.key, self.bind, self.port = room, key, bind, port
        self.store = store
        self.cond = threading.Condition()
        self.members: dict[str, dict] = {}
        self.messages: dict[str, dict] = {}       # Einfügereihenfolge = Chatreihenfolge
        self.events: deque = deque(maxlen=8000)
        self.seq = 0
        self._next = 0
        self._posts: dict[str, deque] = {}
        self.files: dict[str, dict] = {}          # Datei-ID → name, size, sha256, author, time (liegt in _dateien/)
        self.project: projekt.ProjectFolder | None = None  # gemeinsamer Projektordner (set_project)
        # Nur der eigene Teilnehmer des Gastgebers kennt dieses Zeichen (geht nie übers Netz – er verbindet sich
        # lokal); daran erkennt der Server den Gastgeber, statt dem Feld „host“ aus der Anfrage zu glauben
        self.host_token = secrets.token_hex(16)
        self._dirty = False
        self.httpd: ThreadingHTTPServer | None = None
        self._load()

    # ------------------------------------------------------------ Start/Stopp

    def start(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # keine Konsolenausgabe
                pass

            def do_GET(self):
                server._dispatch(self, "GET")

            def do_POST(self):
                server._dispatch(self, "POST")

        self.httpd = ThreadingHTTPServer((self.bind, self.port), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        threading.Thread(target=self._housekeeping, daemon=True).start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        with self.cond:
            self.cond.notify_all()
        self._save()

    # ------------------------------------------------------------ Speichern

    def _load(self):
        if not self.store or not self.store.is_file():
            return
        try:
            data = json.loads(self.store.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.files = {k: v for k, v in (data.get("files") or {}).items() if isinstance(v, dict)}
        shared = data.get("project")
        if isinstance(shared, dict) and Path(str(shared.get("root", ""))).is_dir():
            self.project = projekt.ProjectFolder(Path(shared["root"]), shared.get("write", True), self._versions_dir())
        for m in data.get("messages", [])[-MAX_MESSAGES:]:
            m["done"] = True
            self.messages[m["id"]] = m
            self._next = max(self._next, int(m["id"][1:]) if m["id"][1:].isdigit() else 0)

    def _save(self):
        if not self.store:
            return
        with self.cond:
            data = {"room": self.room, "messages": [dict(m) for m in self.messages.values()],
                    "files": {k: dict(v) for k, v in self.files.items()},
                    "project": {"root": str(self.project.root), "write": self.project.write} if self.project else None}
            self._dirty = False
        try:
            self.store.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.store.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.store)
        except OSError:
            pass

    def _housekeeping(self):
        """Alle paar Sekunden: Teilnehmer ohne Lebenszeichen als offline markieren, Verlauf speichern."""
        while self.httpd:
            time.sleep(5)
            changed = False
            with self.cond:
                now = time.time()
                for m in self.members.values():
                    online = now - m["last_seen"] < OFFLINE_AFTER
                    if online != m["online"]:
                        m["online"], changed = online, True
                if changed:
                    self._emit_members()
                dirty = self._dirty
            if dirty:
                self._save()

    # ------------------------------------------------------------ Zustand (nur mit self.cond aufrufen)

    def _emit(self, event: dict):
        self.seq += 1
        event["seq"] = self.seq
        self.events.append(event)
        self.cond.notify_all()

    def _public_members(self) -> list[dict]:
        keys = ("id", "name", "ai", "model", "ai_ready", "busy", "online", "host", "tools")
        return [{k: m.get(k) for k in keys} for m in self.members.values()]

    def _emit_members(self):
        self._emit({"type": "members", "members": self._public_members()})

    def _add_message(self, msg: dict) -> dict:
        self._next += 1
        msg = {"id": f"m{self._next}", "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "files": [],
               "tools": [], "done": True, "model": "", **msg}
        self.messages[msg["id"]] = msg
        while len(self.messages) > MAX_MESSAGES:
            self.messages.pop(next(iter(self.messages)))
        self._dirty = True
        # Kopie: _patch schreibt msg weiter – sonst enthielte das (später abgeholte) Ereignis schon den
        # fortgesetzten Text, und der Teilnehmer hängte die Fortsetzung ein zweites Mal an
        self._emit({"type": "message", "message": dict(msg)})
        return msg

    def snapshot(self) -> dict:
        """Stand zum Zeitpunkt seq (nur mit self.cond aufrufen) – Kopien, weil die Antwort erst nach dem
        Freigeben der Sperre verschickt wird und Fortsetzungen die Nachrichten sonst noch verändern könnten."""
        return {"room": self.room, "seq": self.seq, "members": self._public_members(),
                "messages": [dict(m) for m in self.messages.values()],
                "project": self.project.info() if self.project else None}

    def set_project(self, root: Path | None, write: bool = True, by: str = ""):
        """Projektordner freigeben (root) bzw. die Freigabe beenden (None) – mit Hinweis im Verlauf. Der volle
        Pfad bleibt beim Gastgeber; die anderen erfahren nur den Ordnernamen."""
        with self.cond:
            self.project = projekt.ProjectFolder(root, write, self._versions_dir()) if root else None
            info = self.project.info() if self.project else None
            text = (f"{by} hat den Projektordner „{info['name']}“ freigegeben – alle KIs dürfen dort "
                    + ("lesen und schreiben." if info["write"] else "lesen (nur der Gastgeber auch schreiben).")
                    if info else f"{by} hat die Freigabe des Projektordners beendet.")
            self._add_message({"kind": "system", "author": "", "name": by, "text": text})
            self._emit({"type": "project", "project": info})

    # ------------------------------------------------------------ HTTP

    def _dispatch(self, h: BaseHTTPRequestHandler, method: str):
        try:
            route = urllib.parse.urlparse(h.path)
            upload = (method, route.path) == ("POST", "/api/upload")  # Rohdaten statt JSON, eigene Grenze
            length = int(h.headers.get("Content-Length") or 0)
            if length > (MAX_FILE if upload else MAX_BODY):
                raise RoomError(413, "Datei zu groß (höchstens 100 MB)." if upload else "Anfrage zu groß.")
            body = h.rfile.read(length) if length else b""
            self._check_signature(h, method, body)
            data = body if upload else (json.loads(body) if body else {})
            handler = {("POST", "/api/join"): self._join, ("GET", "/api/events"): self._events,
                       ("POST", "/api/post"): self._post, ("POST", "/api/patch"): self._patch,
                       ("POST", "/api/member"): self._member, ("POST", "/api/leave"): self._leave,
                       ("POST", "/api/upload"): self._upload, ("GET", "/api/file"): self._file,
                       ("POST", "/api/project"): self._project,
                       }.get((method, route.path))
            if not handler:
                raise RoomError(404, "Unbekannter Pfad.")
            query = {k: v[0] for k, v in urllib.parse.parse_qs(route.query).items()}
            result = handler(data, query)
            if isinstance(result, Path):  # /api/file: Datei direkt von der Festplatte schicken
                self._reply_file(h, result)
            else:
                self._reply(h, 200, result)
        except RoomError as e:
            self._reply(h, e.code, {"error": str(e)})
        except (ValueError, KeyError, TypeError) as e:
            self._reply(h, 400, {"error": f"Ungültige Anfrage: {e}"})
        except (ConnectionError, OSError):
            pass

    def _check_signature(self, h, method: str, body: bytes):
        ts, sig = h.headers.get("X-MS-Zeit", ""), h.headers.get("X-MS-Signatur", "")
        if not ts.isdigit() or abs(time.time() - int(ts)) > MAX_CLOCK_SKEW:
            raise RoomError(401, "Zeitstempel fehlt oder weicht zu stark ab (Uhrzeit der Rechner prüfen).")
        if not hmac.compare_digest(sig, sign(self.key, method, h.path, ts, body)):
            raise RoomError(401, "Falscher Raum-Schlüssel.")

    @staticmethod
    def _reply_file(h, path: Path):
        h.send_response(200)
        h.send_header("Content-Type", "application/octet-stream")
        h.send_header("Content-Length", str(path.stat().st_size))
        h.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, h.wfile, 1 << 20)

    @staticmethod
    def _reply(h, code: int, data: dict):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        h.send_response(code)
        h.send_header("Content-Type", "application/json; charset=utf-8")
        h.send_header("Content-Length", str(len(raw)))
        h.end_headers()
        h.wfile.write(raw)

    def _get_member(self, mid: str) -> dict:
        m = self.members.get(mid or "")
        if not m:
            raise RoomError(404, "Unbekannter Teilnehmer – bitte neu beitreten.")
        m["last_seen"] = time.time()
        if not m["online"]:
            m["online"] = True
            self._emit_members()
        return m

    # ------------------------------------------------------------ Endpunkte

    def _join(self, d: dict, _q) -> dict:
        name, ai = str(d.get("name", "")).strip(), str(d.get("ai", "")).strip()
        if not valid_name(name) or not valid_name(ai):
            raise RoomError(400, "Namen: 2–24 Zeichen, nur Buchstaben, Ziffern, Punkt, Binde- und Unterstrich.")
        if name.lower() == ai.lower():
            raise RoomError(400, "Dein Name und der Name deiner KI müssen sich unterscheiden.")
        client = str(d.get("client", ""))[:40]
        with self.cond:
            old = None
            for m in list(self.members.values()):
                if client and m.get("client") == client:  # dieselbe Monhip-Installation kommt wieder
                    old = m
                    continue
                taken = {m["name"].lower(), m["ai"].lower()}
                if name.lower() in taken or ai.lower() in taken:
                    if m["name"].lower() == name.lower() and not m["online"]:
                        old = m  # derselbe Name, alter Eintrag ist offline
                    else:
                        raise RoomError(409, f"Der Name „{name if name.lower() in taken else ai}“ ist im Raum "
                                             "schon vergeben.")
            if old:
                self.members.pop(old["id"], None)
            mid = secrets.token_hex(8)
            self.members[mid] = {
                "id": mid, "client": client, "name": name, "ai": ai, "model": str(d.get("model", ""))[:80],
                "ai_ready": bool(d.get("ai_ready")), "busy": False, "tools": d.get("tools") or {},
                "host": hmac.compare_digest(str(d.get("host_token", "")).encode(), self.host_token.encode()),
                "online": True, "last_seen": time.time()}
            self._emit_members()
            if not old:
                self._add_message({"kind": "system", "author": mid, "name": name,
                                   "text": f"{name} ist dem Raum beigetreten (KI: @{ai})."})
            return {"member": mid, "snapshot": self.snapshot()}

    def _events(self, _d, q: dict) -> dict:
        since = int(q.get("since", 0))
        deadline = time.time() + min(POLL_WAIT, float(q.get("wait", POLL_WAIT)))
        with self.cond:
            self._get_member(q.get("member", ""))
            oldest = self.events[0]["seq"] if self.events else self.seq + 1
            if since < oldest - 1 or since > self.seq:  # zu weit zurück oder Gastgeber neu gestartet
                return {"resync": True, "snapshot": self.snapshot()}
            while self.seq <= since and self.httpd:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self.cond.wait(remaining)
            # Die Nummern sind lückenlos: die neuen Ereignisse sind genau die letzten seq − since (statt bei jedem
            # Aufwecken alle bis zu 8000 zu durchsuchen – das geschieht unter der Sperre)
            new = list(itertools.islice(reversed(self.events), max(0, self.seq - since)))
            return {"seq": self.seq, "events": new[::-1]}

    def _post(self, d: dict, _q) -> dict:
        kind = d.get("kind")
        if kind not in ("human", "ai"):
            raise RoomError(400, "Unbekannte Nachrichtenart.")
        text, content = str(d.get("text", "")), str(d.get("content") or d.get("text", ""))
        if len(content) > MAX_TEXT or len(text) > MAX_TEXT:
            raise RoomError(413, "Nachricht zu lang.")
        with self.cond:
            m = self._get_member(d.get("member"))
            times = self._posts.setdefault(m["id"], deque(maxlen=40))
            if len(times) == times.maxlen and time.time() - times[0] < 60:
                raise RoomError(429, "Zu viele Nachrichten – bitte kurz warten.")
            times.append(time.time())
            files = []
            for f in (d.get("files") or [])[:10]:
                if not isinstance(f, dict):
                    continue
                item = {"name": safe_file_name(f.get("name", "")), "info": str(f.get("info", ""))[:200]}
                stored = self.files.get(str(f.get("id", "")))
                if stored:  # geteilte Datei: Name und Größe vom Gastgeber, nicht vom Absender
                    item.update(id=f["id"], name=stored["name"], size=stored["size"], image=bool(f.get("image")))
                files.append(item)
            msg = self._add_message({
                "kind": kind, "author": m["id"], "name": m["ai"] if kind == "ai" else m["name"],
                "owner": m["name"], "text": text, "content": content, "files": files,
                "done": kind == "human" or bool(d.get("done")), "model": m["model"] if kind == "ai" else "",
                "nonce": str(d.get("nonce", ""))[:40]})
            return {"id": msg["id"]}

    def _patch(self, d: dict, _q) -> dict:
        """Eine KI schreibt ihre (noch laufende) Antwort fort: Text anhängen, Werkzeuge, fertig."""
        with self.cond:
            m = self._get_member(d.get("member"))
            msg = self.messages.get(d.get("id", ""))
            if not msg or msg["author"] != m["id"]:
                raise RoomError(403, "Nur eigene Nachrichten können fortgeschrieben werden.")
            append = str(d.get("append", ""))
            if len(msg["content"]) + len(append) > MAX_TEXT:
                raise RoomError(413, "Nachricht zu lang.")
            msg["text"] += append
            msg["content"] += append
            event = {"type": "patch", "id": msg["id"], "append": append, "done": bool(d.get("done"))}
            if isinstance(d.get("tools"), list):
                msg["tools"] = [{k: str(t.get(k, ""))[:120] for k in ("icon", "label", "detail")} | {"ok": t.get("ok")}
                                for t in d["tools"][:50] if isinstance(t, dict)]
                event["tools"] = msg["tools"]
            if d.get("done"):
                msg["done"] = True
            self._dirty = True
            self._emit(event)
            return {"ok": True}

    def _files_dir(self) -> Path | None:
        return self.store.with_name(self.store.stem + "_dateien") if self.store else None

    def _versions_dir(self) -> Path | None:
        """Alte Fassungen geänderter/gelöschter Dateien des Projektordners (nur beim Gastgeber)."""
        return self.store.with_name(self.store.stem + "_projekt_alt") if self.store else None

    def _project(self, d: dict, _q) -> dict:
        """Dateiaktion einer KI im gemeinsamen Projektordner (projekt.ProjectFolder)."""
        with self.cond:
            m = self._get_member(d.get("member"))
            folder = self.project
        if not folder:
            raise RoomError(404, "Der Gastgeber hat (gerade) keinen Projektordner freigegeben.")
        try:
            return folder.run(str(d.get("op", "")), d.get("args") or {}, m["id"], m["ai"], bool(m.get("host")))
        except projekt.ProjectError as e:
            raise RoomError(e.code, str(e)) from None

    def _upload(self, body: bytes, q: dict) -> dict:
        """Datei eines Teilnehmers speichern – unter einer zufälligen ID, nie unter dem mitgeschickten Namen."""
        folder = self._files_dir()
        if not folder:
            raise RoomError(501, "Dieser Raum kann keine Dateien speichern.")
        with self.cond:
            m = self._get_member(q.get("member", ""))
            if sum(f.get("size", 0) for f in self.files.values()) + len(body) > MAX_ROOM_FILES:
                raise RoomError(507, "Im Raum ist kein Platz mehr für Dateien (höchstens 2 GB).")
        fid = secrets.token_hex(12)
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f"{fid}.part"
        tmp.write_bytes(body)
        tmp.replace(folder / fid)
        meta = {"name": safe_file_name(q.get("name", "")), "size": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                "author": m["id"], "time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
        with self.cond:
            self.files[fid] = meta
            self._dirty = True
        return {"id": fid, **meta}

    def _file(self, _d, q: dict) -> Path:
        fid = str(q.get("id", ""))
        if not re.fullmatch(r"[0-9a-f]{24}", fid):
            raise RoomError(400, "Ungültige Datei-ID.")
        with self.cond:
            self._get_member(q.get("member", ""))
            known = fid in self.files
        path = (self._files_dir() or Path(".")) / fid
        if not known or not path.is_file():
            raise RoomError(404, "Die Datei gibt es beim Gastgeber nicht (mehr).")
        return path

    def _member(self, d: dict, _q) -> dict:
        with self.cond:
            m = self._get_member(d.get("member"))
            for k in ("model", "ai_ready", "busy", "tools"):
                if k in d:
                    m[k] = d[k] if k != "model" else str(d[k])[:80]
            self._emit_members()
            return {"ok": True}

    def _leave(self, d: dict, _q) -> dict:
        with self.cond:
            m = self.members.pop(d.get("member", ""), None)
            if m:
                self._emit_members()
                self._add_message({"kind": "system", "author": m["id"], "name": m["name"],
                                   "text": f"{m['name']} hat den Raum verlassen."})
            return {"ok": True}


# ---------------------------------------------------------------- Teilnehmer

class RoomClient:
    """Verbindung eines Teilnehmers zum Gastgeber. on_event(art, daten) wird aus dem Hintergrund-Thread
    aufgerufen: ("snapshot", snapshot), ("event", ereignis), ("state", "ok" | Fehlertext)."""

    def __init__(self, host: str, port: int, key: str, profile: dict, on_event):
        host = f"[{host}]" if ":" in host else host
        self.base, self.key, self.profile, self.on_event = f"http://{host}:{port}", key, dict(profile), on_event
        self.member: str | None = None
        self.seq = 0
        self.running = False
        self.state = "?"

    def _req(self, method: str, path: str, data: dict | None = None, timeout: float = 15) -> dict:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else b""
        with self._open(method, path, body, "application/json", timeout) as r:
            return json.loads(r.read() or b"{}")

    def upload(self, path: Path, name: str) -> dict:
        """Datei beim Gastgeber ablegen → {"id", "name", "size", "sha256", …}."""
        data = Path(path).read_bytes()
        if len(data) > MAX_FILE:
            raise RoomError(413, f"„{name}“ ist zu groß zum Teilen (höchstens 100 MB).")
        query = urllib.parse.urlencode({"member": self.member, "name": name})
        with self._open("POST", f"/api/upload?{query}", data, "application/octet-stream", 600) as r:
            return json.loads(r.read() or b"{}")

    def download(self, fid: str, dest: Path):
        """Geteilte Datei nach dest holen (erst als .part, dann umbenannt)."""
        query = urllib.parse.urlencode({"member": self.member, "id": fid})
        tmp = Path(dest).with_name(Path(dest).name + ".part")
        try:
            with self._open("GET", f"/api/file?{query}", b"", "application/json", 600) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)

    def _open(self, method: str, path: str, body: bytes, content_type: str, timeout: float):
        ts = str(int(time.time()))
        headers = {"Content-Type": content_type, "X-MS-Zeit": ts,
                   "X-MS-Signatur": sign(self.key, method, path, ts, body)}
        req = urllib.request.Request(self.base + path, data=body if method == "POST" else None,
                                     headers=headers, method=method)
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read() or b"{}").get("error") or e.reason
            except ValueError:
                msg = e.reason
            raise RoomError(e.code, str(msg)) from None

    def join(self) -> dict:
        res = self._req("POST", "/api/join", self.profile)
        self.member = res["member"]
        self.seq = res["snapshot"]["seq"]
        return res["snapshot"]

    def start(self):
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.running = False

    def _set_state(self, state: str):
        if state != self.state:
            self.state = state
            self.on_event("state", state)

    def _loop(self):
        delay = 1.0
        while self.running:
            try:
                res = self._req("GET", f"/api/events?since={self.seq}&member={self.member}", timeout=POLL_WAIT + 15)
                if not self.running:
                    break
                if res.get("resync"):
                    self.seq = res["snapshot"]["seq"]
                    self.on_event("snapshot", res["snapshot"])
                else:
                    for ev in res.get("events", []):
                        self.on_event("event", ev)
                    self.seq = res.get("seq", self.seq)
                self._set_state("ok")
                delay = 1.0
            except RoomError as e:
                if e.code == 404 and self.running:  # Gastgeber kennt uns nicht mehr (z. B. neu gestartet)
                    try:
                        self.on_event("snapshot", self.join())
                        continue
                    except (RoomError, OSError, ValueError) as e2:
                        e = e2
                self._set_state(f"Fehler: {e}")
                self._sleep(delay)
                delay = min(delay * 2, 15)
            except (OSError, ValueError) as e:
                self._set_state(f"Gastgeber nicht erreichbar ({type(e).__name__})")
                self._sleep(delay)
                delay = min(delay * 2, 15)

    def _sleep(self, seconds: float):
        end = time.time() + seconds
        while self.running and time.time() < end:
            time.sleep(0.2)

    # ------------------------------------------------------------ Aktionen

    def post(self, kind: str, text: str, content: str | None = None, files=None, done: bool = True,
             nonce: str = "") -> str:
        return self._req("POST", "/api/post", {"member": self.member, "kind": kind, "text": text,
                                               "content": content if content is not None else text,
                                               "files": files or [], "done": done, "nonce": nonce})["id"]

    def patch(self, msg_id: str, append: str = "", done: bool = False, tools: list | None = None):
        data = {"member": self.member, "id": msg_id, "append": append, "done": done}
        if tools is not None:
            data["tools"] = tools
        self._req("POST", "/api/patch", data)

    def project(self, op: str, args: dict) -> dict:
        """Aktion im gemeinsamen Projektordner des Gastgebers (list, read, search, write, edit, mkdir, delete)."""
        return self._req("POST", "/api/project", {"member": self.member, "op": op, "args": args}, timeout=120)

    def update_member(self, **fields):
        self.profile.update({k: v for k, v in fields.items() if k in ("model", "ai_ready", "tools")})
        self._req("POST", "/api/member", {"member": self.member, **fields})

    def leave(self):
        self.running = False
        try:
            self._req("POST", "/api/leave", {"member": self.member}, timeout=3)
        except (RoomError, OSError, ValueError):
            pass
