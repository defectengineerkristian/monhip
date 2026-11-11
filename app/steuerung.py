"""Programmfenster bedienen (Werkzeuge fenster_liste/fenster_bedienen): sichtbare Fenster auflisten, ein gewähltes
nach vorn holen, Tasten, Text, Mausklicks und Mausrad per SendInput hineinschicken und ein Bild nur dieses Fensters
aufnehmen. Alles über ctypes, nur Windows; läuft im Werkzeug-Thread (nie Tkinter aufrufen).

Sicherheit: Monhip selbst, Konsolen/Terminals (würden die Rückfrage von run_command umgehen), Explorer/Desktop,
Einstellungen, Task-Manager, Registry und Anmeldefenster sind gesperrt; Windows-Taste, Alt+Tab & Co. ebenso. Vor jeder
Aktion muss ein Fenster dieses Programms vorn sein – klickt der Nutzer woandershin, bricht der Ablauf ab."""

import ctypes
import os
import time
import zlib
from ctypes import wintypes as wt
from datetime import datetime
from pathlib import Path

from images import TEMP_DIR

MAX_SIDE = 1280         # Bild höchstens so breit/hoch (verkleinert)
SCALE = 1000            # Koordinaten der Aktionen: relativ zum Fensterbild, 0 bis SCALE (siehe to_screen in run)
MAX_ACTIONS = 40        # je Aufruf
MAX_WAIT_MS = 30_000    # alle „warten“ und „halten“ eines Aufrufs zusammen
MAX_TEXT = 2000         # Zeichen je „text“
KEY_GAP = 0.012         # Pause zwischen Tastendrücken (manche Programme verschlucken sonst Zeichen)
SETTLE = 0.35           # nach den Aktionen warten, bevor das Bild aufgenommen wird

BLOCKED_EXE = {
    "cmd.exe", "powershell.exe", "pwsh.exe", "windowsterminal.exe", "wt.exe", "conhost.exe", "openconsole.exe",
    "explorer.exe", "taskmgr.exe", "regedit.exe", "mmc.exe", "systemsettings.exe", "consent.exe",
    "credentialuibroker.exe", "logonui.exe", "lockapp.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "msiexec.exe"}
BLOCKED_TITLES = ("einstellungen", "settings")  # Windows-Einstellungen laufen in ApplicationFrameHost.exe
BLOCKED_COMBOS = {frozenset({"win"}), frozenset({"alt", "tab"}), frozenset({"alt", "esc"}),
                  frozenset({"ctrl", "esc"}), frozenset({"ctrl", "shift", "esc"}), frozenset({"ctrl", "alt", "delete"})}

VK = {"enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20, "leertaste": 0x20,
      "backspace": 0x08, "rücktaste": 0x08, "delete": 0x2E, "del": 0x2E, "entf": 0x2E, "insert": 0x2D, "einfg": 0x2D,
      "home": 0x24, "pos1": 0x24, "end": 0x23, "ende": 0x23, "pageup": 0x21, "bildauf": 0x21, "pagedown": 0x22,
      "bildab": 0x22, "up": 0x26, "oben": 0x26, "hoch": 0x26, "down": 0x28, "unten": 0x28, "runter": 0x28,
      "left": 0x25, "links": 0x25, "right": 0x27, "rechts": 0x27, "shift": 0x10, "umschalt": 0x10, "ctrl": 0x11,
      "strg": 0x11, "control": 0x11, "alt": 0x12, "win": 0x5B, "windows": 0x5B, "capslock": 0x14,
      **{f"f{i}": 0x6F + i for i in range(1, 25)},
      **{c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"},
      "+": 0xBB, "plus": 0xBB, "-": 0xBD, "minus": 0xBD, ",": 0xBC, ".": 0xBE}
NAMES = {"strg": "ctrl", "control": "ctrl", "umschalt": "shift", "windows": "win", "escape": "esc", "return": "enter",
         "leertaste": "space", "rücktaste": "backspace", "entf": "delete", "del": "delete", "einfg": "insert",
         "pos1": "home", "ende": "end", "bildauf": "pageup", "bildab": "pagedown", "oben": "up", "hoch": "up",
         "unten": "down", "runter": "down", "links": "left", "rechts": "right", "plus": "+", "minus": "-"}
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B}  # Pfeile, Pos1/Ende, Bild, Einfg/Entf

user32 = ctypes.WinDLL("user32", use_last_error=True) if os.name == "nt" else None
gdi32 = ctypes.WinDLL("gdi32") if os.name == "nt" else None
kernel32 = ctypes.WinDLL("kernel32") if os.name == "nt" else None
if os.name == "nt":  # Typen festlegen – sonst schneidet ctypes 64-Bit-Handles auf int ab
    H, P = wt.HANDLE, ctypes.c_void_p
    for fn, args, res in (
            (user32.GetForegroundWindow, [], wt.HWND), (user32.IsWindow, [wt.HWND], wt.BOOL),
            (user32.IsIconic, [wt.HWND], wt.BOOL), (user32.IsWindowVisible, [wt.HWND], wt.BOOL),
            (user32.GetWindow, [wt.HWND, wt.UINT], wt.HWND), (user32.GetWindowLongW, [wt.HWND, ctypes.c_int], wt.LONG),
            (user32.GetWindowTextLengthW, [wt.HWND], ctypes.c_int),
            (user32.GetWindowTextW, [wt.HWND, wt.LPWSTR, ctypes.c_int], ctypes.c_int),
            (user32.GetWindowThreadProcessId, [wt.HWND, P], wt.DWORD),
            (user32.GetWindowRect, [wt.HWND, P], wt.BOOL), (user32.GetClientRect, [wt.HWND, P], wt.BOOL),
            (user32.ClientToScreen, [wt.HWND, P], wt.BOOL), (user32.ShowWindow, [wt.HWND, ctypes.c_int], wt.BOOL),
            (user32.SetForegroundWindow, [wt.HWND], wt.BOOL), (user32.BringWindowToTop, [wt.HWND], wt.BOOL),
            (user32.AttachThreadInput, [wt.DWORD, wt.DWORD, wt.BOOL], wt.BOOL),
            (user32.SetCursorPos, [ctypes.c_int, ctypes.c_int], wt.BOOL),
            (user32.MapVirtualKeyW, [wt.UINT, wt.UINT], wt.UINT),
            (user32.SendInput, [wt.UINT, P, ctypes.c_int], wt.UINT),
            (user32.GetDC, [wt.HWND], H), (user32.ReleaseDC, [wt.HWND, H], ctypes.c_int),
            (gdi32.CreateCompatibleDC, [H], H), (gdi32.CreateCompatibleBitmap, [H, ctypes.c_int, ctypes.c_int], H),
            (gdi32.SelectObject, [H, H], H), (gdi32.DeleteObject, [H], wt.BOOL), (gdi32.DeleteDC, [H], wt.BOOL),
            (gdi32.SetStretchBltMode, [H, ctypes.c_int], ctypes.c_int),
            (gdi32.SetBrushOrgEx, [H, ctypes.c_int, ctypes.c_int, P], wt.BOOL),
            (gdi32.StretchBlt, [H] + [ctypes.c_int] * 4 + [H] + [ctypes.c_int] * 4 + [wt.DWORD], wt.BOOL),
            (gdi32.GetDIBits, [H, H, wt.UINT, wt.UINT, P, P, wt.UINT], ctypes.c_int),
            (kernel32.OpenProcess, [wt.DWORD, wt.BOOL, wt.DWORD], H), (kernel32.CloseHandle, [H], wt.BOOL),
            (kernel32.QueryFullProcessImageNameW, [H, wt.DWORD, wt.LPWSTR, P], wt.BOOL),
            (kernel32.GetCurrentThreadId, [], wt.DWORD)):
        fn.argtypes, fn.restype = args, res
    try:
        user32.SetThreadDpiAwarenessContext.argtypes = [P]
        user32.SetThreadDpiAwarenessContext.restype = P
    except AttributeError:  # vor Windows 10 1607
        pass


class ControlError(Exception):
    """Fehler beim Bedienen – das Modell bekommt den Text (wie ToolError)."""


# ---------------------------------------------------------------- Fenster finden

def _exe(pid: int) -> str:
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        return Path(buf.value).name if ok else ""
    finally:
        kernel32.CloseHandle(h)


def _info(hwnd: int) -> dict:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return {"hwnd": hwnd, "title": buf.value, "pid": pid.value, "exe": _exe(pid.value),
            "w": r.right - r.left, "h": r.bottom - r.top, "minimized": bool(user32.IsIconic(hwnd))}


def _cloaked(hwnd: int) -> bool:
    """Unsichtbare „Geister“-Fenster von Apps (DWM verhüllt sie) überspringen."""
    val = ctypes.c_int(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), 14, ctypes.byref(val), ctypes.sizeof(val))
    except OSError:
        return False
    return bool(val.value)


def windows() -> list[dict]:
    """Sichtbare Programmfenster (Hauptfenster mit Titel), oberstes zuerst – ohne Monhip selbst."""
    found = []
    own = os.getpid()
    proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def each(hwnd, _):
        if (user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd)
                and not user32.GetWindow(hwnd, 4)                               # GW_OWNER: kein Dialog/Werkzeugfenster
                and not user32.GetWindowLongW(hwnd, -20) & 0x80                 # WS_EX_TOOLWINDOW
                and not _cloaked(hwnd)):
            found.append(hwnd)
        return True

    user32.EnumWindows(proc(each), 0)
    out = []
    for hwnd in found:
        info = _info(hwnd)
        if info["pid"] != own:
            out.append(info)
    return out


def describe(win: dict) -> str:
    """Ohne Größe in Pixeln: mit ihr rechnete das Modell Klickstellen über Pixel (ungenau) statt direkt relativ."""
    state = " · minimiert" if win["minimized"] else ""
    return f"„{win['title']}“ · {win['exe'] or '?'}{state} · id {win['hwnd']}"


def find(spec) -> dict:
    """Fenster zu einer id aus fenster_liste, einem Teil des Titels oder dem Programmnamen."""
    text = str(spec or "").strip().strip("„“\"'")
    if not text:
        raise ControlError("Kein Fenster angegeben – erst fenster_liste aufrufen.")
    if text.lower().startswith("id"):
        text = text[2:].strip(" :")
    if text.isdigit():
        hwnd = int(text)
        if not user32.IsWindow(hwnd):
            raise ControlError(f"Fenster id {hwnd} gibt es nicht mehr – fenster_liste neu aufrufen.")
        info = _info(hwnd)
        if info["pid"] == os.getpid():
            raise ControlError("Monhip selbst kann nicht bedient werden.")
        return info
    wins = windows()
    low = text.lower()
    exact = [w for w in wins if w["title"].lower() == low]
    part = [w for w in wins if low in w["title"].lower()]
    prog = [w for w in wins if w["exe"].lower() in (low, low + ".exe")]
    for hits in (exact, part, prog):
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ControlError(f"„{text}“ passt auf mehrere Fenster – bitte die id angeben:\n"
                               + "\n".join("- " + describe(w) for w in hits[:10]))
    raise ControlError(f"Kein Fenster „{text}“ gefunden. Offene Fenster:\n"
                       + ("\n".join("- " + describe(w) for w in wins[:25]) or "(keine)"))


def check_allowed(win: dict):
    exe, title = win["exe"].lower(), win["title"].lower()
    if win["pid"] == os.getpid():
        raise ControlError("Monhip selbst kann nicht bedient werden.")
    if exe in BLOCKED_EXE or (exe == "applicationframehost.exe" and any(t in title for t in BLOCKED_TITLES)):
        raise ControlError(f"„{win['title']}“ ({win['exe']}) darf nicht bedient werden – Konsolen, Explorer, "
                           "Einstellungen, Task-Manager und Anmeldefenster sind gesperrt (Befehle gehen nur über "
                           "run_command mit Rückfrage).")


# ---------------------------------------------------------------- Aktionen prüfen

def _combo(spec) -> list[str]:
    keys = [NAMES.get(k, k) for k in (p.strip().lower() for p in str(spec).replace(" ", "").split("+")) if k]
    if str(spec).strip().endswith("++"):  # „ctrl++“ = Strg und Plus
        keys.append("+")
    if not keys:
        raise ControlError("Leere Taste.")
    for k in keys:
        if k not in VK:
            raise ControlError(f"Unbekannte Taste „{k}“ – erlaubt: enter, esc, tab, space, backspace, delete, "
                               "up/down/left/right, home, end, pageup, pagedown, f1–f24, Buchstaben, Ziffern, mit + "
                               "kombiniert (ctrl, shift, alt). Für Text „text“ verwenden.")
    s = frozenset(keys)
    if "win" in s or any(b <= s for b in BLOCKED_COMBOS):
        raise ControlError(f"„{spec}“ ist gesperrt (Windows-Taste, Fensterwechsel, Task-Manager).")
    return keys


def _point(v) -> tuple[float, float]:
    try:
        x, y = v
        return float(x), float(y)
    except (TypeError, ValueError):
        raise ControlError(f"Koordinaten als [x, y] angeben, nicht {v!r}.") from None


def parse(actions) -> list[tuple]:
    """Aktionen des Modells prüfen → [(art, …)]; Fehler, bevor irgendetwas passiert."""
    if actions in (None, ""):
        return []
    if not isinstance(actions, list):
        raise ControlError("aktionen muss eine Liste von Objekten sein, z. B. [{\"taste\": \"enter\"}].")
    if len(actions) > MAX_ACTIONS:
        raise ControlError(f"Höchstens {MAX_ACTIONS} Aktionen je Aufruf – in kleineren Schritten arbeiten.")
    out, waited = [], 0
    for i, a in enumerate(actions, 1):
        if not isinstance(a, dict):
            raise ControlError(f"Aktion {i} ist kein Objekt: {a!r}")
        if "text" in a:
            t = str(a["text"])
            if len(t) > MAX_TEXT:
                raise ControlError(f"Aktion {i}: Text zu lang (höchstens {MAX_TEXT} Zeichen).")
            out.append(("text", t))
        elif "taste" in a:
            out.append(("taste", _combo(a["taste"])))
        elif "halten" in a:
            key, ms = a["halten"], a.get("ms")
            if isinstance(key, dict):  # Modelle schreiben auch {"halten": {"taste": "w", "ms": 500}}
                key, ms = key.get("taste") or key.get("key") or "", key.get("ms") or ms
            ms = max(10, min(int(ms or 300), 5000))
            waited += ms
            out.append(("halten", _combo(key), ms))
        elif "klick" in a:
            button = {"rechts": "right", "right": "right", "mitte": "middle", "middle": "middle"}.get(
                str(a.get("maustaste") or "links").lower(), "left")
            out.append(("klick", _point(a["klick"]), button, bool(a.get("doppelt"))))
        elif "scrollen" in a:
            n = max(-20, min(int(a["scrollen"]), 20))
            out.append(("scrollen", n, _point(a["bei"]) if a.get("bei") is not None else None))
        elif "warten" in a:
            ms = max(0, min(int(a["warten"]), 10_000))
            waited += ms
            out.append(("warten", ms))
        else:
            raise ControlError(f"Aktion {i} unbekannt: {a!r} – erlaubt sind text, taste, halten, klick, scrollen, warten.")
        if waited > MAX_WAIT_MS:
            raise ControlError(f"Zu viel Warten/Halten in einem Aufruf (höchstens {MAX_WAIT_MS // 1000} s).")
    return out


def summary(steps: list[tuple], limit: int = 12) -> str:
    """Lesbare Liste für die Rückfrage."""
    lines = []
    for s in steps[:limit]:
        kind = s[0]
        if kind == "text":
            t = s[1] if len(s[1]) <= 80 else s[1][:79] + "…"
            lines.append(f"Text: {t!r}")
        elif kind == "taste":
            lines.append("Taste: " + "+".join(s[1]))
        elif kind == "halten":
            lines.append(f"Halten: {'+'.join(s[1])} ({s[2]} ms)")
        elif kind == "klick":
            what = {"left": "Klick", "right": "Rechtsklick", "middle": "Mittelklick"}[s[2]]
            lines.append(f"{'Doppel' + what.lower() if s[3] else what} bei {s[1][0]:.0f}, {s[1][1]:.0f}")
        elif kind == "scrollen":
            lines.append(f"Scrollen {s[1]:+d}")
        else:
            lines.append(f"Warten {s[1]} ms")
    if len(steps) > limit:
        lines.append(f"… und {len(steps) - limit} weitere")
    return "\n".join(lines)


# ---------------------------------------------------------------- Eingaben (SendInput)

class _MOUSE(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _KEYB(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _HARD(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _U(ctypes.Union):
    _fields_ = [("mi", _MOUSE), ("ki", _KEYB), ("hi", _HARD)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def _send(*inputs: _INPUT):
    arr = (_INPUT * len(inputs))(*inputs)
    if user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT)) != len(inputs):
        raise ControlError("Windows hat die Eingabe abgelehnt (z. B. weil ein Fenster mit Adminrechten vorn ist).")


def _key_input(vk: int, up: bool) -> _INPUT:
    """Taste über den Scancode (Spiele lesen oft nur Scancodes) samt erweitertem Flag für Pfeile usw."""
    scan = user32.MapVirtualKeyW(vk, 0)
    flags = 0x0008 | (0x0002 if up else 0) | (0x0001 if vk in EXTENDED else 0)  # SCANCODE, KEYUP, EXTENDEDKEY
    if not scan:  # ohne Scancode (selten): über den virtuellen Code
        return _INPUT(1, _U(ki=_KEYB(vk, 0, (0x0002 if up else 0), 0, 0)))
    return _INPUT(1, _U(ki=_KEYB(0, scan, flags, 0, 0)))


def _press(keys: list[str], hold: float = 0.0, stop=None):
    vks = [VK[k] for k in keys]
    for vk in vks:
        _send(_key_input(vk, False))
        time.sleep(KEY_GAP)
    try:
        _sleep(hold, stop)
    finally:
        for vk in reversed(vks):
            _send(_key_input(vk, True))
            time.sleep(KEY_GAP)


def _type(text: str, check):
    for ch in text.replace("\r\n", "\n"):
        check()
        if ch == "\n":
            _press(["enter"])
            continue
        if ch == "\t":
            _press(["tab"])
            continue
        units = ch.encode("utf-16-le")
        for i in range(0, len(units), 2):  # Zeichen außerhalb der BMP (Emoji) als zwei Einheiten
            code = int.from_bytes(units[i:i + 2], "little")
            _send(_INPUT(1, _U(ki=_KEYB(0, code, 0x0004, 0, 0))), _INPUT(1, _U(ki=_KEYB(0, code, 0x0004 | 0x0002, 0, 0))))
        time.sleep(KEY_GAP)


def _mouse(flags: int, data: int = 0):
    _send(_INPUT(0, _U(mi=_MOUSE(0, 0, data & 0xFFFFFFFF, flags, 0, 0))))


def _sleep(seconds: float, stop=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if stop is not None and stop.is_set():
            raise ControlError("Vom Nutzer gestoppt.")
        time.sleep(min(0.02, max(0.0, end - time.monotonic())))


# ---------------------------------------------------------------- Ablauf

class _DpiAware:
    """Für diesen Thread echte Bildschirmpixel (sonst rechnet Windows bei Skalierung alle Koordinaten um)."""

    def __enter__(self):
        try:
            self.old = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
        except (AttributeError, OSError):
            self.old = None
        return self

    def __exit__(self, *exc):
        if self.old:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(self.old))


def _foreground_pid() -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    return pid.value


def activate(win: dict):
    """Fenster nach vorn holen (wiederherstellen, falls minimiert). Windows erlaubt das nur dem Programm, das gerade
    vorn ist – sonst über die Eingabe-Warteschlange des vorderen Fensters (AttachThreadInput)."""
    hwnd = win["hwnd"]
    if not user32.IsWindow(hwnd):
        raise ControlError("Das Fenster gibt es nicht mehr – fenster_liste neu aufrufen.")
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    if _foreground_pid() == win["pid"]:
        return
    user32.SetForegroundWindow(hwnd)
    if _foreground_pid() != win["pid"]:
        fg = user32.GetForegroundWindow()
        mine, theirs = kernel32.GetCurrentThreadId(), user32.GetWindowThreadProcessId(fg, None)
        if theirs and user32.AttachThreadInput(mine, theirs, True):
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
            finally:
                user32.AttachThreadInput(mine, theirs, False)
    for _ in range(25):
        if _foreground_pid() == win["pid"]:
            time.sleep(0.15)  # Fenster zeichnet sich nach dem Wechsel noch neu
            return
        time.sleep(0.02)
    raise ControlError("Das Fenster ließ sich nicht nach vorn holen – der Nutzer kann es selbst anklicken.")


def client_rect(win: dict) -> tuple[int, int, int, int]:
    """Innenbereich des Fensters in Bildschirmpixeln: (links, oben, Breite, Höhe)."""
    r = wt.RECT()
    user32.GetClientRect(win["hwnd"], ctypes.byref(r))
    p = wt.POINT(0, 0)
    user32.ClientToScreen(win["hwnd"], ctypes.byref(p))
    return p.x, p.y, r.right - r.left, r.bottom - r.top


def _scale(w: int, h: int) -> float:
    return min(1.0, MAX_SIDE / max(w, h, 1))


def run(win: dict, steps: list[tuple], stop=None) -> int:
    """Aktionen ausführen. Vor jeder: das Programm muss vorn sein, sonst Abbruch (Nutzer hat woandershin geklickt)."""
    done = 0
    with _DpiAware():
        activate(win)

        def check():
            if stop is not None and stop.is_set():
                raise ControlError(f"Vom Nutzer gestoppt (nach {done} Aktionen).")
            if _foreground_pid() != win["pid"]:
                raise ControlError(f"Ein anderes Fenster ist nach vorn gekommen (vermutlich hat der Nutzer geklickt) "
                                   f"– abgebrochen nach {done} von {len(steps)} Aktionen.")

        def to_screen(pt):
            """[x, y] von 0 bis 1000 relativ zum Fensterbild → Bildschirmpixel. Relativ, weil Bildmodelle (Qwen-VL)
            so trainiert sind: gemessen 2 px statt 134 px Abweichung gegenüber Pixelangaben im Bild."""
            left, top, w, h = client_rect(win)
            x, y = pt
            if not (0 <= x <= SCALE and 0 <= y <= SCALE):
                raise ControlError(f"Punkt {x:.0f}, {y:.0f} liegt außerhalb des Fensters (x und y von 0 bis {SCALE}) – "
                                   f"abgebrochen nach {done} Aktionen.")
            return left + min(w - 1, round(x / SCALE * w)), top + min(h - 1, round(y / SCALE * h))

        for s in steps:
            check()
            kind = s[0]
            if kind == "text":
                _type(s[1], check)
            elif kind == "taste":
                _press(s[1])
            elif kind == "halten":
                _press(s[1], s[2] / 1000, stop)
            elif kind == "klick":
                x, y = to_screen(s[1])
                user32.SetCursorPos(x, y)
                time.sleep(0.03)
                down, up = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}[s[2]]
                for _ in range(2 if s[3] else 1):
                    _mouse(down)
                    time.sleep(0.02)
                    _mouse(up)
                    time.sleep(0.06)
            elif kind == "scrollen":
                if s[2] is not None:
                    user32.SetCursorPos(*to_screen(s[2]))
                    time.sleep(0.03)
                for _ in range(abs(s[1])):
                    _mouse(0x0800, -120 if s[1] > 0 else 120)  # WHEEL: positiv = nach unten
                    time.sleep(0.03)
            else:
                _sleep(s[1] / 1000, stop)
            done += 1
            time.sleep(0.05)
    return done


def capture(win: dict) -> tuple[Path, int, int]:
    """Bild nur vom Innenbereich des Fensters (so, wie es auf dem Bildschirm zu sehen ist), höchstens MAX_SIDE
    Pixel → (PNG, Breite, Höhe). Das Fenster muss vorn sein."""
    with _DpiAware():
        activate(win)
        time.sleep(SETTLE)
        left, top, w, h = client_rect(win)
        if w <= 0 or h <= 0:
            raise ControlError("Das Fenster hat keinen sichtbaren Inhalt (minimiert?).")
        k = _scale(w, h)
        bw, bh = max(1, round(w * k)), max(1, round(h * k))
        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bmp = gdi32.CreateCompatibleBitmap(screen, bw, bh)
        old = gdi32.SelectObject(mem, bmp)
        raw = None
        try:
            gdi32.SetStretchBltMode(mem, 4)  # HALFTONE: sauber verkleinern
            gdi32.SetBrushOrgEx(mem, 0, 0, None)
            if not gdi32.StretchBlt(mem, 0, 0, bw, bh, screen, left, top, w, h, 0x00CC0020 | 0x40000000):
                raise ControlError("Das Fensterbild konnte nicht aufgenommen werden.")  # SRCCOPY | CAPTUREBLT

            class BMI(ctypes.Structure):
                _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                            ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                            ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                            ("biClrImportant", wt.DWORD)]

            info = BMI(ctypes.sizeof(BMI), bw, -bh, 1, 32, 0, 0, 0, 0, 0, 0)  # von oben nach unten, BGRA
            raw = ctypes.create_string_buffer(bw * bh * 4)
            gdi32.SelectObject(mem, old)  # GetDIBits will die Bitmap nicht ausgewählt
            if not gdi32.GetDIBits(mem, bmp, 0, bh, raw, ctypes.byref(info), 0):
                raise ControlError("Das Fensterbild konnte nicht gelesen werden.")
        finally:
            gdi32.SelectObject(mem, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(None, screen)
    bgra = raw.raw
    rgb = bytearray(bw * bh * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    stride = bw * 3
    rows = b"".join(b"\x00" + bytes(rgb[y * stride:(y + 1) * stride]) for y in range(bh))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", bw.to_bytes(4, "big") + bh.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")
           + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMP_DIR / datetime.now().strftime("Fenster %Y-%m-%d %H-%M-%S-%f.png")
    path.write_bytes(png)
    return path, bw, bh
