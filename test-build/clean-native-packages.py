"""Remove restored final mpv packages without discarding dependency caches."""
from pathlib import Path
import re
import shutil
import sys


def clean(build):
    build = Path(build).resolve(strict=True)
    if not re.fullmatch(r"build(?:32|64(?:-v3)?|aarch64)", build.name):
        raise ValueError("Expected a named native build directory")
    for path in build.iterdir():
        if not re.fullmatch(r"mpv(?:-dev|-debug)?-(?:x86_64|i686|aarch64)(?:-v3)?-.+", path.name):
            continue
        if path.is_symlink() or path.resolve().parent != build:
            raise ValueError("Package path must remain inside the build directory")
        if path.is_dir():
            shutil.rmtree(path)


if __name__ == "__main__":
    clean(sys.argv[1])
