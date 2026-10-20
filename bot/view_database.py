import sqlite3
from pathlib import Path

database_path = Path(__file__).resolve().parent / "wishlist.db"

with sqlite3.connect(database_path) as connection:
    rows = connection.execute("SELECT * FROM wishlist").fetchall()
    print(rows)