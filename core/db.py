import sqlite3
import datetime

DB_FILE = "history.db"


def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT,
            type TEXT,
            target TEXT,
            status TEXT
        )
        """)


def add_history(type_, target, status):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "INSERT INTO history(time,type,target,status) VALUES(?,?,?,?)",
            (datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"), type_, target, status)
        )


def get_history():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.execute("SELECT id,time,type,target,status FROM history ORDER BY id DESC")
        return cursor.fetchall()


def delete_history(history_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM history WHERE id = ?", (history_id,))


def delete_all_history():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM history")
