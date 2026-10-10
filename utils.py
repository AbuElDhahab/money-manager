"""Shared helpers: validation, filters and safe redirects."""
import csv
import io
import math
from datetime import date
from decimal import Decimal
from flask import Response, flash, redirect, request, url_for


def parse_date(value):
    try:
        return date.fromisoformat((value or "").strip()).isoformat()
    except ValueError:
        return None


def parse_positive(value):
    """Positive, finite, 2-decimal amount, or None."""
    try:
        n = round(float(value), 2)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and 0 < n < 1e12 else None


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def date_range(args):
    """Valid start/end dates; ignores bad input and swaps a reversed range."""
    start, end = parse_date(args.get("start")), parse_date(args.get("end"))
    if start and end and start > end:
        start, end = end, start
    return start, end


def date_conditions(args, col="record_date"):
    conds, params = [], []
    start, end = date_range(args)
    if start:
        conds.append(f"{col} >= ?"); params.append(start)
    if end:
        conds.append(f"{col} <= ?"); params.append(end)
    return conds, params


def where(conds):
    return (" WHERE " + " AND ".join(conds)) if conds else ""


def back(default):
    """Return to the page (and filters) the form was sent from; same-site paths only."""
    nxt = request.form.get("next", "")
    if nxt.startswith("/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(url_for(default))


def fail(message, default):
    flash(message, "error")
    return back(default)


def num(value):
    """Money/percent as a 2-decimal number for CSV (a Decimal, so it is never treated as text)."""
    return Decimal(f"{value or 0:.2f}")


def _safe(cell):
    """Stop spreadsheets from running text that starts like a formula (=, +, -, @)."""
    return "'" + cell if isinstance(cell, str) and cell[:1] in ("=", "+", "-", "@", "\t", "\r") else cell


def csv_response(name, header, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows([[_safe(c) for c in row] for row in rows])
    return Response("\ufeff" + buf.getvalue(),  # BOM so Excel reads accents/Arabic correctly
                    mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}_{date.today().isoformat()}.csv"'})
