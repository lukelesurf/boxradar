"""Preflight's architecture gate.

The gate exists to keep ARMv6/ARMv7 boards off — FR24's armhf binary SIGILLs
on ARMv6 — not to require a Pi. FR24 publishes amd64 in the same apt
component, so an x86_64 box must get past it.
"""

import os
import pathlib
import subprocess
import tempfile
import unittest

PREFLIGHT = (pathlib.Path(__file__).resolve().parents[2]
             / "receiver-install" / "stages" / "10-preflight.sh")


class ArchGateTest(unittest.TestCase):
    def run_as(self, machine):
        with tempfile.TemporaryDirectory() as d:
            uname = pathlib.Path(d) / "uname"
            uname.write_text(f"#!/bin/sh\necho {machine}\n")
            uname.chmod(0o755)
            env = dict(os.environ, PATH=f"{d}:{os.environ['PATH']}")
            return subprocess.run(["bash", str(PREFLIGHT)], env=env,
                                  capture_output=True, text=True, timeout=60)

    def test_x86_64_passes_the_arch_gate(self):
        # Later checks (SDR, disk) may still fail on the test host; only the
        # arch refusal matters here.
        self.assertNotIn("architecture is", self.run_as("x86_64").stderr)

    def test_aarch64_passes_the_arch_gate(self):
        self.assertNotIn("architecture is", self.run_as("aarch64").stderr)

    def test_armv7l_is_refused(self):
        result = self.run_as("armv7l")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("architecture is armv7l", result.stderr)

    def test_armv6l_is_refused(self):
        self.assertIn("architecture is armv6l", self.run_as("armv6l").stderr)


if __name__ == "__main__":
    unittest.main()
