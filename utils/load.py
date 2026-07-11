from database.db import get_db_connection

def data(table):
    comm = get_db_connection()
    cursor = comm.cursor()
    rows = cursor.execute(f"SELECT * FROM {table} ORDER BY id DESC").fetchall()
    return rows