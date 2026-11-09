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
            paths = re.search(r"(?m)^          path: ([^\n]+)", step[1])
            self.assertIsNotNone(paths, name)
            patterns.append(paths[1].strip())
        self.assertEqual(patterns[0], patterns[1])
        self.assertEqual(patterns[1], patterns[2])
        self.assertEqual(patterns[0], "${{ github.workspace }}/mpv-winbuild-cmake/build${{ matrix.bit }}")

    def test_addon_builds_do_not_reuse_production_build_keys(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/mpv.yml").read_text()
        self.assertIn("${{ inputs.addon_metadata && 'addon-' || '' }}${{ inputs.compiler }}-build", workflow)
        self.assertNotIn("success() || inputs.addon_metadata", workflow)

    def test_addon_builds_do_not_save_shared_dependency_caches(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/mpv.yml").read_text()
        for name in ("Save clang sysroot cache", "Save Sources Cache", "Save Rust Cache"):
            step = re.search(r"(?ms)^      - name: " + name + r"\n(.*?)(?=^      - name:|\Z)", workflow)
            self.assertIsNotNone(step, name)
            self.assertIn("inputs.addon_metadata != true", step[1])


if __name__ == "__main__": unittest.main()
