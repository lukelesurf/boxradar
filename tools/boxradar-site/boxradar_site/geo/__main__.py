"""Geography generation CLI.

    python3 -m boxradar_site.geo list      --selection sel.json
    python3 -m boxradar_site.geo suggest   --selection sel.json
    python3 -m boxradar_site.geo build     --selection sel.json --out path.h

`list` is the candidate catalog as a table — the thing that replaces having to
know your local CTRs by their YAIXM names. `suggest` shows what the four
default rules would tick, and why it rejected the rest.
"""

import argparse
import pathlib
import subprocess
import sys

CACHE_DIR = pathlib.Path("~/.cache/boxradar-airspace").expanduser()
REPO_DIR = CACHE_DIR / "airspace"
YAML_PATH = REPO_DIR / "airspace.yaml"
REPO_URL = "https://github.com/ahsparrow/airspace"

PX_PER_NM_OVERVIEW = 2.2  # 50nm overview, per docs/viewport-design.md


def fetch_source():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if REPO_DIR.exists():
        subprocess.run(["git", "-C", str(REPO_DIR), "pull", "--ff-only"],
                       check=True)
    else:
        subprocess.run(["git", "clone", "--depth", "1", REPO_URL,
                        str(REPO_DIR)], check=True)


def load_features(fetch):
    if fetch:
        fetch_source()
    if not YAML_PATH.exists():
        raise SystemExit(f"{YAML_PATH} not found — run with --fetch")
    import yaml
    with YAML_PATH.open() as f:
        return yaml.safe_load(f).get("airspace", [])


def main(argv=None):
    p = argparse.ArgumentParser(prog="boxradar_site.geo")
    p.add_argument("command", choices=["list", "suggest", "build"])
    p.add_argument("--selection", required=True)
    p.add_argument("--out")
    p.add_argument("--fetch", action="store_true",
                   help="git pull the YAIXM source first")
    p.add_argument("--kind", action="append",
                   help="restrict the listing to a kind (repeatable)")
    args = p.parse_args(argv)

    from . import catalog, emit, rules, selection
    sel = selection.load(args.selection)
    features = load_features(args.fetch)

    gone = selection.missing_features(sel, features)
    if gone:
        print(f"WARNING: {len(gone)} selected feature(s) no longer in the "
              f"dataset: {', '.join(gone)}", file=sys.stderr)

    if args.command in ("list", "suggest"):
        cands = catalog.catalog(features, sel.home_lat, sel.home_lon,
                                sel.reach_nm)
        if args.command == "list":
            if args.kind:
                cands = [c for c in cands if c.kind in args.kind]
            print(f"{'dist':>5} {'size':>5} {'px':>5} {'verts':>6} "
                  f"{'kind':<12} name")
            for c in cands:
                print(f"{c.distance_nm:>5.0f} {c.diag_nm:>5.0f} "
                      f"{c.diag_px(PX_PER_NM_OVERVIEW):>5.0f} "
                      f"{c.vertices:>6} {c.kind:<12} {c.name}")
            print(f"\n{len(cands)} features, "
                  f"{sum(c.vertices for c in cands)} vertices")
            return 0
        accepted, rejected = rules.suggest(cands)
        print(f"SUGGESTED ({len(accepted)}):")
        for c in accepted:
            print(f"  {c.name}  [{c.kind}] "
                  f"{c.diag_px(PX_PER_NM_OVERVIEW):.0f}px "
                  f"@{c.distance_nm:.0f}nm")
        print(f"\nREJECTED ({len(rejected)}), largest first:")
        for c, reason in sorted(rejected, key=lambda t: -t[0].diag_nm)[:15]:
            print(f"  {c.name}: {reason}")
        return 0

    outlines, problems = emit.build_airspace_outlines(sel, features)
    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    if problems:
        return 1
    text = emit.render_header(outlines)
    if args.out:
        pathlib.Path(args.out).write_text(text)
        total = sum(len(r) for _, r in outlines)
        print(f"wrote {args.out}: {len(outlines)} outlines, {total} vertices",
              file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
