from flask import Flask, render_template, request, url_for, redirect
from database.db import init_database
from utils import load, income, accounts, expenses

app = Flask(__name__)

# ----- Overview Page -----
@app.route("/")
def overview():
    return render_template("overview.html")

# ----- Income Page -----
# Load data to the page
@app.route("/income")
def income_page():
    return render_template("income.html", rows=load.data("income"))

# Add income record to the data
app.route("/income/add", methods=["POST"], endpoint="add_income")(income.add)

# Edit income record to the data
app.route("/income/edit", methods=["POST"], endpoint="edit_income")(income.edit)

# Remove income record to the data
app.route("/income/remove", methods=["POST"], endpoint="remove_income")(income.remove)

# ----- Accounts Page ------
# Load account page
@app.route("/accouts")
def accounts_page():
    return render_template("accounts.html", rows=load.data("accounts"), total=accounts.calculate_total())

# Create new account
app.route("/accounts/create", methods=["POST"], endpoint="create_account")(accounts.create)

# Edit account
app.route("/accounts/edit", methods=["POST"], endpoint="edit_account")(accounts.edit)

# Transfer from account to another
app.route("/accounts/transfer", methods=["POST"], endpoint="transfer_accounts")(accounts.transfer)

# Delete account
app.route("/accounts/delete", methods=["POST"], endpoint="delete_account")(accounts.delete)

# ----- Expenses Page ------
# Load expenses page
@app.route("/expenses")
def expenses_page():
    return render_template("expenses.html", rows=load.data("expenses"), accounts=load.data("accounts"))

# Add expenses record
app.route("/expenses/add", methods=["POST"], endpoint="add_expenses")(expenses.add)

# Edit record
app.route("/expenses/edit", methods=["POST"], endpoint="edit_expenses")(expenses.edit)

# Remove record
app.route("/expenses/remove", methods=["POST"], endpoint="remove_expenses")(expenses.remove)

if __name__ == "__main__":
    init_database()
    app.run(debug=True)