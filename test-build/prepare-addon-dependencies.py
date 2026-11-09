"""Adapt the pinned recipe after the upstream recipe patch series is applied."""
from pathlib import Path
import shutil


FONTCONFIG_REVISION = "b6cf4b270c42b13347a4012cdceb9bbc3d2e8f32"


def prepare(toolchain, script):
    # The addon host loads/unloads libmpv in-process. Match its tested lifetime
    # behavior when OpenSSL is statically linked into the production artifact.
    recipe = toolchain / "packages/openssl.cmake"
    text = recipe.read_text()
    if text.count("        no-shared\n") != 1:
        raise RuntimeError("OpenSSL recipe changed; review addon DLL unload configuration")
    recipe.write_text(text.replace("        no-shared\n", "        no-shared\n        no-pinshared\n"))
    recipe = toolchain / "packages/curl.cmake"
    text = recipe.read_text()
    # cd1edc11 has no patch command; do not assume a newer upstream recipe
    # which uses git-am (or a previous build's cached, edited CMake tree).
    command = 'PATCH_COMMAND ""'
    if text.count(command) != 1:
        raise RuntimeError("curl patch recipe changed; review addon dependency preparation")
    recipe.write_text(text.replace(command, f'PATCH_COMMAND ${{EXEC}} python "{script.resolve().as_posix()}" <SOURCE_DIR>'))
    # The pinned toolchain's patches no longer apply to fontconfig main. Use
    # shinchiro's bda10a2816ce9908d419b3f4b564227330457e76 rebase and the source
    # revision against which both patches were verified; leave production alone.
    recipe = toolchain / "packages/fontconfig.cmake"
    text = recipe.read_text()
    if text.count("GIT_TAG main") != 1:
        raise RuntimeError("fontconfig recipe changed; review addon dependency preparation")
    recipe.write_text(text.replace("GIT_TAG main", "GIT_TAG " + FONTCONFIG_REVISION))
    for name in ("fontconfig-0001-Custom-changes-for-mpv-builds.patch", "fontconfig-0002-Do-not-use-dirent.h.patch"):
        shutil.copyfile(Path(__file__).with_name(name), toolchain / "packages" / name)


if __name__ == "__main__":
    prepare(Path("mpv-winbuild-cmake"), Path("test-build/patch-curl-includes.py"))
