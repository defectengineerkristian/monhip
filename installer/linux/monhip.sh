#!/bin/sh
# Startet Monhip aus dem Linux-Paket (/usr/bin/monhip). Das Programm liegt schreibgeschützt in /opt/monhip,
# die Daten (config.json, modelle/, server/, chats/ …) im Benutzerordner.
export MONHIP_DATA="${MONHIP_DATA:-${XDG_DATA_HOME:-$HOME/.local/share}/monhip}"
exec /usr/bin/python3 /opt/monhip/Monhip.pyw "$@"
