#!/usr/bin/env python3
"""Extract the enroute fix table from the NATS eAIP ENR 4.4 page.

    python3 tools_import_eaip_fixes.py                    # current AIRAC
    python3 tools_import_eaip_fixes.py --airac 2026-09-03 # a specific one
    python3 tools_import_eaip_fixes.py --from-file x.html # already downloaded
    python3 tools_import_eaip_fixes.py --check            # verify, write nothing

Writes boxradar_config/data/enroute_fixes.csv, which ships with the
application. This is a **developer tool, not part of the service** — it is why
boxradar_config needs no HTML parser and no second network source. Run it when
an AIRAC cycle moves something and commit the result.

5-letter RNAV significant points are the one reference this project cannot
download as data: they appear in no open dataset, only in this published page.
The page turns out to be strongly structured — each point is a <tr id="SP-XXXXX">
carrying spans tagged TDESIGNATED_POINT;GEO_LAT and ;GEO_LONG — so parsing it
is a good deal more honest than transcribing by hand, which is what the phase 4
scoping note assumed would be needed.

The extraction is checked against two points curated independently by hand in
include/location.h long before this tool existed. If those disagree, the page
layout has changed and the output is not to be trusted; the script exits
non-zero rather than writing.
"""

import argparse
import csv
import datetime
import pathlib
import re
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from boxradar_site.geo import yaixm  # noqa: E402

AURORA = ("https://www.aurora.nats.co.uk/htmlAIP/Publications/"
          "{airac}-AIRAC/html/eAIP/EG-ENR-4.4-en-GB.html")
INDEX = "https://nats-uk.ead-it.com/cms-nats/opencms/en/Publications/AIP/"

OUT = (pathlib.Path(__file__).resolve().parent / "boxradar_config" / "data"
       / "enroute_fixes.csv")

# Hand-curated in include/location.h, from a different reading of the same
# publication and years before this parser. They are the check that the page
# still means what it used to.
ANCHORS = {"LOREL": (52.01394, -0.05264), "ABBOT": (52.01611, 0.59958)}
ANCHOR_TOLERANCE_DEG = 1e-4  # ~11m

ROW = re.compile(r'<tr id="SP-([A-Z0-9]+)"(.*?)</tr>', re.S)
LAT = re.compile(r'>([0-9]{6}(?:\.[0-9]+)?[NS])</span>'
                 r'<span class="sdParams"[^>]*>TDESIGNATED_POINT;GEO_LAT')
LON = re.compile(r'>([0-9]{7}(?:\.[0-9]+)?[EW])</span>'
                 r'<span class="sdParams"[^>]*>TDESIGNATED_POINT;GEO_LONG')
NOTE = re.compile(r'>([^<>]{1,60})</span><span class="sdParams"[^>]*>'
                  r'TDESIGNATED_POINT;ANNOTATION')


def current_airac():
    """The most recent AIRAC folder that is not in the future."""
    with urllib.request.urlopen(INDEX, timeout=60) as response:
        page = response.read().decode("utf-8", "replace")
    dates = sorted(set(re.findall(
        r"htmlAIP/Publications/(\d{4}-\d{2}-\d{2})-AIRAC/", page)))
    if not dates:
        raise SystemExit("could not find any AIRAC cycle on the index page")
    today = datetime.date.today().isoformat()
    live = [d for d in dates if d <= today]
    return live[-1] if live else dates[0]


def parse(html):
    """[(ident, lat, lon, note)] and a list of rows that would not parse."""
    out, problems = [], []
    for ident, body in ROW.findall(html):
        lat, lon = LAT.search(body), LON.search(body)
        if not (lat and lon):
            problems.append(ident)
            continue
        try:
            dec_lat, dec_lon = yaixm.parse_latlon(
                f"{lat.group(1)} {lon.group(1)}")
        except ValueError as e:
            problems.append(f"{ident}: {e}")
            continue
        note = NOTE.search(body)
        text = (note.group(1).strip() if note else "")
        out.append((ident, dec_lat, dec_lon,
                    "" if text in ("", "&#160;") else text))
    out.sort()
    return out, problems


def check_anchors(fixes):
    found = {ident: (lat, lon) for ident, lat, lon, _ in fixes}
    failures = []
    for ident, (want_lat, want_lon) in ANCHORS.items():
        got = found.get(ident)
        if got is None:
            failures.append(f"{ident} is not in the extracted table")
            continue
        if (abs(got[0] - want_lat) > ANCHOR_TOLERANCE_DEG
                or abs(got[1] - want_lon) > ANCHOR_TOLERANCE_DEG):
            failures.append(f"{ident} extracted as {got[0]:.5f},{got[1]:.5f} "
                            f"but location.h has {want_lat},{want_lon}")
    return failures


def write(fixes, airac, url):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        f.write(
            "# Enroute (RNAV) significant points — the one dataset with no\n"
            "# machine-readable source. Extracted from the UK eAIP ENR 4.4\n"
            "# table by tools_import_eaip_fixes.py; re-run it when an AIRAC\n"
            "# cycle moves something rather than editing rows by hand.\n"
            "#\n"
            f"#   AIRAC:  {airac}\n"
            f"#   source: {url}\n"
            "#\n"
            "# Contains public UK AIP data about published airspace\n"
            "# structure, Crown copyright, reproduced for non-commercial use\n"
            "# — the same basis as the AIP-derived tables in\n"
            "# include/location.h. Not for navigation.\n"
            "#\n"
            "# 3-letter VOR/NDB idents are NOT here: those come from\n"
            "# OurAirports navaids.csv, which the configuration UI downloads.\n"
            "#\n"
            "# ident,lat,lon,note\n")
        writer = csv.writer(f)
        for ident, lat, lon, note in fixes:
            writer.writerow([ident, f"{lat:.5f}", f"{lon:.5f}", note])


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--airac", help="cycle folder, e.g. 2026-08-06")
    p.add_argument("--from-file", help="parse a local copy instead")
    p.add_argument("--check", action="store_true",
                   help="parse and verify, write nothing")
    args = p.parse_args(argv)

    if args.from_file:
        html = pathlib.Path(args.from_file).read_text(errors="replace")
        airac, url = args.airac or "unknown", args.from_file
    else:
        airac = args.airac or current_airac()
        url = AURORA.format(airac=airac)
        print(f"fetching {url}", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=180) as response:
            html = response.read().decode("utf-8", "replace")

    fixes, problems = parse(html)
    print(f"parsed {len(fixes)} significant points from AIRAC {airac}",
          file=sys.stderr)
    if problems:
        # Reported, never silently dropped: a layout change that halved the
        # table would otherwise look like a successful extraction.
        print(f"WARNING: {len(problems)} row(s) would not parse: "
              f"{problems[:10]}", file=sys.stderr)

    failures = check_anchors(fixes)
    if failures:
        for failure in failures:
            print(f"ANCHOR FAILED: {failure}", file=sys.stderr)
        print("refusing to write — the page layout has probably changed",
              file=sys.stderr)
        return 1
    print(f"anchors agree with include/location.h: "
          f"{', '.join(sorted(ANCHORS))}", file=sys.stderr)

    if len(fixes) < 500:
        print(f"refusing to write: {len(fixes)} points is far fewer than the "
              f"~1000 this table normally holds", file=sys.stderr)
        return 1

    if args.check:
        print("--check given, nothing written", file=sys.stderr)
        return 0
    write(fixes, airac, url)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
