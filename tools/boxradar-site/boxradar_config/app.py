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

from . import VERSION, store
from .settings import Settings


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

    def load_features():
        """Features, or None when the source has not been fetched yet."""
        try:
            return generate.load_features(cache_dir=settings.source_cache)
        except generate.SourceMissing:
            return None

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

        cands = catalog.catalog(features, sel.home_lat, sel.home_lon,
                                sel.reach_nm)
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

        store.write_atomic(settings.blob_path, result.blob)
        flash(f"Published {len(result.blob)} bytes to "
              f"{settings.blob_path} ({result.summary()}). The board picks "
              f"it up on its next geography poll.", "ok")
        return redirect(url_for("airspace"))

    @app.route("/healthz")
    def healthz():
        sel = load_selection()
        return {"ok": True, "version": VERSION,
                "has_selection": sel is not None,
                "has_source": generate.yaml_path(
                    settings.source_cache).exists(),
                "blob": settings.blob_path.exists()}

    return app
