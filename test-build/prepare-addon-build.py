"""Preserve the actual configuration before upstream cleanup, then emit evidence."""
from pathlib import Path


def prepare(script, toolchain):
    source = script.read_text()
    needle = "    zip $bit $arch $x86_64_level\n"
    if source.count(needle) != 1:
        raise RuntimeError("Upstream packaging changed; review the addon evidence hook")
    compile_step = "    ninja -C $buildroot/build$bit mpv\n"
    if source.count(compile_step) != 1:
        raise RuntimeError("Upstream compilation changed; review the addon build check")
    package = toolchain / "packages/mpv.cmake"
    cmake = package.read_text()
    cleanup = "cleanup(mpv copy-package-dir)"
    if cmake.count(cleanup) != 1:
        raise RuntimeError("Upstream mpv cleanup changed; review configuration preservation")
    saved = "${CMAKE_BINARY_DIR}/ajn-addon-configuration"
    capture = f'''ExternalProject_Add_Step(mpv save-addon-configuration
    DEPENDEES copy-package-dir
    COMMAND ${{CMAKE_COMMAND}} -E make_directory "{saved}/meson-info"
    COMMAND ${{CMAKE_COMMAND}} -E copy <BINARY_DIR>/config.h "{saved}/config.h"
    COMMAND ${{CMAKE_COMMAND}} -E copy <BINARY_DIR>/meson-info/intro-projectinfo.json "{saved}/meson-info/intro-projectinfo.json"
    COMMAND ${{CMAKE_COMMAND}} -E copy <BINARY_DIR>/meson-info/intro-buildoptions.json "{saved}/meson-info/intro-buildoptions.json"
    COMMENT "Preserving native addon build configuration before cleanup"
    LOG 1
)
cleanup(mpv save-addon-configuration)'''
    package.write_text(cmake.replace(cleanup, capture))
    hook = '''    python "$AJN_METADATA_TOOL" --source "$srcdir/mpv" --libass-source "$srcdir/libass" \\
        --build "$buildroot/build$bit/ajn-addon-configuration" --binaries "$buildroot/build$bit"/mpv-* \\
        --output "$gitdir/release/mpv-addon-native-x86_64.json" --linkage static || exit 1
'''
    # The compiler cache and target runtime cache are independent. A restored
    # clang executable does not establish that MinGW headers/CRT/libc++ exist.
    # This target is incremental when both caches are complete.
    runtime = '''    python "$(dirname "$AJN_METADATA_TOOL")/clean-native-packages.py" "$buildroot/build$bit" || exit 1
    if [ "$compiler" = "clang" ]; then
        ninja -C $buildroot/build$bit llvm-clang || exit 1
    fi
'''
    source = source.replace(compile_step, runtime + compile_step.rstrip("\n") + " || exit 1\n")
    script.with_name("build-addons.sh").write_text(source.replace(needle, hook + needle))


if __name__ == "__main__":
    prepare(Path("build.sh"), Path("mpv-winbuild-cmake"))
