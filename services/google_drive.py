"""Minimal Google OAuth2 + Drive v3 client using only the standard library.

Scope is `drive.file`: the app can only see files it created itself (here: one backup file).
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive.file"
MIME = "application/vnd.sqlite3"
FIELDS = "id,name,modifiedTime,appProperties,trashed"


class DriveError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NeedsReconnect(DriveError):
    """The saved Google access was revoked or expired; the user must connect again."""


# ---------- credentials ----------
def load_credentials(path):
    """OAuth client from GOOGLE_CLIENT_ID/SECRET env vars or the credentials.json Google lets you download."""
    cid, secret = os.environ.get("GOOGLE_CLIENT_ID"), os.environ.get("GOOGLE_CLIENT_SECRET")
    if cid and secret:
        return {"client_id": cid, "client_secret": secret, "redirect_uris": []}
    try:
        with open(path) as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return None
    block = raw.get("web") or raw.get("installed") or raw
    if not isinstance(block, dict) or not block.get("client_id") or not block.get("client_secret"):
        return None
    return {"client_id": block["client_id"], "client_secret": block["client_secret"],
            "redirect_uris": block.get("redirect_uris", [])}


def pick_redirect(creds, default):
    for uri in creds.get("redirect_uris", []):
        if uri.rstrip("/").endswith("/drive/callback"):
            return uri
    return default


# ---------- HTTP ----------
def _describe(status, body):
    try:
        data = json.loads(body)
        err = data.get("error")
        if isinstance(err, dict):
            text = err.get("message") or str(err)
        else:
            text = f"{err} {data.get('error_description', '')}".strip()
    except (ValueError, AttributeError):
        text = body[:200]
    return f"Google said: {text} ({status})"


def _open(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise DriveError(_describe(e.code, e.read().decode("utf-8", "replace")), e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise DriveError("Can't reach Google Drive. Check the internet connection.") from None


def _token_request(params):
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(params).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        return json.loads(_open(req, 15))
    except DriveError as e:
        if "invalid_grant" in str(e):
            raise NeedsReconnect("Google Drive access was revoked or expired. Connect again.", e.status) from None
        raise


# ---------- OAuth ----------
def auth_url(creds, redirect_uri, state):
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": creds["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state})


def _tokens(data, old_refresh=None):
    return {"access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", old_refresh),
            "expires_at": time.time() + int(data.get("expires_in", 3600))}


def exchange_code(creds, redirect_uri, code):
    data = _token_request({"code": code, "client_id": creds["client_id"], "client_secret": creds["client_secret"],
                           "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
    if not data.get("refresh_token"):
        raise DriveError("Google didn't return a long-lived sign-in. Remove this app's access in your "
                         "Google account settings and connect again.")
    return _tokens(data)


def refresh_tokens(creds, tokens):
    data = _token_request({"refresh_token": tokens["refresh_token"], "client_id": creds["client_id"],
                           "client_secret": creds["client_secret"], "grant_type": "refresh_token"})
    return _tokens(data, tokens["refresh_token"])


def revoke(token):
    try:
        _open(urllib.request.Request(REVOKE_URL, data=urllib.parse.urlencode({"token": token}).encode(),
                                     method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"}), 10)
    except DriveError:
        pass  # best effort


# ---------- Drive ----------
def multipart(meta, data):
    b = uuid.uuid4().hex
    head = (f"--{b}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{b}\r\nContent-Type: {MIME}\r\n\r\n").encode()
    return head + data + f"\r\n--{b}--".encode(), f"multipart/related; boundary={b}"


def _meta(f):
    p = f.get("appProperties") or {}
    return {"id": f["id"], "modified": f.get("modifiedTime"), "rev": p.get("rev"), "device": p.get("device")}


class GoogleDriveClient:
    def __init__(self, creds, tokens, on_tokens, timeout=20):
        self.creds, self.tokens, self.on_tokens, self.timeout = creds, tokens, on_tokens, timeout

    def _bearer(self):
        t = self.tokens or {}
        if not t.get("refresh_token"):
            raise NeedsReconnect("Google Drive isn't connected.")
        if t.get("access_token") and t.get("expires_at", 0) - 60 > time.time():
            return t["access_token"]
        self.tokens = refresh_tokens(self.creds, t)
        self.on_tokens(self.tokens)
        return self.tokens["access_token"]

    def _call(self, method, url, body=None, content_type=None):
        headers = {"Authorization": "Bearer " + self._bearer()}
        if content_type:
            headers["Content-Type"] = content_type
        try:
            return _open(urllib.request.Request(url, data=body, method=method, headers=headers), self.timeout)
        except DriveError as e:
            if e.status == 401:
                raise NeedsReconnect("Google Drive access expired. Connect again.", 401) from None
            raise

    def find(self, name):
        safe = name.replace("\\", "\\\\").replace("'", "\\'")
        url = f"{API}/files?" + urllib.parse.urlencode({
            "q": f"name = '{safe}' and trashed = false", "orderBy": "modifiedTime desc",
            "pageSize": 1, "fields": f"files({FIELDS})", "spaces": "drive"})
        files = json.loads(self._call("GET", url)).get("files", [])
        return _meta(files[0]) if files else None

    def get_meta(self, file_id):
        try:
            f = json.loads(self._call("GET", f"{API}/files/{file_id}?fields={FIELDS}"))
        except DriveError as e:
            if e.status == 404:
                return None
            raise
        return None if f.get("trashed") else _meta(f)

    def download(self, file_id):
        return self._call("GET", f"{API}/files/{file_id}?alt=media")

    def _upload(self, method, url, meta, data):
        body, ctype = multipart(meta, data)
        return _meta(json.loads(self._call(method, url, body, ctype)))

    def create(self, name, data, props):
        return self._upload("POST", f"{UPLOAD}/files?uploadType=multipart&fields={FIELDS}",
                            {"name": name, "mimeType": MIME, "appProperties": props}, data)

    def update(self, file_id, data, props):
        return self._upload("PATCH", f"{UPLOAD}/files/{file_id}?uploadType=multipart&fields={FIELDS}",
                            {"mimeType": MIME, "appProperties": props}, data)
