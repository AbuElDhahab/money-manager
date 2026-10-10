"""Google Drive tests. No network: sync logic runs against FakeDrive (shared by 'PC' and 'phone' apps),
the HTTP layer runs against recorded urlopen calls."""
import glob, io, json, os, re, shutil, sqlite3, sys, tempfile, time, unittest, urllib.error, urllib.parse
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app
from services import google_drive as gd
from services.drive_sync import plan
from test_app import make_legacy_db


class FakeDrive:
    def __init__(self):
        self.files, self.n, self.fail, self.log = {}, 0, None, []

    def _go(self, op):
        self.log.append(op)
        if self.fail:
            raise gd.DriveError(self.fail)

    def _meta(self, fid):
        f = self.files[fid]
        return {"id": fid, "modified": f["modified"], "rev": f["props"].get("rev"), "device": f["props"].get("device")}

    def find(self, name):
        self._go("find")
        hits = [i for i, f in self.files.items() if f["name"] == name]
        return self._meta(hits[-1]) if hits else None

    def get_meta(self, fid):
        self._go("meta")
        return self._meta(fid) if fid in self.files else None

    def download(self, fid):
        self._go("download")
        return self.files[fid]["data"]

    def create(self, name, data, props):
        self._go("create")
        self.n += 1
        fid = f"f{self.n}"
        self.files[fid] = {"name": name, "data": data, "props": dict(props), "modified": "2026-10-10T12:00:00.000Z"}
        return self._meta(fid)

    def update(self, fid, data, props):
        self._go("update")
        self.files[fid].update(data=data, props=dict(props))
        return self._meta(fid)

    def count(self, op):
        return self.log.count(op)

    def remote_db(self, tmp):
        path = os.path.join(tmp, "remote.db")
        with open(path, "wb") as f:
            f.write(next(iter(self.files.values()))["data"])
        con = sqlite3.connect(path)
        try:
            return dict(con.execute("SELECT account_name, balance FROM accounts")), \
                con.execute("SELECT COUNT(*) FROM income").fetchone()[0], con.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        finally:
            con.close()


class Device:
    def __init__(self, drive, name, tmp, configured=True, **cfg):
        self.dir = os.path.join(tmp, name)
        os.makedirs(self.dir)
        self.db = os.path.join(self.dir, "money.db")
        creds = os.path.join(self.dir, "credentials.json")
        if configured:
            with open(creds, "w") as f:
                json.dump({"web": {"client_id": "cid", "client_secret": "sec",
                                   "redirect_uris": ["http://127.0.0.1:5000/drive/callback"]}}, f)
        conf = {"DB_PATH": self.db, "TESTING": True, "GOOGLE_CREDENTIALS_PATH": creds, "DRIVE_INLINE": True,
                "DRIVE_CHECK_INTERVAL": 0, "DRIVE_DEVICE_NAME": name}
        if drive is not None:
            conf["DRIVE_CLIENT"] = drive
        conf.update(cfg)
        self.app = create_app(conf)
        self.c = self.app.test_client()
        self.c.get("/")
        self.sync = self.app.extensions["drive"]

    def connect(self):
        self.sync.save(connected=True, tokens={"refresh_token": "r", "access_token": "a", "expires_at": time.time() + 3600})
        return self.sync.manual_sync()

    def post(self, url, **data):
        with self.c.session_transaction() as s:
            data["_csrf"] = s["_csrf"]
        return self.c.post(url, data=data, follow_redirects=True)

    def income(self, amount="1000", date="2026-10-01", source="Salary"):
        return self.post("/income/save", record_date=date, amount=amount, source=source)

    def expense(self, amount="100", acc="1", cat="Housing"):
        return self.post("/expenses/save", record_date="2026-10-02", amount=amount, account_id=acc, main_category=cat)

    def q(self, sql):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def bal(self):
        return dict(self.q("SELECT account_name, balance FROM accounts"))

    def page(self, url="/"):
        r = self.c.get(url)
        assert r.status_code == 200, (url, r.status_code)
        return r.get_data(as_text=True)


class DriveBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.drive = FakeDrive()
        self.pc = Device(self.drive, "PC", self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def phone(self):
        return Device(self.drive, "Phone", self.tmp)

    def assertRemoteMatches(self, dev):
        bal, n_in, n_ex = self.drive.remote_db(self.tmp)
        self.assertEqual(bal, dev.bal())
        self.assertEqual(n_in, dev.q("SELECT COUNT(*) FROM income")[0][0])
        self.assertEqual(n_ex, dev.q("SELECT COUNT(*) FROM expenses")[0][0])


class TestPlan(unittest.TestCase):
    def test_decision_table(self):
        r = lambda rev: {"rev": rev}
        cases = [(False, None, None, "push"), (True, "a", None, "push"), (False, None, r("x"), "choose"),
                 (True, None, r("x"), "choose"), (False, "a", r("a"), "none"), (True, "a", r("a"), "push"),
                 (False, "a", r("b"), "pull"), (True, "a", r("b"), "conflict")]
        for dirty, synced, remote, want in cases:
            self.assertEqual(plan(dirty, synced, remote), want, (dirty, synced, remote))


class TestBackup(DriveBase):
    def test_first_connect_creates_backup(self):
        res = self.pc.connect()
        self.assertEqual(res["action"], "push")
        self.assertEqual([f["name"] for f in self.drive.files.values()], ["ledger-backup.db"])
        st = self.pc.sync.load()
        self.assertFalse(st["dirty"])
        self.assertEqual(st["synced_rev"], next(iter(self.drive.files.values()))["props"]["rev"])
        self.assertEqual(self.pc.sync.status()["state"], "synced")

    def test_every_change_is_backed_up(self):
        self.pc.connect()
        steps = [lambda: self.pc.income("1000"), lambda: self.pc.expense("100"),
                 lambda: self.pc.post("/income/save", id="1", record_date="2026-10-01", amount="2000", source="Salary"),
                 lambda: self.pc.post("/expenses/save", id="1", record_date="2026-10-02", amount="50", account_id="2", main_category="Food"),
                 lambda: self.pc.post("/accounts/save", id="1", account_name="Needs", account_percentage="40", balance="7800"),
                 lambda: self.pc.post("/accounts/save", account_name="Trip", account_percentage="10"),
                 lambda: self.pc.post("/expenses/delete/1"), lambda: self.pc.post("/income/delete/1"),
                 lambda: self.pc.post("/accounts/save", id="4", account_name="Trip", account_percentage="0", balance="0"),
                 lambda: self.pc.post("/accounts/delete/4")]
        for i, step in enumerate(steps, 1):
            step()
            self.assertEqual(self.drive.count("update"), i, f"step {i}")
            self.assertRemoteMatches(self.pc)
            self.assertFalse(self.pc.sync.load()["dirty"])
        self.assertEqual(self.pc.bal()["Needs"], 6800)  # 7800 set by hand, minus the deleted income's 1000 share

    def test_rejected_input_is_not_backed_up(self):
        self.pc.connect()
        self.pc.income("abc"); self.pc.expense("0"); self.pc.post("/income/delete/99")
        self.assertEqual(self.drive.count("update"), 0)

    def test_device_import_is_backed_up(self):
        self.pc.connect()
        legacy = os.path.join(self.tmp, "legacy.db"); make_legacy_db(legacy)
        with open(legacy, "rb") as f:
            blob = f.read()
        with self.pc.c.session_transaction() as s:
            tok = s["_csrf"]
        self.pc.c.post("/data/import", data={"_csrf": tok, "dbfile": (io.BytesIO(blob), "x.db")},
                       content_type="multipart/form-data", follow_redirects=True)
        self.assertEqual(self.drive.count("update"), 1)
        self.assertEqual(self.drive.remote_db(self.tmp)[0]["Needs"], 7800)

    def test_not_connected_does_nothing(self):
        self.pc.income()
        self.assertEqual(self.drive.log, [])
        self.assertEqual(self.pc.sync.status()["state"], "disconnected")

    def test_auto_sync_off(self):
        self.pc.connect(); self.pc.sync.set_auto(False)
        self.pc.income()
        self.assertEqual(self.drive.count("update"), 0)
        self.assertTrue(self.pc.sync.load()["dirty"])
        self.assertEqual(self.pc.sync.status()["state"], "pending")
        self.pc.page("/")  # no automatic pull/push either
        self.assertEqual(self.drive.count("update"), 0)
        self.assertEqual(self.pc.sync.manual_sync()["action"], "push")
        self.assertRemoteMatches(self.pc)

    def test_offline_keeps_data_and_recovers(self):
        self.pc.connect()
        self.drive.fail = "Can't reach Google Drive. Check the internet connection."
        shown = self.pc.income("500").get_data(as_text=True)  # the page you land on after saving
        self.assertEqual(self.pc.bal()["Needs"], 250)  # saved locally regardless
        self.assertEqual(self.pc.sync.status()["state"], "error")
        self.assertIn("back up to Google Drive", shown)  # one-time warning
        self.drive.fail = None
        self.pc.sync._next_check = 0  # ...a minute later (the failed check above started a back-off)
        self.pc.page("/")  # opening a page retries the unsent backup
        self.assertEqual(self.pc.sync.status()["state"], "synced")
        self.assertRemoteMatches(self.pc)

    def test_remote_file_deleted_is_recreated(self):
        self.pc.connect(); self.drive.files.clear()
        self.pc.income()
        self.assertEqual(self.drive.count("create"), 2)
        self.assertRemoteMatches(self.pc)

    def test_change_during_upload_stays_dirty(self):
        self.pc.connect()
        sync, orig = self.pc.sync, self.drive.update
        def racing_update(fid, data, props):
            sync.save(changes=sync.load().get("changes", 0) + 1)  # a save lands while uploading
            return orig(fid, data, props)
        self.drive.update = racing_update
        self.pc.income()
        self.assertTrue(sync.load()["dirty"])


class TestTwoDevices(DriveBase):
    def test_phone_imports_then_follows_pc(self):
        self.pc.post("/accounts/save", id="1", account_name="Needs", account_percentage="50", balance="7800")
        self.pc.income("1000")
        self.pc.connect()
        phone = self.phone()
        self.assertEqual(phone.connect()["action"], "choose")  # existing backup: ask first
        phone.income("5")  # while undecided nothing is pushed or pulled
        self.assertEqual(self.drive.count("update"), 0)
        self.assertEqual(phone.sync.status()["state"], "choose")
        self.assertEqual(phone.sync.force_pull()["action"], "pull")
        self.assertEqual(phone.bal(), self.pc.bal())  # stored balances travel exactly (7800 + share)
        self.assertEqual(phone.bal()["Needs"], 8300)
        self.assertEqual(len(glob.glob(phone.db + ".before-drive-*.backup")), 1)
        self.pc.income("100", date="2026-10-03")  # PC changes...
        html = phone.page("/")  # ...phone picks it up on the next page view
        self.assertIn("Updated from Google Drive", html.replace("Imported the data from Google Drive", "Updated from Google Drive"))
        self.assertEqual(phone.bal(), self.pc.bal())
        phone.expense("40", acc="2")  # and the other way round
        self.pc.page("/")
        self.assertEqual(self.pc.bal(), phone.bal())

    def test_conflict_is_never_overwritten_use_drive(self):
        self.pc.connect(); phone = self.phone(); phone.connect(); phone.sync.force_pull()
        self.pc.income("1000")  # PC backs up first
        remote_before = next(iter(self.drive.files.values()))["props"]["rev"]
        landed = phone.income("7", source="Phone only").get_data(as_text=True)  # never saw PC's change -> conflict
        self.assertEqual(next(iter(self.drive.files.values()))["props"]["rev"], remote_before)
        self.assertEqual(phone.sync.status()["state"], "conflict")
        self.assertEqual(phone.sync.nav_level(), "warn")
        self.assertIn("newer changes", landed)  # one-time warning on the page you land on
        page = phone.page("/data/")
        self.assertIn("Use Google Drive", page); self.assertIn("Keep this device", page)
        self.assertEqual(phone.sync.maybe_pull(), None)  # no auto action while undecided
        res = phone.sync.force_pull()
        self.assertEqual(res["action"], "pull")
        saved = glob.glob(phone.db + ".before-drive-*.backup")
        self.assertEqual(len(saved), 1)
        con = sqlite3.connect(saved[0])
        self.assertIn("Phone only", [r[0] for r in con.execute("SELECT source FROM income")])  # nothing lost
        con.close()
        self.assertNotIn("Phone only", [r[0] for r in phone.q("SELECT source FROM income")])
        self.assertEqual(phone.sync.status()["state"], "synced")

    def test_conflict_keep_this_device(self):
        self.pc.connect(); phone = self.phone(); phone.connect(); phone.sync.force_pull()
        self.pc.income("1000"); phone.income("7", source="Phone only")
        self.assertEqual(phone.sync.force_push()["action"], "push")
        self.assertRemoteMatches(phone)
        self.pc.page("/")  # PC is clean, so it follows
        self.assertIn("Phone only", [r[0] for r in self.pc.q("SELECT source FROM income")])

    def test_manual_sync_pulls_when_clean(self):
        self.pc.connect(); phone = self.phone(); phone.connect(); phone.sync.force_pull()
        self.pc.income("300")
        phone.sync.set_auto(False)
        self.assertEqual(phone.sync.manual_sync()["action"], "pull")
        self.assertEqual(phone.bal(), self.pc.bal())

    def test_legacy_balances_survive_the_round_trip(self):
        legacy = os.path.join(self.tmp, "legacy.db"); make_legacy_db(legacy)
        with open(legacy, "rb") as f:
            blob = f.read()
        self.pc.connect()
        with self.pc.c.session_transaction() as s:
            tok = s["_csrf"]
        self.pc.c.post("/data/import", data={"_csrf": tok, "dbfile": (io.BytesIO(blob), "x.db")},
                       content_type="multipart/form-data")
        phone = self.phone(); phone.connect(); phone.sync.force_pull()
        self.assertEqual(phone.bal(), {"Needs": 7800, "Wants": 4321.5, "Savings": 1500})

    def test_bad_remote_file_is_refused(self):
        self.pc.connect(); phone = self.phone(); phone.connect(); phone.sync.force_pull()
        f = next(iter(self.drive.files.values()))
        f["data"], f["props"]["rev"] = b"definitely not a database", "other-rev"
        before = phone.bal()
        self.assertIn("can't be used", phone.sync.maybe_pull()["message"])
        self.assertEqual(phone.bal(), before)
        phone.page("/"); phone.page("/data/")  # app keeps working
        self.assertEqual(phone.sync.status()["state"], "error")
        self.assertEqual(phone.sync.nav_level(), "err")
        self.assertIn("can&#39;t be used", phone.page("/data/"))


class TestBackoff(DriveBase):
    def test_failed_checks_back_off_instead_of_retrying_every_click(self):
        self.pc.connect(); self.pc.sync.interval = 30
        self.drive.fail = "Can't reach Google Drive. Check the internet connection."
        self.pc.page("/")
        calls = len(self.drive.log)
        for _ in range(5):
            self.pc.page("/accounts/")
        self.assertEqual(len(self.drive.log), calls)  # pages stay fast while offline


class TestConnectionManagement(DriveBase):
    def test_disconnect_forgets_link_but_keeps_drive_file(self):
        self.pc.connect()
        self.pc.post("/drive/disconnect")
        st = self.pc.sync.load()
        self.assertFalse(st["connected"]); self.assertIsNone(st["tokens"]); self.assertIsNone(st["synced_rev"])
        self.assertEqual(len(self.drive.files), 1)
        before = self.drive.count("update")
        self.pc.income()
        self.assertEqual(self.drive.count("update"), before)
        self.assertEqual(self.pc.connect()["action"], "choose")  # reconnecting asks again

    @unittest.skipIf(os.name == "nt", "posix permissions")
    def test_state_file_is_private(self):
        self.pc.connect()
        self.assertEqual(os.stat(self.pc.sync.state_path).st_mode & 0o777, 0o600)

    def test_data_page_in_every_state_and_no_secrets(self):
        none = Device(None, "Bare", self.tmp, configured=False)
        self.assertIn("credentials.json", none.page("/data/"))
        self.assertIn("Connect Google Drive", self.pc.page("/data/"))
        self.pc.connect()
        h = self.pc.page("/data/")
        for text in ("Sync now", "Import from Google Drive", "Back up now", "Automatic sync", "Disconnect", "Backed up and in sync"):
            self.assertIn(text, h)
        self.assertNotIn("refresh_token", h); self.assertNotIn("expires_at", h)
        self.assertIn("dot ok", h)
        self.pc.sync.set_auto(False); self.pc.income()
        self.assertIn("Changes waiting", self.pc.page("/data/"))
        self.pc.sync.save(needs_reconnect=True, last_error="Google Drive access was revoked or expired. Connect again.")
        self.assertIn("Reconnect", self.pc.page("/data/"))

    def test_routes_need_csrf_and_work(self):
        for url in ("/drive/sync", "/drive/push", "/drive/pull", "/drive/auto", "/drive/disconnect"):
            self.assertEqual(self.pc.c.post(url).status_code, 400, url)
        self.pc.connect(); self.pc.income("100")
        self.assertIn("Backed up", self.pc.post("/drive/push").get_data(as_text=True))
        self.pc.income("5", date="2026-10-05"); self.pc.sync.set_auto(False)
        self.assertIn("Backed up", self.pc.post("/drive/sync").get_data(as_text=True))
        self.pc.income("5", date="2026-10-06")
        self.assertIn("Imported the data from Google Drive", self.pc.post("/drive/pull").get_data(as_text=True))
        self.assertEqual(self.pc.q("SELECT COUNT(*) FROM income")[0][0], 2)  # last local-only change replaced
        self.pc.post("/drive/auto", enabled="1")
        self.assertTrue(self.pc.sync.load()["auto_sync"])

    def test_pull_with_no_remote_backup(self):
        self.pc.connect(); self.drive.files.clear()
        self.assertIn("no backup", self.pc.post("/drive/pull").get_data(as_text=True))

    def test_oauth_flow(self):
        r = self.pc.c.get("/drive/connect")
        self.assertEqual(r.status_code, 302)
        q = urllib.parse.urlparse(r.headers["Location"])
        self.assertEqual(q.netloc, "accounts.google.com")
        args = urllib.parse.parse_qs(q.query)
        self.assertEqual(args["client_id"], ["cid"])
        self.assertEqual(args["redirect_uri"], ["http://127.0.0.1:5000/drive/callback"])
        self.assertEqual(args["scope"], [gd.SCOPE]); self.assertEqual(args["access_type"], ["offline"])
        state = args["state"][0]
        h = self.pc.c.get("/drive/callback?code=abc&state=WRONG", follow_redirects=True).get_data(as_text=True)
        self.assertIn("didn", h); self.assertFalse(self.pc.sync.load().get("connected"))
        h = self.pc.c.get("/drive/callback?error=access_denied", follow_redirects=True).get_data(as_text=True)
        self.assertIn("cancelled", h)
        seen = {}
        def fake_exchange(creds, uri, code):
            seen.update(creds=creds, uri=uri, code=code)
            return {"access_token": "a", "refresh_token": "r", "expires_at": time.time() + 3600}
        self.pc.sync.exchange = fake_exchange
        h = self.pc.c.get(f"/drive/callback?code=abc&state={state}", follow_redirects=True).get_data(as_text=True)
        self.assertEqual((seen["code"], seen["uri"]), ("abc", "http://127.0.0.1:5000/drive/callback"))
        self.assertIn("backed up to Google Drive", h)
        self.assertTrue(self.pc.sync.load()["connected"]); self.assertEqual(len(self.drive.files), 1)
        self.pc.c.get(f"/drive/callback?code=abc&state={state}")  # a state can't be reused
        self.assertIsNone(self.pc.sync.load()["oauth_state"])

    def test_connect_without_credentials(self):
        none = Device(None, "Bare", self.tmp, configured=False)
        self.assertIn("isn", none.c.get("/drive/connect", follow_redirects=True).get_data(as_text=True))


# ---------------- HTTP layer ----------------
class Resp:
    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else body.encode()
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *a): return False


def http_error(code, body):
    return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body.encode()))


CREDS = {"client_id": "cid", "client_secret": "sec", "redirect_uris": []}


class TestGoogleHttp(unittest.TestCase):
    def client(self, tokens=None, on_tokens=None):
        return gd.GoogleDriveClient(CREDS, tokens or {"access_token": "tok", "refresh_token": "r", "expires_at": time.time() + 3600},
                                    on_tokens or (lambda t: None))

    def test_credentials_formats(self):
        with tempfile.TemporaryDirectory() as d:
            for key in ("web", "installed"):
                p = os.path.join(d, key + ".json")
                with open(p, "w") as f:
                    json.dump({key: {"client_id": "i", "client_secret": "s", "redirect_uris": ["http://127.0.0.1:5000/drive/callback"]}}, f)
                self.assertEqual(gd.load_credentials(p)["client_id"], "i")
            self.assertIsNone(gd.load_credentials(os.path.join(d, "missing.json")))
            with open(os.path.join(d, "bad.json"), "w") as f:
                f.write("{not json")
            self.assertIsNone(gd.load_credentials(os.path.join(d, "bad.json")))
            with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "e", "GOOGLE_CLIENT_SECRET": "es"}):
                self.assertEqual(gd.load_credentials(os.path.join(d, "missing.json"))["client_id"], "e")
        self.assertEqual(gd.pick_redirect({"redirect_uris": ["http://a/other", "http://b/drive/callback"]}, "d"), "http://b/drive/callback")
        self.assertEqual(gd.pick_redirect({"redirect_uris": ["http://a/other"]}, "dflt"), "dflt")

    def test_exchange_code(self):
        with mock.patch("urllib.request.urlopen", return_value=Resp(json.dumps({"access_token": "A", "refresh_token": "R", "expires_in": 3600}))) as m:
            t = gd.exchange_code(CREDS, "http://r/drive/callback", "the-code")
        req = m.call_args[0][0]
        self.assertEqual(req.full_url, gd.TOKEN_URL)
        body = urllib.parse.parse_qs(req.data.decode())
        self.assertEqual(body["grant_type"], ["authorization_code"]); self.assertEqual(body["code"], ["the-code"])
        self.assertEqual((t["access_token"], t["refresh_token"]), ("A", "R"))
        with mock.patch("urllib.request.urlopen", return_value=Resp(json.dumps({"access_token": "A"}))):
            with self.assertRaises(gd.DriveError):
                gd.exchange_code(CREDS, "u", "c")  # no refresh token

    def test_refresh_when_expired_and_saved(self):
        saved = []
        c = self.client({"access_token": "old", "refresh_token": "R", "expires_at": time.time() - 10}, saved.append)
        calls = [Resp(json.dumps({"access_token": "new", "expires_in": 3600})), Resp(json.dumps({"files": []}))]
        with mock.patch("urllib.request.urlopen", side_effect=calls) as m:
            self.assertIsNone(c.find("x.db"))
        self.assertEqual(m.call_args_list[1][0][0].get_header("Authorization"), "Bearer new")
        self.assertEqual(saved[0]["refresh_token"], "R")  # refresh token kept

    def test_revoked_means_reconnect(self):
        c = self.client({"access_token": "old", "refresh_token": "R", "expires_at": 0})
        with mock.patch("urllib.request.urlopen", side_effect=http_error(400, '{"error":"invalid_grant","error_description":"Token has been expired"}')):
            with self.assertRaises(gd.NeedsReconnect):
                c.find("x")
        with mock.patch("urllib.request.urlopen", side_effect=http_error(401, '{"error":{"message":"Invalid Credentials"}}')):
            with self.assertRaises(gd.NeedsReconnect):
                self.client().find("x")

    def test_find_get_download(self):
        listing = {"files": [{"id": "F1", "modifiedTime": "T", "appProperties": {"rev": "r1", "device": "PC"}}]}
        with mock.patch("urllib.request.urlopen", return_value=Resp(json.dumps(listing))) as m:
            meta = self.client().find("it's.db")
        url = urllib.parse.unquote_plus(m.call_args[0][0].full_url)
        self.assertIn("trashed = false", url); self.assertIn("name = 'it\\'s.db'", url)
        self.assertEqual(meta, {"id": "F1", "modified": "T", "rev": "r1", "device": "PC"})
        with mock.patch("urllib.request.urlopen", return_value=Resp(b"\x00bytes")) as m:
            self.assertEqual(self.client().download("F1"), b"\x00bytes")
        self.assertIn("alt=media", m.call_args[0][0].full_url)
        with mock.patch("urllib.request.urlopen", side_effect=http_error(404, "{}")):
            self.assertIsNone(self.client().get_meta("gone"))
        with mock.patch("urllib.request.urlopen", return_value=Resp(json.dumps({"id": "F", "trashed": True}))):
            self.assertIsNone(self.client().get_meta("F"))  # in the bin = missing

    def test_upload_requests(self):
        ok = Resp(json.dumps({"id": "F9", "appProperties": {"rev": "R"}}))
        data = b"SQLite format 3\x00\x01\x02binary"
        for method, call, args, expect in [
            ("POST", "create", ("ledger-backup.db", data, {"rev": "R", "device": "PC"}), f"{gd.UPLOAD}/files?uploadType=multipart"),
            ("PATCH", "update", ("F9", data, {"rev": "R", "device": "PC"}), f"{gd.UPLOAD}/files/F9?uploadType=multipart")]:
            with mock.patch("urllib.request.urlopen", return_value=ok) as m:
                meta = getattr(self.client(), call)(*args)
            req = m.call_args[0][0]
            self.assertEqual(req.get_method(), method); self.assertTrue(req.full_url.startswith(expect))
            ctype = req.get_header("Content-type")
            boundary = ctype.split("boundary=")[1]
            self.assertTrue(ctype.startswith("multipart/related"))
            parts = req.data.split(("--" + boundary).encode())
            self.assertEqual(parts[-1], b"--"); self.assertEqual(len(parts), 4)
            self.assertIn(b"application/json", parts[1]); self.assertIn(b'"rev": "R"', parts[1])
            self.assertIn(data, parts[2])
            self.assertEqual(meta["id"], "F9")

    def test_network_down(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("dns")):
            with self.assertRaises(gd.DriveError) as cm:
                self.client().find("x")
        self.assertIn("Can't reach", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
