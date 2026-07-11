-- Income Table
-- date, amount, source, created_time
CREATE TABLE IF NOT EXISTS income (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_date TEXT NOT NULL,
    amount NUMERIC(10, 2) NOT NULL CHECK (amount > 0),
    source TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Accounts Table
-- id, name, percentage, created_time
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_name TEXT NOT NULL,
    account_percentage NUMERIC(10, 2) NOT NULL DEFAULT 0,
    balance NUMERIC(10, 2) NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Expenses Table
-- id, date, amount, created_time, account_id, main_category, sub_category
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_date TEXT NOT NULL,
    amount NUMERIC(10, 2) NOT NULL CHECK (amount > 0),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    account_id INTEGER,
    main_category TEXT NOT NULL,
    sub_category TEXT,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

