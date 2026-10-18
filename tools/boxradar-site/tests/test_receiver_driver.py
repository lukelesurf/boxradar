"""The installer driver: stage discovery, stamping and resumption.

Stamping is an optimisation, not the correctness mechanism — every stage is
independently idempotent — but resumption is what turns "it died at the FR24
step" into something the second operator can act on, so it is worth testing.
"""

import os
import pathlib
import re
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

    def run_driver(self, *args, stdin=None, timeout=None, extra_env=None):
        env = dict(os.environ)
        env.update({
            "BOXRADAR_STAGE_DIR": str(self.stages),
            "BOXRADAR_STAMP_DIR": str(self.stamps),
            "BOXRADAR_LOG": str(self.root / "install.log"),
            "BOXRADAR_CONF": str(self.root / "receiver.conf"),
            "BOXRADAR_SKIP_ROOT_CHECK": "1",
        })
        env.update(extra_env or {})
        return subprocess.run(["bash", str(INSTALL), *args],
                              env=env, capture_output=True, text=True,
                              input=stdin, timeout=timeout)


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

    def test_an_empty_stage_dir_fails_rather_than_reporting_success(self):
        # `shopt -s nullglob` makes the *.sh glob vanish when self.stages is
        # empty (DriverCase.setUp creates the directory but adds no stages),
        # so the for loop simply never runs. Same class of bug as
        # `bash -c "$(curl ...)"` degrading to `bash -c ""` on a failed
        # fetch: an incomplete copy of the installer should not "succeed" at
        # doing nothing.
        result = self.run_driver("--no-wizard")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("all stages complete", result.stdout)

    def test_from_needs_an_argument(self):
        # Under `set -u`, a bare `FROM="$2"` with nothing left in $@ already
        # dies non-zero on "unbound variable" — that alone doesn't prove
        # this fix (an explicit, named check) is what's firing. Assert the
        # specific message the fix adds, not just a non-zero exit.
        result = self.run_driver("--no-wizard", "--from")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--from needs a stage number",
                      result.stdout + result.stderr)


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
        # Both secrets are echoed, not just FR24_KEY: an earlier version of
        # this test only echoed the key, which meant its ADSBX_UUID
        # assertNotIn passed vacuously — nothing had ever emitted the uuid,
        # so redact() being wired up for it at all was unverified.
        self.stage("10-first.sh",
                   'echo "key is ${FR24_KEY:-unset}"; '
                   'echo "uuid is ${ADSBX_UUID:-unset}"')
        self.run_driver("--no-wizard")
        log = (self.root / "install.log").read_text()
        self.assertNotIn("supersecret123", log)
        self.assertNotIn("uuid-secret-456", log)
        # Positive assertions, not just absence: a stage that never ran, or
        # a redact() that discarded the whole stream, would also make the
        # two assertNotIn calls above pass vacuously. Prove each secret was
        # actually replaced by its placeholder, and that the stage's own
        # output genuinely reached the log.
        self.assertIn("<FR24_KEY>", log)
        self.assertIn("<ADSBX_UUID>", log)
        self.assertIn("key is", log)


class TestWizard(DriverCase):
    # Answers keyed by the variable each prompt fills, piped in run_wizard's
    # own order — read out of install.sh rather than restated here.
    #
    # Order is load-bearing: answers are piped, so an inserted prompt shifts
    # every later answer into the wrong field rather than failing outright.
    # This used to be a flat list in prompt order, and adding the adsb.fi
    # prompts duly broke three tests with symptoms (an invalid FR24 key, a
    # hostname assertion) that named nothing to do with the actual cause.
    # Deriving the order means a new prompt fails once, by name, saying what
    # to add.
    ANSWER_BY_VAR = {
        "HOSTNAME": "boxradar",
        "LAT": "51.8849826",
        "LON": "0.2349914",
        "ALT_FT": "348",
        "GAIN": "auto",
        "PPM": "0",
        "SDR_DEVICE": "0",
        "STATIC_IP": "",            # blank = DHCP
        "METAR_STATION": "EGSS",
        "CALM_KT": "7",
        "ADSBX_USER": "example-feeder",
        "ADSBX_UUID": "",           # blank on a new box
        "ADSBLOL_USER": "",         # blank = don't feed adsb.lol
        "ADSBLOL_UUID": "",         # blank on a new box
        "ADSBFI_USER": "",          # blank = don't feed adsb.fi
        "ADSBFI_UUID": "",          # blank on a new box
        "AERODATABOX_USER": "",     # blank = don't feed AeroDataBox
        "AERODATABOX_UUID": "",     # blank = mint one
        "FR24_KEY": "typedsecret999",
    }

    @classmethod
    def answers(cls, skip=()):
        """run_wizard's prompts, in its order, answered from ANSWER_BY_VAR.

        `skip` leaves a prompt unanswered so the caller can supply its own
        line — used to press enter at HOSTNAME and take the default.
        """
        prompts = re.findall(r"^\s*ask (\w+)\s", INSTALL.read_text(), re.M)
        assert prompts, "found no `ask` prompts in install.sh"
        out = []
        for var in prompts:
            if var in skip:
                continue
            if var not in cls.ANSWER_BY_VAR:
                raise AssertionError(
                    f"install.sh prompts for {var}, which ANSWER_BY_VAR has no "
                    f"answer for — add one")
            out.append(cls.ANSWER_BY_VAR[var])
        return "\n".join(out) + "\n"

    def test_the_wizard_completes_and_writes_a_valid_conf(self):
        # Drives the wizard end to end from piped answers and confirms it
        # completes, the stage after it runs, and the typed secret is not
        # sitting in the log. It does NOT prove the wizard-before-logging
        # ordering: read -p only emits its prompt to a terminal, and the
        # tty (not this process) echoes what's typed, so a piped-stdin run
        # produces the same (empty) prompt/echo output regardless of
        # whether logging started before or after the wizard — confirmed
        # by mutation-testing a reordered copy of install.sh, which passed
        # this exact assertion too. The ordering itself is covered
        # structurally by test_the_wizard_runs_before_logging_starts below.
        (self.root / "receiver.conf").unlink(missing_ok=True)
        self.stage("10-first.sh", "echo ran-10")
        result = self.run_driver(stdin=self.answers())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        log = (self.root / "install.log").read_text()
        self.assertNotIn("typedsecret999", log)
        self.assertIn("ran-10", log)

    def test_the_wizard_runs_before_logging_starts(self):
        # Structural, not behavioural, and deliberately so: read -p emits
        # its prompt only to a terminal, so a piped-stdin test sees nothing
        # either way and would pass under both orderings (verified by
        # mutation). The invariant that matters is source order — on a
        # re-run the FR24 prompt carries the stored key as its default, and
        # tee would capture it if logging had already started.
        src = INSTALL.read_text().splitlines()
        wizard = next(i for i, l in enumerate(src) if l.strip() == "run_wizard")
        logging_starts = next(i for i, l in enumerate(src)
                              if l.startswith("exec > >("))
        self.assertLess(wizard, logging_starts,
                        "run_wizard must precede the tee redirection")

    def test_eof_on_a_required_prompt_exits_instead_of_spinning(self):
        # Regression test for a real infinite loop: `read -r -p ... || true`
        # on a *required* prompt (one with no stored default — LAT is the
        # first such prompt the wizard hits) swallowed EOF, leaving `reply`
        # empty forever, so `while :; do ...; done` never terminated.
        # Measured at 433,418 iterations in 5 seconds before the fix.
        # Closed stdin (`ssh box 'sudo ./install.sh'`, or plain Ctrl-D) must
        # fail fast instead. `timeout=5` bounds this test to a clear
        # failure rather than hanging the suite if this ever regresses.
        (self.root / "receiver.conf").unlink(missing_ok=True)
        result = self.run_driver(stdin="", timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no input available", result.stdout + result.stderr)

    def test_pressing_enter_takes_the_default_hostname(self):
        # Bash pre-sets $HOSTNAME at shell startup — from the environment if
        # inherited (confirmed: `HOSTNAME=x bash -c 'echo $HOSTNAME'` prints
        # x, it is not overwritten), otherwise the machine's real hostname.
        # Without an `unset HOSTNAME` ahead of the conditional `conf_load`
        # on a fresh box (no receiver.conf to load one from), `ask
        # HOSTNAME` would see that inherited/machine name as its "current"
        # value and offer it as the default instead of "adsb" — pressing
        # enter would then silently keep whatever the box was already
        # called. HOSTNAME is set explicitly here, to a value that is
        # deterministically wrong, rather than relying on this test
        # machine's ambient hostname (or lack of an inherited HOSTNAME)
        # happening not to already be "adsb".
        (self.root / "receiver.conf").unlink(missing_ok=True)
        self.stage("10-first.sh", "echo ran-10")
        # A bare newline first: that is the "pressed enter" at the HOSTNAME
        # prompt, which answers() is told to leave for us.
        answers = "\n" + self.answers(skip={"HOSTNAME"})
        result = self.run_driver(
            stdin=answers, extra_env={"HOSTNAME": "some-inherited-machine-name"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('HOSTNAME="adsb"',
                      (self.root / "receiver.conf").read_text())

    def test_the_wizard_writes_a_conf_the_next_run_reuses(self):
        # Proves conf_write is actually wired up — it had no caller before
        # this task.
        (self.root / "receiver.conf").unlink(missing_ok=True)
        self.run_driver(stdin=self.answers())
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
            "ADSBX_USER=test\nADSBX_UUID=uuid12345\nFR24_KEY=key123456\n")
        out = self.run_driver("--no-wizard", "--check").stdout
        self.assertIn("--net-bi-port 30004,30104", out)
        self.assertIn('LATITUDE="51.8849826"', out)


class TestHelp(DriverCase):
    def test_help_exits_zero_and_lists_the_flags(self):
        result = self.run_driver("--help")
        self.assertEqual(result.returncode, 0)
        for flag in ("--check", "--from", "--force"):
            self.assertIn(flag, result.stdout)
