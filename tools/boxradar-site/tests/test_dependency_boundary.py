"""The METAR service must stay stdlib-only so it can run on a Debian Pi with
no venv and no pip. The geography generator may use shapely and yaml. This
test is what stops the second set leaking into the first.

It works by source inspection rather than by import, because importing proves
nothing on a dev machine that happens to have shapely installed.
"""

import ast
import pathlib
import unittest

PKG = pathlib.Path(__file__).resolve().parents[1] / "boxradar_site"

SERVICE_MODULES = ["metar.py", "cache.py", "server.py", "upstream.py",
                   "config.py", "__main__.py", "__init__.py"]

# Anything not in the standard library, plus the geo subpackage itself.
FORBIDDEN_IN_SERVICE = {"shapely", "yaml", "boxradar_site.geo", "geo"}


def imported_names(path):
    tree = ast.parse(path.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, e.g. "from .geo import x"
                out.add((node.module or "").split(".")[0])
            elif node.module:
                out.add(node.module.split(".")[0])
    return out


class TestServiceStaysStdlibOnly(unittest.TestCase):
    def test_no_third_party_or_geo_imports(self):
        offenders = {}
        for name in SERVICE_MODULES:
            path = PKG / name
            bad = imported_names(path) & FORBIDDEN_IN_SERVICE
            if bad:
                offenders[name] = sorted(bad)
        self.assertEqual(offenders, {},
                         "service modules must not import shapely, yaml or geo")

    def test_every_service_module_exists(self):
        # Guards against the list above silently drifting from reality.
        for name in SERVICE_MODULES:
            self.assertTrue((PKG / name).is_file(), f"missing {name}")


class TestGeoSubpackageExists(unittest.TestCase):
    def test_geo_is_a_package(self):
        self.assertTrue((PKG / "geo" / "__init__.py").is_file())


if __name__ == "__main__":
    unittest.main()
