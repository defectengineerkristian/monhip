"""WebFusedAgentMod – Netzwerkteil. RoomServer läuft beim Gastgeber (Teilnehmer, Nachrichten, nummerierte
Ereignisse, Long-Polling bis 20 s), RoomClient bei jedem Teilnehmer, auch beim Gastgeber.

Sicherheit: Jede Anfrage ist HMAC-SHA256-signiert (Methode, Pfad, Zeit, Inhalt), der Schlüssel geht nie über
das Netz. Teilnehmer schreiben nur eigene Nachrichten fort; Größe und Häufigkeit sind begrenzt. Der Server
reicht nur Chatnachrichten weiter – was eine KI tut, entscheidet allein ihr eigener Rechner.
"""

import base64
import hashlib
import hmac
import ipaddress
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

PROTOCOL = 1
DEFAULT_PORT = 47821
MAX_BODY = 4 * 1024 * 1024        # Bytes pro Anfrage
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


def tailscale_status() -> str:
    """"verbunden", "nicht verbunden" (installiert, aber z. B. nicht angemeldet) oder "" (nicht installiert)."""
    if any(kind == "Tailscale" for _, kind in local_addresses()):
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
        for m in data.get("messages", [])[-MAX_MESSAGES:]:
            m["done"] = True
            self.messages[m["id"]] = m
            self._next = max(self._next, int(m["id"][1:]) if m["id"][1:].isdigit() else 0)

    def _save(self):
        if not self.store:
            return
        with self.cond:
            data = {"room": self.room, "messages": list(self.messages.values())}
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
        self._emit({"type": "message", "message": msg})
        return msg

    def snapshot(self) -> dict:
        return {"room": self.room, "seq": self.seq, "members": self._public_members(),
                "messages": list(self.messages.values())}

    # ------------------------------------------------------------ HTTP

    def _dispatch(self, h: BaseHTTPRequestHandler, method: str):
        try:
            length = int(h.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise RoomError(413, "Anfrage zu groß.")
            body = h.rfile.read(length) if length else b""
            self._check_signature(h, method, body)
            data = json.loads(body) if body else {}
            route = urllib.parse.urlparse(h.path)
            handler = {("POST", "/api/join"): self._join, ("GET", "/api/events"): self._events,
                       ("POST", "/api/post"): self._post, ("POST", "/api/patch"): self._patch,
                       ("POST", "/api/member"): self._member, ("POST", "/api/leave"): self._leave,
                       }.get((method, route.path))
            if not handler:
                raise RoomError(404, "Unbekannter Pfad.")
            query = {k: v[0] for k, v in urllib.parse.parse_qs(route.query).items()}
            self._reply(h, 200, handler(data, query))
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
                "host": bool(d.get("host")), "online": True, "last_seen": time.time()}
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
            return {"seq": self.seq, "events": [e for e in self.events if e["seq"] > since]}

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
            files = [{"name": str(f.get("name", ""))[:200], "info": str(f.get("info", ""))[:200]}
                     for f in (d.get("files") or [])[:10] if isinstance(f, dict)]
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
        ts = str(int(time.time()))
        headers = {"Content-Type": "application/json", "X-MS-Zeit": ts,
                   "X-MS-Signatur": sign(self.key, method, path, ts, body)}
        req = urllib.request.Request(self.base + path, data=body if method == "POST" else None,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
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

    def update_member(self, **fields):
        self.profile.update({k: v for k, v in fields.items() if k in ("model", "ai_ready", "tools")})
        self._req("POST", "/api/member", {"member": self.member, **fields})

    def leave(self):
        self.running = False
        try:
            self._req("POST", "/api/leave", {"member": self.member}, timeout=3)
        except (RoomError, OSError, ValueError):
            pass
