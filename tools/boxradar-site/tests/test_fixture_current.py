"""The committed C++ fixture must stay regenerable from the writer.

Without this, a format change would leave the C++ tests passing against a
stale fixture — green tests proving the reader can still parse a file the
writer no longer produces.
"""

import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[3]
FIXTURE = REPO / "test" / "test_geoblob" / "fixture_blob.h"


@unittest.skipUnless(FIXTURE.exists(), "fixture not generated yet")
class TestFixtureMatchesWriter(unittest.TestCase):
    def test_bytes_are_what_the_writer_produces_now(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "make_fixture",
            REPO / "tools" / "boxradar-site" / "tools_make_fixture.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        from boxradar_site.geo import blob
        expected = blob.write(module.HOME_LAT, module.HOME_LON,
                              module.SECTIONS)

        text = FIXTURE.read_text()
        declared = int(re.search(r"FIXTURE_LEN = (\d+)", text).group(1))
        committed = bytes(int(b, 16) for b in
                          re.findall(r"0x([0-9a-f]{2})", text))

        self.assertEqual(declared, len(expected),
                         "fixture length is stale — re-run "
                         "tools_make_fixture.py")
        self.assertEqual(committed, expected,
                         "fixture bytes are stale — re-run "
                         "tools_make_fixture.py")


if __name__ == "__main__":
    unittest.main()
