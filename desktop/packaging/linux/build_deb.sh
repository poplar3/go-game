#!/usr/bin/env bash
# Упаковывает dist/GoTrainer (результат PyInstaller) в пакет .deb.
# Программа ставится в /opt/gotrainer, команда запуска — gotrainer, значок появляется в меню «Игры».
set -euo pipefail
VERSION="${1:-1.0.0}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/packaging/linux"
SRC="$ROOT/dist/GoTrainer"
[ -x "$SRC/GoTrainer" ] || { echo "Нет $SRC/GoTrainer — сначала соберите PyInstaller'ом"; exit 1; }

PKG="$ROOT/build/deb/gotrainer"
rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/opt" "$PKG/usr/bin" "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/512x512/apps" "$PKG/usr/share/doc/gotrainer"
cp -a "$SRC" "$PKG/opt/gotrainer"
ln -s /opt/gotrainer/GoTrainer "$PKG/usr/bin/gotrainer"
install -m 644 "$HERE/gotrainer.desktop" "$PKG/usr/share/applications/gotrainer.desktop"
install -m 644 "$ROOT/gogame/icon.png" "$PKG/usr/share/icons/hicolor/512x512/apps/gotrainer.png"
cat > "$PKG/usr/share/doc/gotrainer/copyright" <<'TXT'
Go Trainer (Го — тренер). KataGo скачивается отдельно из https://github.com/lightvector/KataGo (MIT).
Qt / PySide6: LGPLv3, https://www.qt.io/
TXT

SIZE=$(du -sk "$PKG" | cut -f1)
cat > "$PKG/DEBIAN/control" <<TXT
Package: gotrainer
Version: $VERSION
Section: games
Priority: optional
Architecture: amd64
Installed-Size: $SIZE
Depends: libc6 (>= 2.35), libgl1, libegl1, libfontconfig1, libxkbcommon0, libxkbcommon-x11-0, libdbus-1-3, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-xkb1
Recommends: ocl-icd-libopencl1
Maintainer: Go Trainer <gotrainer@users.noreply.github.com>
Homepage: https://github.com/poplar3/go-game
Description: Игра го с ботом KataGo и учебными задачами
 Партии с ботом на досках 9x9, 13x13 и 19x19, подсказки и объяснения ходов,
 разбор партии, курс задач и библиотека на 15 000+ задач на русском языке.
 Сильный бот KataGo скачивается из меню «Настройки → ИИ KataGo».
TXT
cat > "$PKG/DEBIAN/postinst" <<'TXT'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -f /usr/share/icons/hicolor || true
exit 0
TXT
cp "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"

mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/gotrainer_${VERSION}_amd64.deb"
dpkg-deb --root-owner-group --build -Zxz "$PKG" "$OUT"
echo "Готово: $OUT"
