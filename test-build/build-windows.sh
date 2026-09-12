#!/usr/bin/env bash
# Build the pinned AJN player and libass with the MSYS2 UCRT64 toolchain.
set -euo pipefail

prefix="$(cygpath -m "$PWD/native-prefix")"
export PKG_CONFIG_PATH="$prefix/lib/pkgconfig"
export PATH="$PWD/native-prefix/bin:$PATH"

meson setup build-ass libass-source --prefix="$prefix" --buildtype=release \
    --default-library=shared --wrap-mode=nodownload \
    -Dthreads=enabled -Ddirectwrite=enabled -Dfontconfig=disabled \
    -Dlibunibreak=enabled -Dtest=disabled -Dcompare=disabled \
    -Dprofile=disabled -Dcheckasm=disabled
meson compile -C build-ass -j 4
meson install -C build-ass

meson setup build-mpv mpv-source --prefix="$prefix" --buildtype=release \
    --wrap-mode=nodownload -Dlibmpv=true -Dcplayer=true -Dtests=true \
    -Dlua=luajit -Djavascript=enabled -Dd3d11=enabled -Dvulkan=enabled \
    -Dmanpage-build=disabled -Dhtml-build=disabled \
    -Dpdf-build=disabled
meson compile -C build-mpv -j 4
meson install -C build-mpv

python test-build/stage-native.py "$prefix" "$(cygpath -m /ucrt64)" native-output
# Meson prepends dependency directories to PATH on Windows. That can select
# MSYS2's stock libass instead of the fork whose extra symbols mpv imports.
# Co-locate the final bundle's DLLs with each test executable so these tests
# exercise exactly the runtime dependencies being shipped.
python test-build/prepare-test-runtime.py
meson test -C build-mpv --print-errorlogs
pacman -Q > native-output/build-info/msys2-packages.txt
git -C mpv-source rev-parse HEAD > native-output/build-info/mpv-commit.txt
git -C libass-source rev-parse HEAD > native-output/build-info/libass-commit.txt
