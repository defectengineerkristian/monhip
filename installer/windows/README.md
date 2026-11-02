# Windows installer

The Windows installer is `Monhip-Setup.exe`, a small C# program for .NET Framework 4 (WinForms,
about 190 KB). Its sources are not in this repository yet – this folder is the place for them, next to
[`../linux/`](../linux/). What follows was read from the compiled program (disassembled, not run).

## How it works

- **Install location:** `%LOCALAPPDATA%\Programs\Monhip` – writable for the user, so Monhip keeps its
  data next to `Monhip.pyw` there. `MONHIP_DATA` is not needed on Windows.
- **Program files:** it does not ship Monhip itself. It reads `releases/latest` of
  `defectengineerkristian/monhip` (or the default branch), downloads the source ZIP from
  `codeload.github.com`, checks for `Monhip.pyw` and `app/monhip.py` and then replaces **every
  top-level entry** of the installation with the one from the ZIP – except the protected names below.
  Old entries that are neither in the ZIP nor protected are deleted.
- **Protected (never replaced or deleted):** `config.json`, `chats`, `modelle`, `server`, `raeume`,
  `sicherungen`, `gedaechtnis.json`, `erinnerungen.json`, `installation.json`, `_update`, `.git`,
  `Monhip.exe`, `Monhip-Setup.exe`.
- **Also:** installs Python 3.13 from python.org if needed, downloads llama.cpp (`bin-win-…`) and
  optionally the Qwen3.8-27B model, creates shortcuts and the Apps entry (`Monhip.exe --verwalten`,
  `--deinstallieren`), checks for updates.

## Effects of the Linux port

- **`app/plattform.py` comes along automatically**, because the whole `app/` folder is taken from the
  ZIP. Nothing to change.
- **New top-level folders** (`installer/`, `.github/`, `.gitignore`) are copied into the installation
  as well, like `tests/` already was. Harmless; the installer could skip everything except
  `Monhip.pyw`, `app/` and the documents.
- **Release files:** the installer uses the source ZIP of a release, not its attached files. The
  `.deb` that [the release workflow](../../.github/workflows/linux-deb.yml) attaches does not affect it.
- **Python:** the installer requires 3.13; the code itself runs on 3.12 and newer.

## Known issue

`checkpoints` (undo points for file changes, `app/checkpoints.py`, since v1.4) is **not protected**.
Every update therefore deletes the undo history. Fix in the installer sources: add `"checkpoints"` to
`Const.Protected`.
