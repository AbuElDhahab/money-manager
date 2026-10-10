"""SQLite connection handling and balance logic.

The `balance` column is the source of truth: it is stored, can be edited by hand,
and is only ever *adjusted* (never recomputed) when records are added, edited or deleted.
"""
import os
import sqlite3
from flask import g, current_app

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
DB_VERSION = 2  # 2 = stored-balance model


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DB_PATH"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def prepare_database(path, backup=True):
    """Create/upgrade the database file at `path` without ever changing stored balances."""
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        existing = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()
        if backup and existing and version < DB_VERSION and not os.path.exists(path + ".backup"):
            dest = sqlite3.connect(path + ".backup")  # safety copy before the first upgrade
            db.backup(dest)
            dest.close()
        with open(SCHEMA) as f:
            db.executescript(f.read())
        if not db.execute("SELECT 1 FROM accounts").fetchone():
            db.executemany("INSERT INTO accounts (account_name, account_percentage) VALUES (?, ?)",
                           [("Needs", 50), ("Wants", 30), ("Savings", 20)])
        if version < 1:
            # Older database: remember a split for each old income (needed to edit/delete it later).
            # Balances are NOT touched, so the numbers you already have stay exactly as stored.
            for r in db.execute("SELECT id, amount FROM income WHERE id NOT IN "
                                "(SELECT income_id FROM income_allocations)").fetchall():
                allocate_income(db, r["id"], r["amount"], apply=False)
        if version < DB_VERSION:
            db.execute(f"PRAGMA user_version = {DB_VERSION}")
        db.commit()
    finally:
        db.close()


def init_app(app):
    app.teardown_appcontext(close_db)
    prepare_database(app.config["DB_PATH"])


def commit_change(db):
    """Commit a data change and flag it so Google Drive sync can pick it up."""
    db.commit()
    g.data_changed = True


def adjust_balance(db, account_id, delta):
    if account_id is not None and delta:
        db.execute("UPDATE accounts SET balance = ROUND(balance + ?, 2) WHERE id = ?", (delta, account_id))


def allocate_income(db, income_id, amount, apply=True):
    """Split one income using the percentages in effect right now; add the parts to balances."""
    parts = db.execute("SELECT id, ROUND(? * account_percentage / 100.0, 2) AS part "
                       "FROM accounts WHERE account_percentage > 0", (amount,)).fetchall()
    for p in parts:
        db.execute("INSERT INTO income_allocations (income_id, account_id, amount) VALUES (?,?,?)",
                   (income_id, p["id"], p["part"]))
        if apply:
            adjust_balance(db, p["id"], p["part"])


def rescale_income(db, income_id, old_amount, new_amount):
    """Editing an income amount keeps its original split proportions; balances move by the difference."""
    rows = db.execute("SELECT account_id, amount FROM income_allocations WHERE income_id = ?",
                      (income_id,)).fetchall()
    for r in rows:
        new = round(r["amount"] * new_amount / old_amount, 2)
        db.execute("UPDATE income_allocations SET amount = ? WHERE income_id = ? AND account_id = ?",
                   (new, income_id, r["account_id"]))
        adjust_balance(db, r["account_id"], new - r["amount"])


def release_income(db, income_id):
    """Take an income's stored split back out of the balances (call before deleting it)."""
    for r in db.execute("SELECT account_id, amount FROM income_allocations WHERE income_id = ?",
                        (income_id,)).fetchall():
        adjust_balance(db, r["account_id"], -r["amount"])
