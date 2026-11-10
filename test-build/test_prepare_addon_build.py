"""Exercise evidence retention through a real ExternalProject cleanup sequence."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("prepare", Path(__file__).with_name("prepare-addon-build.py"))
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)

spec = importlib.util.spec_from_file_location("rife", Path(__file__).with_name("prepare-rife-build.py"))
rife = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rife)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.script = self.root / "build.sh"
        self.script.write_text("package() {\n    build $bit $arch\n    zip $bit $arch $x86_64_level\n}\nbuild() {\n    ninja -C $buildroot/build$bit mpv\n}\n")
        self.toolchain = self.root / "toolchain"
        (self.toolchain / "packages").mkdir(parents=True)
        self.package = self.toolchain / "packages/mpv.cmake"

    def test_configuration_survives_actual_cmake_cleanup(self):
        cmake, ninja = shutil.which("cmake"), shutil.which("ninja")
        self.assertIsNotNone(cmake, "Install CMake to exercise the real cleanup sequence")
        self.assertIsNotNone(ninja, "Install Ninja to exercise the real cleanup sequence")
        fixture = self.toolchain / "fixture"
        (fixture / "meson-info").mkdir(parents=True)
        (fixture / "video/filter/mvtools").mkdir(parents=True)
        (fixture / "video/filter/mvtools/ajn-mvtools.dll").write_bytes(b"detector fixture")
        (fixture / "config.h").write_text("#define HAVE_D3D11 1\n")
        (fixture / "meson-info/intro-projectinfo.json").write_text(json.dumps({"descriptive_name": "mpv"}))
        (fixture / "meson-info/intro-buildoptions.json").write_text(json.dumps([{"name": "libmpv", "value": True}]))
        (self.toolchain / "CMakeLists.txt").write_text('''cmake_minimum_required(VERSION 3.20)
project(RecordedConfiguration NONE)
include(ExternalProject)
function(cleanup name last_step)
    ExternalProject_Add_Step(${name} postremovebuild
        DEPENDEES ${last_step}
        COMMAND ${CMAKE_COMMAND} -E rm -rf <BINARY_DIR>)
endfunction()
include(packages/mpv.cmake)
''')
        self.package.write_text('''set(mpv_options -Dlibmpv=true)
ExternalProject_Add(mpv
    SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/fixture"
    DOWNLOAD_COMMAND ""
    UPDATE_COMMAND ""
    CONFIGURE_COMMAND ${CMAKE_COMMAND} -E copy_directory <SOURCE_DIR> <BINARY_DIR>
    BUILD_COMMAND ${CMAKE_COMMAND} -E true
    INSTALL_COMMAND ${CMAKE_COMMAND} -E true)
ExternalProject_Add_Step(mpv copy-package-dir DEPENDEES install COMMAND ${CMAKE_COMMAND} -E true)
cleanup(mpv copy-package-dir)
''')
        prepare.prepare(self.script, self.toolchain)
        build = self.root / "build"
        for command in ([cmake, "-S", str(self.toolchain), "-B", str(build), "-G", "Ninja", "-DCMAKE_MAKE_PROGRAM=" + ninja],
                        [cmake, "--build", str(build)]):
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((build / "mpv-prefix/src/mpv-build").exists())
        saved = build / "ajn-addon-configuration"
        for file in fixture.rglob("*"):
            if file.is_file():
                name = file.name if file.suffix == ".dll" else file.relative_to(fixture)
                self.assertEqual((saved / name).read_bytes(), file.read_bytes())
        self.assertIn("-Dajn-mvtools=true", self.package.read_text())
        self.assertIn('--build "$buildroot/build$bit/ajn-addon-configuration"', self.script.with_name("build-addons.sh").read_text())
        self.assertIn('ninja -C $buildroot/build$bit mpv || exit 1', self.script.with_name("build-addons.sh").read_text())

    def test_changed_cleanup_is_rejected_before_build(self):
        self.package.write_text("cleanup(mpv new-step)\n")
        with self.assertRaisesRegex(RuntimeError, "cleanup changed"):
            prepare.prepare(self.script, self.toolchain)
        self.assertFalse(self.script.with_name("build-addons.sh").exists())

    def test_ordinary_rife_package_contains_detector_and_licenses(self):
        fixture = self.toolchain / "fixture"
        source = fixture / "video/filter/mvtools"
        source.mkdir(parents=True)
        for name in ("ajn-mvtools.dll", "LICENSE", "UPSTREAM.md"):
            (source / name).write_text("fixture " + name)
        (self.toolchain / "CMakeLists.txt").write_text('''cmake_minimum_required(VERSION 3.20)
project(RifePackage NONE)
include(ExternalProject)
include(packages/mpv.cmake)
''')
        self.package.write_text('''set(mpv_options -Dlibmpv=true)
ExternalProject_Add(mpv
    SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/fixture"
    DOWNLOAD_COMMAND "" UPDATE_COMMAND ""
    CONFIGURE_COMMAND ${CMAKE_COMMAND} -E copy_directory <SOURCE_DIR> <BINARY_DIR>
    BUILD_COMMAND ${CMAKE_COMMAND} -E true
    INSTALL_COMMAND ${CMAKE_COMMAND} -E true)
ExternalProject_Add_Step(mpv copy-binary
    DEPENDEES install
    COMMENT "Copying mpv binaries and manual")
ExternalProject_Add_Step(mpv cleanup
    DEPENDEES copy-binary
    COMMAND ${CMAKE_COMMAND} -E rm -rf <BINARY_DIR>)
''')
        rife.prepare(self.package)
        cmake, ninja = shutil.which("cmake"), shutil.which("ninja")
        self.assertIsNotNone(cmake)
        self.assertIsNotNone(ninja)
        build = self.root / "build"
        for command in ([cmake, "-S", str(self.toolchain), "-B", str(build), "-G", "Ninja", "-DCMAKE_MAKE_PROGRAM=" + ninja],
                        [cmake, "--build", str(build)]):
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for package in ("mpv-package", "mpv-dev"):
            for name in ("ajn-mvtools.dll", "LICENSE", "UPSTREAM.md"):
                relative = name if name.endswith(".dll") else "licenses/mvtools/" + name
                self.assertEqual((build / package / relative).read_bytes(), (source / name).read_bytes())
        self.assertIn("-Dajn-mvtools=true", self.package.read_text())


if __name__ == "__main__":
    unittest.main()
