import sqlite3
from contextlib import closing

from database import DATABASE_PATH, create_tables


def init_db():
    create_tables()


def add_store_game(guild_id, user_id, store, link, name):
    """Returns True if added, False if this user already has this game from this store.
    store is steam, epic or gog. The link is what tells two copies of a game apart."""
    try:
        with closing(sqlite3.connect(DATABASE_PATH)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO wishlist (discord_guild_id, discord_user_id, game, store, link) VALUES (?, ?, ?, ?, ?)",
                    (str(guild_id), str(user_id), name, store, link),
                )
        return True
    except sqlite3.IntegrityError:
        return False


def add_game(guild_id, user_id, app_id, name):
    """Adds a Steam game. Returns True if added, False if this user already has the game."""
    link = f"https://store.steampowered.com/app/{app_id}/"   # one link per game, so duplicates are caught
    return add_store_game(guild_id, user_id, "steam", link, name)


# Individual User
def get_wishlist(guild_id, user_id):
    """Return games wishlisted by one user in one server."""
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        return conn.execute(
            """
            SELECT game, store, link
            FROM wishlist
            WHERE discord_guild_id = ?
              AND discord_user_id = ?
            ORDER BY game COLLATE NOCASE, store, link
            """,
            (str(guild_id), str(user_id)),
        ).fetchall()

# Whole server
def get_server_wishlist(guild_id):
    """Return each unique game and how many users want it."""
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        return conn.execute(
            """
            SELECT
                MIN(game) AS game,
                store,
                link,
                COUNT(DISTINCT discord_user_id) AS wanted_by
            FROM wishlist
            WHERE discord_guild_id = ?
            GROUP BY store, link
            ORDER BY game COLLATE NOCASE, store, link
            """,
            (str(guild_id),),
        ).fetchall()

def remove_game(guild_id, user_id, name):
    """Removes this user's game with this name, ignoring capitalization.
    If the same game is saved under more than one store, every copy is removed.
    Returns the saved name of the game, or None if the user did not have it.
    Only this user's rows are touched, so other users keep the game."""
    name = (name or "").strip()
    if not name:
        return None
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        with conn:
            rows = conn.execute(
                """
                SELECT game
                FROM wishlist
                WHERE discord_guild_id = ?
                  AND discord_user_id = ?
                  AND game = ? COLLATE NOCASE
                """,
                (str(guild_id), str(user_id), name),
            ).fetchall()
            if not rows:
                return None
            conn.execute(
                """
                DELETE FROM wishlist
                WHERE discord_guild_id = ?
                  AND discord_user_id = ?
                  AND game = ? COLLATE NOCASE
                """,
                (str(guild_id), str(user_id), name),
            )
    return rows[0][0]