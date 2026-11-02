# Linux package (.deb)

Builds a Debian/Ubuntu package from this repository. It needs only `python3` and `dpkg-deb`, no root
rights and no extra tools.

```sh
installer/linux/build-deb.sh
```

The package ends up in `dist/monhip_<version>_all.deb` (set `OUT=…` for another folder). The maintainer
field comes from `MONHIP_MAINTAINER="Name <mail>"`, otherwise from `DEBFULLNAME`/`DEBEMAIL` or
`git config user.name`/`user.email`.

Install it with apt, so the dependencies come along:

```sh
sudo apt install ./dist/monhip_1.4.6_all.deb
```

## What gets installed

| Path | Contents |
| --- | --- |
| `/opt/monhip/` | `Monhip.pyw` and `app/` (write-protected; `postinst` byte-compiles `app/`) |
| `/usr/bin/monhip` | starter ([`monhip.sh`](monhip.sh)): sets `MONHIP_DATA` and runs `/usr/bin/python3` |
| `/usr/share/applications/monhip.desktop` | menu entry ([`monhip.desktop`](monhip.desktop)) |
| `/usr/share/icons/hicolor/256x256/apps/monhip.png` | icon, taken from the PNG inside `app/monhip.ico` |
| `/usr/share/doc/monhip/README.md` | the project README |

User data lives in `~/.local/share/monhip` (or `$XDG_DATA_HOME/monhip`): settings, models, the
downloaded llama.cpp, chats. Removing or purging the package leaves it untouched.

## Dependencies

Declared in [`debian/control`](debian/control):

- **Depends:** `python3 (>= 3.12)`, `python3-tk`, `python3-pil`, `xdg-utils` – Ubuntu 24.04 or newer,
  Debian 13 or newer.
- **Recommends** (installed by default): `poppler-utils` (scanned PDFs in expert mode),
  `libnotify-bin` (reminders), `xclip` and `wl-clipboard` (clipboard on X11 and Wayland), `tkdnd`
  (drag & drop), `pipewire-bin` or `pulseaudio-utils` or `alsa-utils` (microphone).
- **Suggests:** a screenshot program for Wayland desktops other than GNOME/KDE.

whisper.cpp has no package in Debian/Ubuntu yet; for speech recognition, users install `whisper-cli`
themselves (see the main README).

## Releases

[`.github/workflows/linux-deb.yml`](../../.github/workflows/linux-deb.yml) runs for every published
release: it checks that the tag is `v` + `VERSION` from `app/monhip.py`, runs the tests, builds the
package, installs and starts it on Ubuntu 24.04 and attaches `monhip_<version>_all.deb` and its
`.sha256` to the release. The maintainer field comes from the repository variable
`MONHIP_MAINTAINER` (Settings → Secrets and variables → Actions → Variables), otherwise from the
owner's GitHub noreply address. For a release that already exists: Actions → “Linux-Paket (.deb)” →
Run workflow → enter the tag. Releases before this workflow existed contain no
`installer/linux/` and are rejected with a clear message.

## Checked so far

On Ubuntu 24.04 (container, virtual display): build, `apt install` with all recommended packages,
start with an empty home folder (data appears in `~/.local/share/monhip`, window class `Monhip`
matches `StartupWMClass`), reinstall/upgrade, remove and purge (nothing left in `/opt`).
`tests/test_installer.py` builds the package and checks its contents and metadata.

## Open points

- **License:** the repository has no license file yet. Debian packages normally ship
  `/usr/share/doc/monhip/copyright`; `lintian` will flag its absence.
- **Further formats:** an RPM (Fedora/openSUSE) and an AppImage or Flatpak for other distributions can
  reuse `monhip.sh`, `monhip.desktop` and the icon. An AppStream file (`metainfo.xml`) would make
  Monhip show up nicely in software centers.
