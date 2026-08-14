"""What may depend on what, and on which third-party packages.

The rule this encodes is **"nothing here comes from pip"**, not "nothing here
is outside the standard library". Debian's Python is externally managed under
PEP 668, so pip and a venv are both off the table on the receiver Pi — but apt
is outside PEP 668's scope, which is why shapely and PyYAML were always
acceptable and why Flask is acceptable now. Every name in ALLOWED_THIRD_PARTY
must be installable as a `python3-*` package on bookworm.

Two boundaries, then:

  1. The METAR proxy and contact feed stay stdlib-only. They are what the
     display polls every couple of seconds, and they should not gain shapely,
     Flask, or a reason to restart when the configuration UI is touched. This
     is the stricter of the two rules and it is the one worth defending.

  2. Nothing anywhere imports something that is not on the apt list.

Both work by source inspection rather than by import, because importing proves
nothing on a dev machine that happens to have all of it installed.
"""

import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "boxradar_site"
CONFIG_PKG = ROOT / "boxradar_config"

SERVICE_MODULES = ["metar.py", "cache.py", "server.py", "upstream.py",
                   "config.py", "contacts.py", "feed.py", "presence.py",
                   "aircraft_types.py", "__main__.py", "__init__.py"]

# apt: python3-shapely, python3-yaml, python3-flask (which pulls jinja2,
# werkzeug, click, itsdangerous — all imported by Flask, not by us).
ALLOWED_THIRD_PARTY = {"shapely", "yaml", "flask", "jinja2"}

FIRST_PARTY = {"boxradar_site", "boxradar_config"}

# The geo subpackage, by any spelling a service module could reach it.
FORBIDDEN_IN_SERVICE = {"shapely", "yaml", "flask", "jinja2",
                        "boxradar_site.geo", "geo", "boxradar_config"}


def imported_names(path, relative=True):
    """Top-level names this module imports.

    `relative=False` drops `from .x import y`, which is what the third-party
    check wants: a relative import is first-party by construction, and
    counting its module name would report `from .cache import ...` as a
    dependency on something called "cache". The service boundary check needs
    the opposite — `from .geo import ...` is exactly what it is looking for.
    """
    tree = ast.parse(path.read_text())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, e.g. "from .geo import x"
                if relative:
                    out.add((node.module or "").split(".")[0])
            elif node.module:
                out.add(node.module.split(".")[0])
    return out


def python_files(*roots):
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


class TestServiceStaysStdlibOnly(unittest.TestCase):
    def test_no_third_party_or_geo_imports(self):
        offenders = {}
        for name in SERVICE_MODULES:
            bad = imported_names(PKG / name) & FORBIDDEN_IN_SERVICE
            if bad:
                offenders[name] = sorted(bad)
        self.assertEqual(offenders, {},
                         "service modules must not import shapely, yaml, "
                         "flask, geo or the configuration UI")

    def test_every_service_module_exists(self):
        # Guards against the list above silently drifting from reality.
        for name in SERVICE_MODULES:
            self.assertTrue((PKG / name).is_file(), f"missing {name}")

    def test_the_list_covers_every_service_module(self):
        # A new stdlib-only module added beside these would otherwise be
        # unchecked, and the boundary would erode a file at a time.
        present = {p.name for p in PKG.glob("*.py")}
        self.assertEqual(present, set(SERVICE_MODULES),
                         "a module was added to boxradar_site/ without being "
                         "added to SERVICE_MODULES")


class TestNothingComesFromPip(unittest.TestCase):
    """Every third-party import must be an apt-installable package."""

    def test_only_allowed_third_party_imports(self):
        stdlib = sys.stdlib_module_names
        offenders = {}
        for path in python_files(PKG, CONFIG_PKG):
            outside = {n for n in imported_names(path, relative=False)
                       if n and n not in stdlib and n not in FIRST_PARTY
                       and n not in ALLOWED_THIRD_PARTY}
            if outside:
                offenders[str(path.relative_to(ROOT))] = sorted(outside)
        self.assertEqual(offenders, {},
                         "these imports are not on the apt list — see "
                         "ALLOWED_THIRD_PARTY")


class TestPackageLayout(unittest.TestCase):
    def test_geo_is_a_package(self):
        self.assertTrue((PKG / "geo" / "__init__.py").is_file())

    def test_config_is_a_package(self):
        self.assertTrue((CONFIG_PKG / "__init__.py").is_file())

    def test_the_config_ui_does_not_import_the_service(self):
        # It may use boxradar_site.geo or boxradar_site.metar (for constants).
        # The service half is a running daemon, not a library.
        for path in python_files(CONFIG_PKG):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith("boxradar_site"):
                        self.assertTrue(
                            node.module.startswith("boxradar_site.geo") or
                            node.module.startswith("boxradar_site.metar"),
                            f"{path.name} imports {node.module}")


if __name__ == "__main__":
    unittest.main()
