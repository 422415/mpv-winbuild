"""Cache lookup/restore must use the same path-derived version as save."""
from pathlib import Path
import re
import unittest


class BuildCacheTests(unittest.TestCase):
    def test_lookup_restore_and_save_share_path_patterns(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/mpv.yml").read_text()
        patterns = []
        for name in ("Lookup Build Cache", "Restore Build Cache", "Save Build Cache"):
            step = re.search(r"(?ms)^      - name: " + name + r"\n(.*?)(?=^      - name:|\Z)", workflow)
            self.assertIsNotNone(step, name)
            paths = re.search(r"(?m)^          path: \|\n((?:            [^\n]*\n)+)", step[1])
            self.assertIsNotNone(paths, name)
            patterns.append(tuple(line.strip() for line in paths[1].splitlines()))
        self.assertEqual(patterns[0], patterns[1])
        self.assertEqual(patterns[1], patterns[2])
        self.assertTrue(any(p.startswith("!") and p.endswith("/ajn-addon-configuration") for p in patterns[0]))


if __name__ == "__main__": unittest.main()
