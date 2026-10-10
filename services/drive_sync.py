"""Google Drive backup + sync logic (device-local state, conflict detection).

Model: the Drive file carries a random `rev` id that changes on every upload. Each device remembers
`synced_rev` (the Drive revision its data is based on) and `dirty` (local changes not yet uploaded).
    Drive missing                      -> upload
    never synced, Drive has a file     -> ask the user (choose)
    Drive rev == synced_rev            -> upload if dirty, else nothing to do
    Drive rev != synced_rev            -> download if clean, otherwise CONFLICT (user decides)
Nothing is ever overwritten silently when both sides changed.
"""
import json
import os
import secrets
import socket
import sqlite3
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone

import database
import dbtools
from services import google_drive
from services.google_drive import DriveError, GoogleDriveClient, NeedsReconnect

LABELS = {
    "not_configured": "Not set up", "disconnected": "Not connected", "reconnect": "Connection expired",
    "choose": "Waiting for your choice", "conflict": "Needs your decision", "error": "Last sync failed",
    "pending": "Changes waiting to be backed up", "synced": "Backed up and in sync",
}


def plan(dirty, synced_rev, remote):
    """Decide what a sync should do. Pure function: easy to reason about and test."""
    if remote is None:
        return "push"
    if synced_rev is None:
        return "choose"
    if remote["rev"] == synced_rev:
        return "push" if dirty else "none"
    return "conflict" if dirty else "pull"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class DriveSync:
    def __init__(self, db_path, state_path, creds_path, client=None, device=None,
                 file_name="ledger-backup.db", inline=False, interval=30):
        self.db_path, self.state_path, self.creds_path = db_path, state_path, creds_path
        self._injected, self._device, self.file_name = client, device, file_name
        self.inline, self.interval = inline, interval
        self.lock = threading.RLock()
        self._next_check = 0.0
        self.exchange = google_drive.exchange_code

    # ----- state file (device-local; never part of the database) -----
    def load(self):
        try:
            with open(self.state_path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save(self, **changes):
        with self.lock:
            st = self.load()
            st.update(changes)
            tmp = self.state_path + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # holds a refresh token
            with os.fdopen(fd, "w") as f:
                json.dump(st, f)
            os.replace(tmp, self.state_path)

    def pop_notice(self):
        st = self.load()
        if st.get("notice"):
            self.save(notice=None)
        return st.get("notice")

    @property
    def device(self):
        if self._device:
            return self._device
        st = self.load()
        if not st.get("device"):
            self.save(device=f"{socket.gethostname()}-{secrets.token_hex(2)}")
            st = self.load()
        return st["device"]

    # ----- configuration / status -----
    def credentials(self):
        return google_drive.load_credentials(self.creds_path)

    @property
    def configured(self):
        return self._injected is not None or self.credentials() is not None

    def client(self):
        if self._injected is not None:
            return self._injected
        creds = self.credentials()
        if not creds:
            raise DriveError("Google Drive isn't set up. Add credentials.json first.")
        tokens = self.load().get("tokens")
        if not tokens:
            raise NeedsReconnect("Google Drive isn't connected.")
        return GoogleDriveClient(creds, tokens, on_tokens=lambda t: self.save(tokens=t))

    def status(self):
        st = self.load()
        connected = bool(st.get("connected"))
        if not self.configured:
            state = "not_configured"
        elif not connected:
            state = "disconnected"
        elif st.get("needs_reconnect"):
            state = "reconnect"
        elif st.get("choose"):
            state = "choose"
        elif st.get("conflict"):
            state = "conflict"
        elif st.get("last_error"):
            state = "error"  # e.g. offline, or a Drive backup that couldn't be used
        elif st.get("dirty"):
            state = "pending"
        else:
            state = "synced"
        level = None if not connected else ("ok" if state == "synced" else "err" if state in ("error", "reconnect") else "warn")
        return {"state": state, "label": LABELS[state], "level": level, "connected": connected,
                "auto_sync": st.get("auto_sync", True), "dirty": bool(st.get("dirty")),
                "last_sync_at": st.get("last_sync_at"), "last_error": st.get("last_error"),
                "device": self.device if connected else None}

    def nav_level(self):
        return self.status()["level"] if self.load().get("connected") else None

    def remote_info(self):
        try:
            return self._remote(self.client(), self.load()), None
        except DriveError as e:
            return None, str(e)

    # ----- connecting -----
    def begin_connect(self, redirect_uri):
        state = secrets.token_urlsafe(16)
        self.save(oauth_state=state)  # kept here, not in the session: works whichever host name was used
        return google_drive.auth_url(self.credentials(), redirect_uri, state)

    def finish_connect(self, redirect_uri, code, state):
        st = self.load()
        if not state or state != st.get("oauth_state"):
            raise DriveError("The sign-in request didn't match. Start again from the Data page.")
        tokens = self.exchange(self.credentials(), redirect_uri, code)
        self.save(oauth_state=None, connected=True, needs_reconnect=False, tokens=tokens,
                  auto_sync=st.get("auto_sync", True), last_error=None)
        return self._guard(self.sync)

    def disconnect(self):
        tokens = self.load().get("tokens") or {}
        if tokens.get("refresh_token") and self._injected is None:
            google_drive.revoke(tokens["refresh_token"])
        # forget the link, so the next connection asks which side wins; the Drive file is left alone
        self.save(connected=False, tokens=None, needs_reconnect=False, synced_rev=None, file_id=None,
                  conflict=False, choose=False, last_error=None, notice=None)

    def set_auto(self, enabled):
        self.save(auto_sync=bool(enabled))

    # ----- syncing -----
    def _guard(self, fn):
        try:
            return fn()
        except NeedsReconnect as e:
            self.save(needs_reconnect=True, last_error=str(e))
            return {"action": "error", "message": str(e)}
        except DriveError as e:
            self.save(last_error=str(e))
            return {"action": "error", "message": str(e)}
        except (OSError, sqlite3.Error) as e:
            self.save(last_error=f"Sync failed: {e}")
            return {"action": "error", "message": f"Sync failed: {e}"}

    def _remote(self, client, st):
        meta = client.get_meta(st["file_id"]) if st.get("file_id") else None
        if meta is None:
            meta = client.find(self.file_name)
        new_id = meta["id"] if meta else None
        if new_id != st.get("file_id"):
            self.save(file_id=new_id)
        return meta

    def sync(self):
        with self.lock:
            client, st = self.client(), self.load()
            remote = self._remote(client, st)
            action = plan(st.get("dirty", False), st.get("synced_rev"), remote)
            if action == "push":
                return self._push(client, remote)
            if action == "pull":
                return self._pull(client, remote, keep_backup=False)
            flags = {"conflict": action == "conflict", "choose": action == "choose", "last_error": None}
            self.save(**flags)
            if action == "conflict":
                return {"action": "conflict", "message": "Google Drive has newer changes from another device "
                        "and so does this one. Choose which version to keep."}
            if action == "choose":
                who = (remote or {}).get("device") or "another device"
                return {"action": "choose", "message": f"Google Drive already holds a backup (from {who}). "
                        "Choose whether to import it or replace it with this device's data."}
            return {"action": "none", "message": "Everything is up to date."}

    def _push(self, client, remote):
        before = self.load().get("changes", 0)
        data = dbtools.snapshot_bytes(self.db_path)
        rev = uuid.uuid4().hex
        props = {"rev": rev, "device": self.device, "format": "ledger-db-2"}
        meta = client.update(remote["id"], data, props) if remote else client.create(self.file_name, data, props)
        # a change made while uploading stays "dirty" and goes up on the next sync
        self.save(file_id=meta["id"], synced_rev=rev, dirty=self.load().get("changes", 0) != before,
                  conflict=False, choose=False, last_sync_at=_now(), last_error=None)
        return {"action": "push", "message": "Backed up to Google Drive."}

    def _pull(self, client, remote, keep_backup):
        data = client.download(remote["id"])
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            problem = dbtools.check_database(tmp)
            if problem:
                raise DriveError("The backup on Google Drive can't be used: " + problem)
            database.prepare_database(tmp, backup=False)
            saved = f"{self.db_path}.before-drive-{datetime.now():%Y%m%d-%H%M%S}.backup" if keep_backup else None
            dbtools.replace_database(self.db_path, tmp, saved)
        finally:
            os.remove(tmp)
        self.save(file_id=remote["id"], synced_rev=remote["rev"], dirty=False, conflict=False, choose=False,
                  last_sync_at=_now(), last_error=None)
        who = remote.get("device") or "another device"
        note = f" Your previous data here was saved as {os.path.basename(saved)}." if saved else ""
        return {"action": "pull", "message": f"Imported the data from Google Drive (saved by {who}).{note}"}

    def force_push(self):
        """Replace the Drive backup with this device's data."""
        def run():
            with self.lock:
                client = self.client()
                return self._push(client, self._remote(client, self.load()))
        return self._guard(run)

    def force_pull(self):
        """Replace this device's data with the Drive backup (what you had is kept as a backup file)."""
        def run():
            with self.lock:
                client = self.client()
                remote = self._remote(client, self.load())
                if remote is None:
                    raise DriveError("There is no backup on Google Drive yet.")
                return self._pull(client, remote, keep_backup=True)
        return self._guard(run)

    def manual_sync(self):
        return self._guard(self.sync)

    # ----- automatic behaviour -----
    def _auto(self):
        res = self._guard(self.sync)
        if res["action"] == "conflict":
            self.save(notice="Google Drive has newer changes from another device, so your latest change "
                             "wasn't backed up yet. Open Data to choose which version to keep.")
        elif res["action"] == "error":
            self.save(notice="Couldn't back up to Google Drive: " + res["message"])
        return res

    def after_change(self, response=None):
        """Called after any data change: mark it unsynced, then back it up (after the page is sent)."""
        with self.lock:
            st = self.load()
            if not st.get("connected"):
                return
            self.save(dirty=True, changes=st.get("changes", 0) + 1)
        if st.get("auto_sync", True) and not st.get("needs_reconnect"):
            if self.inline or response is None:
                self._auto()
            else:
                response.call_on_close(self._auto)

    def maybe_pull(self):
        """On page views: at most every `interval` seconds, look for changes made on another device."""
        st = self.load()
        if (not st.get("connected") or not st.get("auto_sync", True) or st.get("needs_reconnect")
                or st.get("choose") or st.get("conflict")):
            return None
        now = time.monotonic()
        if now < self._next_check:
            return None
        self._next_check = now + self.interval
        res = self._guard(self.sync)
        if res["action"] == "error":
            self._next_check = now + max(self.interval, 60)  # offline: don't retry on every click
        elif res["action"] == "conflict":
            self.save(notice=res["message"])
        return res
