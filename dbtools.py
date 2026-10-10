"""Whole-database-file helpers shared by the Data page and Google Drive sync."""
import os
import sqlite3
import tempfile
from pathlib import Path

REQUIRED = {
    "income": {"record_date", "amount", "source", "created_at"},
    "accounts": {"account_name", "account_percentage", "balance", "created_at"},
    "expenses": {"record_date", "amount", "account_id", "main_category", "sub_category", "created_at"},
}


def check_database(path):
    """Return a problem description, or None when the file is a usable Ledger database."""
    with open(path, "rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            return "That file is not a SQLite database."
    try:
        con = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return "The database file is damaged."
            if con.execute("SELECT 1 FROM sqlite_master WHERE type = 'trigger'").fetchone():
                return "Databases with triggers can't be imported."
            for table, cols in REQUIRED.items():
                have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
                if not have:
                    return f"The file has no {table} table, so it isn't a Ledger database."
                if cols - have:
                    return f"The {table} table is missing: {', '.join(sorted(cols - have))}."
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return "That file could not be read as a database."
    return None


def _copy(src_path, dest_path):
    src, dest = sqlite3.connect(src_path), sqlite3.connect(dest_path)
    try:
        src.backup(dest)  # consistent copy, safe while the app is running
    finally:
        src.close()
        dest.close()


def snapshot_bytes(db_path):
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        _copy(db_path, tmp)
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        os.remove(tmp)


def replace_database(db_path, new_file, backup_path=None):
    """Make `db_path` contain exactly what `new_file` contains; optionally keep the old data first."""
    if backup_path:
        _copy(db_path, backup_path)
    _copy(new_file, db_path)
