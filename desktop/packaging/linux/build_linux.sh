#!/usr/bin/env bash
# Сборка игры для Linux: программа без Python (PyInstaller), пакет .deb и AppImage.
#   packaging/linux/build_linux.sh [версия]
# Готовые файлы появятся в папке dist/: gotrainer_<версия>_amd64.deb и GoTrainer-<версия>-x86_64.AppImage.
# Нужны: python3 (3.10+), dpkg-deb; для AppImage скрипт сам скачает appimagetool.
# Перед сборкой поставьте библиотеки Qt для X11, чтобы они попали внутрь AppImage
# (собирайте на Ubuntu 22.04, тогда программа пойдёт и на более новых системах):
#   sudo apt install python3-venv libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 \
#        libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xkb1 libxcb-shape0 libxcb-randr0 desktop-file-utils
set -euo pipefail
VERSION="${1:-${VERSION:-1.0.0}}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
if [ -z "${NO_VENV:-}" ]; then
  [ -d .venv-build ] || "$PY" -m venv .venv-build
  PY=.venv-build/bin/python
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q -r requirements.txt pyinstaller
fi

rm -rf build/GoTrainer dist/GoTrainer
"$PY" -m PyInstaller --noconfirm --clean packaging/gotrainer.spec
packaging/linux/build_deb.sh "$VERSION"
packaging/linux/build_appimage.sh "$VERSION"
ls -la dist/*.deb dist/*.AppImage
