"""Config rendering for the receiver installer.

The renderers are pure functions of receiver.conf, so they are testable
without a Pi. This is the layer that closes the position drift found on the
hand-built receiver, where readsb, the ADSBExchange feeder and selection.json
each carried a slightly different home position.
"""

import os
import pathlib
import re
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


def local_ports(rendered):
    """The ports a feeder's env file makes something bind or connect to.

    Every run of digits on the RESULTS/NET_OPTIONS lines, keeping those
    >= 30000. The threshold is what separates ports from the other numbers
    those lines carry (--net-heartbeat 60, --net-ro-size 1280,
    --net-ro-port 0, the octets of 127.0.0.1, and the trailing digit of
    "RESULTS3" itself).

    Regex rather than splitting on commas and whitespace, which is what this
    did first: that left the last field of every RESULTS line holding its
    closing quote — "30157\"" — which is not .isdigit(), so it was silently
    dropped. The effect was that only the --net-bi-port values were ever
    compared and the mlat-client listen ports, the ones that actually
    collide, were invisible. The test read as though it covered them and
    passed either way.
    """
    found = set()
    for line in rendered.splitlines():
        if line.startswith(("RESULTS", "NET_OPTIONS")):
            found.update(n for n in map(int, re.findall(r"\d+", line))
                         if n >= 30000)
    return found


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

    def test_sdr_device_selects_the_dongle_by_serial(self):
        # Index 0 is whichever dongle enumerated first; on a box with more
        # than one, only the serial pins the 1090 dongle.
        out = render("render_readsb", SDR_DEVICE="00000011")
        self.assertIn("--device 00000011 ", out)

    def test_sdr_device_defaults_to_index_zero(self):
        # A receiver.conf written before SDR_DEVICE existed has no such key.
        env_without = {k: v for k, v in os.environ.items() if k != "SDR_DEVICE"}
        result = subprocess.run(
            ["bash", "-c", f'set -euo pipefail; source "{RENDER_SH}"; render_readsb'],
            env={**env_without, **BASE}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--device 0 ", result.stdout)

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

    def test_mlat_is_given_a_position(self):
        # The regression this class was missing. mlat="yes" plus
        # mlat-without-gps="yes" asked FR24 for MLAT while never supplying the
        # position that mlat-without-gps selects, and FR24 answered
        # mlat_problem="no-config" for months while feed_status stayed
        # "connected" and mlat-started stayed "YES". The assertion above
        # passed throughout — it checks the switch, not the position.
        out = render("render_fr24")
        self.assertIn('mlat-without-gps="yes"', out)
        self.assertIn('latitude="51.8849826"', out)
        self.assertIn('longitude="0.2349914"', out)

    def test_altitude_is_bare_feet(self):
        # fr24feed wants a bare number ("antenna's altitude above the sea
        # level (in feet)"), unlike ADSBExchange's ALTITUDE, which takes a
        # "ft" suffix. Getting this backwards is silent in both directions.
        out = render("render_fr24", ALT_FT="363")
        self.assertIn('altitude="363"', out)
        self.assertNotIn('altitude="363ft"', out)


class TestRenderAdsblol(unittest.TestCase):
    LOL = {"ADSBLOL_USER": "example-feeder"}

    def test_station_name_and_position_come_from_the_conf(self):
        out = render("render_adsblol", **self.LOL)
        self.assertIn('USER="example-feeder"', out)
        self.assertIn('LATITUDE="51.8849826"', out)
        self.assertIn('LONGITUDE="0.2349914"', out)

    def test_altitude_carries_the_ft_suffix(self):
        # The opposite of render_fr24's rule, on the same ALT_FT. adsb.lol's
        # configure.sh validates ^(-?[0-9]*)(ft|m)$ and mlat-client reads a
        # bare number as metres — 363 without the suffix would place the
        # receiver 100m underground, and nothing would report an error.
        out = render("render_adsblol", ALT_FT="363", **self.LOL)
        self.assertIn('ALTITUDE="363ft"', out)

    def test_it_feeds_adsblol_not_adsbexchange(self):
        out = render("render_adsblol", **self.LOL)
        self.assertIn("feed.adsb.lol", out)
        self.assertNotIn("adsbexchange.com", out)

    def test_output_is_valid_shell(self):
        # Sourced by adsblol-feed.sh and adsblol-mlat.sh, as well as update.sh.
        out = render("render_adsblol", **self.LOL)
        subprocess.run(["bash", "-n"], input=out, text=True, check=True)


class TestRenderAdsbfi(unittest.TestCase):
    FI = {"ADSBFI_USER": "example-feeder"}

    def test_station_name_and_position_come_from_the_conf(self):
        out = render("render_adsbfi", **self.FI)
        self.assertIn('USER="example-feeder"', out)
        self.assertIn('LATITUDE="51.8849826"', out)
        self.assertIn('LONGITUDE="0.2349914"', out)

    def test_altitude_carries_the_ft_suffix(self):
        # adsb.fi's configure.sh validates ^(-?[0-9]*)(ft|m)$ exactly as
        # adsb.lol's does, and the same mlat-client reads a bare number as
        # metres.
        out = render("render_adsbfi", ALT_FT="363", **self.FI)
        self.assertIn('ALTITUDE="363ft"', out)

    def test_it_does_not_ship_adsbexchanges_beast_listen_port(self):
        # The whole reason this renderer deviates from upstream. adsb.fi
        # forked the feedclient before the "avoid listen port overlap with ax
        # scripts" commit, so their configure.sh still writes 30157 — which
        # adsbexchange-mlat listens on. Asserted by value, not just via the
        # disjointness test below, so that "someone pasted upstream's block
        # back in" fails with a message that says what happened.
        out = render("render_adsbfi", **self.FI)
        self.assertNotIn("30157", out)
        self.assertIn("--results beast,listen,30170", out)

    def test_the_uuid_file_stays_in_net_options(self):
        # Upstream's, and unlike the ADSBExchange and adsb.lol copies.
        # Dropping it to "match the others" would make the feed client stop
        # identifying by uuid, so every rebuild would register as a new
        # receiver however faithfully ADSBFI_UUID was restored.
        out = render("render_adsbfi", **self.FI)
        self.assertIn("--uuid-file /usr/local/share/adsbfi/adsbfi-uuid", out)

    def test_it_feeds_adsbfi_not_the_others(self):
        out = render("render_adsbfi", **self.FI)
        self.assertIn("feed.adsb.fi", out)
        self.assertNotIn("adsbexchange.com", out)
        self.assertNotIn("adsb.lol", out)

    def test_output_is_valid_shell(self):
        # Sourced by adsbfi-feed.sh and adsbfi-mlat.sh, as well as update.sh.
        out = render("render_adsbfi", **self.FI)
        subprocess.run(["bash", "-n"], input=out, text=True, check=True)


class TestFeederPortsAreDisjoint(unittest.TestCase):
    """What makes three feeders and three MLAT clients share one Pi.

    Two of these blocks were separated by upstream ("avoid listen port overlap
    with ax scripts") and the third, adsb.fi's, was not — it predates that
    commit and still ships 30157. A merge that "tidied" any of them together
    would leave an mlat-client unable to bind, which does not stop its feed
    and so looks fine from every angle except the missing results.
    """

    # 30104 is readsb's --net-bi-port. Every MLAT client connects out to it on
    # purpose, so it is the one number allowed to appear in all three.
    SHARED = {30104}

    RENDERED = {
        # The third element is that feeder's mlat-client beast listen port —
        # the one that collides, and the one local_ports() used to miss. Used
        # below as the guard against this passing vacuously, so it has to be
        # a port from a RESULTS line rather than a --net-bi-port.
        "ADSBExchange": ("render_adsbexchange", {}, 30157),
        "adsb.lol": ("render_adsblol", {"ADSBLOL_USER": "example-feeder"}, 31422),
        "adsb.fi": ("render_adsbfi", {"ADSBFI_USER": "example-feeder"}, 30170),
    }

    def test_no_two_feeders_bind_the_same_port(self):
        ports = {}
        for name, (fn, env, expected) in self.RENDERED.items():
            ports[name] = local_ports(render(fn, **env))
            # Each side must actually have found its ports, or a renamed line
            # would make every pair below pass vacuously.
            self.assertIn(expected, ports[name],
                          f"{name}: local_ports() found nothing recognisable")

        names = sorted(ports)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                overlap = (ports[a] & ports[b]) - self.SHARED
                self.assertEqual(overlap, set(),
                                 f"{a} and {b} share port(s): {sorted(overlap)}")


class TestSecretsAreNotEchoed(unittest.TestCase):
    def test_rendering_writes_nothing_to_stderr(self):
        # Stages tee stdout to a log. Anything a renderer puts on stderr could
        # carry a key into /var/log/boxradar-install.log.
        env = dict(os.environ)
        env.update(BASE)
        env["ADSBLOL_USER"] = "example-feeder"
        env["ADSBFI_USER"] = "example-feeder"
        result = subprocess.run(
            ["bash", "-c",
             f'set -euo pipefail; source "{RENDER_SH}"; '
             f'render_readsb >/dev/null; render_adsbexchange >/dev/null; '
             f'render_adsblol >/dev/null; render_adsbfi >/dev/null; '
             f'render_fr24 >/dev/null'],
            env=env, capture_output=True, text=True)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.returncode, 0)
