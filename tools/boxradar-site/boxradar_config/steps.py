"""The wizard's spine: six ordered steps and the state of each.

The old UI presented seven tabs as peers when they are actually a dependency
chain, and enforced the chain with redirects instead of showing it — you found
out the airspace source was missing by being bounced off the page you asked
for, and `need_datasets()` did the same thing to the pickers. This module makes
that order visible so the redirects become a fallback rather than the interface.

**This code is on every page render, so it may only stat() files and read the
Selection the request already loaded.** No catalog, no dataset filter, no
coastline. Those cost a second or more each on a Pi, which is why app.py
memoises them on mtime; a progress rail that reached for them would put that
cost back onto every request including the cheap ones.
test_config_steps.TestCost enforces this by making the expensive calls raise.

Two states are worth naming explicitly:

BLOCKED   the step cannot be done yet because something earlier is missing.
          Better than a redirect: it says why, in place, without moving you.
STALE     Publish only. The blob is older than the selection, so what the board
          is drawing is not what is on screen. Every save in the old UI flashed
          "Publish to rebuild the map" and nothing ever said whether you had.
"""

import time

from boxradar_site.geo import generate

from . import datasets

TODO = "todo"
DONE = "done"
BLOCKED = "blocked"
STALE = "stale"
OPTIONAL = "optional"


class Step:
    def __init__(self, key, label, route, state, detail="", active=False):
        self.key = key
        self.label = label
        self.route = route
        self.state = state
        self.detail = detail
        self.active = active

    @property
    def mark(self):
        """The glyph for the rail. Plain text — this is a server-rendered
        page on a Pi and an icon font would be a download for no gain."""
        return {DONE: "✔", BLOCKED: "✗", STALE: "!",
                OPTIONAL: "•"}.get(self.state, "○")

    def __repr__(self):
        return f"<Step {self.key} {self.state} {self.detail!r}>"


def _plural(n, singular, plural=None):
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def _ago(seconds):
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{int(seconds // 60)}m ago"
    if seconds < 172800:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def have_source(settings):
    return generate.yaml_path(settings.source_cache).exists()


def _site_step(settings, sel):
    if sel is None:
        return TODO, "not set"
    return DONE, f"{sel.home_lat:.3f}, {sel.home_lon:.3f} · {sel.reach_nm:g}nm"


def _data_step(settings, sel):
    """The airspace source counts as a dataset here, deliberately.

    It is a prerequisite in exactly the way the four downloads are. Keeping it
    as a separate hidden concept is what produced source.html as a surprise
    interstitial on the Airspace tab.
    """
    names = list(datasets.SOURCES)
    ages = [datasets.age_days(n, settings.cache_dir) for n in names]
    present = [a for a in ages if a is not None]
    total = len(names) + 1
    have = len(present) + (1 if have_source(settings) else 0)
    if have < total:
        return TODO, f"{have} of {total} downloaded"
    oldest = max(present) if present else 0
    return DONE, f"{total} sets · oldest {oldest}d"


def _airspace_step(settings, sel):
    if not have_source(settings):
        return BLOCKED, "needs the airspace source"
    groups = len(sel.groups) if sel else 0
    if not groups:
        return TODO, "nothing selected"
    return DONE, _plural(groups, "group")


def _points_step(settings, sel):
    absent = [n for n in ("airports", "runways", "towns")
              if datasets.age_days(n, settings.cache_dir) is None]
    if absent:
        return BLOCKED, f"needs {', '.join(absent)}"
    counts = [
        (len(sel.airfields) if sel else 0, "airfield", None),
        (len(sel.waypoints) if sel else 0, "fix", "fixes"),
        (len(sel.towns) if sel else 0, "town", None),
    ]
    if not any(n for n, _, _ in counts):
        return TODO, "nothing picked"
    return DONE, " · ".join(_plural(n, s, p) for n, s, p in counts)


def _device_step(settings, sel):
    """Always available, never "done".

    There is no stored state on the Pi saying the board has been configured,
    and inventing one would make the Pi a second authority for the board's NVS
    — the inversion site_config.h warns about in capitals. The board's address
    and liveness come from the display service on :8081, and asking for them
    here would put an HTTP round trip into every page render, so the device
    page asks for itself.
    """
    return OPTIONAL, ""


def _publish_step(settings, sel):
    blob = _mtime(settings.blob_path)
    if blob is None:
        return TODO, "never published"
    selection_at = _mtime(settings.selection_path)
    if selection_at is not None and selection_at > blob:
        return STALE, "selection changed since publishing"
    return DONE, f"published {_ago(max(0.0, time.time() - blob))}"


_STEPS = [
    ("site", "Site", "/site", _site_step),
    ("data", "Data", "/data", _data_step),
    ("airspace", "Airspace", "/airspace", _airspace_step),
    ("points", "Points", "/points", _points_step),
    ("device", "Device", "/device", _device_step),
    ("publish", "Publish", "/preview", _publish_step),
]


def rail(settings, sel, current):
    """Every step, in dependency order, with its state.

    `sel` is passed in rather than loaded because the caller already has it —
    reloading it here would parse the same JSON twice per request.
    """
    out = []
    for key, label, route, evaluate in _STEPS:
        state, detail = evaluate(settings, sel)
        out.append(Step(key, label, route, state, detail, active=key == current))
    return out


def next_action(rail_steps):
    """The one thing to do next, for the landing page.

    Returns the first step that is not finished, skipping the optional one. A
    single named next action is the thing the flat tab layout could never give:
    it knew the order internally and expressed it only as a redirect.
    """
    for step in rail_steps:
        if step.state in (TODO, BLOCKED, STALE):
            return step
    return None
