#!/bin/sh
# Installs cleanCT for the current user: the app goes to ~/.local/share/cleanCT-app
# (never the data folder, which is ~/.local/share/cleanCT), a `cleanct` command in
# ~/.local/bin, and an application-menu entry.
set -e
src=$(cd "$(dirname "$0")" && pwd)
share="${XDG_DATA_HOME:-$HOME/.local/share}"
dst="$share/cleanCT-app"
rm -rf "$dst"
mkdir -p "$dst" "$HOME/.local/bin" "$share/applications"
cp -a "$src"/. "$dst"/
ln -sf "$dst/cleanCT" "$HOME/.local/bin/cleanct"
cat > "$share/applications/cleanct.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=cleanCT
Comment=Metal-base removal for micro-CT wood scans
Exec=$dst/cleanCT
Icon=$dst/app/icons/icon_256x256.png
Terminal=false
Categories=Science;
DESKTOP
echo "cleanCT installed to $dst (command: cleanct)"
