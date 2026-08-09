"""The configuration UI.

Kept to APIs common to Flask 2.2 and 3.x: the receiver Pi has bookworm's
python3-flask 2.2.2 and this repo's devShell has 3.1, the same split as
shapely 1.8 against 2.x. Nothing here needs a feature newer than 2.2.

The application owns no geography logic. Everything it does is already tested
in boxradar_site.geo — the catalog is the picker's data source, `rules` is the
Suggest button, and `generate` builds the blob. This is presentation plus a
file to write, which is what the phase 4 scoping note said it should be.
"""

import secrets

from flask import (Flask, flash, redirect, render_template, request,
                   url_for)

from boxradar_site.geo import catalog, generate, rules, selection

from . import VERSION, datasets, fixes as fixesmod, picks, preview, store
from .settings import Settings

# The town map, in CSS pixels. Not the panel's 240x320 — this is a picker, and
# a map you choose from wants to be bigger than the one you end up with.
MAP_W, MAP_H = 640, 640


def create_app(settings=None):
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    app.config["SETTINGS"] = settings
    # Only signs flash cookies. Regenerated per start deliberately: there is
    # nothing here worth persisting a key for, and a restart losing a flash
    # message is not a defect.
    app.secret_key = secrets.token_bytes(32)

    def load_selection():
        return store.load(settings.selection_path)

    # Parsing the 256KB airspace source and walking its ~700 features to build
    # the catalog costs about a second on a Pi and does not change between
    # requests. Keyed on the file's mtime so a source fetch invalidates it.
    source_memo = {}

    def load_features():
        """Features, or None when the source has not been fetched yet."""
        path = generate.yaml_path(settings.source_cache)
        if not path.exists():
            return None
        key = ("features", path.stat().st_mtime)
        if key not in source_memo:
            source_memo.clear()
            try:
                source_memo[key] = generate.load_features(
                    cache_dir=settings.source_cache)
            except generate.SourceMissing:
                return None
        return source_memo[key]

    def load_catalog(sel, features):
        path = generate.yaml_path(settings.source_cache)
        key = ("catalog", path.stat().st_mtime, sel.home_lat, sel.home_lon,
               sel.reach_nm)
        if key not in source_memo:
            source_memo[key] = catalog.catalog(features, sel.home_lat,
                                               sel.home_lon, sel.reach_nm)
        return source_memo[key]

    # Filtering 85,000 airports or 109,000 populated places takes a second or
    # two on a Pi, and the pickers re-read on every page load. Memoised on the
    # file's mtime so a re-download invalidates it without a restart. A plain
    # dict is enough: single user, four datasets, one bounding box at a time.
    dataset_memo = {}

    def scoped(name, loader, *args):
        path = datasets.path_for(name, settings.cache_dir)
        stamp = path.stat().st_mtime if path.exists() else None
        key = (name, stamp, args)
        if key not in dataset_memo:
            if len(dataset_memo) > 8:
                dataset_memo.clear()
            dataset_memo[key] = loader(*args)
        return dataset_memo[key]

    def box_for(sel):
        return catalog.bbox_for(sel.home_lat, sel.home_lon, sel.reach_nm)

    def missing_datasets():
        return [name for name in datasets.SOURCES
                if datasets.age_days(name, settings.cache_dir) is None]

    @app.route("/")
    def index():
        if load_selection() is None:
            return redirect(url_for("site"))
        return redirect(url_for("airspace"))

    @app.route("/site", methods=["GET", "POST"])
    def site():
        sel = load_selection()
        if request.method == "POST":
            try:
                lat = float(request.form.get("home_lat", ""))
                lon = float(request.form.get("home_lon", ""))
                reach = float(request.form.get("reach_nm", "")
                              or selection.DEFAULT_REACH_NM)
            except ValueError:
                flash("Latitude, longitude and reach must be numbers.",
                      "error")
                return render_template("site.html", sel=sel), 400
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                flash("Latitude must be within ±90 and longitude ±180.",
                      "error")
                return render_template("site.html", sel=sel), 400
            if reach <= 0:
                flash("Reach must be greater than zero.", "error")
                return render_template("site.html", sel=sel), 400

            sel = (store.with_site(sel, lat, lon, reach) if sel
                   else store.empty(lat, lon, reach))
            store.save(settings.selection_path, sel)
            # Home is on the wire in the contact feed and stamped into the
            # blob, so moving it invalidates the published map — say so rather
            # than letting the board discover it as GEO_WRONG_HOME.
            flash("Site saved. Publish to rebuild the map for the new home.",
                  "ok")
            return redirect(url_for("airspace"))
        return render_template("site.html", sel=sel)

    @app.route("/airspace")
    def airspace():
        sel = load_selection()
        if sel is None:
            return redirect(url_for("site"))
        features = load_features()
        if features is None:
            return render_template("source.html", cache=settings.source_cache)

        cands = load_catalog(sel, features)
        selected = set(sel.feature_names())
        reasons = {}
        if request.args.get("suggest"):
            accepted, rejected = rules.suggest(cands)
            # A preview, never a pipeline: the rules pre-tick the boxes and
            # explain themselves, and nothing is stored until Save. Discovery
            # was the problem the rules solve; taste is not automatable.
            selected = {c.name for c in accepted}
            reasons = {c.name: reason for c, reason in rejected}
            flash(f"Suggested {len(accepted)} of {len(cands)} features. "
                  f"Nothing is saved until you press Save.", "ok")

        kinds = sorted({c.kind for c in cands})
        show = request.args.getlist("kind")
        visible = [c for c in cands if not show or c.kind in show]

        missing = selection.missing_features(sel, features)
        if missing:
            flash(f"{len(missing)} selected feature(s) are no longer in the "
                  f"dataset and will block publishing: "
                  f"{', '.join(missing)}", "error")

        return render_template(
            "airspace.html", sel=sel, candidates=visible, selected=selected,
            reasons=reasons, kinds=kinds, show=show, total=len(cands),
            px_per_nm=catalog.PX_PER_NM_OVERVIEW, missing=missing)

    @app.route("/airspace", methods=["POST"])
    def save_airspace():
        sel = load_selection()
        if sel is None:
            return redirect(url_for("site"))
        ticked = request.form.getlist("feature")
        sel = store.apply_airspace(sel, ticked)
        store.save(settings.selection_path, sel)
        flash(f"Saved {len(sel.groups)} airspace group(s). "
              f"Publish to rebuild the map.", "ok")
        return redirect(url_for("airspace"))

    @app.route("/source/fetch", methods=["POST"])
    def fetch_source():
        try:
            generate.fetch_source(cache_dir=settings.source_cache)
        except Exception as e:  # subprocess, network, disk — all the same here
            flash(f"Could not fetch the airspace source: {e}", "error")
            return redirect(url_for("airspace"))
        source_memo.clear()  # mtime would catch it, but do not rely on that
        flash("Airspace source updated.", "ok")
        return redirect(url_for("airspace"))

    @app.route("/publish", methods=["POST"])
    def publish():
        sel = load_selection()
        if sel is None:
            return redirect(url_for("site"))
        features = load_features()
        if features is None:
            return render_template("source.html", cache=settings.source_cache)

        want_coast = bool(request.form.get("coastline"))
        loader = None
        if want_coast:
            def loader():
                return generate.load_coastline(
                    sel, cache_dir=settings.coastline_cache)

        try:
            result = generate.build(sel, features, coast_loader=loader)
        except Exception as e:
            flash(f"Build failed: {e}", "error")
            return redirect(url_for("airspace"))

        if not result.ok:
            for problem in result.problems:
                flash(problem, "error")
            flash("Nothing was published — the map would have had a hole "
                  "in it.", "error")
            return redirect(url_for("airspace"))

        try:
            # 0644, not the default: lighttpd serves this as www-data.
            store.write_atomic(settings.blob_path, result.blob,
                               permissions=0o644)
        except OSError as e:
            flash(f"Could not write {settings.blob_path}: {e}. The previously "
                  f"published map is untouched.", "error")
            return redirect(url_for("airspace"))
        flash(f"Published {len(result.blob)} bytes to "
              f"{settings.blob_path} ({result.summary()}). The board picks "
              f"it up on its next geography poll.", "ok")
        return redirect(url_for("airspace"))

    # ------------------------------------------------------------- datasets

    @app.route("/datasets", methods=["GET"])
    def dataset_status():
        return render_template(
            "datasets.html",
            rows=[(name, datasets.age_days(name, settings.cache_dir))
                  for name in datasets.SOURCES])

    @app.route("/datasets/fetch", methods=["POST"])
    def fetch_datasets():
        wanted = request.form.getlist("dataset") or list(datasets.SOURCES)
        done, failed = [], []
        for name in wanted:
            if name not in datasets.SOURCES:
                continue
            try:
                datasets.fetch(name, settings.cache_dir)
                done.append(name)
            except Exception as e:
                failed.append(f"{name}: {e}")
        dataset_memo.clear()
        if done:
            flash(f"Downloaded {', '.join(done)}.", "ok")
        for problem in failed:
            flash(f"Could not download {problem}", "error")
        return redirect(request.form.get("next") or url_for("dataset_status"))

    def need_datasets(*names):
        """A page to render instead, when a dataset is not downloaded yet."""
        absent = [n for n in names
                  if datasets.age_days(n, settings.cache_dir) is None]
        if not absent:
            return None
        return render_template(
            "datasets.html", needed=absent, next_page=request.path,
            rows=[(name, datasets.age_days(name, settings.cache_dir))
                  for name in datasets.SOURCES])

    # ------------------------------------------------------------ airfields

    @app.route("/airfields")
    def airfields():
        sel = load_selection()
        if sel is None:
            return redirect(url_for("site"))
        blocked = need_datasets("airports", "runways")
        if blocked:
            return blocked

        box = box_for(sel)
        small = bool(request.args.get("small"))
        types = (datasets.AIRPORT_TYPES if small
                 else datasets.DEFAULT_AIRPORT_TYPES)
        records = scoped("airports", datasets.airfields, settings.cache_dir,
                         box, types)

        query = (request.args.get("q") or "").strip().upper()
        if query:
            records = [a for a in records
                       if query in a.ident or query in a.name.upper()
                       or query in a.municipality.upper()]

        chosen = picks.selected_airfields(sel)
        # Runways are only offered for airfields already ticked. Offering every
        # runway in the box would be hundreds of rows for a list where two or
        # three entries is the normal answer.
        runway_records = (scoped("runways", datasets.runways,
                                 settings.cache_dir, tuple(sorted(chosen)))
                          if chosen else [])
        return render_template(
            "airfields.html", sel=sel, records=records, chosen=chosen,
            runways=runway_records,
            chosen_runways=picks.selected_runways(sel, runway_records),
            query=request.args.get("q") or "", small=small, picks=picks,
            runway_key=picks.runway_key)

    @app.route("/airfields", methods=["POST"])
    def save_airfields():
        sel = load_selection()
        if sel is None:
            return redirect(url_for("site"))
        box = box_for(sel)
        every = scoped("airports", datasets.airfields, settings.cache_dir,
                       box, datasets.AIRPORT_TYPES)
        by_ident = {a.ident: a for a in every}

        wanted = [i for i in request.form.getlist("airfield") if i in by_ident]
        airfield_rows = [(by_ident[i].ident, by_ident[i].lat, by_ident[i].lon)
                         for i in wanted]

        # Runway ticks arrive only for airfields that were displayed, which are
        # the ones that were already selected. Re-reading the previous set is
        # what stops unticking an airfield's checkbox on this page silently
        # orphaning its centrelines.
        previous = picks.selected_airfields(sel)
        runway_records = scoped("runways", datasets.runways,
                                settings.cache_dir,
                                tuple(sorted(previous | set(wanted))))
        ticked = set(request.form.getlist("runway"))
        runway_rows = [(r.lat0, r.lon0, r.lat1, r.lon1) for r in runway_records
                       if picks.runway_key(r) in ticked
                       and r.airport in set(wanted)]

        store.save(settings.selection_path,
                   store.with_points(sel, airfields=airfield_rows,
                                     runways=runway_rows))
        flash(f"Saved {len(airfield_rows)} airfield(s) and "
              f"{len(runway_rows)} centreline(s). Publish to rebuild the map.",
              "ok")
        return redirect(url_for("airfields"))

    # ---------------------------------------------------------------- fixes

    def fix_candidates(sel):
        """Navaids in the box, merged with the curated enroute table."""
        box = box_for(sel)
        south, north, west, east = box
        out = []
        if datasets.age_days("navaids", settings.cache_dir) is not None:
            out.extend(
                picks.Candidate(n.ident, n.name, n.kind, n.lat, n.lon,
                                "navaid")
                for n in scoped("navaids", datasets.navaids,
                                settings.cache_dir, box))
        for fix in fixesmod.load(settings.fixes_path):
            if south <= fix.lat <= north and west <= fix.lon <= east:
                out.append(picks.Candidate(fix.ident, fix.note or "enroute fix",
                                           "FIX", fix.lat, fix.lon,
                                           fix.source))
        out.sort(key=lambda c: c.ident)
        return out

    @app.route("/fixes")
    def fixes():
        sel = load_selection()
        if sel is None:
            return redirect(url_for("site"))
        records = fix_candidates(sel)
        query = (request.args.get("q") or "").strip().upper()
        if query:
            records = [c for c in records
                       if query in c.ident or query in c.name.upper()]
        return render_template(
            "fixes.html", sel=sel, records=records,
            chosen=picks.selected_fixes(sel),
            query=request.args.get("q") or "", picks=picks,
            have_navaids=datasets.age_days("navaids",
                                           settings.cache_dir) is not None)

    @app.route("/fixes", methods=["POST"])
    def save_fixes():
        sel = load_selection()
        if sel is None:
            return redirect(url_for("site"))
        by_ident = {c.ident: c for c in fix_candidates(sel)}
        wanted = [i for i in request.form.getlist("fix") if i in by_ident]
        rows = [(by_ident[i].ident, by_ident[i].lat, by_ident[i].lon)
                for i in wanted]
        store.save(settings.selection_path,
                   store.with_points(sel, waypoints=rows))
        flash(f"Saved {len(rows)} fix(es). Publish to rebuild the map.", "ok")
        return redirect(url_for("fixes"))

    @app.route("/fixes/import", methods=["POST"])
    def import_fixes():
        parsed, problems = fixesmod.parse_eaip(request.form.get("eaip") or "")
        for problem in problems[:10]:
            flash(problem, "error")
        if len(problems) > 10:
            flash(f"...and {len(problems) - 10} more unreadable line(s).",
                  "error")
        if parsed:
            merged = {f.ident: f for f in fixesmod.load(settings.fixes_path)
                      if f.source == "imported"}
            merged.update({f.ident: f for f in parsed})
            fixesmod.save(settings.fixes_path, list(merged.values()))
            flash(f"Imported {len(parsed)} fix(es): "
                  f"{', '.join(f.ident for f in parsed[:12])}"
                  f"{'...' if len(parsed) > 12 else ''}. They still have to be "
                  f"ticked below.", "ok")
        elif not problems:
            flash("Nothing to import.", "error")
        return redirect(url_for("fixes"))

    # ---------------------------------------------------------------- towns

    @app.route("/towns")
    def towns():
        sel = load_selection()
        if sel is None:
            return redirect(url_for("site"))
        blocked = need_datasets("towns")
        if blocked:
            return blocked

        floor = request.args.get("min_population", "2000")
        try:
            floor = max(0, int(floor))
        except ValueError:
            floor = 2000
        records = scoped("towns", datasets.towns, settings.cache_dir,
                         box_for(sel), floor)
        chosen = picks.selected_towns(sel, records)
        return render_template(
            "towns.html", sel=sel, records=records, chosen=chosen,
            labels=picks.town_labels(sel, records), picks=picks,
            floor=floor, map_w=MAP_W, map_h=MAP_H,
            plotted=picks.layout(records, sel.home_lat, sel.home_lon,
                                 sel.reach_nm, MAP_W, MAP_H))

    @app.route("/towns", methods=["POST"])
    def save_towns():
        sel = load_selection()
        if sel is None:
            return redirect(url_for("site"))
        records = scoped("towns", datasets.towns, settings.cache_dir,
                         box_for(sel), 0)
        by_uid = {t.uid: t for t in records}

        rows, problems = [], []
        for uid in request.form.getlist("town"):
            town = by_uid.get(uid)
            if town is None:
                continue
            label = (request.form.get(f"label_{uid}")
                     or picks.default_label(town.name)).strip().upper()
            complaint = picks.check_label(label)
            if complaint:
                problems.append(f"{town.name}: {complaint}")
                continue
            rows.append((label, town.lat, town.lon))

        if problems:
            # Refused as a set rather than partially: a save that dropped the
            # one town with a bad label and reported it in a flash would be
            # read as "saved", and the map would come back short.
            for problem in problems:
                flash(problem, "error")
            flash("Nothing was saved — fix the labels and save again.",
                  "error")
            return redirect(url_for("towns"))

        store.save(settings.selection_path, store.with_points(sel, towns=rows))
        flash(f"Saved {len(rows)} town(s). Publish to rebuild the map.", "ok")
        return redirect(url_for("towns"))

    # -------------------------------------------------------------- preview

    def cached_coast_loader(sel):
        """A coastline loader, but only if the answer is already on disk.

        The preview must not reach Overpass. It is the page you flick back to
        after every tick, and a slow rate-limited network call behind that is
        the difference between a tool you use and one you avoid. Publishing
        still fetches; this just draws without the coast until it has.
        """
        from boxradar_site.geo import coastline
        box = coastline.query_box(sel.home_lat, sel.home_lon)
        if not coastline.cache_path(box, settings.coastline_cache).exists():
            return None
        return lambda: generate.load_coastline(
            sel, cache_dir=settings.coastline_cache)

    preview_memo = {}

    def preview_build(sel, features):
        """The build the preview draws, memoised on what would change it."""
        path = settings.selection_path
        key = (path.stat().st_mtime if path.exists() else None,
               generate.yaml_path(settings.source_cache).stat().st_mtime)
        if key not in preview_memo:
            preview_memo.clear()
            preview_memo[key] = generate.build(
                sel, features, coast_loader=cached_coast_loader(sel))
        return preview_memo[key]

    @app.route("/preview")
    def preview_page():
        sel = load_selection()
        if sel is None:
            return redirect(url_for("site"))
        features = load_features()
        if features is None:
            return render_template("source.html", cache=settings.source_cache)

        result = preview_build(sel, features)
        if not result.ok:
            for problem in result.problems:
                flash(problem, "error")
            flash("Cannot draw a preview of a selection that will not build.",
                  "error")
            return redirect(url_for("airspace"))

        views = []
        for range_nm in (preview.OVERVIEW_NM,) + preview.DETAIL_RANGES_NM:
            shapes = preview.scene(result, sel, range_nm)
            views.append({
                "range_nm": range_nm,
                "px_per_nm": preview.px_per_nm(range_nm),
                "svg": preview.to_svg(shapes),
                "labels": len(preview.label_boxes(shapes)),
                "collisions": preview.collisions(shapes),
            })
        return render_template("preview.html", sel=sel, views=views,
                               counts=result.counts,
                               has_coast=bool(result.coast))

    @app.route("/healthz")
    def healthz():
        sel = load_selection()
        return {"ok": True, "version": VERSION,
                "has_selection": sel is not None,
                "has_source": generate.yaml_path(
                    settings.source_cache).exists(),
                "blob": settings.blob_path.exists(),
                "datasets": {name: datasets.age_days(name, settings.cache_dir)
                             for name in datasets.SOURCES}}

    return app
