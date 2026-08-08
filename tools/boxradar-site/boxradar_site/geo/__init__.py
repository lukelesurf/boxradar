"""Geography generation: airspace and coastline selection and codegen.

Requires PyYAML and shapely. Deliberately a subpackage rather than flat
modules, because it is a dependency boundary: the METAR service under
boxradar_site/ is stdlib-only so it can run on a Debian Pi without a venv,
and tests/test_dependency_boundary.py enforces that nothing here is imported
from there.

Install the dependencies from apt, not pip — Debian's Python is externally
managed (PEP 668), and apt is outside its scope:

    sudo apt install python3-shapely python3-yaml
"""
