"""Dateien per Drag & Drop (WM_DROPFILES) und aus der Zwischenablage (CF_HDROP) übernehmen – über ctypes,
weil Tkinter das nicht kann. Auf anderen Systemen tun die Funktionen nichts.
"""

import ctypes
import sys
import time
import tkinter as tk

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
        return False
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


def clipboard_files() -> list[str]:
    """Im Explorer kopierte Dateien (Strg+C) aus der Zwischenablage; leer, wenn keine da sind."""
    if sys.platform != "win32" or not user32.IsClipboardFormatAvailable(CF_HDROP):
        return []
    if not user32.OpenClipboard(None):
        return []
    try:
        handle = user32.GetClipboardData(CF_HDROP)
        return _query_files(ctypes.c_void_p(handle)) if handle else []
    finally:
        user32.CloseClipboard()


def clipboard_has_image() -> bool:
    """Liegt ein Bild ohne Text in der Zwischenablage (z. B. Screenshot)? Mit Text (etwa aus Excel oder Word,
    die zusätzlich ein Bild ablegen) wird normal eingefügt."""
    if sys.platform != "win32":
        return False
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
    if sys.platform != "win32" or not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
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
        raise OSError("Nur unter Windows.")
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
