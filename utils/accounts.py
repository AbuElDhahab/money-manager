from flask import request, redirect, url_for
from database.db import get_db_connection
from datetime import datetime

# Create account
def create():
    comm = get_db_connection()
    cursor = comm.cursor()

    # Get data
    name = request.form.get("name")
    percentage = request.form.get("percentage", type=float)
    balance = request.form.get("balance", type=float)
    created_at = datetime.now()

    # Check total percentages
    if not check_percentage(percentage):
        raise ValueError("Total percentages shouldn't exceeds 100%")

    # Update database
    cursor.execute("""INSERT INTO accounts (account_name, account_percentage, balance, created_at)
                VALUES
                (?, ?, ?, ?)""",
                (name, percentage, balance, created_at))
    comm.commit()
    comm.close()

    # Redirect
    return redirect(url_for("accounts_page"))  

# Edit account
def edit():
    comm = get_db_connection()
    cursor = comm.cursor()

    id = request.form.get("id", type=int)
    name = request.form.get("name")
    percentage = request.form.get("percentage", type=float)
    balance = request.form.get("balance", type=float)

    # Check total percentages
    if not check_percentage(percentage, id):
        raise ValueError("Total percentages shouldn't exceeds 100%")
    
    # Update the database
    cursor.execute("""UPDATE accounts
                   SET account_name = ?,
                   account_percentage = ?,
                   balance = ?
                   WHERE id = ?""",
                   (name, percentage, balance, id))
    comm.commit()
    comm.close()

    # Redirect
    return redirect(url_for("accounts_page"))

# Transfer
def transfer():
    comm = get_db_connection()
    cursor = comm.cursor()

    # Get data
    from_account = request.form.get("from_account")
    from_balance = float(cursor.execute("SELECT balance FROM accounts WHERE id = ?", (from_account,)).fetchone()[0])
    to_account = request.form.get("to_account")
    to_balance = float(cursor.execute("SELECT balance FROM accounts WHERE id = ?", (to_account,)).fetchone()[0])
    amount = float(request.form.get("amount"))

    if from_account == to_account:
        raise Exception("Choose different acconts.")

    # Update database
    cursor.execute("""UPDATE accounts
                   SET balance = ?
                   WHERE id = ?""",
                   (from_balance - amount, from_account))
    comm.commit()

    cursor.execute("""UPDATE accounts
                   SET balance = ?
                   WHERE id = ?""",
                   (to_balance + amount, to_account))
    comm.commit()
    comm.close()

    # Redirect
    return redirect(url_for("accounts_page"))

# Delete account
def delete():
    comm = get_db_connection()
    cursor = comm.cursor()

    # Get id
    id = request.form.get("id")

    # Check if there is any balance
    balance = cursor.execute("SELECT balance FROM accounts WHERE id = ?", (id,)).fetchone()[0]
    if balance > 0:
        raise Exception("Accounts must be empty before deleteing")

    # Delete account
    cursor.execute("DELETE FROM accounts WHERE id = ?", (id,))
    comm.commit()
    comm.close()

    # Redirect
    return redirect(url_for("accounts_page"))

def check_percentage(percentage, account_id=None):
    conn = get_db_connection()
    cursor = conn.cursor()

    total = percentage

    if account_id is None:
        rows = cursor.execute(
            "SELECT account_percentage FROM accounts"
        ).fetchall()
    else:
        rows = cursor.execute(
            "SELECT account_percentage FROM accounts WHERE id != ?",
            (account_id,)
        ).fetchall()

    for row in rows:
        total += row["account_percentage"]

    conn.close()

    return total <= 100

def calculate_total():
    comm = get_db_connection()
    cursor = comm.cursor()

    total = cursor.execute("SELECT sum(balance) FROM accounts").fetchone()[0]

    return total
