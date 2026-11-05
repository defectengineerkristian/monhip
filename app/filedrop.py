"""Dateien per Drag & Drop (WM_DROPFILES) und aus der Zwischenablage (CF_HDROP) übernehmen – über ctypes,
weil Tkinter das nicht kann.

Linux: Drag & Drop mit der Tk-Erweiterung tkdnd (Paket tkdnd), falls installiert. Zwischenablage im Tk-Thread über
Tk selbst (widget übergeben – ein externes Programm würde dort hängen, solange Monhip selbst die Zwischenablage
besitzt und nicht antworten kann), in Werkzeug-Threads über wl-paste/wl-copy (Wayland) bzw. xclip (X11).
"""

import ctypes
import os
import subprocess
import sys
import time
import tkinter as tk
import urllib.parse

import plattform

WM_DROPFILES = 0x0233
CF_HDROP = 15
CF_DIB = 8
CF_UNICODETEXT = 13
GWLP_WNDPROC = -4

if sys.platform == "win32":
    from ctypes import wintypes

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.CallWindowProcW.restype = LRESULT
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                       wintypes.LPARAM]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT]
    shell32.DragFinish.argtypes = [ctypes.c_void_p]
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]


def _query_files(hdrop) -> list[str]:
    files = []
    for i in range(shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)):
        n = shell32.DragQueryFileW(hdrop, i, None, 0)
        buf = ctypes.create_unicode_buffer(n + 1)
        shell32.DragQueryFileW(hdrop, i, buf, n + 1)
        files.append(buf.value)
    return files


def enable_drop(window: tk.Misc, callback) -> bool:
    """Erlaubt das Ablegen von Dateien auf window. callback(liste_von_pfaden) läuft im Tk-Thread."""
    if sys.platform != "win32":
        return _enable_drop_tkdnd(window, callback)
    try:
        window.update_idletasks()
        hwnd = window.winfo_id()
        old = None
        dropped: list[list[str]] = []

        def proc(h, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                # Hier KEIN Tkinter aufrufen („Fatal Python error: PyEval_RestoreThread“) – poll() übernimmt.
                try:
                    dropped.append(_query_files(ctypes.c_void_p(wparam)))
                except Exception:
                    pass
                finally:
                    shell32.DragFinish(ctypes.c_void_p(wparam))
                return 0
            return user32.CallWindowProcW(old, h, msg, wparam, lparam)

        def poll():
            while dropped:
                callback(dropped.pop(0))
            window.after(100, poll)

        new_proc = WNDPROC(proc)
        old = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(new_proc, ctypes.c_void_p))
        if not old:
            return False
        window._filedrop_proc = new_proc  # Verweis halten, sonst räumt Python die Rückruffunktion weg
        shell32.DragAcceptFiles(hwnd, True)
        poll()
        return True
    except Exception:
        return False


def clipboard_files(widget: tk.Misc | None = None) -> list[str]:
    """Im Explorer bzw. Dateimanager kopierte Dateien (Strg+C) aus der Zwischenablage; leer, wenn keine da sind.
    widget: nur unter Linux, im Tk-Thread (siehe oben)."""
    if sys.platform != "win32":
        return _linux_files(widget)
    if not user32.IsClipboardFormatAvailable(CF_HDROP):
        return []
    if not user32.OpenClipboard(None):
        return []
    try:
        handle = user32.GetClipboardData(CF_HDROP)
        return _query_files(ctypes.c_void_p(handle)) if handle else []
    finally:
        user32.CloseClipboard()


def clipboard_has_image(widget: tk.Misc | None = None) -> bool:
    """Liegt ein Bild ohne Text in der Zwischenablage (z. B. Screenshot)? Mit Text (etwa aus Excel oder Word,
    die zusätzlich ein Bild ablegen) wird normal eingefügt."""
    if sys.platform != "win32":
        targets = _targets(widget)
        return any(t.startswith("image/") for t in targets) and not any(t in TEXT_TARGETS for t in targets)
    return bool(user32.IsClipboardFormatAvailable(CF_DIB)) and not user32.IsClipboardFormatAvailable(CF_UNICODETEXT)


# ---------------------------------------------------------------- Text (Agent-Werkzeuge clipboard_read/_write)
# Direkt über die Windows-API statt über Tk: läuft im Werkzeug-Thread, Tk darf dort nicht angefasst werden.

def _kernel32():
    k = ctypes.windll.kernel32
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    k.GlobalFree.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    return k


def _open_clipboard(hwnd=None) -> bool:
    """Ein anderes Programm kann die Zwischenablage gerade offen haben – dann kurz warten."""
    for _ in range(20):
        if user32.OpenClipboard(hwnd):
            return True
        time.sleep(0.05)
    return False


def clipboard_text() -> str | None:
    """Text aus der Zwischenablage (None: kein Text oder nicht lesbar)."""
    if sys.platform != "win32":
        data = _read("text/plain;charset=utf-8") or _read("UTF8_STRING") or _read(None)
        return data.decode("utf-8", "replace") if data else None
    if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None
    k = _kernel32()
    if not _open_clipboard():
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        ptr = k.GlobalLock(handle) if handle else None
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr).replace("\r\n", "\n")
        finally:
            k.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str):
    """Text in die Zwischenablage legen. Dafür braucht es ein Fenster als Besitzer (mit None scheitert
    SetClipboardData) – ein unsichtbares, nur für diesen Aufruf; der Text bleibt danach in der Zwischenablage."""
    if sys.platform != "win32":
        _write_text(text)
        return
    k = _kernel32()
    data = ctypes.create_unicode_buffer(text.replace("\r\n", "\n").replace("\n", "\r\n"))  # Windows-Zeilenenden
    hwnd = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, None, None, None, None)
    try:
        if not _open_clipboard(hwnd):
            raise OSError("Die Zwischenablage ist gerade von einem anderen Programm belegt.")
        try:
            user32.EmptyClipboard()
            mem = k.GlobalAlloc(0x0002, ctypes.sizeof(data))  # GMEM_MOVEABLE
            ptr = k.GlobalLock(mem)
            ctypes.memmove(ptr, data, ctypes.sizeof(data))
            k.GlobalUnlock(mem)
            if not user32.SetClipboardData(CF_UNICODETEXT, mem):  # danach gehört der Speicher Windows
                k.GlobalFree(mem)
                raise OSError("Text konnte nicht in die Zwischenablage gelegt werden.")
        finally:
            user32.CloseClipboard()
    finally:
        user32.DestroyWindow(hwnd)


# ---------------------------------------------------------------- Linux

TEXT_TARGETS = {"UTF8_STRING", "STRING", "TEXT", "text/plain", "text/plain;charset=utf-8"}
FILE_TARGETS = ("text/uri-list", "x-special/gnome-copied-files")


def _enable_drop_tkdnd(window: tk.Misc, callback) -> bool:
    """Drag & Drop über tkdnd: abgelegte Dateien kommen als Tcl-Liste von Pfaden (%D)."""
    try:
        window.tk.call("package", "require", "tkdnd")

        def dropped(data):
            files = [f for f in window.tk.splitlist(data) if f]
            if files:
                window.after_idle(callback, files)
            return "copy"

        command = window.register(dropped)
        window.tk.call("tkdnd::drop_target", "register", window._w, "DND_Files")
        window.tk.call("bind", window._w, "<<Drop:DND_Files>>", f"{command} %D")
        return True
    except tk.TclError:
        return False


def _tool(write: bool = False) -> list[str] | None:
    """Programm für die Zwischenablage: Wayland wl-paste/wl-copy, sonst xclip (über XWayland geht es auch dort)."""
    if plattform.WAYLAND and plattform.which("wl-copy" if write else "wl-paste"):
        return ["wl-copy"] if write else ["wl-paste", "--no-newline"]
    if plattform.which("xclip"):
        return ["xclip", "-selection", "clipboard", "-i" if write else "-o"]
    return None


def _read(target: str | None) -> bytes | None:
    """Inhalt der Zwischenablage in einem Format (None: Text) – nie im Tk-Thread aufrufen."""
    tool = _tool()
    if not tool:
        return None
    if target:
        tool += ["--type", target] if tool[0] == "wl-paste" else ["-t", target]
    try:
        r = subprocess.run(tool, capture_output=True, stdin=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 and r.stdout else None


def _write_text(text: str):
    tool = _tool(write=True)
    if not tool:
        raise OSError("wl-copy oder xclip fehlt – bitte installieren (Paket wl-clipboard bzw. xclip).")
    try:  # beide bleiben im Hintergrund, bis jemand anderes etwas kopiert – nicht auf ihre Ausgabe warten
        subprocess.run(tool, input=text.encode("utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=10)
    except subprocess.SubprocessError as e:
        raise OSError("Text konnte nicht in die Zwischenablage gelegt werden.") from e


def _targets(widget: tk.Misc | None) -> list[str]:
    """Formate, die gerade in der Zwischenablage liegen."""
    if widget is not None:
        try:
            return list(widget.tk.splitlist(widget.clipboard_get(type="TARGETS")))
        except tk.TclError:
            return []
    tool = _tool()
    if not tool:
        return []
    args = ["wl-paste", "--list-types"] if tool[0] == "wl-paste" else tool + ["-t", "TARGETS"]
    try:
        r = subprocess.run(args, capture_output=True, stdin=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    return r.stdout.decode("utf-8", "replace").split() if r.returncode == 0 else []


def _tk_text(value: str) -> str:
    """Tk gibt Formate, die es nicht als Text kennt (text/uri-list …), als Bytes in Hex aus: „0x66 0x69 …“."""
    parts = value.split()
    if parts and all(p.startswith("0x") for p in parts):
        try:
            return bytes(int(p, 16) for p in parts).decode("utf-8", "replace")
        except ValueError:
            pass
    return value


def parse_uri_list(text: str) -> list[str]:
    """file://-Adressen (text/uri-list, GNOME mit „copy“/„cut“ davor) → vorhandene Pfade."""
    files = []
    for line in text.replace("\r", "\n").split("\n"):
        line = line.strip()
        if line.startswith("file://"):
            path = urllib.parse.unquote(urllib.parse.urlparse(line).path)
            if path and os.path.exists(path):
                files.append(path)
    return files


def _linux_files(widget: tk.Misc | None) -> list[str]:
    targets = _targets(widget)
    for target in FILE_TARGETS:
        if target not in targets:
            continue
        if widget is not None:
            try:
                text = _tk_text(widget.clipboard_get(type=target))
            except tk.TclError:
                continue
        else:
            data = _read(target)
            text = data.decode("utf-8", "replace") if data else ""
        files = parse_uri_list(text)
        if files:
            return files
    return []


def clipboard_image_png() -> bytes | None:
    """Linux: Bild aus der Zwischenablage als PNG (nicht im Tk-Thread aufrufen)."""
    data = _read("image/png")
    return data if data and data.startswith(b"\x89PNG") else None
