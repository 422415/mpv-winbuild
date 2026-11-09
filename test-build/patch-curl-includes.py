"""Apply the libssh include adjustment safely to fresh or restored curl sources."""
from pathlib import Path
import sys


def patch(source):
    header = source / "lib/vssh/ssh.h"
    text = header.read_text()
    include = "#include <libssh/libssh.h>\n"
    added = "#include <libssh/scp.h>\n"
    if text.count(include) != 1:
        raise RuntimeError("curl's libssh includes changed; review the compatibility patch")
    if added in text:
        if text.count(added) != 1:
            raise RuntimeError("curl has duplicate SCP includes")
        return
    header.write_text(text.replace(include, include + added))


if __name__ == "__main__":
    patch(Path(sys.argv[1]))
