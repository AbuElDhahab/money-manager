CREATE TABLE IF NOT EXISTS income (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_date TEXT NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0),
    source TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_name TEXT NOT NULL,
    account_percentage REAL NOT NULL DEFAULT 0,
    balance REAL NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_date TEXT NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    account_id INTEGER,
    main_category TEXT NOT NULL,
    sub_category TEXT,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

-- Extra table (not part of the original schema): remembers how each income
-- was split when it was recorded, so changing an account's percentage later
-- never alters existing balances.
CREATE TABLE IF NOT EXISTS income_allocations (
    income_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    PRIMARY KEY (income_id, account_id),
    FOREIGN KEY (income_id) REFERENCES income(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
