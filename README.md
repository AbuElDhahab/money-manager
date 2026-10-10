# Ledger – personal money manager

Flask + SQLite + vanilla HTML/CSS/JS.

## Run
```
pip install -r requirements.txt
python app.py        # http://127.0.0.1:5000
```
The database (`money.db`) is created on first run with Needs 50% / Wants 30% / Savings 20%.

## Structure
- `app.py` – app factory, registers blueprints
- `config.py`, `database.py`, `schema.sql`, `utils.py`
- `routes/` – one blueprint per page (overview, accounts, income, expenses)
- `templates/` – one template per page, plus `base.html` and the shared `_modal.html`
- `static/css/style.css`, `static/js/main.js` (theme, dialogs), `static/js/overview.js` (charts)

## How balances work
The `balance` column is stored and is the source of truth. It is only adjusted by what you do:
- Add income: split by the percentages at that moment (the split is stored in `income_allocations`) and added to balances.
- Edit/delete income: balances move by the difference, using that income's original split.
- Add/edit/delete an expense: the account balance moves by the difference.
- Edit an account: change its name, percentage and/or balance. A percentage change only affects future income; the balance field sets the balance directly.

Using an existing database: copy `money.db` into the project folder. Balances are never recalculated on start-up.
The first time an older database is opened, a copy is saved next to it as `money.db.backup`.

## Import / export
- **Data page:** download the whole database as a `.db` file, or import one (replaces current data; balances in the file stay as stored; your previous data is saved as `money.db.before-import-<time>.backup`).
- **CSV:** `Export CSV` on Income, Expenses and Accounts downloads the rows matching the filters applied to that page.

## Calculator
The Add/Edit dialogs for income and expenses have a **Calculator** button next to Amount: type or tap a calculation (`+ − × ÷ ( )`), then **Use result** fills the amount.

## Google Drive backup and sync
Set-up (once, about 5 minutes):
1. Go to https://console.cloud.google.com, create a project, and enable the **Google Drive API**.
2. *OAuth consent screen*: choose External, fill the app name/email, add your Google account as a test user. Then set the publishing status to **In production** (the app only uses the non-sensitive `drive.file` scope, so no review is needed; in "Testing" mode Google expires the sign-in every 7 days).
3. *Credentials → Create credentials → OAuth client ID → Web application*. Add this authorised redirect URI: `http://127.0.0.1:5000/drive/callback`.
4. Download the JSON and save it as `credentials.json` in the project folder (or set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`).
5. Open the app at `http://127.0.0.1:5000`, go to **Data → Connect Google Drive**.

How it works: one file, `ledger-backup.db`, is kept on Drive (the app can only see files it created). Every change is uploaded after you save it. On other devices, changes are picked up when you open a page (checked at most every 30 s), or with **Sync now**.
Each device remembers which Drive version it is based on. If this device and Drive both changed, **nothing is overwritten**: you choose "Use Google Drive's version" (your local data is saved as `money.db.before-drive-<time>.backup`) or "Keep this device's version".
Connecting a second device (or phone instance) to an existing backup asks whether to import it or replace it.
Sign-in tokens are stored in `money.db.drive.json` (not inside the database, so it is never exported or uploaded).

Phone access: run `HOST=0.0.0.0 python app.py` on the computer and open `http://<computer-ip>:5000` on the phone (same Wi-Fi). Connect Drive on the computer only; the phone shares that connection. Anyone on your network could open the app, so only do this on a network you trust.
