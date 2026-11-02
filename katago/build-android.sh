#!/usr/bin/env bash
# Сборка KataGo (CPU, бэкенд Eigen) под Android с помощью NDK.
# Использование: katago/build-android.sh <abi> <папка_результата>
#   abi: arm64-v8a | armeabi-v7a | x86_64
# Результат: <папка>/<abi>/libkatago.so — это исполняемая программа KataGo. Имя lib*.so нужно,
# чтобы Android распаковал её в папку нативных библиотек, откуда разрешён запуск программ.
set -euo pipefail
ABI="$1"
OUT="$(realpath -m "$2")"
KATAGO_VERSION="${KATAGO_VERSION:-v1.16.4}"
NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_LATEST_HOME:-}}"
EIGEN="${EIGEN3_INCLUDE_DIR:-/usr/include/eigen3}"
[ -d "$NDK" ] || { echo "Не найден Android NDK (ANDROID_NDK_HOME)"; exit 1; }
[ -d "$EIGEN/Eigen" ] || { echo "Не найдены заголовки Eigen ($EIGEN)"; exit 1; }

WORK="${WORK:-$PWD/build-katago}"
SRC="$WORK/KataGo"
mkdir -p "$WORK"
if [ ! -d "$SRC" ]; then
  git clone --depth 1 --branch "$KATAGO_VERSION" https://github.com/lightvector/KataGo "$SRC"
  # Eigen — библиотека только из заголовков: указываем путь напрямую, без поиска пакета
  sed -i "s|find_package(Eigen3 REQUIRED)|set(EIGEN3_INCLUDE_DIRS \"$EIGEN\")|" "$SRC/cpp/CMakeLists.txt"
fi

BUILD="$WORK/build-$ABI"
cmake -S "$SRC/cpp" -B "$BUILD" -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI="$ABI" \
  -DANDROID_PLATFORM=android-26 \
  -DANDROID_STL=c++_static \
  -DCMAKE_BUILD_TYPE=Release \
  -DUSE_BACKEND=EIGEN \
  -DNO_GIT_REVISION=1
cmake --build "$BUILD" --target katago -j"$(nproc)"

mkdir -p "$OUT/$ABI"
"$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip" -o "$OUT/$ABI/libkatago.so" "$BUILD/katago"
ls -la "$OUT/$ABI"
