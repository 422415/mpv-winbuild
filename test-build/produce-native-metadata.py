"""Produce addon capability evidence alongside the native binaries, before packaging.

Called only for opted-in builds of the AJN native source contract. Consumers must
verify this record against the exact binaries; a marker is not a signature or a
claim that a GPU backend has passed its hardware tests.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def run(*args):
    return subprocess.check_output(args, text=True, encoding="utf-8", errors="strict").strip()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def produce(source, libass_source, build, binaries, output, linkage):
    source = source.resolve()
    contract = json.loads((source / "etc/ajn-native-capabilities.json").read_text())
    if contract.get("schemaVersion") != 1 or any(contract.get(k) != 1 for k in
            ("privateSampleAbi", "privatePlayerSampleAbi", "privateOutputAbi", "nullHardwareFramesOptIn")):
        raise ValueError("Unsupported native addon source contract")
    if not re.search(r"^#define AJN_SAMPLE_VERSION 1$",
                     (source / "video/filter/ajn_sample_shared.h").read_text(), re.M):
        raise ValueError("Sample source ABI does not match the declaration")
    configs = [p for p in build.rglob("config.h")
               if (p.parent / "meson-info/intro-projectinfo.json").is_file()
               and json.loads((p.parent / "meson-info/intro-projectinfo.json").read_text()).get("descriptive_name") == "mpv"]
    if len(configs) != 1:
        raise ValueError(f"Expected exactly one mpv build configuration, found {configs}")
    config = configs[0].read_text()
    features = sorted(re.findall(r"^#define HAVE_(\w+) 1$", config, re.M))
    if not set(contract["requiredFeatures"]).issubset(features):
        raise ValueError(f"Missing native features: {set(contract['requiredFeatures']) - set(features)}")
    files = {}
    for folder in binaries:
        for p in folder.rglob("*"):
            if p.is_file() and (p.name.lower().endswith(".dll") or p.name.lower() in ("mpv.exe", "mpv.com")):
                if p.name in files and digest(files[p.name]) != digest(p):
                    raise ValueError(f"Ambiguous native binary: {p.name}")
                files[p.name] = p
    if not {"mpv.exe", "libmpv-2.dll"}.issubset(files):
        raise ValueError("Both native player and libmpv are required")
    imports = {}
    for name, binary in files.items():
        pe = run("objdump", "-p", str(binary))
        if "pei-x86-64" not in pe:
            raise ValueError(f"Expected Windows x64 PE: {name}")
        imports[name] = sorted(set(n.lower() for n in re.findall(r"DLL Name:\s*(\S+)", pe)))
    consumer = "libmpv-2.dll" if linkage == "static" else next(
        (n for n in files if re.fullmatch(r"avformat-\d+\.dll", n)), "")
    if not consumer or not any(n == "ucrtbase.dll" or n.startswith("api-ms-win-crt-") for n in imports[consumer]):
        raise ValueError("FFmpeg descriptor consumer has no verified UCRT import")
    if "msvcrt.dll" in imports[consumer]:
        raise ValueError("Mixed CRT descriptor consumer is unsupported")
    external_ffmpeg = [n for n in imports["libmpv-2.dll"] if re.match(r"(?:avcodec|avformat|avutil)-\d+\.dll", n)]
    if (linkage == "static" and external_ffmpeg) or (linkage == "shared" and not external_ffmpeg):
        raise ValueError("Declared FFmpeg linkage differs from the PE imports")
    source_commit = run("git", "-C", str(source), "rev-parse", "HEAD")
    ass_commit = run("git", "-C", str(libass_source), "rev-parse", "HEAD")
    for name, actual in (("AJN_MPV_SHA", source_commit), ("AJN_LIBASS_SHA", ass_commit)):
        if os.environ.get(name) and os.environ[name] != actual:
            raise ValueError(f"Build used the wrong source revision: {name}")
    if run("git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Native addon metadata requires unmodified pinned mpv sources")
    metadata = {
        "schemaVersion": 1, "platform": "win-x64", "cRuntime": "ucrt", "ffmpegLinkage": linkage,
        **{k: contract[k] for k in ("privateSampleAbi", "privatePlayerSampleAbi", "privateOutputAbi", "nullHardwareFramesOptIn")},
        "sampleBackends": ["DirectML"], "sampleColor": "processed-sdr",
        "producer": {"repository": os.environ.get("GITHUB_REPOSITORY", "local"),
                     "commit": os.environ.get("GITHUB_SHA", "local"),
                     "runId": os.environ.get("GITHUB_RUN_ID", "local")},
        "sources": {"mpv": source_commit, "libass": ass_commit},
        "configurationSha256": digest(configs[0]), "features": features,
        "files": {n: digest(p) for n, p in sorted(files.items())}, "imports": imports,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--libass-source", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--binaries", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--linkage", choices=("static", "shared"), required=True)
    produce(**vars(parser.parse_args()))
