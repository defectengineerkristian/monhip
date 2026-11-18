"""Hörbücher erzeugen: Qwen3-TTS (Apache-2.0) über audio.cpp (github.com/0xShug0/audio.cpp, Apache-2.0), MP3 mit
ffmpeg – Werkzeug hoerbuch_erstellen. Den Text liefert hoerbuchtext.py.

Einrichtung (plan/install, Einstellungen → Sprache): audio.cpp nach server/audiocpp-b<build>-<art>/ – unter Windows
mit CUDA, unter Linux mit Vulkan (sonst Prozessor, für ganze Bücher zu langsam). Den CUDA-Fassungen fehlen Laufzeit-
Bibliotheken: cudart und cuBLAS kommen von einem llama.cpp derselben CUDA-Hauptversion (liegt bei NVIDIA-Karten schon
da), cuFFT lädt Monhip offiziell von NVIDIA (redistrib-JSON mit Prüfsumme). Das Sprachmodell (je Stimme „VoiceDesign“
= Stimme nach Beschreibung oder „CustomVoice“ = feste Sprecher, je 2,8 GB) nach modelle/stimmen/Qwen3-TTS/, ffmpeg
(LGPL, mit libmp3lame) nach server/ffmpeg-b<version>-lgpl/ bzw. aus dem PATH.

Erzeugen (render): je Kapitel ein Aufruf von audiocpp_cli mit --batch-text-dir – das Modell lädt einmal je Kapitel,
jeder Abschnitt (einige Absätze) wird eine WAV-Datei, danach baut ffmpeg daraus mit kurzen Pausen eine MP3 mit
Titel, Album und Tracknummer. Fertige Kapitel bleiben liegen: Nach einem Abbruch geht es beim nächsten Mal mit dem
ersten fehlenden Kapitel weiter. Gemessen (RTX 5060 Ti): etwa 5-mal schneller als gesprochen, rund 3,5 GB
Grafikspeicher – ein 10-Stunden-Buch dauert gut 2 Stunden."""

from i18n import tr

import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
import wave
import zipfile
from pathlib import Path

import downloads
import engines
import llamacpp
import plattform
from backend import _end_with_app, library_dirs
from images import TEMP_DIR

SERVER_DIR = llamacpp.SERVER_DIR
MODEL_DIR = plattform.DATA_DIR / "modelle" / "stimmen" / "Qwen3-TTS"
RELEASES_URL = "https://api.github.com/repos/0xShug0/audio.cpp/releases?per_page=5"
FFMPEG_URL = "https://api.github.com/repos/FFmpeg-Builds/FFmpeg-Builds/releases/tags/latest"
NVIDIA_REDIST = "https://developer.download.nvidia.com/compute/cuda/redist/"
CUDA_REDIST = {13: "redistrib_13.4.3.json", 12: "redistrib_12.9.1.json"}  # cuFFT passend zur CUDA-Hauptversion
CUFFT_DLL = {13: "cufft64_12.dll", 12: "cufft64_11.dll"}
CUDA_DLLS = ("cudart64_{0}.dll", "cublas64_{0}.dll", "cublasLt64_{0}.dll")
HF_URL = "https://huggingface.co/audio-cpp/audio.cpp-gguf/resolve/main/{path}"
CLI_EXE = plattform.exe("audiocpp_cli")
FFMPEG_EXE = plattform.exe("ffmpeg")
_FOLDER_RE = re.compile(r"audiocpp-b(\d+)-(.+)$")     # server/audiocpp-b905-cuda13.3
_FFMPEG_RE = re.compile(r"ffmpeg-b(\d+)-(.+)$")       # server/ffmpeg-b900-lgpl
NEED_MIB = 4500              # Grafikspeicher fürs Sprachmodell (gemessen gut 3,5 GB) samt Reserve
SEGMENT_CHARS = 1500         # so viel Text je Abschnitt (eine WAV-Datei, Fortschritt in diesen Schritten)
PAUSE_SECONDS = 0.6          # Pause zwischen Abschnitten
SEED = 42                    # gleicher Startwert für alle Abschnitte: die Stimme bleibt möglichst gleich
LICENSE = tr('Qwen3-TTS und audio.cpp: Apache-2.0 – die Hörbücher dürfen auch kommerziell genutzt werden.')

MODELS = {  # Variante → Datei im Repository audio-cpp/audio.cpp-gguf, Größe, SHA-256
    "voicedesign": ("Qwen3-TTS-12Hz-1.7B-VoiceDesign-GGUF/qwen3-tts-12hz-1.7b-voicedesign-q8_0.gguf", 2817000064,
                    "b86e03d1d2077bbaed157ab7a7fc646c3e309e69afa52c5e1c86b622b4715057"),
    "customvoice": ("Qwen3-TTS-12Hz-1.7B-CustomVoice-GGUF/qwen3-tts-12hz-1.7b-customvoice-q8_0.gguf", 2817055200,
                    "c8ac3f94b6e73f137c0e7ecc9270bc8faec7a476ff799b87e48844d1d0987ac3"),
}
_DESIGN = {
    "de": {"erzaehler": "Eine warme, ruhige männliche Erzählerstimme, mittleres Alter, deutscher Muttersprachler, wie "
                        "in einem professionellen Hörbuch.",
           "erzaehlerin": "Eine klare, freundliche weibliche Erzählerstimme, etwa 35 Jahre, deutsche Muttersprachlerin, "
                          "ruhig und lebendig wie in einem Hörbuch."},
    "en": {"erzaehler": "A warm, calm male narrator voice, middle-aged, native English speaker, like in a professional "
                        "audiobook.",
           "erzaehlerin": "A clear, friendly female narrator voice, about 35 years old, native English speaker, calm "
                          "and lively like in an audiobook."},
}
VOICES = {  # Hörbuch-Stimme → Beschriftung, Variante, Sprecher bzw. Beschreibung (_DESIGN)
    "erzaehler": {"label": tr('Erzähler – warm und ruhig (Stimme nach Beschreibung)'), "variant": "voicedesign"},
    "erzaehlerin": {"label": tr('Erzählerin – klar und freundlich (Stimme nach Beschreibung)'),
                    "variant": "voicedesign"},
    "aiden": {"label": tr('Aiden – fester Sprecher, männlich'), "variant": "customvoice", "speaker": "aiden"},
    "ryan": {"label": tr('Ryan – fester Sprecher, männlich'), "variant": "customvoice", "speaker": "ryan"},
    "eric": {"label": tr('Eric – fester Sprecher, männlich'), "variant": "customvoice", "speaker": "eric"},
    "dylan": {"label": tr('Dylan – fester Sprecher, männlich'), "variant": "customvoice", "speaker": "dylan"},
    "serena": {"label": tr('Serena – feste Sprecherin, weiblich'), "variant": "customvoice", "speaker": "serena"},
    "vivian": {"label": tr('Vivian – feste Sprecherin, weiblich'), "variant": "customvoice", "speaker": "vivian"},
}
DEFAULT_VOICE = "erzaehler"
LANGUAGES = {"de": "German", "en": "English"}


class Cancelled(RuntimeError):
    """Abgebrochen („Stopp“)."""


def voice_key(name: str | None) -> str:
    return name if name in VOICES else DEFAULT_VOICE


# ---------------------------------------------------------------- Installiert?

def find_cli() -> Path | None:
    """audiocpp_cli – CUDA vor Vulkan vor Prozessor, neueste zuerst (nicht aus dem PATH)."""
    return engines.find_program(SERVER_DIR, _FOLDER_RE, CLI_EXE, kind=None, usable=_complete) if SERVER_DIR.is_dir() \
        else None


def _complete(exe: Path, kind: str) -> bool:
    """Eine CUDA-Fassung taugt nur mit ihren Laufzeit-Bibliotheken daneben."""
    major = cuda_major(kind)
    return not major or all((exe.parent / name).is_file() for name in _cuda_names(major))


def cuda_major(kind: str) -> int | None:
    m = re.match(r"cuda(\d+)", kind or "")
    return int(m.group(1)) if m else None


def _cuda_names(major: int) -> list[str]:
    return [n.format(major) for n in CUDA_DLLS] + [CUFFT_DLL.get(major, "")] if plattform.WINDOWS else []


def backend_of(exe: Path) -> str:
    m = _FOLDER_RE.match(exe.parent.name)
    kind = m.group(2) if m else ""
    return "cuda" if kind.startswith("cuda") else "vulkan" if kind.startswith("vulkan") else "cpu"


def model_path(voice: str) -> Path:
    return MODEL_DIR / Path(MODELS[VOICES[voice_key(voice)]["variant"]][0]).name


def find_ffmpeg() -> Path | None:
    exe = engines.find_program(SERVER_DIR, _FFMPEG_RE, FFMPEG_EXE, kind="lgpl") if SERVER_DIR.is_dir() else None
    if exe:
        return exe
    found = plattform.which("ffmpeg")
    return Path(found) if found else None


def ready(voice: str) -> bool:
    return bool(find_cli() and model_path(voice).is_file() and find_ffmpeg())


def describe(voice: str) -> str:
    """Stand für die Einstellungen."""
    exe = find_cli()
    if not exe:
        return tr('Noch nicht eingerichtet.')
    m = _FOLDER_RE.match(exe.parent.name)
    build = int(m.group(1)) if m else 0
    text = f"audio.cpp {build // 10000}.{build // 100 % 100}.{build % 100} ({engines.kind_label(m.group(2)) if m else '?'})"
    text += tr(' · Modell vorhanden') if model_path(voice).is_file() else tr(' · Modell fehlt noch')
    return text + ("" if find_ffmpeg() else tr(' · ffmpeg fehlt noch'))


# ---------------------------------------------------------------- Herunterladen

def _version(tag: str) -> int:
    nums = [int(x) for x in re.findall(r"\d+", tag)[:3]] + [0, 0, 0]
    return nums[0] * 10000 + nums[1] * 100 + nums[2]


def _pick(assets: dict, vendor: str, cuda) -> tuple[str, dict | None]:
    """Passende Fassung von audio.cpp: Windows – CUDA (höchstens die vom Treiber unterstützte), sonst Prozessor;
    Linux – Vulkan (NVIDIA, AMD, Intel), sonst Prozessor."""
    if plattform.WINDOWS:
        if vendor == "nvidia":
            found = sorted(((int(m.group(1)), int(m.group(2))), n) for n in assets
                           if (m := re.search(r"windows-x64-cuda(\d+)\.(\d+)\.zip$", n)))
            usable = [f for f in found if not cuda or f[0] <= tuple(cuda)[:2]]
            if usable:
                (major, minor), name = usable[-1]
                return f"cuda{major}.{minor}", assets[name]
        name = next((n for n in assets if n.endswith("windows-x64-cpu.zip")), None)
        return ("cpu", assets[name]) if name else ("", None)
    if platform.machine().lower() not in ("x86_64", "amd64"):
        return "", None
    if vendor in ("nvidia", "amd", "intel"):
        name = next((n for n in assets if n.endswith("ubuntu-x64-vulkan.tar.gz")), None)
        if name:
            return "vulkan", assets[name]
    name = next((n for n in assets if n.endswith("ubuntu-x64-cpu.tar.gz")), None)
    return ("cpu", assets[name]) if name else ("", None)


def _cuda_sources(major: int) -> tuple[list[Path], list[str]]:
    """cudart/cuBLAS derselben CUDA-Hauptversion aus einem installierten llama.cpp → (gefundene Dateien, fehlende)."""
    found, missing = [], []
    for pattern in CUDA_DLLS:
        name = pattern.format(major)
        hit = next(iter(sorted(SERVER_DIR.glob(f"llama-*/{name}"), reverse=True)), None) if SERVER_DIR.is_dir() else None
        (found.append(hit) if hit else missing.append(name))
    return found, missing


def _nvidia_archive(major: int, component: str) -> tuple[str, str, int, str]:
    """(Name, URL, Größe, SHA-256) eines NVIDIA-Archivs (Windows) aus dem redistrib-JSON."""
    info = downloads.get_json(NVIDIA_REDIST + CUDA_REDIST[major])[component]["windows-x86_64"]
    rel = info["relative_path"]
    return Path(rel).name, NVIDIA_REDIST + rel, int(info["size"]), info["sha256"]


def plan(voice: str) -> dict:
    """Was fürs Hörbuch fehlt (Netzwerk – im Thread): program = [(name, url, größe, sha)] von audio.cpp, nvidia =
    [(name, url, größe, sha)] (cuFFT, ggf. cudart/cuBLAS), copy = Bibliotheken aus llama.cpp, ffmpeg = Archiv oder
    None, weights = [(name, url, größe, ziel, sha)] des Sprachmodells, size = alles zusammen."""
    voice = voice_key(voice)
    exe = find_cli()
    p = {"program": [], "nvidia": [], "copy": [], "ffmpeg": None, "ffmpeg_target": None, "target": None, "tag": "",
         "kind": "", "gpu": ""}
    if not exe:
        vendor, gpu, cuda = llamacpp.detect_gpu()
        for rel in downloads.get_json(RELEASES_URL):
            if rel.get("draft") or rel.get("prerelease"):
                continue
            kind, asset = _pick({a["name"]: a for a in rel.get("assets", [])}, vendor, cuda)
            if asset:
                break
        else:
            raise RuntimeError(tr('Auf GitHub wurde keine passende Version von audio.cpp gefunden.'))
        p.update(tag=rel["tag_name"], kind=kind, gpu=gpu,
                 target=SERVER_DIR / f"audiocpp-b{_version(rel['tag_name'])}-{kind}",
                 program=[(asset["name"], asset["browser_download_url"], asset["size"], downloads.asset_sha256(asset))])
        major = cuda_major(kind)
        if major and plattform.WINDOWS:
            p["copy"], missing = _cuda_sources(major)
            p["nvidia"].append(_nvidia_archive(major, "libcufft"))
            if missing:  # kein llama.cpp mit dieser CUDA-Version: Laufzeit von NVIDIA
                p["nvidia"] += [_nvidia_archive(major, "cuda_cudart"), _nvidia_archive(major, "libcublas")]
    if not find_ffmpeg():
        rel = downloads.get_json(FFMPEG_URL)
        want = (r"ffmpeg-n(\d+)\.(\d+)-latest-win64-lgpl-[\d.]+\.zip$" if plattform.WINDOWS else
                r"ffmpeg-n(\d+)\.(\d+)-latest-linux(?:arm)?64-lgpl-[\d.]+\.tar\.xz$")
        arch = "linuxarm64" if platform.machine().lower() in ("aarch64", "arm64") else "linux64"
        found = sorted(((int(m.group(1)), int(m.group(2))), a) for a in rel.get("assets", [])
                       if (m := re.search(want, a["name"])) and (plattform.WINDOWS or f"-{arch}-" in a["name"]))
        if not found:
            raise RuntimeError(tr('ffmpeg wurde auf GitHub nicht gefunden – unter Linux: sudo apt install ffmpeg'))
        (major, minor), asset = found[-1]
        p["ffmpeg"] = (asset["name"], asset["browser_download_url"], asset["size"], downloads.asset_sha256(asset))
        p["ffmpeg_target"] = SERVER_DIR / f"ffmpeg-b{major * 100 + minor}-lgpl"
    path, size, sha = MODELS[VOICES[voice]["variant"]]
    dest = MODEL_DIR / Path(path).name
    p["weights"] = [] if dest.is_file() else [(dest.name, HF_URL.format(path=path), size, dest, sha)]
    p["size"] = (sum(x[2] for x in p["program"] + p["nvidia"]) + (p["ffmpeg"][2] if p["ffmpeg"] else 0)
                 + sum(x[2] for x in p["weights"]))
    return p


def install(p: dict, progress, cancel):
    """Lädt, was plan() aufzählt: audio.cpp (ältere Fassungen derselben Art fliegen raus), die CUDA-Bibliotheken
    dazu, ffmpeg und das Sprachmodell (über .part, mit Prüfsumme)."""
    total, done = p["size"], 0
    SERVER_DIR.mkdir(parents=True, exist_ok=True)
    if p["program"]:
        downloads.clean_leftovers(SERVER_DIR)
        done = downloads.install_zips(p["program"], p["target"], CLI_EXE, progress, cancel, done=done, total=total)
        try:
            for src in p["copy"]:
                shutil.copy2(src, p["target"] / src.name)
            for name, url, _size, sha in p["nvidia"]:
                done = _install_nvidia(url, sha, p["target"], progress, cancel, done, total)
        except BaseException:
            shutil.rmtree(p["target"], ignore_errors=True)  # ohne Bibliotheken taugt diese Fassung nicht
            raise
        downloads.remove_older(p["target"], _FOLDER_RE)
    if p["ffmpeg"]:
        done = downloads.install_zips([p["ffmpeg"]], p["ffmpeg_target"], FFMPEG_EXE, progress, cancel, done=done,
                                      total=total)
        _keep_only(p["ffmpeg_target"], {FFMPEG_EXE, "LICENSE.txt", "LICENSE"})
    for _name, url, _size, dest, sha in p["weights"]:
        done = downloads.fetch_one(url, dest, progress, cancel, done, total, sha256=sha)


def _install_nvidia(url: str, sha: str, target: Path, progress, cancel, done: int, total: int) -> int:
    """NVIDIA-Archiv laden (Prüfsumme) und nur seine DLLs (bin/…) neben audiocpp_cli legen."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="nvidia-", suffix=".zip", dir=TEMP_DIR)
    os.close(fd)
    archive = Path(name)
    try:
        done = downloads.download(url, archive, progress, cancel, done, total, sha256=sha)
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                base = info.filename.rsplit("/", 1)[-1]
                if "/bin/" in info.filename and base.lower().endswith(".dll"):
                    with z.open(info) as src, open(target / base, "wb") as dst:
                        shutil.copyfileobj(src, dst)
    finally:
        archive.unlink(missing_ok=True)
    return done


def _keep_only(folder: Path, names: set[str]):
    """Aus dem ffmpeg-Paket nur das Programm (und die Lizenz) behalten – ffplay, ffprobe und die Doku nicht."""
    for f in folder.iterdir():
        if f.name not in names:
            shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink(missing_ok=True)


# ---------------------------------------------------------------- Erzeugen

def segments(chapter: dict, max_chars: int = SEGMENT_CHARS) -> list[str]:
    """Kapitel → Abschnitte für die Stimme: der Titel für sich, dann Absätze zu höchstens max_chars gebündelt (ein
    überlanger Absatz wird an Satzenden geteilt)."""
    out = [chapter["title"].rstrip(".") + "."] if chapter.get("title") else []
    current = ""
    for p in chapter["paragraphs"]:
        pieces = [p] if len(p) <= max_chars else _split_sentences(p, max_chars)
        for piece in pieces:
            if current and len(current) + 1 + len(piece) > max_chars:
                out.append(current)
                current = ""
            current = f"{current}\n{piece}" if current else piece
    if current:
        out.append(current)
    return out


def _split_sentences(text: str, max_chars: int) -> list[str]:
    parts, current = [], ""
    for sentence in re.split(r"(?<=[.!?…])\s+", text):
        while len(sentence) > max_chars:  # ein Satz ohne Ende: an einem Leerzeichen kürzen
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            parts.append((current + " " + sentence[:cut]).strip())
            current, sentence = "", sentence[cut:].strip()
        if current and len(current) + 1 + len(sentence) > max_chars:
            parts.append(current)
            current = ""
        current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def file_name(number: int, title: str) -> str:
    """„03 – Die Reise.mp3“ – ohne Zeichen, die Windows in Dateinamen nicht erlaubt."""
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", title or "").strip(" .")
    clean = re.sub(r"\s+", " ", clean)[:80].rstrip(" .")
    return f"{number:02d} – {clean}.mp3" if clean else f"{number:02d}.mp3"


def _write_silence(path: Path, seconds: float, rate: int = 24000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))


def _wav_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 24000)
    except (OSError, wave.Error, EOFError):
        return 0.0


def _environment(exe: Path) -> dict:
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(exe.parent), env.get("PATH", "")])
    if not plattform.WINDOWS:
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            library_dirs(exe.parent) + [p for p in [env.get("LD_LIBRARY_PATH")] if p])
    return env


def voice_args(voice: str, language: str) -> list[str]:
    """Aufruf-Teil für die Stimme: feste Sprecher (CustomVoice) bzw. Stimme nach Beschreibung (VoiceDesign)."""
    v = VOICES[voice_key(voice)]
    if v["variant"] == "customvoice":
        return ["--task", "tts", "--speaker", v["speaker"], "--instruct",
                "Ruhig und erzählend, wie in einem Hörbuch." if language == "de" else "Calm narration, like an "
                                                                                     "audiobook."]
    design = _DESIGN.get(language, _DESIGN["en"])
    return ["--task", "vdes", "--instruct", design.get(voice_key(voice), design["erzaehler"])]


def render(book: dict, chosen: list[int], folder: Path, voice: str, language: str, stop: threading.Event,
           progress=None, log=None) -> dict:
    """Die gewählten Kapitel als MP3 nach folder (blockiert – im Thread). progress(erledigte Zeichen, alle Zeichen,
    Kapitelnummer, Titel). Schon vorhandene MP3s werden übersprungen. → {"files", "seconds", "skipped"}.
    Abbruch: Cancelled (fertige Kapitel bleiben)."""
    exe, ffmpeg, model = find_cli(), find_ffmpeg(), model_path(voice)
    if not exe or not ffmpeg or not model.is_file():
        raise RuntimeError(tr('Die Hörbuch-Stimme ist noch nicht eingerichtet (Einstellungen → Sprache).'))
    chapters = book["chapters"]
    folder.mkdir(parents=True, exist_ok=True)
    jobs = []
    for i in chosen:
        target = folder / file_name(i + 1, chapters[i]["title"])
        jobs.append((i, target, segments(chapters[i])))
    total = sum(len(s) for _, target, segs in jobs if not target.is_file() for s in segs) or 1
    done, files, skipped, seconds = 0, [], 0, 0.0
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="hoerbuch-", dir=TEMP_DIR))
    try:
        silence = work / "pause.wav"
        _write_silence(silence, PAUSE_SECONDS)
        for i, target, segs in jobs:
            if target.is_file():
                files.append(target)
                skipped += 1
                continue
            if stop.is_set():
                raise Cancelled(tr('Abgebrochen.'))
            title = chapters[i]["title"] or tr('Teil {0}', i + 1)
            src, out = work / f"k{i}", work / f"k{i}-wav"
            shutil.rmtree(src, ignore_errors=True)
            shutil.rmtree(out, ignore_errors=True)
            src.mkdir()
            out.mkdir()
            sizes = {}
            for n, text in enumerate(segs):
                (src / f"{n:04d}.txt").write_text(text, encoding="utf-8")
                sizes[f"{n:04d}"] = len(text)
            if progress:
                progress(done, total, i + 1, title)
            done = _speak(exe, model, voice, language, src, out, sizes, stop, done, total,
                          lambda d, t=title, nr=i + 1: progress(d, total, nr, t) if progress else None, log)
            wavs = [out / f"{n:04d}.wav" for n in range(len(segs))]
            seconds += sum(_wav_seconds(w) for w in wavs) + PAUSE_SECONDS * (len(wavs) - 1)
            _encode(ffmpeg, wavs, silence, target, title, book.get("title") or "", i + 1, len(chapters), stop)
            files.append(target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"files": files, "seconds": seconds, "skipped": skipped}


def _speak(exe: Path, model: Path, voice: str, language: str, src: Path, out: Path, sizes: dict, stop, done: int,
           total: int, on_progress, log) -> int:
    """Ein Kapitel: audiocpp_cli liest alle Abschnitte aus src und schreibt je eine WAV nach out."""
    args = [str(exe), "--family", "qwen3_tts", "--model", str(model), "--backend", backend_of(exe),
            "--language", LANGUAGES.get(language, "auto"), "--seed", str(SEED), *voice_args(voice, language),
            "--batch-text-dir", str(src), "--out-dir", str(out)]
    if log:
        log("> " + subprocess.list2cmdline(args[:9]) + " …\n")
    proc = plattform.popen(args, bound=True, env=_environment(exe), cwd=str(exe.parent), stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _end_with_app(proc)
    tail: list[str] = []

    def errors():  # stderr: CUDA-Meldungen usw. – nur die letzten Zeilen für eine Fehlermeldung
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace").strip()
            if line and "warmup complete" not in line:
                tail.append(line)
                del tail[:-8]

    threading.Thread(target=errors, daemon=True).start()
    state = {"done": done}

    def pump():
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            m = re.match(r"request_id=(\S+)", line)
            if m:
                state["done"] += sizes.get(m.group(1), 0)
                on_progress(state["done"])

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        while proc.poll() is None:
            if stop.is_set():
                proc.kill()
                proc.wait()
                raise Cancelled(tr('Abgebrochen.'))
            time.sleep(0.2)
        reader.join(5)
    finally:
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except OSError:
                pass
    missing = [k for k in sizes if not (out / f"{k}.wav").is_file()]
    if proc.returncode != 0 or missing:
        reason = next((t for t in reversed(tail) if re.search(r"error|fail|out of memory|cannot", t, re.I)),
                      tail[-1] if tail else "")
        raise RuntimeError(tr('Die Stimme ist abgebrochen (Code {0}): {1}', proc.returncode,
                              reason or tr('Details unter Einstellungen → Server-Log')))
    return state["done"]


def _encode(ffmpeg: Path, wavs: list[Path], silence: Path, target: Path, title: str, album: str, track: int,
            tracks: int, stop):
    """WAVs mit Pausen dazwischen → MP3 (mono, 96 kbit/s) mit Titel, Album und Tracknummer – erst als .part, damit
    ein Abbruch keine halbe Datei hinterlässt, die beim nächsten Mal als fertig gälte."""
    listing = wavs[0].parent / "liste.txt"
    entries = []
    for n, w in enumerate(wavs):
        if n:
            entries.append(silence)
        entries.append(w)
    quote = lambda p: p.as_posix().replace("'", "'\\''")  # noqa: E731 – Apostroph im Pfad (z. B. Benutzername)
    listing.write_text("".join(f"file '{quote(p)}'\n" for p in entries), encoding="utf-8")
    part = target.with_name(target.name + ".part")
    args = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c:a", "libmp3lame", "-b:a", "96k", "-ac", "1", "-metadata", f"title={title}",
            "-metadata", f"album={album or title}", "-metadata", "artist=Monhip", "-metadata", "genre=Hörbuch",
            "-metadata", f"track={track}/{tracks}", "-f", "mp3", str(part)]
    proc = plattform.popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        while proc.poll() is None:
            if stop.is_set():
                proc.kill()
                proc.wait()
                part.unlink(missing_ok=True)
                raise Cancelled(tr('Abgebrochen.'))
            time.sleep(0.1)
        err = proc.stderr.read().decode("utf-8", "replace").strip()
    finally:
        proc.stderr.close()
    if proc.returncode != 0 or not part.is_file():
        part.unlink(missing_ok=True)
        raise RuntimeError(tr('MP3 ließ sich nicht schreiben: {0}', err.splitlines()[-1] if err else proc.returncode))
    part.replace(target)
