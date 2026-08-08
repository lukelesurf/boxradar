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
CONTACT_FIXTURE = REPO / "test" / "test_contact_feed" / "fixture_contacts.h"


def load_script(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        name, REPO / "tools" / "boxradar-site" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def committed_bytes(path):
    text = path.read_text()
    declared = int(re.search(r"_LEN = (\d+)", text).group(1))
    data = bytes(int(b, 16) for b in re.findall(r"0x([0-9a-f]{2})", text))
    return declared, data


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


@unittest.skipUnless(CONTACT_FIXTURE.exists(), "fixture not generated yet")
class TestContactFixtureMatchesWriter(unittest.TestCase):
    """The contact feed's C++ reader is only cross-checked by this fixture.

    If it goes stale the boundary test in test/test_contact_feed still passes,
    against bytes the writer no longer produces — which is exactly the
    disagreement it exists to catch.
    """

    def test_bytes_are_what_the_writer_produces_now(self):
        module = load_script("tools_make_contact_fixture")
        from boxradar_site import contacts
        expected = contacts.build(module.FEED, module.HOME_LAT,
                                  module.HOME_LON, module.LIMIT)

        declared, committed = committed_bytes(CONTACT_FIXTURE)
        self.assertEqual(declared, len(expected),
                         "fixture length is stale — re-run "
                         "tools_make_contact_fixture.py")
        self.assertEqual(committed, expected,
                         "fixture bytes are stale — re-run "
                         "tools_make_contact_fixture.py")


if __name__ == "__main__":
    unittest.main()
