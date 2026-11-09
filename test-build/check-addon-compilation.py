"""Compile the changed native paths with -Werror, independent of other mpv files."""
import json
from pathlib import Path
import shlex
import subprocess
import sys

build = Path(sys.argv[1]).resolve()
legacy = Path(sys.argv[2]).resolve()
required = {
    "video/filter/vf_animejanai.c", "video/filter/vf_ajn_sample.c",
    "video/filter/ajn_scene.c", "video/filter/ajn_sample_cuda.c",
    "video/filter/ajn_sample_gpu.c", "video/out/hwdec/hwdec_cuda.c",
    "common/ajn_mux.c",
}
found = set()
for entry in json.loads((build / "compile_commands.json").read_text()):
    source = entry["file"].replace("\\", "/")
    match = next((name for name in required if source.endswith("/" + name)), None)
    if not match or match in found:
        continue
    command = entry.get("arguments") or shlex.split(entry["command"])
    subprocess.run(command + ["-Werror", "-fsyntax-only"], cwd=entry["directory"], check=True)
    print("PASS -Werror", match, flush=True)
    if match == "common/ajn_mux.c":
        # Use real FFmpeg 6.1 headers, not a forced version macro paired with
        # a newer avio_alloc_context declaration.
        subprocess.run(command[:1] + ["-I" + legacy.as_posix()] + command[1:] +
                       ["-Werror", "-fsyntax-only"], cwd=entry["directory"], check=True)
        print("PASS -Werror lavf 60 callback", flush=True)
    found.add(match)
if missing := required - found:
    raise RuntimeError("Native compile coverage missing: " + repr(sorted(missing)))
