"""One build pipeline: selection plus source features in, blob bytes out.

This was inline in the `geo` CLI's main() until the configuration UI needed the
same path. Two implementations of "outlines, then coastline, then sections,
then bytes" would not fail loudly if they diverged — both would emit a valid
blob, and the board would draw whichever site it was handed. So there is one,
and the CLI is now a caller like any other.

Everything that touches the network is a separate function from build(), which
is deliberate: build() is pure, so it can be tested without a git clone or an
Overpass round trip, and a UI can rebuild from an already-fetched dataset
without going back out to the internet on every save.
"""

import pathlib
import subprocess

from . import blob as blobmod
from . import emit

REPO_URL = "https://github.com/ahsparrow/airspace"

# Left unexpanded, and expanded only when actually used. A DynamicUser systemd
# service has no passwd entry and ProtectHome=true takes away what it would
# have read anyway, so Path.expanduser() raises "Could not determine home
# directory" there — at import time, which takes the whole application down
# before main() runs. The CLI never sees it because a shell always has $HOME.
# Callers that pass cache_dir, which is every caller inside the service, never
# reach these at all.
DEFAULT_SOURCE_CACHE = "~/.cache/boxradar-airspace"
DEFAULT_COASTLINE_CACHE = "~/.cache/boxradar-coastline"


def _cache_root(cache_dir, fallback):
    return pathlib.Path(cache_dir) if cache_dir \
        else pathlib.Path(fallback).expanduser()


class SourceMissing(Exception):
    """The YAIXM checkout is not there. Recoverable — fetch it."""


def yaml_path(cache_dir=None):
    return _cache_root(cache_dir, DEFAULT_SOURCE_CACHE) / "airspace" \
        / "airspace.yaml"


def fetch_source(cache_dir=None):
    """git clone or ff-only pull the YAIXM repo. Returns the yaml path."""
    path = yaml_path(cache_dir)
    repo = path.parent
    repo.parent.mkdir(parents=True, exist_ok=True)
    if repo.exists():
        subprocess.run(["git", "-C", str(repo), "pull", "--ff-only"],
                       check=True)
    else:
        subprocess.run(["git", "clone", "--depth", "1", REPO_URL, str(repo)],
                       check=True)
    return path


def load_features(cache_dir=None, fetch=False):
    """The airspace feature list from the cached YAIXM source."""
    if fetch:
        fetch_source(cache_dir)
    path = yaml_path(cache_dir)
    if not path.exists():
        raise SourceMissing(f"{path} not found — fetch the source first")
    import yaml
    # CSafeLoader where libyaml is available, which on a Pi is the difference
    # between about 15 seconds and about one. yaml.safe_load() uses the pure
    # Python loader regardless of whether the C extension is installed, and
    # Debian's python3-yaml does ship it.
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    with path.open() as f:
        return (yaml.load(f, Loader=loader) or {}).get("airspace", []) or []


def load_coastline(sel, cache_dir=None):
    """Coastline segments around home. Hits Overpass unless already cached."""
    from . import coastline
    cache = _cache_root(cache_dir, DEFAULT_COASTLINE_CACHE)
    box = coastline.query_box(sel.home_lat, sel.home_lon)
    return coastline.segments(coastline.fetch(box, cache),
                              sel.home_lat, sel.home_lon)


class Build:
    """The result of one build: what was made, or why it could not be.

    `blob` is None whenever `problems` is non-empty. That coupling lives here
    rather than in each caller because the failure mode it guards against is
    quiet: a selection naming a feature an AIRAC cycle renamed still produces a
    perfectly valid blob, just one with a hole where that airspace used to be.
    Nothing downstream — not the CRC, not the board — can tell that from a site
    that genuinely has no airspace there.
    """

    def __init__(self, outlines, coast, problems, blob, counts):
        self.outlines = outlines
        self.coast = coast
        self.problems = problems
        self.blob = blob
        self._counts = counts  # ordered, so summary() reads consistently

    @property
    def ok(self):
        return not self.problems

    @property
    def counts(self):
        return dict(self._counts)

    def summary(self):
        return ", ".join(f"{n} {name}" for name, n in self._counts)


def build(sel, features, coast=None, coast_loader=None):
    """Build the blob for a selection. Never raises on a bad selection.

    `coast_loader` is a callable used instead of `coast`, and it is called only
    once the selection is known to be sound. Overpass is slow and rate-limited,
    so someone iterating on a selection should be told their feature name is
    wrong before waiting on a coastline they are about to throw away.
    """
    outlines, problems = emit.build_airspace_outlines(sel, features)
    if coast is None and coast_loader is not None and not problems:
        coast = coast_loader()
    coast = list(coast or [])

    sections = {
        # outlines carry [lon, lat] from the GeoJSON convention; the blob
        # stores lat, lon to match the firmware's Vertex.
        blobmod.KIND_AIRSPACE: [[(lat, lon) for lon, lat in ring]
                                for _, ring in outlines],
        blobmod.KIND_COASTLINE: coast,
        blobmod.KIND_AIRFIELDS: sel.airfields,
        blobmod.KIND_RUNWAYS: sel.runways,
        blobmod.KIND_WAYPOINTS: sel.waypoints,
        blobmod.KIND_TOWNS: sel.towns,
    }

    counts = [("airspace", len(sections[blobmod.KIND_AIRSPACE])),
              ("coastline", len(coast)),
              ("airfields", len(sel.airfields)),
              ("runways", len(sel.runways)),
              ("fixes", len(sel.waypoints)),
              ("towns", len(sel.towns))]
    data = None if problems else blobmod.write(sel.home_lat, sel.home_lon,
                                               sections)
    return Build(outlines, coast, problems, data, counts)
