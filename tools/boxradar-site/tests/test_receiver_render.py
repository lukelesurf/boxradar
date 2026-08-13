"""Config rendering for the receiver installer.

The renderers are pure functions of receiver.conf, so they are testable
without a Pi. This is the layer that closes the position drift found on the
hand-built receiver, where readsb, the ADSBExchange feeder and selection.json
each carried a slightly different home position.
"""

import os
import pathlib
import subprocess
import unittest

RENDER_SH = (pathlib.Path(__file__).resolve().parents[2]
             / "receiver-install" / "lib" / "render.sh")

BASE = {"LAT": "51.8849826", "LON": "0.2349914", "ALT_FT": "348",
        "GAIN": "auto", "PPM": "0", "ADSBX_USER": "example-feeder",
        "ADSBX_UUID": "test-uuid-1234", "FR24_KEY": "testkey9876"}


def render(function, **overrides):
    env = dict(os.environ)
    env.update(BASE)
    env.update(overrides)
    result = subprocess.run(
        ["bash", "-c", f'set -euo pipefail; source "{RENDER_SH}"; {function}'],
        env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"{function} failed: {result.stderr}")
    return result.stdout


class TestRenderReadsb(unittest.TestCase):
    def test_position_comes_from_the_conf(self):
        out = render("render_readsb")
        self.assertIn("--lat 51.8849826", out)
        self.assertIn("--lon 0.2349914", out)

    def test_mlat_return_port_is_present(self):
        # Without 30104 in --net-bi-port, mlat-client has nowhere to return
        # results and MLAT positions silently vanish.
        self.assertIn("--net-bi-port 30004,30104", render("render_readsb"))

    def test_gain_and_ppm_come_from_the_conf(self):
        out = render("render_readsb", GAIN="49.6", PPM="-2")
        self.assertIn("--gain 49.6", out)
        self.assertIn("--ppm -2", out)

    def test_every_expected_variable_is_defined(self):
        out = render("render_readsb")
        for key in ("RECEIVER_OPTIONS", "DECODER_OPTIONS", "NET_OPTIONS",
                    "JSON_OPTIONS"):
            self.assertIn(f"{key}=", out)

    def test_output_is_valid_shell(self):
        # /etc/default/readsb is sourced by systemd's EnvironmentFile.
        out = render("render_readsb")
        subprocess.run(["bash", "-n"], input=out, text=True, check=True)

    def test_multi_word_values_are_quoted(self):
        # /etc/default/readsb is sourced by systemd's EnvironmentFile=.
        # Unquoted, NET_OPTIONS would take only its first word and the shell
        # would try to execute the second as a command.
        out = render("render_readsb")
        for key in ("RECEIVER_OPTIONS", "DECODER_OPTIONS", "NET_OPTIONS",
                    "JSON_OPTIONS"):
            line = next(l for l in out.splitlines() if l.startswith(f"{key}="))
            value = line.split("=", 1)[1]
            self.assertTrue(value.startswith('"') and value.endswith('"'),
                             f"{key} must be quoted, got: {line}")


class TestRenderAdsbexchange(unittest.TestCase):
    def test_position_matches_readsb_exactly(self):
        readsb, adsbx = render("render_readsb"), render("render_adsbexchange")
        self.assertIn("--lat 51.8849826", readsb)
        self.assertIn('LATITUDE="51.8849826"', adsbx)
        self.assertIn('LONGITUDE="0.2349914"', adsbx)

    def test_altitude_is_carried_in_feet(self):
        self.assertIn('ALTITUDE="348ft"', render("render_adsbexchange"))

    def test_user_comes_from_the_conf(self):
        self.assertIn('USER="example-feeder"', render("render_adsbexchange"))

    def test_multi_word_values_are_quoted(self):
        # /etc/default/adsbexchange is sourced by the feeder's shell script.
        # Unquoted, NET_OPTIONS would take only its first word and the shell
        # would try to execute the second as a command.
        out = render("render_adsbexchange")
        for key in ("RESULTS", "TARGET", "NET_OPTIONS", "JSON_OPTIONS"):
            line = next(l for l in out.splitlines() if l.startswith(f"{key}="))
            value = line.split("=", 1)[1]
            self.assertTrue(value.startswith('"') and value.endswith('"'),
                             f"{key} must be quoted, got: {line}")

    def test_output_is_valid_shell(self):
        # /etc/default/adsbexchange is sourced by the feeder's own shell
        # script, exactly like readsb's EnvironmentFile.
        out = render("render_adsbexchange")
        subprocess.run(["bash", "-n"], input=out, text=True, check=True)

    def test_max_range_is_carried_into_json_options(self):
        # Without it feed-adsbx falls back to a lower default range and
        # silently drops distant positions from what it feeds upstream.
        out = render("render_adsbexchange")
        line = next(l for l in out.splitlines() if l.startswith("JSON_OPTIONS="))
        self.assertIn("--max-range 450", line)

    def test_net_options_match_the_working_receiver(self):
        out = render("render_adsbexchange")
        line = next(l for l in out.splitlines() if l.startswith("NET_OPTIONS="))
        self.assertNotIn("--net ", line)          # the feeder script adds --net itself
        self.assertIn("--write-json-every 1", line)


class TestRenderFr24(unittest.TestCase):
    def test_key_is_written(self):
        self.assertIn('fr24key="testkey9876"', render("render_fr24"))

    def test_receiver_is_beast_on_localhost(self):
        out = render("render_fr24")
        self.assertIn('receiver="beast-tcp"', out)
        self.assertIn('host="127.0.0.1:30005"', out)

    def test_mlat_is_enabled(self):
        self.assertIn('mlat="yes"', render("render_fr24"))


class TestSecretsAreNotEchoed(unittest.TestCase):
    def test_rendering_writes_nothing_to_stderr(self):
        # Stages tee stdout to a log. Anything a renderer puts on stderr could
        # carry a key into /var/log/boxradar-install.log.
        env = dict(os.environ)
        env.update(BASE)
        result = subprocess.run(
            ["bash", "-c",
             f'set -euo pipefail; source "{RENDER_SH}"; '
             f'render_readsb >/dev/null; render_adsbexchange >/dev/null; '
             f'render_fr24 >/dev/null'],
            env=env, capture_output=True, text=True)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.returncode, 0)
