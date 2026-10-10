"""Run:  python -m unittest discover -s tests -v"""
import json, os, re, shutil, sqlite3, sys, tempfile, unittest
from html import unescape

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "t.db")
        self.app = create_app({"DB_PATH": self.db, "TESTING": True})
        self.c = self.app.test_client()
        self.c.get("/")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def token(self):
        with self.c.session_transaction() as s:
            return s["_csrf"]

    def post(self, url, **data):
        data["_csrf"] = self.token()
        return self.c.post(url, data=data, follow_redirects=True)

    def q(self, sql, *args):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()

    def balances(self):
        return dict(self.q("SELECT account_name, balance FROM accounts"))

    def income(self, amount="1000", date="2026-10-01", source="Salary"):
        return self.post("/income/save", record_date=date, amount=amount, source=source)

    def expense(self, amount="100", date="2026-10-02", acc="1", cat="Housing", sub="Rent", **kw):
        return self.post("/expenses/save", record_date=date, amount=amount, account_id=acc,
                         main_category=cat, sub_category=sub, **kw)


class TestSetup(Base):
    def test_seed_accounts(self):
        self.assertEqual(self.q("SELECT account_name, account_percentage FROM accounts ORDER BY id"),
                         [("Needs", 50), ("Wants", 30), ("Savings", 20)])

    def test_pages_empty_and_populated(self):
        urls = ["/", "/accounts/", "/income/", "/expenses/"]
        for u in urls:
            self.assertEqual(self.c.get(u).status_code, 200, u)
        self.income(); self.expense()
        for u in urls:
            self.assertEqual(self.c.get(u).status_code, 200, u)

    def test_404_page(self):
        r = self.c.get("/nope")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Page not found", r.get_data(as_text=True))

    def test_csrf_required(self):
        r = self.c.post("/income/save", data={"record_date": "2026-10-01", "amount": "5", "source": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.q("SELECT COUNT(*) FROM income")[0][0], 0)


class TestBalances(Base):
    def test_income_split_and_edit_delete(self):
        self.income("1000")
        self.assertEqual(self.balances(), {"Needs": 500, "Wants": 300, "Savings": 200})
        self.post("/income/save", id="1", record_date="2026-10-01", amount="2000", source="Salary")
        self.assertEqual(self.balances()["Needs"], 1000)
        self.post("/income/delete/1")
        self.assertEqual(self.balances(), {"Needs": 0, "Wants": 0, "Savings": 0})

    def test_expense_edit_move_delete(self):
        self.income("1000"); self.expense("100", acc="1")
        self.assertEqual(self.balances()["Needs"], 400)
        self.expense("50", acc="2", id="1")  # move to Wants, new amount
        self.assertEqual(self.balances(), {"Needs": 500, "Wants": 250, "Savings": 200})
        self.post("/expenses/delete/1")
        self.assertEqual(self.balances()["Wants"], 300)

    def test_overspend_warning(self):
        self.income("100")
        r = self.expense("80", acc="1")
        self.assertIn("overspent", r.get_data(as_text=True))
        self.assertEqual(self.balances()["Needs"], -30)

    def test_invariant_after_many_ops(self):
        for i in range(5):
            self.income(str(100 + i * 33.33)); self.expense(str(10 + i * 7.77), acc=str(i % 3 + 1))
        self.post("/accounts/save", id="1", account_name="Needs", account_percentage="40")
        tin = self.q("SELECT SUM(amount) FROM income")[0][0]
        tex = self.q("SELECT SUM(amount) FROM expenses")[0][0]
        tot = sum(self.balances().values())
        self.assertAlmostEqual(tot, tin - tex, delta=0.1)


class TestPercentageChanges(Base):
    def test_editing_percentage_keeps_balance(self):
        self.income("1000")
        before = self.balances()
        self.post("/accounts/save", id="1", account_name="Needs", account_percentage="10")
        self.post("/accounts/save", id="2", account_name="Wants", account_percentage="60")
        self.assertEqual(self.balances(), before)
        self.income("1000", date="2026-10-03")  # new income uses the new split
        self.assertEqual(self.balances(), {"Needs": 600, "Wants": 900, "Savings": 400})

    def test_edit_and_delete_old_income_use_original_split(self):
        self.income("1000")
        self.post("/accounts/save", id="1", account_name="Needs", account_percentage="10")
        self.post("/accounts/save", id="2", account_name="Wants", account_percentage="70")
        self.post("/income/save", id="1", record_date="2026-10-01", amount="500", source="Salary")
        self.assertEqual(self.balances(), {"Needs": 250, "Wants": 150, "Savings": 100})
        self.post("/income/delete/1")
        self.assertEqual(self.balances(), {"Needs": 0, "Wants": 0, "Savings": 0})
        self.assertEqual(self.q("SELECT COUNT(*) FROM income_allocations")[0][0], 0)

    def test_new_account_gets_no_past_income(self):
        self.income("1000")
        self.post("/accounts/save", id="3", account_name="Savings", account_percentage="10")
        self.post("/accounts/save", account_name="Fun", account_percentage="10")
        self.assertEqual(self.balances()["Fun"], 0)
        self.income("100", date="2026-10-04")
        self.assertEqual(self.balances()["Fun"], 10)

    def test_overview_account_income_ignores_later_percent_change(self):
        self.income("1000")
        self.post("/accounts/save", id="1", account_name="Needs", account_percentage="5")
        h = self.c.get("/?account_id=1").get_data(as_text=True)
        self.assertIn("500.00", h)



def make_legacy_db(path):
    """A database like one from an older version: no allocations table, balances already stored."""
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")) as f:
        schema = f.read()
    con = sqlite3.connect(path)
    con.executescript(schema.split("-- Extra table")[0])
    con.executemany("INSERT INTO accounts (account_name, account_percentage, balance) VALUES (?,?,?)",
                    [("Needs", 50, 7800), ("Wants", 30, 4321.5), ("Savings", 20, 1500)])
    con.executemany("INSERT INTO income (record_date, amount, source) VALUES (?,?,?)",
                    [("2026-07-25", 9000, "Salary"), ("2026-08-25", 9000, "Salary"), ("2026-09-25", 9000, "Salary")])
    con.execute("INSERT INTO expenses (record_date, amount, account_id, main_category, sub_category) "
                "VALUES ('2026-09-26', 250, 1, 'Food', 'Groceries')")
    con.execute("PRAGMA user_version = 0")
    con.commit(); con.close()


class TestExistingDatabase(Base):
    def setUp(self):
        super().setUp()
        self.db = os.path.join(self.tmp, "legacy.db")
        make_legacy_db(self.db)
        self.app = create_app({"DB_PATH": self.db, "TESTING": True})
        self.c = self.app.test_client(); self.c.get("/")

    def test_balances_untouched_on_import_and_restart(self):
        want = {"Needs": 7800, "Wants": 4321.5, "Savings": 1500}
        self.assertEqual(self.balances(), want)
        for _ in range(2):
            create_app({"DB_PATH": self.db, "TESTING": True})
        self.assertEqual(self.balances(), want)
        self.assertEqual(self.q("PRAGMA user_version")[0][0], 2)

    def test_backup_made_before_upgrade(self):
        con = sqlite3.connect(self.db + ".backup")
        self.assertEqual(con.execute("SELECT balance FROM accounts WHERE id=1").fetchone()[0], 7800)
        con.close()

    def test_old_income_has_a_split_but_no_balance_effect(self):
        self.assertEqual(self.q("SELECT COUNT(*) FROM income_allocations")[0][0], 9)
        self.post("/accounts/save", id="1", account_name="Needs", account_percentage="10")
        self.assertEqual(self.balances()["Needs"], 7800)

    def test_working_on_old_data_adjusts_by_difference(self):
        self.income("1000")
        self.assertEqual(self.balances()["Needs"], 8300)
        self.expense("300", acc="1")
        self.assertEqual(self.balances()["Needs"], 8000)
        self.post("/expenses/delete/1")  # the old 250 expense comes back
        self.assertEqual(self.balances()["Needs"], 8250)
        self.post("/income/delete/1")  # an old 9000 income leaves its 50% share
        self.assertEqual(self.balances()["Needs"], 3750)

    def test_restart_keeps_manual_values_for_current_version(self):
        self.post("/accounts/save", id="1", account_name="Needs", account_percentage="50", balance="1234.56")
        create_app({"DB_PATH": self.db, "TESTING": True})
        self.assertEqual(self.balances()["Needs"], 1234.56)


class TestManualBalance(Base):
    def test_edit_balance_directly(self):
        r = self.post("/accounts/save", id="1", account_name="Needs", account_percentage="50", balance="7800")
        self.assertEqual(self.balances()["Needs"], 7800)
        self.income("100")  # 50% = 50 added on top of the manual value
        self.assertEqual(self.balances()["Needs"], 7850)
        self.expense("25", acc="1")
        self.assertEqual(self.balances()["Needs"], 7825)
        self.post("/income/save", id="1", record_date="2026-10-01", amount="200", source="Salary")
        self.assertEqual(self.balances()["Needs"], 7875)  # +50 more, not a reset
        self.post("/expenses/delete/1")
        self.assertEqual(self.balances()["Needs"], 7900)

    def test_negative_allowed_and_blank_keeps(self):
        self.post("/accounts/save", id="1", account_name="Needs", account_percentage="50", balance="-40.5")
        self.assertEqual(self.balances()["Needs"], -40.5)
        self.post("/accounts/save", id="1", account_name="Needs", account_percentage="45", balance="")
        self.assertEqual(self.balances()["Needs"], -40.5)
        self.post("/accounts/save", id="1", account_name="Needs", account_percentage="40")  # field absent
        self.assertEqual(self.balances()["Needs"], -40.5)

    def test_invalid_balance_rejected(self):
        for bad in ["abc", "nan", "inf", "1e99"]:
            r = self.post("/accounts/save", id="1", account_name="Needs", account_percentage="50", balance=bad)
            self.assertIn("valid balance", r.get_data(as_text=True))
        self.assertEqual(self.balances()["Needs"], 0)

    def test_new_account_with_opening_balance(self):
        self.post("/accounts/save", id="3", account_name="Savings", account_percentage="10")
        self.post("/accounts/save", account_name="Trip", account_percentage="10", balance="250")
        self.assertEqual(self.balances()["Trip"], 250)
        self.income("100")
        self.assertEqual(self.balances()["Trip"], 260)

    def test_modal_has_balance_field_and_prefills(self):
        self.post("/accounts/save", id="1", account_name="Needs", account_percentage="50", balance="7800")
        h = self.c.get("/accounts/").get_data(as_text=True)
        self.assertIn('name="balance"', h)
        self.assertEqual(json.loads(unescape(re.search(r"data-edit='(.*?)'", h).group(1)))["balance"], 7800)


class TestDoughnut(Base):
    def cats(self, n):
        self.income("100000")
        for i in range(n):  # category i has total (i+1)*10, so C{n-1} is biggest
            self.expense(str((i + 1) * 10), cat=f"C{i}", acc="1")
        h = self.c.get("/").get_data(as_text=True)
        d = json.loads(re.search(r"window.DATA = (.*?);</script>", h, re.S).group(1))
        return d["cats"], d["catTotals"]

    def test_top_five_plus_other(self):
        names, totals = self.cats(9)
        self.assertEqual(names[:5], ["C8", "C7", "C6", "C5", "C4"])
        self.assertEqual(names[5], "Other (4 categories)")
        self.assertEqual(totals[5], 10 + 20 + 30 + 40)
        self.assertEqual(len(names), 6)

    def test_few_categories_shown_as_is(self):
        self.assertEqual(len(self.cats(5)[0]), 5)

    def test_single_leftover_not_hidden(self):
        names, _ = self.cats(6)
        self.assertEqual(names[-1], "C0")
        self.assertFalse(any(n.startswith("Other") for n in names))

    def test_other_total_matches_all_spending(self):
        _, totals = self.cats(12)
        self.assertEqual(sum(totals), sum((i + 1) * 10 for i in range(12)))

    def test_filter_applies_before_grouping(self):
        self.cats(9)
        h = self.c.get("/?category=C8").get_data(as_text=True)
        d = json.loads(re.search(r"window.DATA = (.*?);</script>", h, re.S).group(1))
        self.assertEqual(d["cats"], ["C8"])


import csv, glob, io


def rb(path):
    with open(path, "rb") as f:
        return f.read()


def parse_csv(response):
    text = response.get_data().decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


class TestCsvExport(Base):
    def setUp(self):
        super().setUp()
        self.income("1000", "2026-09-10", "Salary"); self.income("200.5", "2026-10-05", "Freelance")
        self.expense("100", "2026-09-12", "1", "Housing", "Rent")
        self.expense("40", "2026-10-06", "2", "Food", "Cafe")
        self.expense("60", "2026-10-07", "1", "Food", "Groceries")

    def test_headers_and_download(self):
        r = self.c.get("/expenses/export.csv")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.mimetype == "text/csv")
        self.assertRegex(r.headers["Content-Disposition"], r'attachment; filename="expenses_\d{4}-\d{2}-\d{2}\.csv"')
        self.assertTrue(r.get_data().startswith(b"\xef\xbb\xbf"))  # BOM for Excel
        rows = parse_csv(r)
        self.assertEqual(rows[0], ["Date", "Account", "Category", "Sub-category", "Amount", "Created at"])
        self.assertEqual(len(rows), 4)

    def test_expenses_csv_follows_filters_exactly_like_the_page(self):
        cases = ["", "?account_id=1", "?category=food", "?account_id=1&category=food",
                 "?start=2026-10-01&end=2026-10-31", "?start=2026-10-31&end=2026-10-01", "?start=zzz&account_id=abc"]
        for q in cases:
            page = self.c.get("/expenses/" + q).get_data(as_text=True)
            shown = len(re.findall(r'<td data-l="Date">', page))
            self.assertEqual(len(parse_csv(self.c.get("/expenses/export.csv" + q))) - 1, shown, q)
        rows = parse_csv(self.c.get("/expenses/export.csv?account_id=1&category=food"))
        self.assertEqual(rows[1][:5], ["2026-10-07", "Needs", "Food", "Groceries", "60.00"])

    def test_income_csv_follows_filters(self):
        self.assertEqual(len(parse_csv(self.c.get("/income/export.csv"))), 3)
        rows = parse_csv(self.c.get("/income/export.csv?source=free"))
        self.assertEqual([r[:3] for r in rows[1:]], [["2026-10-05", "Freelance", "200.50"]])
        self.assertEqual(len(parse_csv(self.c.get("/income/export.csv?end=2026-09-30"))), 2)
        self.assertEqual(len(parse_csv(self.c.get("/income/export.csv?source=nothing"))), 1)  # header only

    def test_accounts_csv(self):
        self.post("/accounts/save", id="1", account_name="Needs", account_percentage="50", balance="-40.5")
        rows = parse_csv(self.c.get("/accounts/export.csv"))
        self.assertEqual(rows[0], ["Account", "Share of income (%)", "Balance", "Created at"])
        self.assertEqual(len(rows), 4)
        needs = [r for r in rows if r[0] == "Needs"][0]
        self.assertEqual(needs[1:3], ["50.00", "-40.50"])  # negative number is not mangled

    def test_formula_injection_and_unicode(self):
        self.income("5", source="=HYPERLINK(\"http://x\")"); self.income("5", source="مرتب, \"q\" é\nline2")
        rows = parse_csv(self.c.get("/income/export.csv?source=" ))
        sources = [r[1] for r in rows]
        self.assertIn("'=HYPERLINK(\"http://x\")", sources)
        self.assertIn("مرتب, \"q\" é\nline2", sources)

    def test_export_links_carry_the_applied_filters(self):
        h = self.c.get("/expenses/?account_id=1&category=food").get_data(as_text=True)
        self.assertRegex(unescape(h), r'href="/expenses/export\.csv\?[^"]*account_id=1[^"]*"')
        self.assertIn("category=food", unescape(h))
        self.assertIn("/income/export.csv", self.c.get("/income/").get_data(as_text=True))
        self.assertIn("/accounts/export.csv", self.c.get("/accounts/").get_data(as_text=True))


class TestDatabaseExportImport(Base):
    def upload(self, content, name="x.db", **extra):
        data = {"_csrf": self.token(), "dbfile": (io.BytesIO(content), name)}
        data.update(extra)
        return self.c.post("/data/import", data=data, content_type="multipart/form-data", follow_redirects=True)

    def export(self):
        r = self.c.get("/data/export.db")
        self.assertEqual(r.status_code, 200)
        self.assertRegex(r.headers["Content-Disposition"], r"money_\d{4}-\d{2}-\d{2}\.db")
        return r.get_data()

    def test_data_page(self):
        r = self.c.get("/data/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("/data/export.db", r.get_data(as_text=True))

    def test_export_is_a_real_database_with_same_numbers(self):
        self.income("1000"); self.expense("100")
        self.post("/accounts/save", id="2", account_name="Wants", account_percentage="30", balance="4321.5")
        blob = self.export()
        self.assertTrue(blob.startswith(b"SQLite format 3\x00"))
        path = os.path.join(self.tmp, "out.db")
        with open(path, "wb") as f:
            f.write(blob)
        con = sqlite3.connect(path)
        self.assertEqual(dict(con.execute("SELECT account_name, balance FROM accounts")),
                         {"Needs": 400, "Wants": 4321.5, "Savings": 200})
        self.assertEqual(con.execute("SELECT COUNT(*) FROM income").fetchone()[0], 1)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 2)
        con.close()

    def test_roundtrip_restores_state_and_keeps_a_backup(self):
        self.income("1000"); self.expense("100")
        snapshot = self.export()
        self.income("500", date="2026-10-09"); self.post("/accounts/save", id="1", account_name="Needs", account_percentage="50", balance="1")
        r = self.upload(snapshot)
        self.assertIn("Database imported", r.get_data(as_text=True))
        self.assertEqual(self.balances(), {"Needs": 400, "Wants": 300, "Savings": 200})
        self.assertEqual(self.q("SELECT COUNT(*) FROM income")[0][0], 1)
        saved = glob.glob(self.db + ".before-import-*.backup")
        self.assertEqual(len(saved), 1)
        old = sqlite3.connect(saved[0])
        self.assertEqual(old.execute("SELECT COUNT(*) FROM income").fetchone()[0], 2)  # what you had is kept
        old.close()
        for u in ["/", "/accounts/", "/income/", "/expenses/", "/data/"]:
            self.assertEqual(self.c.get(u).status_code, 200)
        self.income("100", date="2026-10-10")  # still fully working afterwards
        self.assertEqual(self.balances()["Needs"], 450)

    def test_import_legacy_database_keeps_balances(self):
        legacy = os.path.join(self.tmp, "legacy.db"); make_legacy_db(legacy)
        self.income("1000")
        self.upload(rb(legacy))
        self.assertEqual(self.balances(), {"Needs": 7800, "Wants": 4321.5, "Savings": 1500})
        self.assertEqual(self.q("PRAGMA user_version")[0][0], 2)
        self.assertEqual(self.q("SELECT COUNT(*) FROM income_allocations")[0][0], 9)
        self.income("1000", date="2026-10-11")
        self.assertEqual(self.balances()["Needs"], 8300)

    def test_bad_files_rejected_and_nothing_changes(self):
        self.income("1000")
        before = self.balances()
        bad = {
            "text": b"hello world, not a database",
            "garbage": b"SQLite format 3\x00" + os.urandom(2000),
        }
        other = os.path.join(self.tmp, "other.db")
        con = sqlite3.connect(other); con.execute("CREATE TABLE notes (id INTEGER)"); con.commit(); con.close()
        bad["wrong tables"] = rb(other)
        part = os.path.join(self.tmp, "part.db")
        con = sqlite3.connect(part)
        con.executescript("CREATE TABLE income (id INTEGER, amount REAL); CREATE TABLE accounts (id INTEGER);"
                          "CREATE TABLE expenses (id INTEGER);")
        con.commit(); con.close()
        bad["missing columns"] = rb(part)
        trig = os.path.join(self.tmp, "trig.db"); make_legacy_db(trig)
        con = sqlite3.connect(trig)
        con.execute("CREATE TRIGGER t AFTER INSERT ON income BEGIN SELECT 1; END"); con.commit(); con.close()
        bad["trigger"] = rb(trig)
        for name, blob in bad.items():
            r = self.upload(blob)
            self.assertEqual(r.status_code, 200, name)
            self.assertIn("Nothing was changed", r.get_data(as_text=True), name)
            self.assertEqual(self.balances(), before, name)
        self.assertEqual(glob.glob(self.db + ".before-import-*.backup"), [])

    def test_no_file_and_csrf(self):
        r = self.c.post("/data/import", data={"_csrf": self.token()}, content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("Choose a .db file", r.get_data(as_text=True))
        r = self.c.post("/data/import", data={"dbfile": (io.BytesIO(b"x"), "x.db")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)

    def test_too_large_file(self):
        self.app.config["MAX_CONTENT_LENGTH"] = 1000
        r = self.upload(b"x" * 5000)
        self.assertEqual(r.status_code, 413)
        self.assertIn("too large", r.get_data(as_text=True).lower())


class TestValidation(Base):
    def test_bad_amounts_rejected(self):
        for bad in ["0", "-5", "abc", "nan", "inf", "", "0.001", "1e99"]:
            self.income(bad); self.expense(bad)
        self.assertEqual(self.q("SELECT COUNT(*) FROM income")[0][0], 0)
        self.assertEqual(self.q("SELECT COUNT(*) FROM expenses")[0][0], 0)

    def test_bad_dates_and_fields(self):
        for d in ["", "2026-13-40", "not-a-date", "10/01/2026"]:
            self.income(date=d); self.expense(date=d)
        self.income(source="   "); self.expense(cat="  ")
        self.assertEqual(self.q("SELECT COUNT(*) FROM income")[0][0], 0)
        self.assertEqual(self.q("SELECT COUNT(*) FROM expenses")[0][0], 0)

    def test_expense_bad_account(self):
        for acc in ["999", "", "abc"]:
            r = self.expense(acc=acc)
            self.assertEqual(r.status_code, 200)
        self.assertEqual(self.q("SELECT COUNT(*) FROM expenses")[0][0], 0)

    def test_missing_records(self):
        for url in ["/income/delete/99", "/expenses/delete/99", "/accounts/delete/99"]:
            self.assertIn("no longer exists", self.post(url).get_data(as_text=True))
        r = self.post("/income/save", id="99", record_date="2026-10-01", amount="5", source="x")
        self.assertIn("no longer exists", r.get_data(as_text=True))
        self.assertEqual(self.q("SELECT COUNT(*) FROM income")[0][0], 0)
        r = self.post("/income/save", id="abc", record_date="2026-10-01", amount="5", source="x")
        self.assertEqual(self.q("SELECT COUNT(*) FROM income")[0][0], 0)

    def test_account_rules(self):
        self.assertIn("exceed 100", self.post("/accounts/save", account_name="Fun", account_percentage="5").get_data(as_text=True))
        self.assertIn("already exists", self.post("/accounts/save", account_name="needs", account_percentage="0").get_data(as_text=True))
        for bad in ["-1", "101", "x", "nan", ""]:
            self.post("/accounts/save", account_name="Z", account_percentage=bad)
        self.assertEqual(self.q("SELECT COUNT(*) FROM accounts")[0][0], 3)
        self.post("/accounts/save", id="3", account_name="Savings", account_percentage="10")
        self.post("/accounts/save", account_name="Fun", account_percentage="10")
        self.assertEqual(self.q("SELECT COUNT(*) FROM accounts")[0][0], 4)
        self.post("/accounts/save", id="1", account_name="Needs", account_percentage="60")  # 60+30+10+10 > 100
        self.assertEqual(self.q("SELECT account_percentage FROM accounts WHERE id=1")[0][0], 50)

    def test_delete_account_with_expenses_blocked(self):
        self.income(); self.expense(acc="1")
        self.assertIn("has expenses", self.post("/accounts/delete/1").get_data(as_text=True))
        self.assertEqual(self.q("SELECT COUNT(*) FROM accounts")[0][0], 3)
        self.assertIn("still holds money", self.post("/accounts/delete/3").get_data(as_text=True))
        self.post("/accounts/save", account_name="Temp", account_percentage="0")
        self.post("/accounts/delete/4")  # empty account can go
        self.assertEqual(self.q("SELECT COUNT(*) FROM accounts")[0][0], 3)
        self.post("/accounts/save", id="3", account_name="Savings", account_percentage="20", balance="0")
        self.post("/accounts/delete/3")  # balance set to 0 by hand, now it can go
        self.assertEqual(self.q("SELECT COUNT(*) FROM accounts")[0][0], 2)


class TestFilters(Base):
    def setUp(self):
        super().setUp()
        self.income("1000", "2026-09-10", "Salary"); self.income("200", "2026-10-05", "Freelance")
        self.expense("100", "2026-09-12", "1", "Housing", "Rent")
        self.expense("40", "2026-10-06", "2", "Food", "Cafe")
        self.expense("60", "2026-10-07", "1", "Food", "Groceries")

    def get(self, url):
        r = self.c.get(url); self.assertEqual(r.status_code, 200, url)
        h = r.get_data(as_text=True)
        m = re.search(r"<tbody>(.*?)</tbody>", h, re.S)
        return m.group(1) if m else h  # list pages: table rows only

    def test_income_filters(self):
        self.assertIn("Freelance", self.get("/income/?source=free"))
        self.assertNotIn("Freelance", self.get("/income/?end=2026-09-30"))
        self.assertNotIn("Salary", self.get("/income/?start=2026-10-01"))

    def test_expense_filters(self):
        h = self.get("/expenses/?account_id=1&category=food")
        self.assertIn("Groceries", h); self.assertNotIn("Cafe", h); self.assertNotIn("Rent", h)
        self.assertNotIn("Rent", self.get("/expenses/?start=2026-10-01&end=2026-10-31"))

    def test_reversed_and_invalid_dates(self):
        self.assertIn("Freelance", self.get("/income/?start=2026-10-31&end=2026-10-01"))
        for u in ["/?start=zzz", "/income/?end=2026-99-99", "/expenses/?account_id=abc", "/?account_id=abc"]:
            self.get(u)

    def test_overview_numbers(self):
        h = self.get("/")
        self.assertIn("1,200.00", h); self.assertIn("200.00", h)
        h = self.get("/?account_id=1")  # Needs: 50% of income, expenses 160
        self.assertIn("600.00", h); self.assertIn("160.00", h)
        data = json.loads(re.search(r"window.DATA = (.*?);</script>", h, re.S).group(1))
        self.assertEqual(data["months"], ["2026-09", "2026-10"])
        self.assertEqual(data["expenses"], [100, 60])

    def test_filters_survive_save(self):
        r = self.c.post("/income/save", data={"_csrf": self.token(), "record_date": "2026-10-09",
                        "amount": "5", "source": "Gift", "next": "/income/?source=Gift"})
        self.assertEqual(r.headers["Location"], "/income/?source=Gift")
        r = self.c.post("/income/save", data={"_csrf": self.token(), "record_date": "2026-10-09",
                        "amount": "5", "source": "Gift", "next": "//evil.com"})
        self.assertEqual(r.headers["Location"], "/income/")
        r = self.c.post("/income/save", data={"_csrf": self.token(), "record_date": "2026-10-09",
                        "amount": "5", "source": "Gift", "next": "https://evil.com"})
        self.assertEqual(r.headers["Location"], "/income/")


class TestEscaping(Base):
    def test_xss_and_edit_json_roundtrip(self):
        nasty = """<script>alert(1)</script> "q" 'a' & é"""
        self.income(source=nasty)
        h = self.c.get("/income/").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)", h)
        m = re.search(r"data-edit='(.*?)'", h)
        row = json.loads(unescape(m.group(1)))
        self.assertEqual(row["source"], nasty)
        self.expense(cat=nasty, sub=nasty)
        for u in ["/expenses/", "/"]:
            self.assertNotIn("<script>alert(1)", self.c.get(u).get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
