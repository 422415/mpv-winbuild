"""Include the lazy-loaded RIFE detector in ordinary x64 GPL packages."""
from pathlib import Path
import sys


def prepare(package):
    source = package.read_text()
    option = "-Dlibmpv=true"
    copy_step = '    COMMENT "Copying mpv binaries and manual"'
    if source.count(option) != 1 or source.count(copy_step) != 1:
        raise RuntimeError("mpv recipe changed; review RIFE detector packaging")
    commands = []
    for destination in ("mpv-package", "mpv-dev"):
        root = "${CMAKE_CURRENT_BINARY_DIR}/" + destination
        commands.append(f'    COMMAND ${{CMAKE_COMMAND}} -E copy <BINARY_DIR>/video/filter/mvtools/ajn-mvtools.dll "{root}/ajn-mvtools.dll"')
        commands.append(f'    COMMAND ${{CMAKE_COMMAND}} -E make_directory "{root}/licenses/mvtools"')
        for name in ("LICENSE", "UPSTREAM.md"):
            commands.append(f'    COMMAND ${{CMAKE_COMMAND}} -E copy <SOURCE_DIR>/video/filter/mvtools/{name} "{root}/licenses/mvtools/{name}"')
    package.write_text(source.replace(option, option + " -Dajn-mvtools=true")
                       .replace(copy_step, "\n".join(commands) + "\n" + copy_step))


if __name__ == "__main__":
    prepare(Path(sys.argv[1]))
