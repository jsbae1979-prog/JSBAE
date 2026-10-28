#!/usr/bin/env bash
set -euo pipefail
test "${GITHUB_ACTIONS:-}" = true && test "${RUNNER_OS:-}" = Windows
ROOT=$(cygpath -u "$RUNNER_TEMP")/newsflow-ffmpeg-candidate
PREFIX="$ROOT/prefix"
export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig:$PREFIX/share/pkgconfig"
export PKG_CONFIG_PATH="$PKG_CONFIG_LIBDIR"
export PATH="$PREFIX/bin:$PATH"
source_dir() { printf '%s\n' "$ROOT/src/$1"; }
FT=$(source_dir freetype); FB=$(source_dir fribidi); HB=$(source_dir harfbuzz)
ASS=$(source_dir libass); X264=$(source_dir x264); FF=$(source_dir ffmpeg)
pacman -Q > "$ROOT/evidence/toolchain-packages.txt"
gcc -v > "$ROOT/evidence/compiler.txt" 2>&1
meson --version > "$ROOT/evidence/meson-version.txt"
cmake --version > "$ROOT/evidence/cmake-version.txt"
export CFLAGS='-O2'
export CXXFLAGS='-O2'
ZLIB=$(source_dir zlib)
cmake -G Ninja -S "$ZLIB" -B "$ROOT/build/zlib" -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" -DZLIB_BUILD_EXAMPLES=OFF -DCMAKE_POLICY_VERSION_MINIMUM=3.5
cmake --build "$ROOT/build/zlib" --parallel 4
cmake --install "$ROOT/build/zlib"
if test -f "$PREFIX/lib/libzlibstatic.a"; then cp "$PREFIX/lib/libzlibstatic.a" "$PREFIX/lib/libz.a"; fi
cmake -G Ninja -S "$FT" -B "$ROOT/build/freetype" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" -DBUILD_SHARED_LIBS=OFF \
  -DFT_DISABLE_ZLIB=TRUE -DFT_DISABLE_BZIP2=TRUE -DFT_DISABLE_PNG=TRUE \
  -DFT_DISABLE_HARFBUZZ=TRUE -DFT_DISABLE_BROTLI=TRUE
cmake --build "$ROOT/build/freetype" --parallel 4
cmake --install "$ROOT/build/freetype"
meson setup "$ROOT/build/fribidi" "$FB" --prefix="$PREFIX" --libdir=lib \
  --buildtype=release --default-library=static --wrap-mode=nodownload -Ddocs=false -Dbin=false -Dtests=false
meson compile -C "$ROOT/build/fribidi" -j4
meson install -C "$ROOT/build/fribidi"
meson setup "$ROOT/build/harfbuzz" "$HB" --prefix="$PREFIX" --libdir=lib \
  --buildtype=release --default-library=static --wrap-mode=nodownload --auto-features=disabled \
  -Dtests=disabled -Ddocs=disabled -Dutilities=disabled -Dsubset=disabled \
  -Draster=disabled -Dvector=disabled -Dgpu=disabled -Dgpu_demo=disabled
meson compile -C "$ROOT/build/harfbuzz" -j4
meson install -C "$ROOT/build/harfbuzz"
meson setup "$ROOT/build/libass" "$ASS" --prefix="$PREFIX" --libdir=lib \
  --buildtype=release --default-library=static --wrap-mode=nodownload --auto-features=disabled \
  -Ddirectwrite=enabled -Dasm=enabled -Dfontconfig=disabled -Dlibunibreak=disabled
meson compile -C "$ROOT/build/libass" -j4
meson install -C "$ROOT/build/libass"
cd "$X264"
./configure --prefix="$PREFIX" --host=x86_64-w64-mingw32 --enable-static \
  --disable-cli --disable-opencl
make -j4
make install
cd "$FF"
./configure --prefix="$PREFIX" --pkg-config=pkg-config --pkg-config-flags=--static \
  --enable-gpl --enable-version3 --enable-static --disable-shared --disable-autodetect \
  --disable-network --disable-doc --disable-debug --disable-ffplay --enable-libx264 --enable-libass --enable-zlib \
  --disable-pthreads --enable-w32threads --extra-cflags="-I$PREFIX/include" \
  --extra-ldflags="-L$PREFIX/lib -static -static-libgcc -static-libstdc++"
make -j4
make install
cp ffbuild/config.log "$ROOT/evidence/ffmpeg-config.log"
cp config.h config_components.h "$ROOT/evidence/"
"$PREFIX/bin/ffmpeg.exe" -version > "$ROOT/evidence/ffmpeg-version.txt" 2>&1
"$PREFIX/bin/ffmpeg.exe" -buildconf > "$ROOT/evidence/ffmpeg-buildconf.txt" 2>&1
"$PREFIX/bin/ffmpeg.exe" -L > "$ROOT/evidence/ffmpeg-license.txt" 2>&1
objdump -p "$PREFIX/bin/ffmpeg.exe" | sed -n 's/.*DLL Name: //p' > "$ROOT/evidence/ffmpeg-imports.txt"
objdump -p "$PREFIX/bin/ffprobe.exe" | sed -n 's/.*DLL Name: //p' > "$ROOT/evidence/ffprobe-imports.txt"
mkdir -p "$ROOT/evidence/runtime-licenses"
find /ucrt64/share/licenses -maxdepth 3 -type f \( -iname '*copying*' -o -iname '*license*' \) \
  -print > "$ROOT/evidence/runtime-license-locations.txt"
# These are toolchain notices, not a claim that every tool is linked into FFmpeg.
find /ucrt64/share/licenses -maxdepth 3 -type f \( -iname '*copying*' -o -iname '*license*' \) \
  -exec cp --parents '{}' "$ROOT/evidence/runtime-licenses/" \;
