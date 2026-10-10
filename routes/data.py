"""Whole-database export and import (.db files) and the Google Drive panel."""
import io
import os
import sqlite3
import tempfile
from datetime import date, datetime

from flask import (Blueprint, current_app, flash, g, redirect, render_template, request, send_file, url_for)
import dbtools
from database import close_db, get_db, prepare_database
from utils import fail

bp = Blueprint("data", __name__, url_prefix="/data")


@bp.route("/")
def index():
    db = get_db()
    counts = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("income", "expenses", "accounts")}
    drive = current_app.extensions["drive"]
    info = drive.status()
    remote = remote_error = None
    if info["state"] in ("synced", "pending", "error", "conflict", "choose"):
        remote, remote_error = drive.remote_info()
    return render_template("data.html", counts=counts, page="data", d=info, remote=remote,
                           remote_error=remote_error)


@bp.route("/export.db")
def export_db():
    payload = io.BytesIO(dbtools.snapshot_bytes(current_app.config["DB_PATH"]))
    return send_file(payload, mimetype="application/vnd.sqlite3", as_attachment=True,
                     download_name=f"money_{date.today().isoformat()}.db")


@bp.route("/import", methods=["POST"])
def import_db():
    upload = request.files.get("dbfile")
    if not upload or not upload.filename:
        return fail("Choose a .db file to import.", "data.index")
    path = current_app.config["DB_PATH"]
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        upload.save(tmp)
        problem = dbtools.check_database(tmp)
        if problem:
            return fail(problem + " Nothing was changed.", "data.index")
        prepare_database(tmp, backup=False)  # upgrade the copy first; stored balances stay as they are
        saved = f"{path}.before-import-{datetime.now():%Y%m%d-%H%M%S}.backup"
        close_db()
        dbtools.replace_database(path, tmp, saved)  # keeps what you had, just in case
    except sqlite3.Error as err:
        return fail(f"Import failed ({err}). Nothing was changed.", "data.index")
    finally:
        os.remove(tmp)
    g.data_changed = True  # the imported data is new data: back it up to Google Drive too
    db = get_db()
    n = [db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("income", "expenses", "accounts")]
    flash(f"Database imported: {n[0]} income, {n[1]} expenses, {n[2]} accounts. "
          f"Your previous data was saved as {os.path.basename(saved)}.", "ok")
    return redirect(url_for("overview.index"))
