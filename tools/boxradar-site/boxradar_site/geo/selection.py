"""The selection config: which airspace this site draws.

Structurally this is CURATED_AIRPORTS in JSON, and that is deliberate — the
transcription has to be faithful enough that the generated header is unchanged
on day one, so the first thing verified is "nothing moved".

`primary` is the feature drawn on its own, emitted as <NAME>_CTR. `envelope`
lists features merged WITH the primary into <NAME>_ENV. Grouping is explicit
rather than inferred, which is what makes the dataset's awkward case ordinary:
Heathrow has no HEATHROW feature, because its zone is LONDON CTR and its CTA
is the London TMA, so it is simply a primary with an empty envelope.

Unlike the METAR config, load() RAISES on a malformed file. A bad runway table
costs a runway recommendation; a bad selection would silently produce a map
missing airspace, and there is nothing safe to fall back to.
"""

import json

DEFAULT_REACH_NM = 65.0


class Group:
    def __init__(self, name, primary, envelope=None):
        self.name = name
        self.primary = primary
        self.envelope = list(envelope or [])

    def feature_names(self):
        return [self.primary] + self.envelope

    def __repr__(self):
        return f"<Group {self.name} primary={self.primary!r} " \
               f"envelope={self.envelope}>"


class Selection:
    def __init__(self, home_lat, home_lon, reach_nm, groups):
        self.home_lat = home_lat
        self.home_lon = home_lon
        self.reach_nm = reach_nm
        self.groups = groups

    def feature_names(self):
        out = []
        for g in self.groups:
            out.extend(g.feature_names())
        return out


def load(path):
    try:
        with open(path, "r") as f:
            raw = json.load(f)
    except FileNotFoundError as e:
        raise ValueError(f"selection config not found: {path}") from e
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"cannot read {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")
    for key in ("home_lat", "home_lon"):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path}: {key} missing or not a number")
    reach = raw.get("reach_nm", DEFAULT_REACH_NM)
    if isinstance(reach, bool) or not isinstance(reach, (int, float)):
        raise ValueError(f"{path}: reach_nm must be a number")

    groups, seen = [], set()
    entries = raw.get("airspace", [])
    if not isinstance(entries, list):
        raise ValueError(f"{path}: airspace must be a list")
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: airspace[{i}] is not an object")
        name = entry.get("name")
        primary = entry.get("primary")
        if not name:
            raise ValueError(f"{path}: airspace[{i}] has no name")
        if not primary:
            raise ValueError(f"{path}: airspace[{i}] ({name}) has no primary")
        if name in seen:
            raise ValueError(f"{path}: duplicate group name {name!r} — the "
                             f"generated symbols would collide")
        seen.add(name)
        envelope = entry.get("envelope", [])
        if not isinstance(envelope, list):
            raise ValueError(f"{path}: {name} envelope must be a list")
        groups.append(Group(str(name), str(primary),
                            [str(e) for e in envelope]))

    return Selection(float(raw["home_lat"]), float(raw["home_lon"]),
                     float(reach), groups)


def missing_features(sel, features):
    """Selected names that no longer exist in the dataset, in config order.

    The YAIXM source is updated, and a renamed feature would otherwise vanish
    from the map silently. find_feature() in the old generator was right to
    fail loudly on an unknown name; this is that behaviour made reportable
    rather than fatal, so a UI can say "2 selected features no longer exist".
    """
    available = {str(f.get("name") or "") for f in features}
    missing, seen = [], set()
    for name in sel.feature_names():
        if name not in available and name not in seen:
            seen.add(name)
            missing.append(name)
    return missing
