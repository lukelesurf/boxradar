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
        "FR24_KEY": "key98765"}


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

    def test_non_numeric_longitude_fails(self):
        self.assertEqual(run("conf_validate", LON="east").returncode, 1)

    def test_negative_longitude_is_fine(self):
        # Luton is west of Greenwich. A validator that rejected the sign would
        # break every site in the western half of the country.
        self.assertEqual(run("conf_validate", LON="-0.368333").returncode, 0)

    def test_sdr_device_accepts_an_index_or_a_serial(self):
        self.assertEqual(run("conf_validate", SDR_DEVICE="0").returncode, 0)
        self.assertEqual(run("conf_validate", SDR_DEVICE="00000011").returncode, 0)

    def test_sdr_device_rejects_anything_that_would_split_the_argument(self):
        # It is interpolated unquoted into readsb's RECEIVER_OPTIONS.
        for bad in ("0 --gain 0", "", "abc;x"):
            result = run("conf_validate", SDR_DEVICE=bad)
            self.assertEqual(result.returncode, 1, bad)
            self.assertIn("SDR_DEVICE", result.stderr)

    def test_sdr_device_may_be_absent_from_an_older_conf(self):
        env = {k: v for k, v in os.environ.items() if k != "SDR_DEVICE"}
        env.update(GOOD)
        result = subprocess.run(
            ["bash", "-c", f'set -uo pipefail; source "{LIB}"; conf_validate'],
            env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_a_one_character_fr24_key_is_rejected(self):
        # redact() builds its sed pattern straight from FR24_KEY
        # (s|$FR24_KEY|<FR24_KEY>|g) — a one-character value doesn't just
        # under-validate, it shreds every matching character in the log.
        result = run("conf_validate", FR24_KEY="k")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FR24_KEY", result.stderr)

    def test_empty_static_ip_is_allowed(self):
        self.assertEqual(run("conf_validate", STATIC_IP="").returncode, 0)

    def test_static_ip_with_a_quote_is_rejected(self):
        # conf_write wraps values in quotes, so a value carrying its own
        # closing quote escapes into command context when the file is sourced.
        result = run("conf_validate", STATIC_IP='x"; touch /tmp/poc; y="')
        self.assertEqual(result.returncode, 1)
        self.assertIn("STATIC_IP", result.stderr)

    def test_a_plain_static_ip_is_accepted(self):
        self.assertEqual(run("conf_validate", STATIC_IP="192.0.2.10").returncode, 0)

    def test_a_static_ip_with_a_prefix_is_accepted(self):
        self.assertEqual(run("conf_validate", STATIC_IP="192.0.2.10/24").returncode, 0)

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

    def test_command_substitution_in_a_credential_is_rejected(self):
        # receiver.conf is sourced, by root, during install. A credential
        # carrying $(...) would execute rather than be assigned.
        result = run("conf_validate", FR24_KEY="abc$(id)")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FR24_KEY", result.stderr)

    def test_backtick_in_a_credential_is_rejected(self):
        self.assertEqual(run("conf_validate", ADSBX_USER="a`id`b").returncode, 1)

    def test_blank_adsbx_uuid_is_allowed(self):
        # Blank on a new box — the ADSBExchange installer generates it.
        self.assertEqual(run("conf_validate", ADSBX_UUID="").returncode, 0)

    def test_a_real_looking_uuid_is_allowed(self):
        self.assertEqual(run("conf_validate",
                             ADSBX_UUID="c1f4e0a2-9b3d-4c8e-11aa-7f2b6d5e0c93").returncode, 0)

    def test_a_one_character_adsbx_uuid_is_rejected(self):
        # Same redact()-shredding hazard as FR24_KEY above, when present.
        result = run("conf_validate", ADSBX_UUID="u")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ADSBX_UUID", result.stderr)


    def test_blank_aerodatabox_user_means_not_feeding(self):
        self.assertEqual(run("conf_validate", AERODATABOX_USER="",
                             AERODATABOX_UUID="").returncode, 0)

    def test_aerodatabox_user_with_a_breakout_character_is_rejected(self):
        result = run("conf_validate", AERODATABOX_USER="a$(id)b")
        self.assertEqual(result.returncode, 1)
        self.assertIn("AERODATABOX_USER", result.stderr)

    def test_aerodatabox_uuid_must_be_a_full_guid(self):
        # AeroDataBox keys the receiver on it; a truncated paste would
        # register a new receiver rather than fail.
        result = run("conf_validate", AERODATABOX_USER="example-feeder",
                     AERODATABOX_UUID="0f8e2b4c-6a1d-4e3f")
        self.assertEqual(result.returncode, 1)
        self.assertIn("AERODATABOX_UUID", result.stderr)

    def test_a_full_aerodatabox_guid_is_accepted(self):
        self.assertEqual(run("conf_validate", AERODATABOX_USER="example-feeder",
                             AERODATABOX_UUID="0f8e2b4c-6a1d-4e3f-9b70-2c5d8a1e4f60"
                             ).returncode, 0)


class TestMintAeroDataBoxUuid(unittest.TestCase):
    GUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

    def test_mints_one_when_feeding_and_blank(self):
        result = run('conf_mint_aerodatabox_uuid && echo "$AERODATABOX_UUID"',
                     AERODATABOX_USER="example-feeder", AERODATABOX_UUID="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout.strip(), self.GUID)

    def test_keeps_an_existing_one(self):
        keep = "0f8e2b4c-6a1d-4e3f-9b70-2c5d8a1e4f60"
        result = run('conf_mint_aerodatabox_uuid; echo "$AERODATABOX_UUID"',
                     AERODATABOX_USER="example-feeder", AERODATABOX_UUID=keep)
        self.assertEqual(result.stdout.strip(), keep)

    def test_mints_nothing_when_not_feeding(self):
        result = run('conf_mint_aerodatabox_uuid; echo "[${AERODATABOX_UUID-}]"',
                     AERODATABOX_USER="", AERODATABOX_UUID="")
        self.assertEqual(result.stdout.strip(), "[]")


class TestRoundTrip(unittest.TestCase):
    def test_conf_write_refuses_a_breakout_character(self):
        # The write-side guard, independent of conf_validate — proves a field
        # that slipped past validation still cannot produce a dangerous file.
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "receiver.conf"
            result = run(f'conf_write "{path}"', METAR_STATION='EG"X')
            self.assertEqual(result.returncode, 1)

    def test_write_then_load_recovers_every_value(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "receiver.conf"
            self.assertEqual(run(f'conf_write "{path}"',
                                 AERODATABOX_USER="example-feeder",
                                 AERODATABOX_UUID="0f8e2b4c-6a1d-4e3f-9b70-2c5d8a1e4f60"
                                 ).returncode, 0)
            result = run(f'conf_load "{path}"; '
                         f'echo "$LAT|$METAR_STATION|$FR24_KEY|$ALT_FT|$SDR_DEVICE|'
                         f'$AERODATABOX_USER|$AERODATABOX_UUID"',
                         LAT="0", METAR_STATION="ZZZZ", FR24_KEY="", ALT_FT="0",
                         SDR_DEVICE="9", AERODATABOX_USER="x",
                         AERODATABOX_UUID="y")
            self.assertEqual(result.stdout.strip(),
                             "51.8849826|EGSS|key98765|348|0|example-feeder|"
                             "0f8e2b4c-6a1d-4e3f-9b70-2c5d8a1e4f60")

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

    def test_quoted_write_preserves_a_value_with_whitespace_and_a_hash(self):
        # conf_write quotes every value so that a value with whitespace or a
        # '#' round-trips intact rather than corrupting the file — conf_write
        # itself does not call conf_validate, so this exercises the quoting
        # directly rather than relying on the character-class checks to keep
        # such values out.
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "receiver.conf"
            self.assertEqual(
                run(f'conf_write "{path}"',
                    STATIC_IP="not a real ip # trailing").returncode, 0)
            result = run(f'conf_load "{path}"; echo "$STATIC_IP"')
            self.assertEqual(result.stdout.strip(), "not a real ip # trailing")
