from flask import Blueprint, render_template, request
from database import get_db
from utils import date_conditions, where, to_int

bp = Blueprint("overview", __name__)
TOP_CATEGORIES = 5  # doughnut shows this many, the rest are grouped as "Other"


@bp.route("/")
def index():
    db, args = get_db(), request.args
    acc_id = str(to_int(args.get("account_id")) or "")
    accounts = [dict(r) for r in db.execute("SELECT * FROM accounts ORDER BY account_name")]

    ic, ip = date_conditions(args)
    ec, ep = date_conditions(args)
    if acc_id:
        ec.append("account_id = ?"); ep.append(acc_id)
    if args.get("category"):
        ec.append("main_category = ?"); ep.append(args["category"])

    if acc_id:  # an account's income is what was actually allocated to it
        sql = ("SELECT substr(i.record_date,1,7), SUM(a.amount) FROM income i JOIN income_allocations a "
               f"ON a.income_id = i.id AND a.account_id = ?{where(ic)} GROUP BY 1")
        params = [acc_id] + ip
    else:
        sql = f"SELECT substr(record_date,1,7), SUM(amount) FROM income{where(ic)} GROUP BY 1"
        params = ip
    income_m = {r[0]: r[1] for r in db.execute(sql, params)}
    exp_m = {r[0]: r[1] for r in db.execute(
        f"SELECT substr(record_date,1,7), SUM(amount) FROM expenses{where(ec)} GROUP BY 1", ep)}
    months = sorted(set(income_m) | set(exp_m))
    cats = db.execute(
        f"SELECT main_category, SUM(amount) FROM expenses{where(ec)} GROUP BY 1 ORDER BY 2 DESC", ep).fetchall()
    recent = [dict(r) for r in db.execute(
        f"""SELECT e.*, a.account_name FROM expenses e LEFT JOIN accounts a ON a.id=e.account_id
            {where(ec)}
            ORDER BY e.record_date DESC, e.id DESC LIMIT 6""", ep)]

    chart_cats = [(c[0], round(c[1], 2)) for c in cats[:TOP_CATEGORIES]]
    rest = cats[TOP_CATEGORIES:]
    if len(rest) == 1:  # a single leftover is shown by name rather than hidden in "Other"
        chart_cats.append((rest[0][0], round(rest[0][1], 2)))
    elif rest:
        chart_cats.append((f"Other ({len(rest)} categories)", round(sum(c[1] for c in rest), 2)))

    total_in, total_out = round(sum(income_m.values()), 2), round(sum(exp_m.values()), 2)
    data = {
        "months": months,
        "income": [round(income_m.get(m, 0), 2) for m in months],
        "expenses": [round(exp_m.get(m, 0), 2) for m in months],
        "cats": [c[0] for c in chart_cats], "catTotals": [c[1] for c in chart_cats],
    }
    all_cats = [r[0] for r in db.execute("SELECT DISTINCT main_category FROM expenses ORDER BY 1")]
    return render_template(
        "overview.html", page="overview", f=args, accounts=accounts, categories=all_cats,
        total_in=total_in, total_out=total_out, net=round(total_in - total_out, 2),
        rate=(total_in - total_out) / total_in * 100 if total_in else 0,
        data=data, recent=recent)
