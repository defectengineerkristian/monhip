#!/bin/sh
# Baut das Debian/Ubuntu-Paket dist/monhip_<Version>_all.deb aus diesem Repository.
#
#   installer/linux/build-deb.sh
#
# Braucht nur python3 und dpkg-deb (auf jedem Debian/Ubuntu vorhanden), kein root.
# Maintainer im Paket: MONHIP_MAINTAINER, sonst DEBFULLNAME/DEBEMAIL, sonst git config user.name/user.email.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
OUT=${OUT:-"$REPO/dist"}

VERSION=$(sed -n 's/^VERSION = "\([^"]*\)".*/\1/p' "$REPO/app/monhip.py" | head -n 1)
[ -n "$VERSION" ] || { echo "VERSION in app/monhip.py nicht gefunden." >&2; exit 1; }

if [ -n "${MONHIP_MAINTAINER:-}" ]; then
    MAINTAINER=$MONHIP_MAINTAINER
elif [ -n "${DEBFULLNAME:-}" ] && [ -n "${DEBEMAIL:-}" ]; then
    MAINTAINER="$DEBFULLNAME <$DEBEMAIL>"
elif NAME=$(git -C "$REPO" config user.name) && MAIL=$(git -C "$REPO" config user.email); then
    MAINTAINER="$NAME <$MAIL>"
else
    echo "Kein Maintainer: MONHIP_MAINTAINER=\"Name <mail>\" setzen." >&2
    exit 1
fi

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/monhip_${VERSION}_all"

# ---- Programm: /opt/monhip (Monhip.pyw, app/*.py, Symbol, Icon-Schrift) – ohne Tests, Caches und Nutzerdaten
install -d -m 0755 "$ROOT/opt/monhip/app/fonts"
install -m 0644 "$REPO/Monhip.pyw" "$ROOT/opt/monhip/"
for f in "$REPO"/app/*.py "$REPO/app/monhip.ico"; do
    install -m 0644 "$f" "$ROOT/opt/monhip/app/"
done
for f in "$REPO"/app/fonts/*; do  # MonhipIcons.ttf (Symbole unter Linux) samt Lizenz
    install -m 0644 "$f" "$ROOT/opt/monhip/app/fonts/"
done

# ---- Starter, Desktop-Eintrag, Symbol (das 256er-PNG aus monhip.ico), Doku
install -D -m 0755 "$HERE/monhip.sh" "$ROOT/usr/bin/monhip"
install -D -m 0644 "$HERE/monhip.desktop" "$ROOT/usr/share/applications/monhip.desktop"
install -d -m 0755 "$ROOT/usr/share/icons/hicolor/256x256/apps"
python3 - "$REPO/app/monhip.ico" "$ROOT/usr/share/icons/hicolor/256x256/apps/monhip.png" <<'PY'
import struct, sys
data = open(sys.argv[1], "rb").read()
count = struct.unpack("<H", data[4:6])[0]
frames = [struct.unpack("<II", data[14 + 16 * i:22 + 16 * i]) for i in range(count)]
size, offset = max((f for f in frames if data[f[1]:f[1] + 4] == b"\x89PNG"), key=lambda f: f[0])
open(sys.argv[2], "wb").write(data[offset:offset + size])
PY
chmod 0644 "$ROOT/usr/share/icons/hicolor/256x256/apps/monhip.png"
install -D -m 0644 "$REPO/README.md" "$ROOT/usr/share/doc/monhip/README.md"

# ---- Steuerdateien
install -d -m 0755 "$ROOT/DEBIAN"
SIZE=$(du -sk --exclude=DEBIAN "$ROOT" | cut -f1)
MAINTAINER_SED=$(printf '%s' "$MAINTAINER" | sed 's/[&|\\]/\\&/g')  # & | \ im Namen wären sonst sed-Befehle
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" -e "s|@MAINTAINER@|$MAINTAINER_SED|" \
    "$HERE/debian/control" > "$ROOT/DEBIAN/control"
install -m 0755 "$HERE/debian/postinst" "$HERE/debian/prerm" "$ROOT/DEBIAN/"

mkdir -p "$OUT"
dpkg-deb --root-owner-group -Zxz --build "$ROOT" "$OUT/monhip_${VERSION}_all.deb" >/dev/null
echo "$OUT/monhip_${VERSION}_all.deb"
