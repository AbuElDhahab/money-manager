from flask import request, redirect, url_for
from database.db import get_db_connection
from datetime import datetime
from utils.Class import account

# Add record
def add():
    comm = get_db_connection()
    cursor = comm.cursor()

    # Get the values
    date = request.form.get("date")
    amount = request.form.get("amount", type=float)
    account_id = request.form.get("account_id", type=int)
    main_category = request.form.get("main_category")
    sub_category = request.form.get("sub_category")
    created_at = datetime.now()

    # Update accounts
    row = cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if row:
        acc = account(account_id, row["account_name"], row["account_percentage"], row["balance"])
        balance = acc.subtract(amount)
        cursor.execute("UPDATE accounts SET balance = ? WHERE id = ?", (balance, account_id))
        comm.commit()
    else:
        raise Exception("Account doesn't exist")

    # Insert into database
    cursor.execute("""INSERT INTO expenses
                   (record_date, amount, account_id, main_category, sub_category, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                   (date, amount, account_id, main_category, sub_category, created_at))
    comm.commit()
    comm.close()

    # Redirect
    return redirect(url_for("expenses_page"))

# Edit record
def edit():
    comm = get_db_connection()
    cursor = comm.cursor()

    # Get values
    id = request.form.get("id", type=int)
    new_amount = request.form.get("amount", type=float)
    new_id = request.form.get("account_id", type=int)
    main_category = request.form.get("main_category")
    sub_category = request.form.get("sub_category")
    date = request.form.get("date")
    old_amount = cursor.execute("SELECT amount FROM expenses WHERE id = ?", (id,)).fetchone()[0]
    old_id = cursor.execute("SELECT account_id FROM expenses WHERE id = ?", (id,)).fetchone()[0]

    # Update accounts
    if new_id == old_id:
        row = cursor.execute("SELECT * FROM accounts WHERE id = ?", (new_id,)).fetchone()

        acc = account(row['id'], row['account_name'], row['account_percentage'], row['balance'])
        acc.subtract(new_amount - old_amount)
        cursor.execute("UPDATE accounts SET balance = ? WHERE id = ?", (acc.balance, acc.id))
        comm.commit()

    else:
        rows = cursor.execute("""SELECT * FROM accounts
                           WHERE id IN (?, ?)
                          ORDER BY CASE 
                            WHEN id = ? THEN 1 
                            ELSE 2 
                          END""",
                          (old_id, new_id, old_id)).fetchall()
        
        accounts = []
        for row in rows:
            accounts.append(account(row["id"], row["account_name"], row["account_percentage"], row["balance"]))
        old_account = accounts[0]
        new_account = accounts[1]

        cursor.execute("""UPDATE accounts
                        SET balance = CASE
                            WHEN id = ? THEN ?
                            WHEN id = ? THEN ?
                        END
                       WHERE id IN (?, ?)""",
                        (old_account.id, old_account.subtract(-float(old_amount)),
                          new_account.id, new_account.subtract(new_amount),
                          old_account.id, new_account.id))
        comm.commit()

    # Update database
    cursor.execute("""UPDATE expenses
                   SET amount = ?,
                   account_id = ?,
                   main_category = ?,
                   sub_category = ?,
                   record_date = ?
                   WHERE id = ?""",
                   (new_amount, new_id, main_category, sub_category, date, id))
    comm.commit()
    comm.close()

    # Redirect
    return redirect(url_for("expenses_page"))

# Remove record
def remove():
    comm = get_db_connection()
    cursor = comm.cursor()

    # Get values
    id = request.form.get("id")
    amount = request.form.get("amount")
    account_id = request.form.get("account_id")

    # Update accounts
    row = cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    acc = account(row["id"], row["account_name"], row["account_percentage"], row["balance"])
    balance = acc.subtract(0-float(amount))
    cursor.execute("""UPDATE accounts
                   SET balance = ?
                   WHERE id = ?""",
                   (balance, acc.id))
    comm.commit()

    # Update database
    cursor.execute("DELETE FROM expenses WHERE id = ?", (id,))
    comm.commit()
    comm.close()

    # Redirect
    return redirect(url_for("expenses_page"))