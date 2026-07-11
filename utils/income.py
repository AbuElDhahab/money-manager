from flask import request, redirect, url_for
from database.db import get_db_connection
from datetime import datetime
from utils.Class import account

def add():
    # Save values
    date = request.form.get("date")
    source = request.form.get("source")
    amount = request.form.get("amount", type=float)
    created_at = datetime.now()
    
    # Update database
    comm = get_db_connection()
    cursor = comm.cursor()
    cursor.execute("INSERT INTO income (record_date, source, amount, created_at) VALUES (?, ?, ?, ?)",
    (date, source, amount, created_at))
    comm.commit()
    
    # Separate to the accouts
    rows = cursor.execute("SELECT * FROM accounts").fetchall()
    for row in rows:
        acc = account(row["id"], row["account_name"], row["account_percentage"], row["balance"])
        acc.add(amount)
        cursor.execute("""UPDATE accounts
                    SET balance = ?
                    WHERE id = ?""",
                    (acc.balance, acc.id))
        comm.commit()

    comm.close()

    # Redirect
    return redirect(url_for("income_page"))
    
def edit():
    comm = get_db_connection()
    cursor = comm.cursor()

    # Get new values
    id = request.form.get("id", type=int)
    date = request.form.get("date")
    source = request.form.get("source")
    new_amount = request.form.get("amount", type=float)
    old_amount = cursor.execute("SELECT amount FROM income WHERE id = ?", (id,)).fetchone()[0]

    # Update accouts table
    rows = cursor.execute("SELECT * FROM accounts").fetchall()
    for row in rows:
        acc = account(row["id"], row["account_name"], row["account_percentage"], row["balance"])
        acc.add(new_amount - old_amount)
        cursor.execute("UPDATE accounts SET balance = ? WHERE id = ?",
                    (acc.balance, acc.id))
        comm.commit()

    # Update income table
    cursor.execute("""UPDATE income
                SET record_date = ?,
                source = ?,
                amount = ?
                WHERE id = ?""",
                (date, source, new_amount, id,))
    comm.commit()
    comm.close()

    # Redirect
    return redirect(url_for("income_page"))
    
def remove():

    comm = get_db_connection()
    cursor = comm.cursor()

    # Get the values
    id = request.form.get("id")
    amount = request.form.get("amount")

    # Update accouts table
    rows = cursor.execute("SELECT * FROM accounts").fetchall()
    for row in rows:
        acc = account(row["id"], row["account_name"], row["account_percentage"], row["balance"])
        acc.add(0-float(amount))
        cursor.execute("UPDATE accounts SET balance = ? WHERE id = ?", (acc.balance, acc.id))
        comm.commit()

    # Update income table
    cursor.execute("DELETE FROM income WHERE id = ?", (id,))
    comm.commit()
    comm.close()

    # Redirect
    return redirect(url_for("income_page"))