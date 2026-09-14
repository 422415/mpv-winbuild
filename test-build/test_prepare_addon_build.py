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
        self.package.write_text('''ExternalProject_Add(mpv
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
                self.assertEqual((saved / file.relative_to(fixture)).read_bytes(), file.read_bytes())
        self.assertIn('--build "$buildroot/build$bit/ajn-addon-configuration"', self.script.with_name("build-addons.sh").read_text())
        self.assertIn('ninja -C $buildroot/build$bit mpv || exit 1', self.script.with_name("build-addons.sh").read_text())

    def test_changed_cleanup_is_rejected_before_build(self):
        self.package.write_text("cleanup(mpv new-step)\n")
        with self.assertRaisesRegex(RuntimeError, "cleanup changed"):
            prepare.prepare(self.script, self.toolchain)
        self.assertFalse(self.script.with_name("build-addons.sh").exists())


if __name__ == "__main__":
    unittest.main()
