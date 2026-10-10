from flask import Blueprint, render_template, request, flash
from database import commit_change, get_db, adjust_balance
from utils import (date_conditions, where, parse_positive, parse_date, to_int, back, fail, csv_response, num)

bp = Blueprint("expenses", __name__, url_prefix="/expenses")


def filtered(args):
    """Rows matching the page filters; the page and the CSV export both use this."""
    conds, params = date_conditions(args, "e.record_date")
    if to_int(args.get("account_id")):
        conds.append("e.account_id = ?"); params.append(to_int(args["account_id"]))
    if args.get("category", "").strip():
        conds.append("e.main_category LIKE ?"); params.append(f"%{args['category'].strip()}%")
    return [dict(r) for r in get_db().execute(
        f"""SELECT e.*, a.account_name FROM expenses e
            LEFT JOIN accounts a ON a.id = e.account_id{where(conds)}
            ORDER BY e.record_date DESC, e.id DESC""", params)]


@bp.route("/export.csv")
def export():
    rows = filtered(request.args)
    return csv_response("expenses", ["Date", "Account", "Category", "Sub-category", "Amount", "Created at"],
                        [[r["record_date"], r["account_name"] or "", r["main_category"], r["sub_category"] or "",
                          num(r["amount"]), r["created_at"]] for r in rows])


@bp.route("/")
def index():
    db = get_db()
    rows = filtered(request.args)
    accounts = db.execute("SELECT id, account_name FROM accounts ORDER BY account_name").fetchall()
    categories = [r[0] for r in db.execute("SELECT DISTINCT main_category FROM expenses ORDER BY 1")]
    return render_template("expenses.html", rows=rows, accounts=accounts, categories=categories,
                           total=round(sum(r["amount"] for r in rows), 2), f=request.args, page="expenses")


@bp.route("/save", methods=["POST"])
def save():
    form, db = request.form, get_db()
    amount, date = parse_positive(form.get("amount")), parse_date(form.get("record_date"))
    main = form.get("main_category", "").strip()[:60]
    sub = form.get("sub_category", "").strip()[:60] or None
    account_id = to_int(form.get("account_id"))
    if not (amount and date and main):
        return fail("Enter a valid date, a category and an amount greater than 0.", "expenses.index")
    account = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not account:
        return fail("Choose an existing account.", "expenses.index")
    if form.get("id"):
        rid = to_int(form["id"])
        old = db.execute("SELECT account_id, amount FROM expenses WHERE id=?", (rid,)).fetchone()
        if not old:
            return fail("That expense no longer exists.", "expenses.index")
        adjust_balance(db, old["account_id"], old["amount"])  # give the old amount back
        db.execute("""UPDATE expenses SET record_date=?, amount=?, account_id=?,
                      main_category=?, sub_category=? WHERE id=?""",
                   (date, amount, account_id, main, sub, rid))
        flash("Expense updated.", "ok")
    else:
        db.execute("""INSERT INTO expenses (record_date, amount, account_id, main_category, sub_category)
                      VALUES (?,?,?,?,?)""", (date, amount, account_id, main, sub))
        flash("Expense added.", "ok")
    adjust_balance(db, account_id, -amount)
    commit_change(db)
    balance = db.execute("SELECT balance FROM accounts WHERE id=?", (account_id,)).fetchone()[0]
    if balance < 0:
        flash(f"{account['account_name']} is overspent by {-balance:,.2f}.", "warn")
    return back("expenses.index")


@bp.route("/delete/<int:rid>", methods=["POST"])
def delete(rid):
    db = get_db()
    old = db.execute("SELECT account_id, amount FROM expenses WHERE id=?", (rid,)).fetchone()
    if not old:
        return fail("That expense no longer exists.", "expenses.index")
    adjust_balance(db, old["account_id"], old["amount"])
    db.execute("DELETE FROM expenses WHERE id=?", (rid,))
    commit_change(db)
    flash("Expense deleted.", "ok")
    return back("expenses.index")
