import sqlite3
from contextlib import closing

from database import DATABASE_PATH, create_tables


def init_db():
    create_tables()


def add_game(guild_id, user_id, app_id, name):
    """Returns True if added, False if this user already has the game.
    guild_id is accepted but not stored, because the wishlist table has no server column."""
    link = f"https://store.steampowered.com/app/{app_id}/"   # one link per game, so duplicates are caught
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


def get_wishlist(user_id):
    """Returns (game, store, link) for this user's wishlist only."""
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        return conn.execute(
            """
            SELECT game, store, link
            FROM wishlist
            WHERE discord_user_id = ?
            ORDER BY game COLLATE NOCASE, store, link
            """,
            (str(user_id),),
        ).fetchall()