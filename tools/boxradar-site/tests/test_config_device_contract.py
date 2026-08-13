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

    def test_the_wake_header_name_matches_the_firmware(self):
        # net_task.cpp collects exactly one header name. A mismatch would mean
        # the board never opens its config server and nothing anywhere logs a
        # reason.
        from boxradar_site.server import CONFIG_HEADER
        net_task = (REPO / "src" / "net_task.cpp").read_text()
        self.assertIn(f'"{CONFIG_HEADER}"', net_task)


if __name__ == "__main__":
    unittest.main()
