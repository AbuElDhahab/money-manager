"""Google Drive actions: connect, sync now, back up, import from Drive, auto-sync, disconnect."""
from flask import Blueprint, current_app, flash, redirect, request, url_for
from database import close_db
from services import google_drive

bp = Blueprint("drive", __name__, url_prefix="/drive")


def svc():
    return current_app.extensions["drive"]


def _redirect_uri():
    creds = svc().credentials() or {}
    return google_drive.pick_redirect(creds, url_for("drive.callback", _external=True))


def _flash(res):
    kind = {"error": "error", "conflict": "warn", "choose": "warn"}.get(res["action"], "ok")
    flash(res["message"], kind)
    if res["action"] == "pull":
        close_db()  # the database file was replaced


def _done():
    return redirect(url_for("data.index") + "#drive")


@bp.route("/connect")
def connect():
    if not svc().credentials():
        flash("Google Drive isn't set up yet. Add credentials.json first (see the README).", "error")
        return _done()
    return redirect(svc().begin_connect(_redirect_uri()))


@bp.route("/callback")
def callback():
    if request.args.get("error"):
        flash("Google sign-in was cancelled or refused.", "error")
        return _done()
    try:
        res = svc().finish_connect(_redirect_uri(), request.args.get("code", ""), request.args.get("state"))
    except google_drive.DriveError as e:
        flash(str(e), "error")
        return _done()
    if res["action"] == "push":
        res["message"] = "Connected. Your data was backed up to Google Drive."
    elif res["action"] in ("none", "pull"):
        res["message"] = "Connected to Google Drive and up to date."
    _flash(res)
    return _done()


@bp.route("/sync", methods=["POST"])
def sync():
    _flash(svc().manual_sync())
    return _done()


@bp.route("/push", methods=["POST"])
def push():
    _flash(svc().force_push())
    return _done()


@bp.route("/pull", methods=["POST"])
def pull():
    _flash(svc().force_pull())
    return _done()


@bp.route("/auto", methods=["POST"])
def auto():
    svc().set_auto(request.form.get("enabled") == "1")
    flash("Automatic sync is " + ("on." if request.form.get("enabled") == "1" else "off. Use Sync now when you want."), "ok")
    return _done()


@bp.route("/disconnect", methods=["POST"])
def disconnect():
    svc().disconnect()
    flash("Disconnected from Google Drive. The backup file on Drive was left untouched.", "ok")
    return _done()
