import os
import secrets
from flask import Flask, abort, flash, g, render_template, request, session
from werkzeug.exceptions import HTTPException

import config
import database
from routes import overview, accounts, income, expenses, data, drive
from services.drive_sync import DriveSync


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(config)
    app.config.update(test_config or {})
    app.config.setdefault("MAX_CONTENT_LENGTH", 64 * 1024 * 1024)  # largest database you can import
    database.init_app(app)
    for module in (overview, accounts, income, expenses, data, drive):
        app.register_blueprint(module.bp)

    cfg = app.config
    sync = DriveSync(
        db_path=cfg["DB_PATH"], state_path=cfg.get("DRIVE_STATE_PATH") or cfg["DB_PATH"] + ".drive.json",
        creds_path=cfg["GOOGLE_CREDENTIALS_PATH"], client=cfg.get("DRIVE_CLIENT"), device=cfg.get("DRIVE_DEVICE_NAME"),
        inline=cfg.get("DRIVE_INLINE", False), interval=cfg.get("DRIVE_CHECK_INTERVAL", 30))
    app.extensions["drive"] = sync

    app.jinja_env.filters["money"] = lambda v: f"{(v or 0):,.2f}"
    app.jinja_env.globals["csrf_token"] = lambda: session.get("_csrf", "")
    app.context_processor(lambda: {"drive_level": sync.nav_level()})

    @app.before_request
    def csrf_protect():
        session.setdefault("_csrf", secrets.token_hex(16))
        if request.method == "POST" and not secrets.compare_digest(
                request.form.get("_csrf", ""), session["_csrf"]):
            abort(400)

    @app.before_request
    def drive_check():
        """Pick up changes from another device (and retry any unsent backup) on normal page views."""
        if request.method != "GET" or not request.endpoint or request.endpoint == "static" \
                or request.endpoint.startswith("drive."):
            return
        res = sync.maybe_pull()
        if res and res["action"] == "pull":
            flash(res["message"], "ok")
        notice = sync.pop_notice()
        if notice:
            flash(notice, "warn")

    @app.after_request
    def drive_backup(response):
        if g.pop("data_changed", False) and response.status_code < 400:
            sync.after_change(response)
        return response

    @app.errorhandler(HTTPException)
    def http_error(e):
        return render_template("error.html", page="", e=e), e.code

    return app


if __name__ == "__main__":
    # HOST=0.0.0.0 lets a phone on your network open the app. Debug mode stays off unless FLASK_DEBUG=1.
    create_app().run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)),
                     debug=os.environ.get("FLASK_DEBUG") == "1")
