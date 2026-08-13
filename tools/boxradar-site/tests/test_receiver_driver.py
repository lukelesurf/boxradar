"""The installer driver: stage discovery, stamping and resumption.

Stamping is an optimisation, not the correctness mechanism — every stage is
independently idempotent — but resumption is what turns "it died at the FR24
step" into something the second operator can act on, so it is worth testing.
"""

import os
import pathlib
import subprocess
import tempfile
import unittest

INSTALL = (pathlib.Path(__file__).resolve().parents[2]
           / "receiver-install" / "install.sh")


class DriverCase(unittest.TestCase):
    # conf_validate is unconditional on every driver run, including
    # --no-wizard — that's the hand-edited-file path, exactly where a
    # transposed coordinate appears, and a bad position degrades MLAT
    # silently. Tests that don't care about config content still need one
    # that passes validation; tests that do care overwrite this.
    VALID_CONF = (
        "HOSTNAME=boxradar\n"
        "LAT=51.8849826\n"
        "LON=0.2349914\n"
        "ALT_FT=348\n"
        "GAIN=auto\n"
        "PPM=0\n"
        "STATIC_IP=\n"
        "METAR_STATION=EGSS\n"
        "CALM_KT=7\n"
        "ADSBX_USER=example-feeder\n"
        "ADSBX_UUID=\n"
        "FR24_KEY=testkey9876\n"
    )

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = pathlib.Path(self.dir.name)
        self.stages = self.root / "stages"
        self.stages.mkdir()
        self.stamps = self.root / "stamps"
        (self.root / "receiver.conf").write_text(self.VALID_CONF)

    def stage(self, name, body="exit 0"):
        path = self.stages / name
        path.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{body}\n")
        path.chmod(0o755)

    def run_driver(self, *args, stdin=None):
        env = dict(os.environ)
        env.update({
            "BOXRADAR_STAGE_DIR": str(self.stages),
            "BOXRADAR_STAMP_DIR": str(self.stamps),
            "BOXRADAR_LOG": str(self.root / "install.log"),
            "BOXRADAR_CONF": str(self.root / "receiver.conf"),
            "BOXRADAR_SKIP_ROOT_CHECK": "1",
        })
        return subprocess.run(["bash", str(INSTALL), *args],
                              env=env, capture_output=True, text=True,
                              input=stdin)


class TestStageRunning(DriverCase):
    def test_stages_run_in_numeric_order(self):
        self.stage("10-first.sh", 'echo ran-10')
        self.stage("20-second.sh", 'echo ran-20')
        self.stage("30-third.sh", 'echo ran-30')
        out = self.run_driver("--no-wizard").stdout
        self.assertLess(out.index("ran-10"), out.index("ran-20"))
        self.assertLess(out.index("ran-20"), out.index("ran-30"))

    def test_a_completed_stage_is_stamped(self):
        self.stage("10-first.sh")
        self.run_driver("--no-wizard")
        self.assertTrue((self.stamps / "10-first.done").exists())

    def test_a_stamped_stage_is_skipped_on_rerun(self):
        self.stage("10-first.sh", 'echo ran-10')
        self.run_driver("--no-wizard")
        out = self.run_driver("--no-wizard").stdout
        self.assertNotIn("ran-10", out)
        self.assertIn("skip", out.lower())

    def test_force_reruns_a_stamped_stage(self):
        self.stage("10-first.sh", 'echo ran-10')
        self.run_driver("--no-wizard")
        self.assertIn("ran-10", self.run_driver("--no-wizard", "--force").stdout)

    def test_from_starts_at_the_given_stage(self):
        self.stage("10-first.sh", 'echo ran-10')
        self.stage("20-second.sh", 'echo ran-20')
        out = self.run_driver("--no-wizard", "--from", "20").stdout
        self.assertNotIn("ran-10", out)
        self.assertIn("ran-20", out)


class TestFailureHandling(DriverCase):
    def test_a_failing_stage_stops_the_run(self):
        self.stage("10-first.sh", 'echo ran-10')
        self.stage("20-bad.sh", 'echo about-to-fail; exit 3')
        self.stage("30-third.sh", 'echo ran-30')
        result = self.run_driver("--no-wizard")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("ran-30", result.stdout)

    def test_a_failing_stage_is_not_stamped(self):
        self.stage("10-bad.sh", 'exit 3')
        self.run_driver("--no-wizard")
        self.assertFalse((self.stamps / "10-bad.done").exists())

    def test_earlier_stages_keep_their_stamps_after_a_later_failure(self):
        self.stage("10-first.sh")
        self.stage("20-bad.sh", 'exit 3')
        self.run_driver("--no-wizard")
        self.assertTrue((self.stamps / "10-first.done").exists())

    def test_the_failure_message_names_the_stage_and_the_rerun_command(self):
        self.stage("10-bad.sh", 'exit 3')
        combined = self.run_driver("--no-wizard")
        text = combined.stdout + combined.stderr
        self.assertIn("10-bad", text)
        self.assertIn("re-run", text.lower())

    def test_a_failing_stage_propagates_a_nonzero_exit(self):
        # `if ! bash "$stage"; then status=$?` zeroes $? — the installer
        # would exit 0 on a failed stage and report success.
        self.stage("10-bad.sh", 'exit 3')
        self.assertNotEqual(self.run_driver("--no-wizard").returncode, 0)

    def test_an_invalid_config_stops_a_no_wizard_run(self):
        # --no-wizard is the hand-edited-file path, which is exactly where a
        # transposed coordinate appears. A bad position has no visible
        # symptom; it silently degrades MLAT.
        (self.root / "receiver.conf").write_text(
            self.VALID_CONF.replace("LAT=51.8849826", "LAT=951.9"))
        self.stage("10-first.sh", 'echo ran-10')
        result = self.run_driver("--no-wizard")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("ran-10", result.stdout)
        self.assertIn("LAT", result.stdout + result.stderr)


class TestLogging(DriverCase):
    def test_output_is_written_to_the_log(self):
        self.stage("10-first.sh", 'echo hello-from-stage')
        self.run_driver("--no-wizard")
        self.assertIn("hello-from-stage",
                      (self.root / "install.log").read_text())

    def test_secrets_are_redacted_from_the_log(self):
        (self.root / "receiver.conf").write_text(
            self.VALID_CONF.replace("FR24_KEY=testkey9876",
                                     "FR24_KEY=supersecret123")
                           .replace("ADSBX_UUID=", "ADSBX_UUID=uuid-secret-456"))
        self.stage("10-first.sh", 'echo "key is ${FR24_KEY:-unset}"')
        self.run_driver("--no-wizard")
        log = (self.root / "install.log").read_text()
        self.assertNotIn("supersecret123", log)
        self.assertNotIn("uuid-secret-456", log)
        # Positive assertions, not just absence: a stage that never ran, or
        # a redact() that discarded the whole stream, would also make the
        # two assertNotIn calls above pass vacuously. Prove the secret was
        # actually replaced by its placeholder, and that the stage's own
        # output genuinely reached the log.
        self.assertIn("<FR24_KEY>", log)
        self.assertIn("key is", log)


class TestWizard(DriverCase):
    # Matches run_wizard's actual prompt order in install.sh exactly:
    # HOSTNAME, LAT, LON, ALT_FT, GAIN, PPM, STATIC_IP, METAR_STATION,
    # CALM_KT, ADSBX_USER, ADSBX_UUID, FR24_KEY.
    ANSWERS = "\n".join([
        "boxradar",         # HOSTNAME
        "51.8849826",       # LAT
        "0.2349914",        # LON
        "348",              # ALT_FT
        "auto",             # GAIN
        "0",                # PPM
        "",                 # STATIC_IP (blank = DHCP)
        "EGSS",             # METAR_STATION
        "7",                # CALM_KT
        "example-feeder",      # ADSBX_USER
        "",                 # ADSBX_UUID (blank on a new box)
        "typedsecret999",   # FR24_KEY
    ]) + "\n"

    def test_a_key_typed_at_the_wizard_prompt_never_reaches_the_log(self):
        # read -r echoes what is typed. If logging started before the
        # wizard, the FR24 key would be written to the log before redact()
        # knew the value to mask. This is the ordering the driver must
        # preserve.
        (self.root / "receiver.conf").unlink(missing_ok=True)
        self.stage("10-first.sh", "echo ran-10")
        result = self.run_driver(stdin=self.ANSWERS)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        log = (self.root / "install.log").read_text()
        self.assertNotIn("typedsecret999", log)
        self.assertIn("ran-10", log)

    def test_the_wizard_writes_a_conf_the_next_run_reuses(self):
        # Proves conf_write is actually wired up — it had no caller before
        # this task.
        (self.root / "receiver.conf").unlink(missing_ok=True)
        self.run_driver(stdin=self.ANSWERS)
        conf_path = self.root / "receiver.conf"
        conf = conf_path.read_text()
        self.assertIn("METAR_STATION=", conf)
        # The conf is 0600 and is meant to carry the credential — contrast
        # with the log assertion above, which must never see it.
        self.assertIn("typedsecret999", conf)
        self.assertEqual(oct(conf_path.stat().st_mode & 0o777), "0o600")


class TestCheckMode(DriverCase):
    def test_check_mode_runs_no_stages(self):
        self.stage("10-first.sh", 'echo ran-10')
        out = self.run_driver("--no-wizard", "--check").stdout
        self.assertNotIn("ran-10", out)

    def test_check_mode_renders_configs(self):
        (self.root / "receiver.conf").write_text(
            "HOSTNAME=boxradar\nLAT=51.8849826\nLON=0.2349914\nALT_FT=348\n"
            "GAIN=auto\nPPM=0\nSTATIC_IP=\nMETAR_STATION=EGSS\nCALM_KT=7\n"
            "ADSBX_USER=test\nADSBX_UUID=u\nFR24_KEY=k\n")
        out = self.run_driver("--no-wizard", "--check").stdout
        self.assertIn("--net-bi-port 30004,30104", out)
        self.assertIn('LATITUDE="51.8849826"', out)


class TestHelp(DriverCase):
    def test_help_exits_zero_and_lists_the_flags(self):
        result = self.run_driver("--help")
        self.assertEqual(result.returncode, 0)
        for flag in ("--check", "--from", "--force"):
            self.assertIn(flag, result.stdout)
