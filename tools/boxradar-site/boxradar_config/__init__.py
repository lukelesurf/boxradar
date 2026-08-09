"""BOXRADAR site configuration UI.

A separate application from `boxradar_site` on purpose, and the reason is the
dependency list rather than the code size. The METAR proxy and contact feed are
what the display polls about every two seconds; they are stdlib-only and should
not gain Flask, shapely or yaml, nor a reason to restart when the config UI is
touched. This package may have all three because nothing depends on it being
up: it is used once when a site is set up, and lighttpd serves its output.

Both run on the receiver Pi from the same installed tree. The boundary is
enforced by tests/test_dependency_boundary.py.
"""

VERSION = "0.1.0"
