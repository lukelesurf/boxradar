"""The reference datasets the pickers search, and their on-disk cache.

Three sources, chosen in the phase 4 scoping note and confirmed against the
values already curated by hand in include/location.h:

  OurAirports airports.csv   airfield reference points, by ICAO
  OurAirports runways.csv    runway thresholds — both ends, so the axis is the
                             two points rather than a published heading
  OurAirports navaids.csv    VOR/NDB/DME, the 3-letter half of "fixes"
  GeoNames GB.txt            towns, with population

Spot-checked at build time: Barkway VOR comes back as 51.98970/0.06194 and
Brookmans Park as 51.74970/-0.10667, matching location.h to the decimal.

**Enroute fixes are not here.** 5-letter RNAV fixes (LOREL, ABBOT) appear in
none of the above; they are published only in the NATS eAIP ENR 4.4 table.
They live in a curated CSV instead — see fixes.py.

Everything is filtered to a bounding box before it reaches a picker. That is a
correctness requirement rather than a convenience: OurAirports idents are not
globally unique, and BKY is Barkway in Hertfordshire *and* Bouaké in Côte
d'Ivoire. An unscoped search by ident can silently place a West African VOR on
an Essex map.
"""

import csv
import io
import pathlib
import time
import shutil
import urllib.request
import zipfile
from collections import namedtuple

OURAIRPORTS = "https://davidmegginson.github.io/ourairports-data/"
GEONAMES_GB = "https://download.geonames.org/export/dump/GB.zip"

# GB.txt is 14MB and airports.csv 12MB, so the whole set is about 32MB on the
# Pi. Small enough to keep whole and re-filter per site, which is what lets the
# search reach change without a re-download.
SOURCES = {
    "airports": (OURAIRPORTS + "airports.csv", "airports.csv", None),
    "runways": (OURAIRPORTS + "runways.csv", "runways.csv", None),
    "navaids": (OURAIRPORTS + "navaids.csv", "navaids.csv", None),
    "towns": (GEONAMES_GB, "GB.txt", "GB.txt"),
}

# OurAirports `type`. Everything smaller than this is a farm strip, a private
# helipad or a gliding field, and including them buries the fields a person
# would actually recognise. Widened per-request by the picker, never here.
AIRPORT_TYPES = ("large_airport", "medium_airport", "small_airport")
DEFAULT_AIRPORT_TYPES = ("large_airport", "medium_airport")

# GeoNames feature class P is "populated place".
TOWN_CLASS = "P"

Airfield = namedtuple("Airfield", "ident name kind lat lon municipality")
Runway = namedtuple("Runway", "airport ident lat0 lon0 lat1 lon1 length_ft")
Navaid = namedtuple("Navaid", "ident name kind lat lon")
Town = namedtuple("Town", "uid name lat lon population")


class DatasetMissing(Exception):
    """Not downloaded yet. Recoverable — fetch it."""


def dataset_dir(cache_dir):
    return pathlib.Path(cache_dir) / "datasets"


def path_for(name, cache_dir):
    return dataset_dir(cache_dir) / SOURCES[name][1]


def age_days(name, cache_dir):
    """How stale the cached copy is, or None if it is not there."""
    path = path_for(name, cache_dir)
    if not path.exists():
        return None
    return (time.time() - path.stat().st_mtime) / 86400.0


# 64KB. Small enough that progress moves visibly on a slow wifi link, large
# enough that the per-chunk overhead is nothing against a 14MB file.
CHUNK = 65536


def _content_length(response):
    """Total bytes if the response says, else None.

    None means "count up, no percentage". Reporting a total that is not known
    would render as a bar that jumps or sticks, which is worse than a bare
    byte count. Test fakes are plain BytesIO objects and have no headers at
    all, which is exactly the unknown-length case.
    """
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    try:
        total = int(headers.get("Content-Length"))
    except (TypeError, ValueError):
        return None
    return total if total > 0 else None


def fetch(name, cache_dir, opener=None, progress=None):
    """Download one dataset into the cache. Returns its path.

    Streamed to disk in chunks rather than read whole. The set is about 32MB
    and GB.zip is the biggest of it, so reading a payload into memory cost a
    Pi with 906MB — a third of it already gone to the desktop — a 14MB spike
    per dataset. Chunking is also what makes `progress(done, total)` possible
    at all.
    """
    url, filename, member = SOURCES[name]
    target = dataset_dir(cache_dir) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    opener = opener or (lambda u: urllib.request.urlopen(u, timeout=180))

    # Same directory so the rename is atomic: a half-downloaded 14MB file left
    # where the parser looks would be read as a truncated dataset rather than
    # as a failure.
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        with opener(url) as response:
            total = _content_length(response)
            done = 0
            with tmp.open("wb") as out:
                while True:
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)

        if member:
            # Extracted from the file on disk rather than from memory, so a
            # 14MB archive never becomes 28MB of resident payload.
            extracted = target.with_suffix(target.suffix + ".zip-part")
            try:
                with zipfile.ZipFile(tmp) as archive:
                    with archive.open(member) as src, \
                            extracted.open("wb") as out:
                        shutil.copyfileobj(src, out, CHUNK)
                extracted.replace(target)
            finally:
                extracted.unlink(missing_ok=True)
            tmp.unlink(missing_ok=True)
        else:
            tmp.replace(target)
    except BaseException:
        # Nothing half-written may be left where the parser looks, and a
        # stray .part beside the real file would be picked up by anything
        # globbing the directory.
        tmp.unlink(missing_ok=True)
        raise
    return target


def require(name, cache_dir):
    path = path_for(name, cache_dir)
    if not path.exists():
        raise DatasetMissing(f"{name} not downloaded — fetch it first")
    return path


def _rows(path, delimiter=","):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f, delimiter=delimiter):
            yield row


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _in_box(lat, lon, box):
    south, north, west, east = box
    return south <= lat <= north and west <= lon <= east


def airfields(cache_dir, box, types=DEFAULT_AIRPORT_TYPES):
    """Airfields in the box, largest class first then by name."""
    out = []
    for row in _rows(require("airports", cache_dir)):
        if row.get("type") not in types:
            continue
        lat, lon = _float(row.get("latitude_deg")), _float(
            row.get("longitude_deg"))
        if lat is None or lon is None or not _in_box(lat, lon, box):
            continue
        # `ident` is the ICAO code for real airfields and a synthetic key
        # (GB-0123) for the rest. The blob label has to be the ICAO, so a
        # field without one cannot be drawn.
        ident = (row.get("ident") or "").strip()
        if len(ident) != 4 or not ident.isalnum():
            continue
        out.append(Airfield(ident.upper(), row.get("name") or ident,
                            row.get("type") or "", lat, lon,
                            row.get("municipality") or ""))
    order = {kind: i for i, kind in enumerate(AIRPORT_TYPES)}
    out.sort(key=lambda a: (order.get(a.kind, 99), a.name))
    return out


def runways(cache_dir, idents):
    """Runways for the given airfield ICAOs, as full axes.

    Both thresholds or nothing: the axis is taken from the two points rather
    than from a published heading, because location.h records that published
    headings sometimes disagree with their own threshold coordinates by more
    than a degree. A runway with one end missing has no axis.
    """
    wanted = {i.upper() for i in idents}
    out = []
    for row in _rows(require("runways", cache_dir)):
        airport = (row.get("airport_ident") or "").upper()
        if airport not in wanted or row.get("closed") == "1":
            continue
        lat0, lon0 = _float(row.get("le_latitude_deg")), _float(
            row.get("le_longitude_deg"))
        lat1, lon1 = _float(row.get("he_latitude_deg")), _float(
            row.get("he_longitude_deg"))
        if None in (lat0, lon0, lat1, lon1):
            continue
        label = f"{row.get('le_ident') or '?'}/{row.get('he_ident') or '?'}"
        out.append(Runway(airport, label, lat0, lon0, lat1, lon1,
                          _float(row.get("length_ft")) or 0.0))
    out.sort(key=lambda r: (r.airport, -r.length_ft))
    return out


def navaids(cache_dir, box, country="GB"):
    """Navaids in the box. Country is a coarse pre-filter, the box decides."""
    out = []
    for row in _rows(require("navaids", cache_dir)):
        if country and row.get("iso_country") != country:
            continue
        lat, lon = _float(row.get("latitude_deg")), _float(
            row.get("longitude_deg"))
        if lat is None or lon is None or not _in_box(lat, lon, box):
            continue
        ident = (row.get("ident") or "").strip().upper()
        if not ident:
            continue
        out.append(Navaid(ident, row.get("name") or ident,
                          row.get("type") or "", lat, lon))
    out.sort(key=lambda n: n.ident)
    return out


# GeoNames dumps are headerless TSV; these are the columns we use, from the
# readme.txt shipped inside GB.zip.
_GEONAMES_COLUMNS = ["geonameid", "name", "asciiname", "alternatenames",
                     "latitude", "longitude", "feature_class", "feature_code",
                     "country_code", "cc2", "admin1", "admin2", "admin3",
                     "admin4", "population"]


def towns(cache_dir, box, min_population=0):
    """Populated places in the box, largest population first.

    Population **ranks** and never gates: the phase 4 note is explicit that a
    village you happen to know is a legitimate ground reference. min_population
    exists to make a long list readable, and defaults to keeping everything.
    """
    out = []
    path = require("towns", cache_dir)
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            if len(row) < len(_GEONAMES_COLUMNS):
                continue
            record = dict(zip(_GEONAMES_COLUMNS, row))
            if record["feature_class"] != TOWN_CLASS:
                continue
            lat, lon = _float(record["latitude"]), _float(record["longitude"])
            if lat is None or lon is None or not _in_box(lat, lon, box):
                continue
            population = int(_float(record["population"]) or 0)
            if population < min_population:
                continue
            out.append(Town(record["geonameid"], record["name"], lat, lon,
                            population))
    out.sort(key=lambda t: (-t.population, t.name))
    return out
