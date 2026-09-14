"""Add a fail-closed evidence hook to a disposable copy of the upstream build script."""
from pathlib import Path

source = Path("build.sh").read_text()
needle = "    zip $bit $arch $x86_64_level\n"
if source.count(needle) != 1:
    raise RuntimeError("Upstream packaging changed; review the addon evidence hook")
hook = '''    python "$AJN_METADATA_TOOL" --source "$srcdir/mpv" --libass-source "$srcdir/libass" \\
        --build "$buildroot/build$bit" --binaries "$buildroot/build$bit"/mpv-* \\
        --output "$gitdir/release/mpv-addon-native-x86_64.json" --linkage static || exit 1
'''
Path("build-addons.sh").write_text(source.replace(needle, hook + needle))
