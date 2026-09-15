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
import struct
import subprocess


def run(*args):
    return subprocess.check_output(args, text=True, encoding="utf-8", errors="strict").strip()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pe_exports(path):
    """Read named exports from the PE table, independent of objdump's text format."""
    data = path.read_bytes()
    def uint(offset, fmt="<I"):
        if offset < 0 or offset + struct.calcsize(fmt) > len(data):
            raise ValueError("Truncated PE export table")
        return struct.unpack_from(fmt, data, offset)[0]
    if data[:2] != b"MZ":
        raise ValueError("Expected PE executable")
    pe = uint(0x3c)
    if data[pe:pe + 4] != b"PE\0\0" or uint(pe + 4, "<H") != 0x8664:
        raise ValueError("Expected Windows x64 PE")
    optional = pe + 24
    if uint(optional, "<H") != 0x20b or uint(pe + 20, "<H") < 120:
        raise ValueError("Expected PE32+ optional header")
    sections = optional + uint(pe + 20, "<H")
    def file_offset(rva):
        for index in range(uint(pe + 6, "<H")):
            section = sections + index * 40
            address, size, raw = uint(section + 12), uint(section + 16), uint(section + 20)
            if address <= rva < address + size:
                result = raw + rva - address
                if result < len(data):
                    return result
        raise ValueError("PE export points outside file-backed sections")
    rva = uint(optional + 112)
    if not rva:
        return set()
    table = file_offset(rva)
    count = uint(table + 24)
    if count > 65536:
        raise ValueError("Too many named PE exports")
    if not count:
        return set()
    names = file_offset(uint(table + 32))
    result = set()
    for index in range(count):
        start = file_offset(uint(names + index * 4))
        end = data.find(b"\0", start, min(start + 1024, len(data)))
        if end < 0:
            raise ValueError("Unterminated PE export name")
        result.add(data[start:end].decode("ascii"))
    return result


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
    options = {e["name"]: e["value"] for e in json.loads((configs[0].parent / "meson-info/intro-buildoptions.json").read_text())}
    for name, value in contract["requiredOptions"].items():
        if options.get(name) != value:
            raise ValueError(f"Required build option differs: {name}")
    files = {}
    for folder in binaries:
        for p in folder.rglob("*"):
            if p.is_file() and (p.name.lower().endswith(".dll") or p.name.lower() in ("mpv.exe", "mpv.com")):
                if p.name in files and digest(files[p.name]) != digest(p):
                    raise ValueError(f"Ambiguous native binary: {p.name}")
                files[p.name] = p
    if not {"mpv.exe", "libmpv-2.dll"}.issubset(files):
        raise ValueError("Both native player and libmpv are required")
    if len(files) > 256 or len({n.lower() for n in files}) != len(files):
        raise ValueError("Native dependency set is too large or has duplicate Windows filenames")
    if any(not re.fullmatch(r"[A-Za-z0-9._+-]{1,128}", n) for n in files):
        raise ValueError("Unsupported native filename")
    imports = {}
    probe_abi = contract.get("privateProbeAbi")
    mux_abi = contract.get("privateMuxAbi")
    subtitles_abi = contract.get("privateSubtitlesAbi")
    scene_abi = contract.get("privateSceneAbi")
    if scene_abi is not None and (scene_abi != 1 or not re.search(r"^#define AJN_SCENE_VERSION 1$",
            (source / "video/filter/ajn_scene_shared.h").read_text(), re.M) or
            '"scene-map"' not in (source / "video/filter/vf_animejanai.c").read_text()):
        raise ValueError("Unsupported native scene source contract")
    if subtitles_abi is not None and (subtitles_abi != 1 or not re.search(r"^#define AJN_SUBTITLES_VERSION 1$",
            (source / "common/ajn_subtitles.h").read_text(), re.M)):
        raise ValueError("Unsupported native subtitles source contract")
    if probe_abi is not None and (probe_abi != 1 or not re.search(r"^#define AJN_PROBE_VERSION 1$",
            (source / "common/ajn_probe.h").read_text(), re.M)):
        raise ValueError("Unsupported native probe source contract")
    if mux_abi is not None and (mux_abi != 1 or not re.search(r"^#define AJN_MUX_VERSION 1$",
            (source / "common/ajn_mux.h").read_text(), re.M)):
        raise ValueError("Unsupported native mux source contract")
    for name, binary in files.items():
        pe = run("objdump", "-p", str(binary))
        exports = pe_exports(binary) if name == "libmpv-2.dll" else set()
        if name == "libmpv-2.dll" and subtitles_abi is not None and "mpv_ajn_subtitles_v1" not in exports:
            raise ValueError("Missing native subtitles export")
        if name == "libmpv-2.dll" and probe_abi is not None:
            for symbol in ("mpv_ajn_probe_v1", "mpv_ajn_probe_free_v1"):
                if symbol not in exports:
                    raise ValueError("Missing native probe export: " + symbol)
        if name == "libmpv-2.dll" and mux_abi is not None and "mpv_ajn_mux_v1" not in exports:
            raise ValueError("Missing native mux export")
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
        "buildOptions": {n: options[n] for n in contract["requiredOptions"]},
        "files": {n: digest(p) for n, p in sorted(files.items())}, "imports": imports,
    }
    if probe_abi is not None:
        metadata["privateProbeAbi"] = probe_abi
    if mux_abi is not None:
        metadata["privateMuxAbi"] = mux_abi
    if subtitles_abi is not None:
        metadata["privateSubtitlesAbi"] = subtitles_abi
    if scene_abi is not None:
        metadata["privateSceneAbi"] = scene_abi
    encoded = (json.dumps(metadata, indent=2) + "\n").encode("utf-8")
    if len(encoded) > 1024 * 1024:
        raise ValueError("Native capability evidence exceeds the consumer's size limit")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--libass-source", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--binaries", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--linkage", choices=("static", "shared"), required=True)
    produce(**vars(parser.parse_args()))
