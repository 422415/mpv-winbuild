"""Adapt the pinned recipe after the upstream recipe patch series is applied."""
from pathlib import Path


def prepare(toolchain, script):
    recipe = toolchain / "packages/curl.cmake"
    text = recipe.read_text()
    # cd1edc11 has no patch command; do not assume a newer upstream recipe
    # which uses git-am (or a previous build's cached, edited CMake tree).
    command = 'PATCH_COMMAND ""'
    if text.count(command) != 1:
        raise RuntimeError("curl patch recipe changed; review addon dependency preparation")
    recipe.write_text(text.replace(command, f'PATCH_COMMAND ${{EXEC}} python "{script.resolve().as_posix()}" <SOURCE_DIR>'))


if __name__ == "__main__":
    prepare(Path("mpv-winbuild-cmake"), Path("test-build/patch-curl-includes.py"))
