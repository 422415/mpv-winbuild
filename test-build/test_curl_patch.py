import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("curl_patch", Path(__file__).with_name("patch-curl-includes.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CurlPatchTests(unittest.TestCase):
    def test_pinned_recipe_installs_the_include_adjustment(self):
        recipe_spec = importlib.util.spec_from_file_location("prepare", Path(__file__).with_name("prepare-addon-dependencies.py"))
        recipe_module = importlib.util.module_from_spec(recipe_spec)
        recipe_spec.loader.exec_module(recipe_module)
        with tempfile.TemporaryDirectory() as area:
            root = Path(area)
            recipe = root / "packages/curl.cmake"
            recipe.parent.mkdir()
            recipe.write_text('ExternalProject_Add(curl\n    PATCH_COMMAND ""\n    UPDATE_COMMAND ""\n)\n')
            fontconfig = recipe.with_name("fontconfig.cmake")
            fontconfig.write_text('ExternalProject_Add(fontconfig\n    GIT_TAG main\n)\n')
            openssl = recipe.with_name("openssl.cmake")
            openssl.write_text('ExternalProject_Add(openssl\n        no-shared\n)\n')
            recipe_module.prepare(root, Path(__file__).with_name("patch-curl-includes.py"))
            self.assertIn("no-shared\n        no-pinshared\n", openssl.read_text())
            self.assertIn('PATCH_COMMAND ${EXEC} python "', recipe.read_text())
            self.assertIn('UPDATE_COMMAND ""', recipe.read_text())
            self.assertIn('GIT_TAG ' + recipe_module.FONTCONFIG_REVISION, fontconfig.read_text())
            for patch in Path(__file__).parent.glob('fontconfig-*.patch'):
                self.assertEqual(patch.read_bytes(), (recipe.parent / patch.name).read_bytes())

    def test_fresh_and_cached_source_preserve_exactly_one_include(self):
        with tempfile.TemporaryDirectory() as area:
            root = Path(area)
            header = root / "lib/vssh/ssh.h"
            header.parent.mkdir(parents=True)
            original = "#define SSH_SUPPRESS_DEPRECATED\n#include <libssh/libssh.h>\n#include <libssh/sftp.h>\n"
            header.write_text(original)
            module.patch(root)
            expected = original.replace("#include <libssh/sftp.h>", "#include <libssh/scp.h>\n#include <libssh/sftp.h>")
            self.assertEqual(header.read_text(), expected)
            module.patch(root)
            self.assertEqual(header.read_text(), expected)
            header.write_text("changed recipe\n")
            with self.assertRaisesRegex(RuntimeError, "includes changed"):
                module.patch(root)
            self.assertEqual(header.read_text(), "changed recipe\n")


if __name__ == "__main__": unittest.main()
