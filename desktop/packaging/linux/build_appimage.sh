#!/usr/bin/env bash
# Упаковывает dist/GoTrainer (результат PyInstaller) в один файл AppImage.
set -euo pipefail
VERSION="${1:-1.0.0}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/packaging/linux"
SRC="$ROOT/dist/GoTrainer"
[ -x "$SRC/GoTrainer" ] || { echo "Нет $SRC/GoTrainer — сначала соберите PyInstaller'ом"; exit 1; }

APPDIR="$ROOT/build/GoTrainer.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/512x512/apps"
cp -a "$SRC" "$APPDIR/usr/gotrainer"
cp "$HERE/gotrainer.desktop" "$APPDIR/gotrainer.desktop"
cp "$HERE/gotrainer.desktop" "$APPDIR/usr/share/applications/"
cp "$ROOT/gogame/icon.png" "$APPDIR/gotrainer.png"
cp "$ROOT/gogame/icon.png" "$APPDIR/usr/share/icons/hicolor/512x512/apps/gotrainer.png"
ln -s gotrainer.png "$APPDIR/.DirIcon"
cat > "$APPDIR/AppRun" <<'TXT'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/gotrainer/GoTrainer" "$@"
TXT
chmod 755 "$APPDIR/AppRun"

TOOL="${APPIMAGETOOL:-$ROOT/build/appimagetool-x86_64.AppImage}"
if [ ! -x "$TOOL" ]; then
  curl -fL --retry 3 -o "$TOOL" \
    https://github.com/AppImage/appimagetool/releases/download/1.9.0/appimagetool-x86_64.AppImage
  chmod +x "$TOOL"
fi
mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/GoTrainer-${VERSION}-x86_64.AppImage"
# --appimage-extract-and-run: работает и там, где нет FUSE (контейнеры, CI)
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUT"
echo "Готово: $OUT"
