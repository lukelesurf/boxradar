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
import sys

PX_PER_NM_OVERVIEW = 2.2  # 50nm overview, per docs/viewport-design.md


def main(argv=None):
    p = argparse.ArgumentParser(prog="boxradar_site.geo")
    p.add_argument("command", choices=["list", "suggest", "build"])
    p.add_argument("--selection", required=True)
    p.add_argument("--out", help="write the airspace C header here")
    p.add_argument("--blob", help="also write the binary geography blob")
    p.add_argument("--coastline-out",
                   help="write the coastline C header here (needs Overpass)")
    p.add_argument("--coastline", action="store_true",
                   help="include coastline in the blob (needs Overpass)")
    p.add_argument("--fetch", action="store_true",
                   help="git pull the YAIXM source first")
    p.add_argument("--kind", action="append",
                   help="restrict the listing to a kind (repeatable)")
    args = p.parse_args(argv)

    from . import catalog, emit, generate, rules, selection
    sel = selection.load(args.selection)
    try:
        features = generate.load_features(fetch=args.fetch)
    except generate.SourceMissing as e:
        raise SystemExit(f"{e} — run with --fetch")

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

    want_coast = args.coastline or args.coastline_out
    result = generate.build(
        sel, features,
        coast_loader=(lambda: generate.load_coastline(sel)) if want_coast
        else None)

    for problem in result.problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    if not result.ok:
        return 1

    if args.out:
        pathlib.Path(args.out).write_text(emit.render_header(result.outlines))
        total = sum(len(r) for _, r in result.outlines)
        print(f"wrote {args.out}: {len(result.outlines)} outlines, "
              f"{total} vertices", file=sys.stderr)
    elif not args.blob and not args.coastline_out:
        sys.stdout.write(emit.render_header(result.outlines))

    if args.coastline_out:
        from . import coastline
        pathlib.Path(args.coastline_out).write_text(
            coastline.render_header(result.coast))
        print(f"wrote {args.coastline_out}: {len(result.coast)} segments, "
              f"{sum(len(s) for s in result.coast)} points", file=sys.stderr)

    if args.blob:
        pathlib.Path(args.blob).write_bytes(result.blob)
        print(f"wrote {args.blob}: {len(result.blob)} bytes "
              f"({result.summary()})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
