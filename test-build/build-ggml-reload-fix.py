"""Replace the MSYS2 shared ggml base with the same version plus its unload fix.

Usage: python build-ggml-reload-fix.py <stock-dll> <native-prefix> <work-dir>
Only the optional Windows shared-runtime producer uses this; static production
builds do not acquire another dependency or any player-side workaround.
"""
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

VERSION = "0.28.0"
COMMIT = "facdc44a67da17df4433adcc468b424f48e9ded2"
ARCHIVE_SHA256 = "296a3533da2c6eaaac610008722572eb002a0f3b1aceb45b86a34f31ff4766c9"
URL = f"https://github.com/ggml-org/ggml/archive/refs/tags/v{VERSION}.tar.gz"


def build(stock, prefix, work):
    stock, prefix, work = (p.resolve() for p in (stock, prefix, work))
    here = Path(__file__).resolve().parent
    with os.add_dll_directory(str(stock.parent)):
        dependency = ctypes.CDLL(str(stock))
        dependency.ggml_version.restype = ctypes.c_char_p
        version = dependency.ggml_version().decode("ascii")
    if version != VERSION:
        raise RuntimeError(f"ggml {version} needs a matching reviewed source pin; expected {VERSION}")
    work.mkdir(parents=True, exist_ok=True)
    archive = work / f"ggml-v{VERSION}.tar.gz"
    if not archive.exists():
        urllib.request.urlretrieve(URL, archive)
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    if digest(archive) != ARCHIVE_SHA256:
        raise RuntimeError("ggml source archive checksum mismatch")
    source = work / f"ggml-{VERSION}"
    if source.exists():
        raise RuntimeError("Choose a fresh ggml work directory")
    with tarfile.open(archive) as bundle:
        bundle.extractall(work, filter="data")
    patch = here / "ggml-shared-terminate.patch"
    # Otherwise Git can discover the producer's parent checkout and silently
    # skip src/ggml.cpp as outside this subdirectory's path prefix.
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    # The Windows producer checkout can have CRLF; the source tarball has LF.
    subprocess.run(["git", "apply", "-"], input=patch.read_bytes().replace(b"\r\n", b"\n"),
                   cwd=source, check=True)
    output = work / "build"
    subprocess.run(["cmake", "-S", str(source), "-B", str(output), "-G", "Ninja",
                    "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=ON",
                    "-DGIT_EXE=OFF", f"-DGGML_BUILD_COMMIT={COMMIT}-shared-terminate-fix",
                    # Keep GCC's matching OpenMP runtime on the DLL link too;
                    # FindOpenMP can omit its implicit library on Windows.
                    "-DCMAKE_SHARED_LINKER_FLAGS=-fopenmp",
                    "-DCMAKE_DLL_NAME_WITH_SOVERSION=ON", "-DGGML_BACKEND_DL=ON",
                    "-DGGML_CPU=OFF", "-DGGML_OPENMP=ON", "-DGGML_NATIVE=OFF",
                    "-DGGML_CCACHE=OFF", "-DGGML_BUILD_EXAMPLES=OFF",
                    "-DGGML_BUILD_TESTS=OFF"], check=True)
    subprocess.run(["cmake", "--build", str(output), "--target", "ggml-base", "-j", "4"], check=True)
    fixed = next(output.rglob(stock.name))
    spec = importlib.util.spec_from_file_location("native_metadata", here / "produce-native-metadata.py")
    metadata = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metadata)
    missing = metadata.pe_exports(stock) - metadata.pe_exports(fixed)
    if missing:
        raise RuntimeError(f"Patched ggml is missing existing exports: {sorted(missing)}")
    (prefix / "bin").mkdir(parents=True, exist_ok=True)
    staged = prefix / "bin" / stock.name
    shutil.copy2(fixed, staged)
    test = work / "ggml-reload.exe"
    subprocess.run(["g++", "-Wall", "-Wextra", "-Werror", str(here / "ggml-reload.cpp"),
                    "-o", str(test)], check=True)
    subprocess.run([str(test), str(staged)], check=True)
    record = {"version": VERSION, "sourceCommit": COMMIT, "sourceUrl": URL,
              "sourceSha256": ARCHIVE_SHA256, "patchSha256": digest(patch),
              "originalDllSha256": digest(stock), "patchedDllSha256": digest(staged),
              "exportsPreserved": True, "applicationHandlerAndReloadTestPassed": True}
    (work / "ggml-reload.json").write_text(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    build(*(Path(arg) for arg in sys.argv[1:]))
