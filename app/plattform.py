"""Was je Betriebssystem anders ist – an einer Stelle, damit der übrige Code für Windows und Linux gleich bleibt.

Windows verhält sich wie bisher (os.startfile, Papierkorb der Shell, taskkill, PowerShell). Unter Linux übernehmen
die üblichen Programme: xdg-open, gio trash, bash, dbus-send; fehlt eines, nennt need() das Paket, das es bringt.
Funktionen für einzelne Bereiche (Bilder, Mikrofon, PDF-Seiten …) liegen in ihren Modulen und fragen hier nur ab,
auf welchem System sie laufen.
"""

import ctypes
import functools
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import urllib.parse
from datetime import datetime
from pathlib import Path

WINDOWS = sys.platform == "win32"
LINUX = sys.platform.startswith("linux")
MAC = sys.platform == "darwin"
NAME = "Windows" if WINDOWS else "macOS" if MAC else "Linux"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
EXE = ".exe" if WINDOWS else ""
CONSOLE_ENCODING = "oem" if WINDOWS else "utf-8"  # Ausgabe von Konsolenprogrammen („oem“ gibt es nur unter Windows)
UI_FONT = "Segoe UI" if WINDOWS else "sans-serif"  # Linux: die Schrift des Desktops (über fontconfig)
MONO_FONT = "Consolas" if WINDOWS else "monospace"
SHELL_LABEL = "PowerShell" if WINDOWS else "Bash"
CAN_CONTROL = WINDOWS   # Programme bedienen (steuerung.py): Fenster und Eingaben gibt es nur über die Windows-API
WAYLAND = bool(os.environ.get("WAYLAND_DISPLAY")) or os.environ.get("XDG_SESSION_TYPE") == "wayland"
DEVNULL = subprocess.DEVNULL
CODE_DIR = Path(__file__).resolve().parent.parent  # Monhip.pyw und app/


def data_home() -> Path:
    """Basis für Programmdaten nach XDG (~/.local/share)."""
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _data_dir() -> Path:
    """Wo Monhip seine Daten ablegt (config.json, modelle/, server/, chats/ …): wie bisher neben dem Programm –
    außer MONHIP_DATA nennt einen Ordner (setzt das Linux-Paket: ~/.local/share/monhip) oder der Programmordner ist
    unter Linux schreibgeschützt (installiert, z. B. /opt/monhip): dann ebenfalls ~/.local/share/monhip."""
    env = os.environ.get("MONHIP_DATA", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if not WINDOWS and not os.access(CODE_DIR, os.W_OK):
        return data_home() / "monhip"
    return CODE_DIR


DATA_DIR = _data_dir()


def exe(name: str) -> str:
    """Programmname mit der Endung des Systems: exe("llama-server") → „llama-server.exe“ unter Windows."""
    return name + EXE


def which(*names: str) -> str | None:
    """Das erste der Programme, das im PATH liegt."""
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def need(*names: str, package: str) -> str:
    """Wie which, aber mit verständlichem Fehler, wenn keines da ist."""
    found = which(*names)
    if not found:
        raise OSError(f"{' oder '.join(names)} fehlt – bitte installieren (Paket {package}).")
    return found


# ---------------------------------------------------------------- Prozesse

PS_PREFIX = ("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
             "$OutputEncoding = [System.Text.Encoding]::UTF8; $ProgressPreference = 'SilentlyContinue'; ")


def shell_argv(command: str) -> list[str]:
    """Aufruf für einen Befehl der KI (run_command, prozess_starten): Windows PowerShell 5.1 bzw. bash."""
    if WINDOWS:
        return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                PS_PREFIX + command]
    return [which("bash") or "/bin/sh", "-c", command]


@functools.cache
def _prctl():
    try:
        f = ctypes.CDLL(None, use_errno=True).prctl
        f.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        return f
    except (OSError, AttributeError):
        return None


def _die_with_parent(prctl, parent: int):
    """Im neuen Prozess vor dem Programmstart: SIGKILL, sobald Monhip endet (PR_SET_PDEATHSIG = 1)."""
    prctl(1, signal.SIGKILL, 0, 0, 0)
    if os.getppid() != parent:  # Monhip war schon weg, bevor das Signal stand
        os._exit(1)


_spawn_jobs: queue.Queue = queue.Queue()
_spawn_thread: threading.Thread | None = None
_spawn_lock = threading.Lock()


def _spawn_loop():
    while True:
        make, box, done = _spawn_jobs.get()
        try:
            box["proc"] = make()
        except BaseException as e:  # an den Aufrufer weiterreichen
            box["error"] = e
        finally:
            done.set()


def _spawn(make):
    """make() im dauerhaften Start-Thread ausführen. PR_SET_PDEATHSIG hängt am Thread, der den Prozess startet –
    aus einem Arbeits-Thread gestartet endete llama-server sonst gleich nach dem Laden mit diesem Thread."""
    global _spawn_thread
    with _spawn_lock:
        if _spawn_thread is None:
            _spawn_thread = threading.Thread(target=_spawn_loop, name="monhip-start", daemon=True)
            _spawn_thread.start()
    if threading.current_thread() is _spawn_thread:
        return make()
    done, box = threading.Event(), {}
    _spawn_jobs.put((make, box, done))
    done.wait()
    if "error" in box:
        raise box["error"]
    return box["proc"]


def popen(args, *, bound: bool = False, group: bool = False, **kw) -> subprocess.Popen:
    """subprocess.Popen ohne Konsolenfenster.
    group: eigene Prozessgruppe – kill_tree erreicht dann auch alles, was der Prozess selbst startet.
    bound: unter Linux endet der Prozess mit Monhip, auch nach einem Absturz (unter Windows hängt ihn
    backend._end_with_app an ein Job-Objekt – das bleibt wie bisher dort)."""
    if WINDOWS:
        flags = kw.pop("creationflags", 0) | NO_WINDOW | (NEW_GROUP if group else 0)
        return subprocess.Popen(args, creationflags=flags, **kw)
    if group:
        kw["start_new_session"] = True
    prctl = _prctl() if bound and LINUX else None
    if prctl:
        kw["preexec_fn"] = functools.partial(_die_with_parent, prctl, os.getpid())
        proc = _spawn(lambda: subprocess.Popen(args, **kw))
    else:
        proc = subprocess.Popen(args, **kw)
    proc.monhip_bound = bool(prctl)
    proc.monhip_group = group
    return proc


def kill_tree(proc: subprocess.Popen):
    """Prozess samt Unterprozessen beenden (PowerShell, bash und Python starten oft weitere: npm → node …)."""
    if WINDOWS:
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           stdin=DEVNULL, creationflags=NO_WINDOW, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            pass
    elif getattr(proc, "monhip_group", False):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    if proc.poll() is None:
        proc.kill()


def start_detached(cmd: list[str], cwd):
    """Programm unabhängig von Monhip starten (Neustart): läuft weiter, wenn Monhip endet."""
    if WINDOWS:
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:  # eigenes Job-Objekt des Startprogramms (falls vorhanden) verlassen, sonst endete der neue Prozess mit
            subprocess.Popen(cmd, cwd=cwd, creationflags=flags | 0x01000000, close_fds=True)  # BREAKAWAY_FROM_JOB
        except OSError:
            subprocess.Popen(cmd, cwd=cwd, creationflags=flags, close_fds=True)
    else:
        subprocess.Popen(cmd, cwd=cwd, close_fds=True, start_new_session=True, stdin=DEVNULL)


# ---------------------------------------------------------------- Dateien öffnen, zeigen, löschen

def open_path(path):
    """Datei mit dem zugehörigen Programm bzw. Ordner im Dateimanager öffnen – wie ein Doppelklick."""
    if WINDOWS:
        os.startfile(path)
        return
    tool = "open" if MAC else need("xdg-open", package="xdg-utils")
    subprocess.Popen([tool, str(path)], stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL, start_new_session=True)


def show_in_folder(path):
    """Den Ordner mit der Datei öffnen und sie dort markieren (Dateimanager, der das kann, sonst nur den Ordner)."""
    if WINDOWS:
        subprocess.Popen(f'explorer /select,"{path}"')
        return
    if LINUX and which("dbus-send"):  # org.freedesktop.FileManager1: Nautilus, Dolphin, Nemo, Caja, Thunar …
        try:
            r = subprocess.run(["dbus-send", "--session", "--print-reply", "--dest=org.freedesktop.FileManager1",
                                "--type=method_call", "/org/freedesktop/FileManager1",
                                "org.freedesktop.FileManager1.ShowItems", f"array:string:{Path(path).resolve().as_uri()}",
                                "string:"], capture_output=True, stdin=DEVNULL, timeout=5)
            if r.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
    open_path(Path(path).parent)


def recycle(p: Path):
    """Datei/Ordner in den Papierkorb verschieben (dort wiederherstellbar)."""
    if WINDOWS:
        _recycle_windows(p)
        return
    gio = which("gio")
    if gio:
        try:
            r = subprocess.run([gio, "trash", "--", str(p)], capture_output=True, stdin=DEVNULL, timeout=300)
            if r.returncode == 0 and not os.path.lexists(p):
                return
        except (OSError, subprocess.SubprocessError):
            pass
    trash_home(p)


def _recycle_windows(p: Path):
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    # FO_DELETE; FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    op = SHFILEOPSTRUCTW(None, 3, str(p) + "\0", None, 0x40 | 0x10 | 0x4 | 0x400, False, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc or op.fAnyOperationsAborted:
        raise OSError(f"Konnte {p} nicht in den Papierkorb verschieben (Code {rc}).")


def trash_home(p: Path, base: Path | None = None):
    """Papierkorb nach freedesktop.org (~/.local/share/Trash) ohne gio: Datei nach files/, Herkunft und Zeit in
    info/<Name>.trashinfo – so stellen Dateimanager sie wieder her."""
    p = Path(os.path.abspath(p))
    if not os.path.lexists(p):
        raise FileNotFoundError(f"{p} gibt es nicht.")
    base = base or data_home() / "Trash"
    files, info = base / "files", base / "info"
    files.mkdir(parents=True, exist_ok=True)
    info.mkdir(parents=True, exist_ok=True)
    name, n = p.name, 1
    while True:  # Infodatei exklusiv anlegen: reserviert den Namen
        try:
            fd = os.open(info / f"{name}.trashinfo", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            if os.path.lexists(files / name):
                os.close(fd)
                (info / f"{name}.trashinfo").unlink()
                raise FileExistsError
            break
        except FileExistsError:
            n += 1
            name = f"{p.stem}.{n}{p.suffix}"
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"[Trash Info]\nPath={urllib.parse.quote(str(p))}\n"
                f"DeletionDate={datetime.now():%Y-%m-%dT%H:%M:%S}\n")
    try:
        shutil.move(str(p), str(files / name))
    except BaseException:
        (info / f"{name}.trashinfo").unlink(missing_ok=True)
        raise


def desktop_dir() -> Path:
    """Der Desktop-Ordner: unter Linux aus user-dirs.dirs (auf deutschen Systemen oft „Schreibtisch“)."""
    home = Path.home()
    if not WINDOWS:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
        try:
            for line in config.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "XDG_DESKTOP_DIR":
                    value = value.strip().strip('"').replace("$HOME", str(home))
                    if value and Path(value) != home:
                        return Path(value)
        except OSError:
            pass
    return home / "Desktop"


# ---------------------------------------------------------------- Schriften

def font_dirs() -> list[Path]:
    """Ordner mit installierten Schriften (für pdfsatz)."""
    if WINDOWS:
        return [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    home = Path.home()
    dirs = [Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "fonts", home / ".fonts",
            Path("/usr/local/share/fonts"), Path("/usr/share/fonts")]
    if MAC:
        dirs = [home / "Library" / "Fonts", Path("/Library/Fonts"), Path("/System/Library/Fonts")] + dirs
    return dirs


@functools.cache
def _font_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    for d in font_dirs():
        for root, _dirs, names in os.walk(d) if d.is_dir() else []:
            for name in names:
                index.setdefault(name.lower(), Path(root) / name)
    return index


def font_file(name: str) -> Path | None:
    """Schriftdatei nach Dateiname (z. B. „DejaVuSans.ttf“) – unter Linux auch in Unterordnern."""
    if WINDOWS:
        p = font_dirs()[0] / name
        return p if p.is_file() else None
    return _font_index().get(name.lower())
