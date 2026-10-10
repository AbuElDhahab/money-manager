import math
from flask import Blueprint, render_template, request, flash
from database import commit_change, get_db
from utils import to_int, back, fail, csv_response, num

bp = Blueprint("accounts", __name__, url_prefix="/accounts")


@bp.route("/")
def index():
    rows = [dict(r) for r in get_db().execute("SELECT * FROM accounts ORDER BY account_percentage DESC, id")]
    return render_template("accounts.html", rows=rows, page="accounts",
                           used=round(sum(r["account_percentage"] for r in rows), 2),
                           total_balance=round(sum(r["balance"] for r in rows), 2))


@bp.route("/export.csv")
def export():
    rows = get_db().execute("SELECT * FROM accounts ORDER BY account_percentage DESC, id").fetchall()
    return csv_response("accounts", ["Account", "Share of income (%)", "Balance", "Created at"],
                        [[r["account_name"], num(r["account_percentage"]), num(r["balance"]), r["created_at"]]
                         for r in rows])


@bp.route("/save", methods=["POST"])
def save():
    form, db = request.form, get_db()
    name = form.get("account_name", "").strip()[:40]
    try:
        pct = round(float(form.get("account_percentage", "")), 2)
    except ValueError:
        pct = -1
    if not name or not 0 <= pct <= 100:
        return fail("Enter a name and a percentage between 0 and 100.", "accounts.index")
    raw = form.get("balance", "").strip()  # blank = leave the balance alone (0 for a new account)
    balance = None
    if raw:
        try:
            balance = round(float(raw), 2)
        except ValueError:
            balance = float("nan")
        if not math.isfinite(balance) or abs(balance) >= 1e12:
            return fail("Enter a valid balance.", "accounts.index")
    aid = to_int(form.get("id")) if form.get("id") else None
    if form.get("id") and not db.execute("SELECT 1 FROM accounts WHERE id=?", (aid,)).fetchone():
        return fail("That account no longer exists.", "accounts.index")
    if db.execute("SELECT 1 FROM accounts WHERE lower(account_name)=lower(?) AND id IS NOT ?",
                  (name, aid)).fetchone():
        return fail(f"An account named {name} already exists.", "accounts.index")
    others = db.execute("SELECT COALESCE(SUM(account_percentage),0) FROM accounts WHERE id IS NOT ?",
                        (aid,)).fetchone()[0]
    if others + pct > 100.0001:
        return fail(f"Percentages can't exceed 100%. {max(0, 100 - others):g}% is left to assign.", "accounts.index")
    if aid:
        db.execute("UPDATE accounts SET account_name=?, account_percentage=?, balance=COALESCE(?, balance) "
                   "WHERE id=?", (name, pct, balance, aid))
        flash("Account updated. The new percentage applies to future income only.", "ok")
    else:
        db.execute("INSERT INTO accounts (account_name, account_percentage, balance) VALUES (?,?,?)",
                   (name, pct, balance or 0))
        flash("Account created.", "ok")
    commit_change(db)
    return back("accounts.index")


@bp.route("/delete/<int:rid>", methods=["POST"])
def delete(rid):
    db = get_db()
    if db.execute("SELECT 1 FROM expenses WHERE account_id=?", (rid,)).fetchone():
        return fail("This account has expenses. Move or delete them first.", "accounts.index")
    acc = db.execute("SELECT balance FROM accounts WHERE id=?", (rid,)).fetchone()
    if acc and abs(acc["balance"]) >= 0.005:
        return fail("This account still holds money. Set its balance to 0 before deleting it.", "accounts.index")
    if db.execute("DELETE FROM accounts WHERE id=?", (rid,)).rowcount == 0:
        return fail("That account no longer exists.", "accounts.index")
    commit_change(db)
    flash("Account deleted.", "ok")
    return back("accounts.index")
