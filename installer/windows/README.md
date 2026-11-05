# Windows installer

`Monhip-Setup.exe` installs, starts, updates and removes Monhip on Windows. It is a small C# program for
the .NET Framework 4.8 that every current Windows already has (WinForms, no other dependencies).

The sources in [`src/`](src/) were recovered from the previously published `Monhip-Setup.exe` with the
ILSpy decompiler. The rebuilt program matches the original: same methods, all 621 string literals
identical, same framework calls. Comments and the names of local variables did not survive compilation,
which is why many locals are called `text`, `text2`, …; [`app.manifest`](app.manifest) is the original.

## Build

```sh
dotnet build installer/windows/Monhip-Setup.csproj -c Release -p:Version=1.4.7
```

Works on Linux, macOS and Windows with the .NET SDK 8 or newer – the .NET Framework reference
assemblies come from NuGet. Result: `installer/windows/bin/Release/net48/Monhip-Setup.exe`. The icon is
`app/monhip.ico`.

For every published release, [`.github/workflows/windows-setup.yml`](../../.github/workflows/windows-setup.yml)
builds it with the release version and attaches `Monhip-Setup.exe` and its `.sha256` to the release.
Because the file name never changes, `https://github.com/defectengineerkristian/monhip/releases/latest/download/Monhip-Setup.exe`
always points to the newest installer.

## How it works

- **Install location:** `%LOCALAPPDATA%\Programs\Monhip` (option `--ziel`) – writable for the user, so
  Monhip keeps its data next to `Monhip.pyw`; `MONHIP_DATA` is not needed. The installer copies itself
  there as `Monhip.exe`, which then serves as starter (with update check), `--verwalten` and
  `--deinstallieren`.
- **Program files:** not part of the installer. It reads `releases/latest` of the repository (or the
  default branch), downloads the source ZIP of that commit from `codeload.github.com` (option `--quelle`
  accepts a local ZIP), checks for `Monhip.pyw` and `app/monhip.py` and swaps the top-level entries:
  the ones from the ZIP come in, the ones recorded in `installation.json` (`files`) from the previous
  version go out. Everything else – including all data Monhip creates itself – stays untouched, and
  names on the protection list (`Const.Protected`) are never replaced.
- **Components:** Python 3.13 from python.org if missing, llama.cpp (`bin-win-…`, CUDA/Vulkan/CPU by
  graphics card), optionally the Qwen3.8-27B model; shortcuts and the Apps entry.
- **Uninstall:** the user picks the parts to remove (program, chats, models, llama.cpp, memory, rooms,
  undo points, settings, backups, Python if the installer installed it).

## Changes compared to the recovered original

- `checkpoints` (Monhip's undo points, since v1.4) is on the protection list and can be removed when
  uninstalling. Before, a complete uninstall left the folder – and thus the installation folder –
  behind. Updates never touched it.
- Version information in the file properties now comes from the release (`-p:Version`).

`tests/test_installer.py` checks that every data name Monhip uses (`DATA_DIR / "…"` in `app/`) is on the
protection list, offered when uninstalling and ignored by Git.

## Open points

- **Code signing:** the installer is not signed, so SmartScreen warns on first start. A certificate
  could be used in the workflow (for example with Azure Trusted Signing).
- **Testing on Windows:** the rebuilt installer has been compared with the original but not yet run on
  Windows in this form.
- **Readability:** local variables could get meaningful names step by step.
