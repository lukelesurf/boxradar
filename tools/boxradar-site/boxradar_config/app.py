"""The configuration UI.

Kept to APIs common to Flask 2.2 and 3.x: the receiver Pi has bookworm's
python3-flask 2.2.2 and this repo's devShell has 3.1, the same split as
shapely 1.8 against 2.x. Nothing here needs a feature newer than 2.2.

The application owns no geography logic. Everything it does is already tested
in boxradar_site.geo — the catalog is the picker's data source, `rules` is the
Suggest button, and `generate` builds the blob. This is presentation plus a
file to write, which is what the phase 4 scoping note said it should be.
"""

import html
import queue
import secrets
import threading
import time

from flask import (Flask, Response, flash, g, redirect, render_template,
                   request, stream_with_context, url_for)

from boxradar_site.geo import catalog, generate, rules, selection

from . import (VERSION, datasets, device, fixes as fixesmod, picks, preview,
               sources, steps, store)
from .settings import Settings

# Which step of the wizard each endpoint belongs to. The progress strip is
# rendered from this rather than from a `page` variable set in each template,
# so a route added without a home shows up as one with nothing highlighted
# instead of silently inheriting whatever was there before.
STEP_FOR_ENDPOINT = {
    "index": "",
    "site": "site",
    "dataset_status": "data", "fetch_datasets": "data",
    "airspace": "airspace", "save_airspace": "airspace",
    "publish": "airspace",
    "airfields": "points", "save_airfields": "points",
    "fixes": "points", "save_fixes": "points", "import_fixes": "points",
    "towns": "points", "save_towns": "points",
    "device_page": "device", "save_device": "device",
    "preview_page": "publish",
}

# End-of-stream marker for the download queue. A distinct object rather than
# None, because None is what a throttled progress update returns and the two
# must never be confused — see the note in _fetch_reporting.
_STREAM_END = object()


def create_app(settings=None, board=None):
    """`board` injects a device.Client, so tests never open a socket. Same
    shape as make_server's fetch_feed on the display service side."""
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    app.config["SETTINGS"] = settings
    # Only signs flash cookies. Regenerated per start deliberately: there is
    # nothing here worth persisting a key for, and a restart losing a flash
    # message is not a defect.
    app.secret_key = secrets.token_bytes(32)

    def load_selection():
        """The selection, parsed at most once per request.

        Cached on `g` because the progress strip needs it on every render and
        every view already loads it — without this, each page would parse the
        same JSON twice.
        """
        if "selection" not in g:
            try:
                g.selection = store.load(settings.selection_path)
            except Exception as e:
                # A selection that will not parse must not take the whole UI
                # down: the Site page is how you would fix it.
                flash(f"Could not read the selection file: {e}", "error")
                g.selection = None
        return g.selection

    @app.context_processor
    def inject_rail():
        """The progress strip, on every page.

        Cheap by construction — steps.py may only stat() files and read the
        Selection above. See test_config_steps.TestCost.
        """
        current = STEP_FOR_ENDPOINT.get(request.endpoint or "", "")
        built = steps.rail(settings, load_selection(), current)
        return {"rail": built, "next_step": steps.next_action(built)}

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
        """The landing page names the single next action.

        This used to be a redirect to /site, which redirected to /airspace,
        which might then render source.html telling you to fetch the airspace
        source — three hops before the UI said what to do. The order was
        always known; it was just never shown.
        """
        return render_template("index.html", sel=load_selection())

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
            return need_datasets(sources.AIRSPACE)

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
        # EVERY candidate is rendered, always. Filtering by kind or by name is
        # done in the browser, and that is a correctness decision rather than
        # a performance one.
        #
        # apply_airspace() sets the selection to exactly the ticked names, so
        # while this filtered server-side, ticking what was visible under
        # ?kind=CTR and pressing Save silently deleted every CTA group — the
        # hidden features were simply not in the form. Hiding rows in the
        # browser leaves their checkboxes submitting, so the form is always
        # complete and the whole class of bug goes away rather than being
        # patched.
        #
        # ?kind= is still read, by the script on load, so existing bookmarks
        # keep working.
        show = [k for k in request.args.getlist("kind") if k]

        missing = selection.missing_features(sel, features)
        if missing:
            flash(f"{len(missing)} selected feature(s) are no longer in the "
                  f"dataset and will block publishing: "
                  f"{', '.join(missing)}", "error")

        return render_template(
            "airspace.html", sel=sel, candidates=cands, selected=selected,
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

    @app.route("/publish", methods=["POST"])
    def publish():
        sel = load_selection()
        if sel is None:
            return redirect(url_for("site"))
        features = load_features()
        if features is None:
            return need_datasets(sources.AIRSPACE)

        want_coast = bool(request.form.get("coastline"))
        loader = publish_coast_loader(sel) if want_coast else None

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

    def source_rows():
        return [(name, sources.age_days(name, settings),
                 sources.PURPOSE[name], sources.ORIGIN[name])
                for name in sources.ALL]

    # /datasets kept as an alias: it is in the README, in the systemd notes and
    # probably in a browser history or two. Same endpoint, so url_for() emits
    # the new path everywhere.
    @app.route("/data", methods=["GET"])
    @app.route("/datasets", methods=["GET"])
    def dataset_status():
        return render_template("datasets.html", rows=source_rows())

    @app.route("/data/fetch", methods=["POST"])
    @app.route("/datasets/fetch", methods=["POST"])
    def fetch_datasets():
        """Downloads, streamed, so the page reports progress as it goes.

        A plain POST-and-redirect left the browser spinning for however long
        32MB takes over the Pi's wifi, with nothing to distinguish "working"
        from "hung". Streaming the response means the work IS the page: no
        polling, no background job to supervise, no second request.

        The cost is that the response cannot end in a redirect, so this
        renders its own page with a Continue link rather than flashing.
        """
        wanted = [n for n in request.form.getlist("source") if n in sources.ALL]
        wanted = wanted or list(sources.ALL)
        next_page = request.form.get("next") or url_for("dataset_status")

        def run():
            yield render_template("fetching_head.html", wanted=wanted)
            done, failed = [], []
            started = time.monotonic()
            for name in wanted:
                # Throttled to roughly every 256KB. Flushing a fragment per
                # 64KB chunk would put hundreds of script tags on the wire for
                # a 14MB file and buy no visible smoothness.
                state = {"last": -1}

                def progress(got, total, name=name, state=state):
                    step = got // (4 * datasets.CHUNK)
                    if step == state["last"]:
                        return
                    state["last"] = step
                    self_total = total if total else "null"
                    return f'<script>u("{name}",{got},{self_total})</script>'

                at = time.monotonic()
                try:
                    for fragment in _fetch_reporting(name, progress):
                        yield fragment
                except Exception as e:
                    failed.append(name)
                    note = html.escape(str(e))[:120]
                    yield (f'<script>done("{name}",'
                           f'"failed",false)</script>'
                           f'<li class="why">{html.escape(name)} failed: {note}</li>')
                    continue
                done.append(name)
                took = time.monotonic() - at
                size = _readable_size(name)
                yield (f'<script>done("{name}","{size} in {took:.0f}s",true)'
                       f'</script>'
                       f'<li>{html.escape(name)} — {size} in {took:.0f}s</li>')

            # Both memos key on mtime and would notice anyway, but a fetch is
            # exactly when they are wrong and clearing is free.
            dataset_memo.clear()
            source_memo.clear()
            yield render_template(
                "fetching_tail.html", done=done, failed=failed,
                next_page=next_page,
                elapsed=f"{time.monotonic() - started:.0f}s")

        return Response(stream_with_context(run()), mimetype="text/html")

    def _fetch_reporting(name, progress):
        """Runs one fetch, yielding fragments WHILE it runs.

        The fetchers are ordinary blocking functions, so the work goes on a
        thread and its progress callback pushes onto a queue this generator
        drains. Collecting the fragments in a list and yielding them after the
        fetch returned would compile and pass a shape test while defeating the
        entire feature — every bar would jump from 0 to 100 the instant the
        file had already landed.

        The thread is joined before returning and its exception re-raised on
        this one, so a failure is still the caller's to report.
        """
        pending = queue.Queue()
        outcome = {}

        def report(got, total):
            """Queue a fragment, if this update was not throttled away.

            The `if fragment` matters: `progress` returns None between
            throttle steps, and queueing that would be indistinguishable from
            the end-of-stream marker below. That cost a live 14MB download all
            but its first update — everything after the first skipped step was
            read as "finished" and dropped.
            """
            fragment = progress(got, total)
            if fragment:
                pending.put(fragment)

        def work():
            try:
                sources.fetch(name, settings, progress=report)
            except BaseException as e:
                outcome["error"] = e
            finally:
                pending.put(_STREAM_END)

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        while True:
            fragment = pending.get()
            if fragment is _STREAM_END:
                break
            yield fragment
        worker.join()
        if "error" in outcome:
            raise outcome["error"]

    def _readable_size(name):
        try:
            if name == sources.AIRSPACE:
                path = generate.yaml_path(settings.source_cache)
            else:
                path = datasets.path_for(name, settings.cache_dir)
            n = path.stat().st_size
        except OSError:
            return "done"
        if n >= 1048576:
            return f"{n / 1048576:.1f} MB"
        return f"{n / 1024:.0f} KB"

    def need_datasets(*names):
        """A page to render instead, when a source is not downloaded yet.

        The airspace source goes through here too, which is why source.html no
        longer exists: "you need data before this page works" was the same
        situation in both cases and had two different pages saying it.
        """
        absent = [n for n in names if sources.age_days(n, settings) is None]
        if not absent:
            return None
        return render_template("datasets.html", needed=absent,
                               next_page=request.path, rows=source_rows())

    # ------------------------------------------------------------ airfields
    # Airfields, fixes and towns are three panels of one step. They are the
    # same activity — picking point references — over the same selection and
    # the same picks.py, and presenting them as three of seven equal tabs was
    # most of what made the old nav read as a pile rather than an order.

    @app.route("/points")
    def points():
        return redirect(url_for("airfields"))

    @app.route("/points/airfields")
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

        chosen = picks.selected_airfields(sel)
        # The class toggle is a coarse gate the browser cannot apply for
        # itself, and it used to hide fields that were already selected —
        # which a save then dropped, because a save rebuilds the selection
        # from exactly what the form contained. Anything selected is rendered
        # regardless of the gate.
        if not chosen <= {a.ident for a in records}:
            every = scoped("airports", datasets.airfields, settings.cache_dir,
                           box, datasets.AIRPORT_TYPES)
            records = picks.merge_selected(
                records, [a for a in every if a.ident in chosen],
                lambda a: a.ident)
        records = picks.by_distance(records, sel.home_lat, sel.home_lon)

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
            small=small, picks=picks, runway_key=picks.runway_key)

    @app.route("/points/airfields", methods=["POST"])
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

    @app.route("/points/fixes")
    def fixes():
        sel = load_selection()
        if sel is None:
            return redirect(url_for("site"))
        records = picks.by_distance(fix_candidates(sel),
                                    sel.home_lat, sel.home_lon)
        return render_template(
            "fixes.html", sel=sel, records=records,
            chosen=picks.selected_fixes(sel), picks=picks,
            have_navaids=datasets.age_days("navaids",
                                           settings.cache_dir) is not None)

    @app.route("/points/fixes", methods=["POST"])
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

    @app.route("/points/fixes/import", methods=["POST"])
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

    @app.route("/points/towns")
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
        # The floor stays server-side and is not something the browser could
        # take over: at 0 this box holds 12,102 towns and an 8MB page that
        # takes 20 seconds to render on the Pi. At the 2000 default it is
        # 1,179 rows, which the browser filters instantly.
        records = scoped("towns", datasets.towns, settings.cache_dir,
                         box_for(sel), floor)

        chosen = picks.selected_towns(sel, records)
        # A town under the floor is invisible, and a save then dropped it.
        # Only pay for the unfiltered list when something selected is actually
        # missing from the filtered one — the common case is that it is not.
        if len(chosen) < len(sel.towns):
            every = scoped("towns", datasets.towns, settings.cache_dir,
                           box_for(sel), 0)
            wanted = picks.selected_towns(sel, every)
            records = picks.merge_selected(
                records, [t for t in every if t.uid in wanted],
                lambda t: t.uid)
            chosen = picks.selected_towns(sel, records)
        records = picks.by_distance(records, sel.home_lat, sel.home_lon)

        return render_template(
            "towns.html", sel=sel, records=records, chosen=chosen,
            labels=picks.town_labels(sel, records), picks=picks, floor=floor)

    @app.route("/points/towns", methods=["POST"])
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

    # --------------------------------------------------------------- device

    def board_client():
        return board or device.Client(settings.feed_url)

    @app.route("/device")
    def device_page():
        """The board's own settings, read back off the board itself.

        Opening this page asks the display service to flag the next few
        contact polls, which is what makes the board open its settings server.
        The board answers within a couple of seconds, so a first load that
        arrives before it has heard renders a waiting state and refreshes
        itself once — no polling loop, no JavaScript.
        """
        client = board_client()
        snapshot = client.wake()
        fields, problem = None, None
        if snapshot.get("fresh"):
            try:
                fields = client.read_config(snapshot["addr"])
            except device.BoardError as e:
                problem = str(e)
        return render_template(
            "device.html", snapshot=snapshot, fields=fields, problem=problem,
            groups=device.GROUPS, fields_in=device.fields_in,
            retry=bool(snapshot.get("fresh") and fields is None
                       and not request.args.get("noretry")))

    @app.route("/device", methods=["POST"])
    def save_device():
        client = board_client()
        values, clears, problems = device.parse_form(request.form)
        for problem in problems:
            flash(problem, "error")
        if problems:
            # Refused as a set rather than partially, like the town labels: a
            # save that wrote the good fields and flashed about the bad one
            # would read as "saved" and leave the board half-configured.
            flash("Nothing was sent to the board — fix the values above and "
                  "save again.", "error")
            return redirect(url_for("device_page"))

        snapshot = client.presence()
        if not snapshot.get("fresh"):
            flash("The board has not polled recently, so there is nowhere to "
                  "send this. Check it is powered and on the network.",
                  "error")
            return redirect(url_for("device_page"))

        try:
            result = client.write_config(snapshot["addr"], values, clears)
        except device.BoardError as e:
            flash(str(e), "error")
            return redirect(url_for("device_page"))

        for problem in result.get("problems") or []:
            flash(f"The board refused {problem}", "error")
        if not result["written"] and not result["cleared"]:
            flash("Nothing to send — the board already holds these values.",
                  "ok")
        else:
            flash(f"Sent {result['written']} change(s) and cleared "
                  f"{result['cleared']} override(s). The board is restarting, "
                  f"so the scope goes dark for a few seconds.", "ok")
        return redirect(url_for("device_page"))

    # -------------------------------------------------------------- preview

    coast_memo = {}

    def cached_coast(sel):
        """Coastline segments for this home, or None if not fetched yet.

        Memoised on **home**, not on the selection, and that distinction is
        most of this page's speed. Reducing the cached OSM extract to segments
        is 29 of the 40 seconds a cold preview used to take on a Pi (9s to
        read and parse the JSON, 20s to reduce 4,697 ways to 124 segments) —
        while building the airspace itself is 0.08s. The coast does not move
        when you tick an airfield, so keying this on the selection file meant
        paying all 29 seconds again for every edit.

        Returns None rather than fetching: the preview must never reach
        Overpass. It is the page you flick back to after every tick, and a
        slow rate-limited call behind that is the difference between a tool
        you use and one you avoid. Publishing is what fetches.
        """
        from boxradar_site.geo import coastline
        box = coastline.query_box(sel.home_lat, sel.home_lon)
        path = coastline.cache_path(box, settings.coastline_cache)
        if not path.exists():
            return None
        key = (box, path.stat().st_mtime)
        if key not in coast_memo:
            coast_memo.clear()  # one home at a time
            coast_memo[key] = generate.load_coastline(
                sel, cache_dir=settings.coastline_cache)
        return coast_memo[key]

    def publish_coast_loader(sel):
        """Like cached_coast, but allowed to go and get it."""
        ready = cached_coast(sel)
        if ready is not None:
            return lambda: ready
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
            preview_memo[key] = generate.build(sel, features,
                                               coast=cached_coast(sel))
        return preview_memo[key]

    @app.route("/preview")
    def preview_page():
        sel = load_selection()
        if sel is None:
            return redirect(url_for("site"))
        features = load_features()
        if features is None:
            return need_datasets(sources.AIRSPACE)

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
