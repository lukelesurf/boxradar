"""Stage 20's IPv4 preference in /etc/gai.conf.

adsb.lol's /0/me and re-api, and adsb.fi's /v2/snapshot, authorise by source
IP. Over IPv6 only the receiver itself matches; over IPv4 the whole LAN shares
one NATed address, so the home server can query them too. A rebuild lost this once
because it had only ever been set by hand.
"""

import os
import pathlib
import subprocess
import tempfile
import unittest

OS_SH = (pathlib.Path(__file__).resolve().parents[2]
         / "receiver-install" / "lib" / "os.sh")

# glibc discards its whole built-in table once any precedence line exists, so
# every row has to be restated, not just the IPv4-mapped one.
RFC6724_PREFIXES = ("::1/128", "::/0", "::ffff:0:0/96", "2002::/16",
                    "2001::/32", "fc00::/7", "::/96", "fec0::/10", "3ffe::/16")


def prefer_ipv4(path):
    result = subprocess.run(
        ["bash", "-c", f'set -euo pipefail; source "{OS_SH}"; gai_prefer_ipv4 "$1"',
         "_", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return path.read_text()


def precedence(text):
    rows = {}
    for line in text.splitlines():
        fields = line.split()
        if fields[:1] == ["precedence"]:
            rows.setdefault(fields[1], []).append(int(fields[2]))
    return rows


class GaiPreferIpv4Test(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = pathlib.Path(self.dir.name) / "gai.conf"

    def test_ipv4_mapped_outranks_everything(self):
        self.path.write_text("")
        rows = precedence(prefer_ipv4(self.path))
        top = max(v for vs in rows.values() for v in vs)
        self.assertEqual(rows["::ffff:0:0/96"], [top])
        self.assertGreater(top, rows["::/0"][0])

    def test_the_whole_table_is_restated(self):
        self.path.write_text("")
        self.assertEqual(set(precedence(prefer_ipv4(self.path))),
                         set(RFC6724_PREFIXES))

    def test_rerunning_does_not_duplicate(self):
        self.path.write_text("")
        prefer_ipv4(self.path)
        rows = precedence(prefer_ipv4(self.path))
        self.assertTrue(all(len(v) == 1 for v in rows.values()), rows)

    def test_existing_content_is_kept(self):
        self.path.write_text("# stock comment\nlabel ::1/128 0\n")
        text = prefer_ipv4(self.path)
        self.assertIn("# stock comment\n", text)
        self.assertIn("label ::1/128 0\n", text)

    def test_a_missing_file_is_created(self):
        self.assertIn("::ffff:0:0/96", precedence(prefer_ipv4(self.path)))


if __name__ == "__main__":
    unittest.main()
