# Windows installer

The sources of the Windows installer are not in this repository yet – this folder is the place for
them, next to [`../linux/`](../linux/).

## Changes needed for the Linux port

The Windows program behaves as before. For the installer, only this matters:

- **New file `app/plattform.py`.** If the installer copies the whole `app/` folder (or `app/*.py`), nothing
  needs to change. If it lists files one by one, add `plattform.py` – without it, Monhip does not start.
- **`tests/` and `installer/` stay out** of the installation.
- **Data folder (optional):** Monhip still keeps its data next to `Monhip.pyw`. If the installer puts
  Monhip into a write-protected folder such as `C:\Program Files`, it can set the environment variable
  `MONHIP_DATA` (for example to `%LOCALAPPDATA%\Monhip`) in the shortcut or launcher. Without
  `MONHIP_DATA`, nothing changes on Windows.
- **Update check:** unchanged – still `VERSION` in `app/monhip.py` and the release tag `v<VERSION>`.
