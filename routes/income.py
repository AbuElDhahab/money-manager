from flask import Blueprint, render_template, request, flash
from database import commit_change, get_db, allocate_income, rescale_income, release_income
from utils import (date_conditions, where, parse_positive, parse_date, to_int, back, fail, csv_response, num)

bp = Blueprint("income", __name__, url_prefix="/income")


def filtered(args):
    """Rows matching the page filters; the page and the CSV export both use this."""
    conds, params = date_conditions(args)
    source = args.get("source", "").strip()
    if source:
        conds.append("source LIKE ?")
        params.append(f"%{source}%")
    return [dict(r) for r in get_db().execute(
        f"SELECT * FROM income{where(conds)} ORDER BY record_date DESC, id DESC", params)]


@bp.route("/export.csv")
def export():
    rows = filtered(request.args)
    return csv_response("income", ["Date", "Source", "Amount", "Created at"],
                        [[r["record_date"], r["source"], num(r["amount"]), r["created_at"]] for r in rows])


@bp.route("/")
def index():
    rows = filtered(request.args)
    return render_template("income.html", rows=rows, total=round(sum(r["amount"] for r in rows), 2),
                           f=request.args, page="income")


@bp.route("/save", methods=["POST"])
def save():
    form, db = request.form, get_db()
    amount, date = parse_positive(form.get("amount")), parse_date(form.get("record_date"))
    source = form.get("source", "").strip()[:80]
    if not (amount and date and source):
        return fail("Enter a valid date, a source and an amount greater than 0.", "income.index")
    if form.get("id"):
        rid = to_int(form["id"])
        old = db.execute("SELECT amount FROM income WHERE id=?", (rid,)).fetchone()
        if not old:
            return fail("That income record no longer exists.", "income.index")
        db.execute("UPDATE income SET record_date=?, amount=?, source=? WHERE id=?",
                   (date, amount, source, rid))
        rescale_income(db, rid, old["amount"], amount)
        flash("Income updated.", "ok")
    else:
        cur = db.execute("INSERT INTO income (record_date, amount, source) VALUES (?,?,?)",
                         (date, amount, source))
        allocate_income(db, cur.lastrowid, amount)
        flash("Income added and split across your accounts.", "ok")
    commit_change(db)
    return back("income.index")


@bp.route("/delete/<int:rid>", methods=["POST"])
def delete(rid):
    db = get_db()
    if not db.execute("SELECT 1 FROM income WHERE id=?", (rid,)).fetchone():
        return fail("That income record no longer exists.", "income.index")
    release_income(db, rid)
    db.execute("DELETE FROM income WHERE id=?", (rid,))
    commit_change(db)
    flash("Income deleted.", "ok")
    return back("income.index")
