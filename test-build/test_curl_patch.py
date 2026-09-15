import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("curl_patch", Path(__file__).with_name("patch-curl-includes.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CurlPatchTests(unittest.TestCase):
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
