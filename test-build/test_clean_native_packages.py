import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("cleaner", Path(__file__).with_name("clean-native-packages.py"))
cleaner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleaner)


class CleanupTests(unittest.TestCase):
    def test_stale_packages_removed_dependencies_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary) / "build64"
            names = ["mpv-x86_64-old", "mpv-dev-x86_64-old", "mpv-debug-x86_64-old", "mpv-prefix", "install", "packages"]
            for name in names:
                (build / name).mkdir(parents=True)
                (build / name / "retained.bin").write_bytes(b"data")
            cleaner.clean(build)
            self.assertEqual(sorted(p.name for p in build.iterdir()), ["install", "mpv-prefix", "packages"])
            for name in names[3:]:
                self.assertEqual((build / name / "retained.bin").read_bytes(), b"data")

    def test_wrong_root_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                cleaner.clean(temporary)


if __name__ == "__main__": unittest.main()
