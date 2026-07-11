import sqlite3

def get_db_connection():
    conn = sqlite3.connect("money_database.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    conn = get_db_connection()
    cursor = conn.cursor()

    with open("database/schema.sql", "r", encoding="utf-8") as f:
        conn.executescript(f.read())
        conn.commit()
    
    accounts = cursor.execute("SELECT * FROM accounts").fetchall()

    if not accounts:
        cursor.execute("""INSERT INTO accounts (
                            account_name,
                            account_percentage
                        )
                        VALUES 
                            ( 'Needs', 50 ),
                            ( 'Wants', 30 ),
                            ( 'Saving', 20 );""")
        conn.commit()

    conn.close()