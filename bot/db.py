import sqlite3
from contextlib import closing

from database import DATABASE_PATH, create_tables


def init_db():
    create_tables()


def add_game(guild_id, user_id, app_id, name):
    link = f"https://store.steampowered.com/app/{app_id}/"
    try:
        with closing(sqlite3.connect(DATABASE_PATH)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO wishlist (discord_user_id, game, store, link) VALUES (?, ?, 'steam', ?)",
                    (str(user_id), name, link),
                )
        return True
    except sqlite3.IntegrityError:
        return False

def get_wishlist():
    " Returns  games shared in the wishlist"
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        return conn.execute(
            """
            SELECT DISTINCT game, store, link
            FROM wishlist
            ORDER BY game COLLATE NOCASE, store, link
            """
        ).fetchall()