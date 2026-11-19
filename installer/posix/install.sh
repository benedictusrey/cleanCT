#!/bin/sh
# Installs cleanCT for the current user: the app goes to ~/.local/share/cleanCT-app
# (never the data folder, which is ~/.local/share/cleanCT), a `cleanct` command in
# ~/.local/bin, and an application-menu entry. Run it from the extracted package.
set -e
src=$(cd "$(dirname "$0")" && pwd -P)
share="${XDG_DATA_HOME:-$HOME/.local/share}"
dst="$share/cleanCT-app"
if [ -d "$dst" ]; then
    # compare real paths: a trailing slash or a symlink must not hide the match
    real=$(cd "$dst" && pwd -P)
    case "$src/" in
        "$real/"*)
            echo "run install.sh from the extracted package folder, not from the installed copy" >&2
            exit 1 ;;
    esac
fi
rm -rf "$dst"
mkdir -p "$dst" "$HOME/.local/bin" "$share/applications"
cp -a "$src"/. "$dst"/
# a wrapper, not a symlink: the launcher finds its runtime from its own folder
echo '#!/bin/sh' > "$HOME/.local/bin/cleanct"
echo 'exec "'"$dst"'/cleanCT" "$@"' >> "$HOME/.local/bin/cleanct"
chmod 755 "$HOME/.local/bin/cleanct"
cat > "$share/applications/cleanct.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=cleanCT
Comment=Metal-base removal for micro-CT wood scans
Exec="$dst/cleanCT"
Icon=$dst/app/icons/icon_256x256.png
Terminal=false
Categories=Science;
DESKTOP
echo "cleanCT installed to $dst (command: cleanct)"
