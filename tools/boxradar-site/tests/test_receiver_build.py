"""The compiler the feedclient builds get.

adsbexchange/readsb (the fork all three feedclients build) is pinned at a 2024
commit that GCC 15's -Werror=unterminated-string-initialization rejects.
Ubuntu 26.04 ships GCC 15; Debian trixie ships 14, which has no such warning.
"""

import os
import pathlib
import subprocess
import tempfile
import unittest

BUILD_SH = (pathlib.Path(__file__).resolve().parents[2]
            / "receiver-install" / "lib" / "build.sh")
FLAG = "-Wno-error=unterminated-string-initialization"


def feedclient_cc(gcc_accepts_flag):
    with tempfile.TemporaryDirectory() as d:
        gcc = pathlib.Path(d) / "gcc"
        # Accepts the probe only when told to, the way GCC < 15 rejects a
        # -Wno-error= for a warning it does not have.
        gcc.write_text("#!/bin/sh\n"
                       f'case " $* " in *" {FLAG} "*) exit '
                       f'{0 if gcc_accepts_flag else 1};; esac\nexit 0\n')
        gcc.chmod(0o755)
        env = dict(os.environ, PATH=f"{d}:{os.environ['PATH']}")
        result = subprocess.run(
            ["bash", "-c", f'set -euo pipefail; source "{BUILD_SH}"; feedclient_cc'],
            env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        return result.stdout.strip()


class FeedclientCcTest(unittest.TestCase):
    def test_gcc_15_gets_the_warning_demoted(self):
        self.assertEqual(feedclient_cc(True), f"gcc {FLAG}")

    def test_older_gcc_is_left_alone(self):
        # Empty means "do not set CC": the build uses its own default.
        self.assertEqual(feedclient_cc(False), "")


if __name__ == "__main__":
    unittest.main()
