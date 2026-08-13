"""receiver.conf validation and round-tripping.

Validation matters more here than in most places: the person running this on
the second unit cannot be assumed to spot that they typed a longitude into a
latitude field, and a bad position is not visible on the display — it silently
degrades MLAT.
"""

import os
import pathlib
import subprocess
import tempfile
import unittest

LIB = (pathlib.Path(__file__).resolve().parents[2]
       / "receiver-install" / "lib" / "conf.sh")

GOOD = {"HOSTNAME": "boxradar", "LAT": "51.8849826", "LON": "0.2349914",
        "ALT_FT": "348", "GAIN": "auto", "PPM": "0", "STATIC_IP": "",
        "METAR_STATION": "EGSS", "CALM_KT": "7",
        "ADSBX_USER": "example-feeder", "ADSBX_UUID": "uuid-1234",
        "FR24_KEY": "key9876"}


def run(snippet, **overrides):
    env = dict(os.environ)
    env.update(GOOD)
    env.update(overrides)
    return subprocess.run(
        ["bash", "-c", f'set -uo pipefail; source "{LIB}"; {snippet}'],
        env=env, capture_output=True, text=True)


class TestValidate(unittest.TestCase):
    def test_good_config_passes(self):
        self.assertEqual(run("conf_validate").returncode, 0)

    def test_latitude_out_of_range_fails(self):
        result = run("conf_validate", LAT="951.9")
        self.assertEqual(result.returncode, 1)
        self.assertIn("LAT", result.stderr)

    def test_longitude_out_of_range_fails(self):
        self.assertEqual(run("conf_validate", LON="200").returncode, 1)

    def test_non_numeric_latitude_fails(self):
        self.assertEqual(run("conf_validate", LAT="north").returncode, 1)

    def test_negative_longitude_is_fine(self):
        # Luton is west of Greenwich. A validator that rejected the sign would
        # break every site in the western half of the country.
        self.assertEqual(run("conf_validate", LON="-0.368333").returncode, 0)

    def test_icao_must_be_four_letters(self):
        self.assertEqual(run("conf_validate", METAR_STATION="EGS").returncode, 1)
        self.assertEqual(run("conf_validate", METAR_STATION="EG55").returncode, 1)

    def test_icao_is_accepted_lowercase(self):
        self.assertEqual(run("conf_validate", METAR_STATION="egss").returncode, 0)

    def test_gain_accepts_auto_or_a_number(self):
        self.assertEqual(run("conf_validate", GAIN="auto").returncode, 0)
        self.assertEqual(run("conf_validate", GAIN="49.6").returncode, 0)
        self.assertEqual(run("conf_validate", GAIN="loud").returncode, 1)

    def test_altitude_must_be_an_integer(self):
        self.assertEqual(run("conf_validate", ALT_FT="348.5").returncode, 1)

    def test_missing_fr24_key_fails(self):
        result = run("conf_validate", FR24_KEY="")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FR24_KEY", result.stderr)

    def test_empty_static_ip_is_allowed(self):
        self.assertEqual(run("conf_validate", STATIC_IP="").returncode, 0)

    def test_all_problems_are_reported_not_just_the_first(self):
        result = run("conf_validate", LAT="999", METAR_STATION="X")
        self.assertIn("LAT", result.stderr)
        self.assertIn("METAR_STATION", result.stderr)

    def test_missing_hostname_fails_even_though_bash_presets_it(self):
        # Bash sets $HOSTNAME itself, so a naive [[ -n $HOSTNAME ]] check
        # passes on a config that never mentions it.
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "receiver.conf"
            path.write_text("LAT=51.9\nLON=0.03\n")
            result = run(f'conf_load "{path}"; conf_validate')
            self.assertEqual(result.returncode, 1)
            self.assertIn("HOSTNAME", result.stderr)


class TestRoundTrip(unittest.TestCase):
    def test_write_then_load_recovers_every_value(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "receiver.conf"
            self.assertEqual(run(f'conf_write "{path}"').returncode, 0)
            result = run(f'conf_load "{path}"; '
                         f'echo "$LAT|$METAR_STATION|$FR24_KEY|$ALT_FT"',
                         LAT="0", METAR_STATION="ZZZZ", FR24_KEY="", ALT_FT="0")
            self.assertEqual(result.stdout.strip(),
                             "51.8849826|EGSS|key9876|348")

    def test_written_file_is_owner_read_write_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "receiver.conf"
            run(f'conf_write "{path}"')
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")

    def test_written_file_is_valid_shell(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "receiver.conf"
            run(f'conf_write "{path}"')
            subprocess.run(["bash", "-n", str(path)], check=True)
