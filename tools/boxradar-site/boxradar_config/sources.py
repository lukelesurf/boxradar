"""Everything that has to be downloaded before a site can be built.

Five things: the UK airspace dataset and four reference files. They arrive by
two different mechanisms — a git checkout for the airspace, HTTP downloads for
the rest — and that difference is real. `datasets.SOURCES` entries are
(url, filename, member) tuples fetched with urllib and unzipped; the airspace
source is a shallow git clone that is then pulled. Forcing a git URL into that
tuple would make the registry lie about what it holds.

So the join happens here instead, one layer up, where the only two questions
are "how old is it" and "go and get it". The Data page and the progress strip
both ask exactly those and should not have to know which mechanism answers.

An unknown name raises KeyError rather than reading as absent. The two are
very different: "not downloaded" invites a fetch, and offering to fetch
something that does not exist would loop forever.
"""

from boxradar_site.geo import generate

from . import datasets

AIRSPACE = "airspace"

# Airspace first: everything else is a point reference layered onto the map,
# and this is what the picker is a picker OF. It is also what blocks the most
# when absent — no catalog, no preview, no publish.
ALL = (AIRSPACE,) + tuple(datasets.SOURCES)

PURPOSE = {
    AIRSPACE: "the airspace catalog itself — CTRs, CTAs, TMAs",
    "airports": "airfield markers, by ICAO",
    "runways": "extended centrelines — both thresholds",
    "navaids": "VOR/NDB idents on the Fixes page",
    "towns": "ground references, ranked by population",
}

ORIGIN = {
    AIRSPACE: "github.com/ahsparrow/airspace (git)",
    "airports": "OurAirports",
    "runways": "OurAirports",
    "navaids": "OurAirports",
    "towns": "GeoNames",
}


def _check(name):
    if name not in ALL:
        raise KeyError(f"unknown source: {name!r}")


def age_days(name, settings):
    """Days since this Pi last fetched it, or None if it is not there.

    For the airspace source that is the yaml's mtime rather than anything from
    git: what matters is when this box last pulled, not when the upstream
    commit was authored.
    """
    _check(name)
    if name == AIRSPACE:
        path = generate.yaml_path(settings.source_cache)
        if not path.exists():
            return None
        import time
        return (time.time() - path.stat().st_mtime) / 86400.0
    return datasets.age_days(name, settings.cache_dir)


def missing(settings):
    """The absent ones, in canonical order."""
    return [name for name in ALL if age_days(name, settings) is None]


def fetch(name, settings, progress=None, fetcher=None, source_fetcher=None):
    """Go and get one source.

    `progress(done, total)` is called as it goes. `total` is None when there is
    no measurable size — the git checkout is a subprocess, so reporting a total
    of zero would render as a 0% bar that never moves, which reads as a hang
    rather than as "this step has no byte count".

    The two fetchers are injectable so the tests never open a socket or shell
    out to git.
    """
    _check(name)
    if name == AIRSPACE:
        if progress:
            progress(0, None)
        result = (source_fetcher or generate.fetch_source)(
            cache_dir=settings.source_cache)
        if progress:
            progress(1, None)
        return result
    return (fetcher or datasets.fetch)(name, settings.cache_dir,
                                       progress=progress)
