# Installers

Monhip has one code base for Windows and Linux; only the installers differ.

| Folder | Builds | Status |
| --- | --- | --- |
| [`linux/`](linux/) | Debian/Ubuntu package `monhip_<version>_all.deb` | ready; built for every release |
| [`windows/`](windows/) | `Monhip-Setup.exe` (C#/.NET) | sources not in the repository yet (see its README) |

## Shared contract

Both installers rely on the same few facts:

- **What to ship:** `Monhip.pyw`, every `app/*.py` and `app/monhip.ico` – nothing from `tests/`, no
  `__pycache__`, and never user data (`config.json`, `modelle/`, `server/`, `chats/`, `checkpoints/`,
  `raeume/`, `gedaechtnis.json`, `erinnerungen.json`).
- **Version:** `VERSION` in `app/monhip.py`; GitHub releases are tagged `v<VERSION>`.
- **Data that an update must keep:** `config.json`, `chats/`, `modelle/`, `server/`, `raeume/`,
  `checkpoints/`, `gedaechtnis.json`, `erinnerungen.json` (plus the installer's own files).
- **Data folder:** Monhip stores its data next to `Monhip.pyw` unless the environment variable
  `MONHIP_DATA` names another folder (`app/plattform.py`, `DATA_DIR`). An installer that puts the
  program into a write-protected location sets `MONHIP_DATA` to a per-user folder. On Linux, Monhip
  also falls back to `~/.local/share/monhip` by itself when its program folder is not writable.
- **Python:** 3.12 or newer with Tkinter. On Linux, Pillow is needed for images.
