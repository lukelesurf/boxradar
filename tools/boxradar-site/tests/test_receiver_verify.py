"""60-verify's reading of mlat-client's journal.

adsb.lol and adsb.fi run the same mlat-client fork, which logs
"Results:  N positions/minute" every minute whether or not it is connected.
Matching the line alone passed a client that was disconnected and solving
nothing — found on a box whose feeders were deliberately cut off.
"""

import os
import pathlib
import subprocess
import unittest

VERIFY_SH = (pathlib.Path(__file__).resolve().parents[2]
             / "receiver-install" / "lib" / "verify.sh")

DISCONNECTED = """\
adsblol-mlat[10740]: Receiver: disconnected    0.0 msg/s received        0.0 msg/s processed (0%)
adsblol-mlat[10740]: Server:   disconnected    0.0 kB/s from server      0.0 kB/s to server
adsblol-mlat[10740]: Results:  0.0 positions/minute
"""
WORKING = """\
adsblol-mlat[1]: Results:  0.0 positions/minute
adsblol-mlat[1]: Server:   connected       1.2 kB/s from server      0.3 kB/s to server
adsblol-mlat[1]: Results:  132.9 positions/minute
"""


def returning(log):
    result = subprocess.run(
        ["bash", "-c", f'set -euo pipefail; source "{VERIFY_SH}"; '
                       'mlat_returning_positions "$LOG"'],
        env=dict(os.environ, LOG=log), capture_output=True, text=True)
    return result.returncode == 0


class MlatReturningPositionsTest(unittest.TestCase):
    def test_zero_positions_is_not_returning(self):
        self.assertFalse(returning(DISCONNECTED))

    def test_latest_nonzero_rate_is_returning(self):
        self.assertTrue(returning(WORKING))

    def test_the_latest_line_wins(self):
        # A client that solved once and has since lost its server.
        self.assertFalse(returning(WORKING + DISCONNECTED))

    def test_no_results_line_is_not_returning(self):
        self.assertFalse(returning("adsblol-mlat[1]: starting\n"))
        self.assertFalse(returning(""))


if __name__ == "__main__":
    unittest.main()
