"""The Pi's field table must agree with the firmware's.

Two tables describe the same ten NVS keys: DEVICE_FIELDS in
lib/radarcore/device_config.cpp and FIELDS in boxradar_config/device.py. They
cannot share a definition — one is C++ compiled into flash, the other is Python
on a Pi — so this checks them against each other by reading the source.

Drift here does not fail loudly anywhere else. A key spelled differently on the
two sides is not a compile error and not a runtime exception: it is a setting
that silently never applies, or a value the UI calls valid and the board then
refuses. site_config.cpp already documents an hour lost to exactly that shape
of bug, where a getUChar() on a putUInt() key returned 0 and the symptom was
"the night clock is invisible".

Source inspection rather than import, the same technique and for the same
reason as test_dependency_boundary.py.
"""

import pathlib
import re
import unittest

from boxradar_config import device

REPO = pathlib.Path(__file__).resolve().parents[3]
CPP = REPO / "lib" / "radarcore" / "device_config.cpp"
STRUCT_HEADER = REPO / "lib" / "radarcore" / "site_config_data.h"
NET_TASK = REPO / "src" / "net_task.cpp"

# This one needs the firmware source beside it, which is true in the repo and
# false on the receiver Pi — install.sh copies the two Python packages, not the
# C++. Skipped rather than failed there: a suite that reports failures for
# environmental reasons teaches you to skim past failures, which is the one
# habit a contract test like this cannot afford.
HAVE_FIRMWARE = CPP.is_file() and STRUCT_HEADER.is_file() and NET_TASK.is_file()

_ROW = re.compile(
    r'\{\s*"(?P<key>\w+)"\s*,\s*(?P<kind>DEV_U32|DEV_STR)\s*,'
    r'\s*(?P<low>[^,]+?)\s*,\s*(?P<high>[^}]+?)\s*\}')
_ENUM = re.compile(r"(CFG_\w+)\s*=\s*(\d+)")


def cpp_constants():
    """CFG_HOST_LEN and friends, so symbolic bounds can be resolved."""
    return {name: int(value)
            for name, value in _ENUM.findall(STRUCT_HEADER.read_text())}


def evaluate(expression, constants):
    """A bound like `CFG_TZ_LEN - 1`. Deliberately not eval()."""
    expression = expression.strip()
    for name, value in constants.items():
        expression = expression.replace(name, str(value))
    if not re.fullmatch(r"[\d\s+\-*]+", expression):
        raise AssertionError(f"unexpected bound expression: {expression!r}")
    total, sign, number = 0, 1, ""
    for token in re.findall(r"\d+|[+\-]", expression):
        if token in "+-":
            total += sign * int(number or 0)
            number, sign = "", 1 if token == "+" else -1
        else:
            number = token
    return total + sign * int(number or 0)


def firmware_fields():
    constants = cpp_constants()
    body = CPP.read_text()
    start = body.index("const DeviceField DEVICE_FIELDS[]")
    end = body.index("};", start)
    out = {}
    for match in _ROW.finditer(body[start:end]):
        out[match["key"]] = (
            match["kind"],
            evaluate(match["low"], constants),
            evaluate(match["high"], constants),
        )
    return out


@unittest.skipUnless(HAVE_FIRMWARE,
                     "needs the firmware source (repo checkout only)")
class ContractTest(unittest.TestCase):
    def setUp(self):
        self.firmware = firmware_fields()
        self.assertTrue(self.firmware, "parsed no fields out of device_config.cpp")

    def test_the_same_keys_on_both_sides(self):
        self.assertEqual(sorted(self.firmware),
                         sorted(f.key for f in device.FIELDS))

    def test_the_same_kinds(self):
        want = {"u": "DEV_U32", "s": "DEV_STR"}
        for field in device.FIELDS:
            self.assertEqual(self.firmware[field.key][0], want[field.kind],
                             f"{field.key} is a different type on each side")

    def test_the_same_bounds(self):
        for field in device.FIELDS:
            kind, low, high = self.firmware[field.key]
            if kind == "DEV_U32":
                self.assertEqual((field.low, field.high), (low, high),
                                 f"{field.key} bounds disagree: Pi "
                                 f"{field.low}-{field.high}, firmware "
                                 f"{low}-{high}")
            else:
                # The Pi has no lower bound for strings; the firmware's `low`
                # is unused for DEV_STR. Only the maximum has to agree, and it
                # is what decides whether cfgSetStr() will accept the value.
                self.assertEqual(field.high, high,
                                 f"{field.key} maximum length disagrees")

    def test_no_credential_key_appears_in_the_firmware_table_either(self):
        for forbidden in ("ssid", "pass", "recv", "otahost", "otapass"):
            self.assertNotIn(forbidden, self.firmware)

    def test_both_signal_header_names_match_the_firmware(self):
        # net_task.cpp collects these by name. A mismatch would mean the board
        # never opens its config server, or never notices a published map, and
        # nothing anywhere would log a reason.
        from boxradar_site.server import CONFIG_HEADER, GEO_HEADER
        net_task = NET_TASK.read_text()
        for header in (CONFIG_HEADER, GEO_HEADER):
            self.assertIn(f'"{header}"', net_task, header)

    def test_the_board_still_identifies_itself_by_http_10(self):
        """The Pi tells the board apart from a browser by its HTTP version.

        If the firmware ever stopped calling useHTTP10(true), presence would
        silently stop working: /board would report whichever workstation last
        opened the feed, and the Device page would push settings at it. That
        happened once already from this project's own diagnostics, which is
        why it is pinned here rather than left as a comment.
        """
        from boxradar_site.server import BOARD_HTTP_VERSION
        self.assertEqual(BOARD_HTTP_VERSION, "HTTP/1.0")
        self.assertIn("useHTTP10(true)", NET_TASK.read_text())

    def test_the_geo_signal_does_not_fetch_inside_the_contact_poll(self):
        # Geography has its own cadence and its own `if` so that a slow blob
        # fetch can never delay traffic. The signal must only mark it due.
        net_task = NET_TASK.read_text()
        poll = net_task[net_task.index("static void poll()"):
                        net_task.index("#ifdef METAR_ENABLED")]
        self.assertIn("geoStoreRefreshSoon()", poll)
        self.assertNotIn("geoStoreRefresh()", poll)


if __name__ == "__main__":
    unittest.main()
