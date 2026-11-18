import sqlite3
import json
import genres
from contextlib import closing

from database import DATABASE_PATH, create_tables


def init_db():
    create_tables()


def get_digest_settings(guild_id):
    """Return settings keyed by user ID for one server."""
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        rows = conn.execute("""
            SELECT discord_user_id, frequency, delivery_time, last_scheduled_day
            FROM digest_settings
            WHERE discord_guild_id = ?
        """, (str(guild_id),)).fetchall()
    return {
        int(user_id): (frequency, delivery_time, last_scheduled_day)
        for user_id, frequency, delivery_time, last_scheduled_day in rows
    }


def update_digest_settings(guild_id, user_id, frequency, delivery_time):
    """Save the supplied preferences, keeping the other preferences and run history."""
    with closing(sqlite3.connect(DATABASE_PATH)) as conn, conn:
        freq, time = conn.execute("""
            INSERT INTO digest_settings
                (discord_guild_id, discord_user_id, frequency, delivery_time)
            VALUES (?, ?, COALESCE(?, 'daily'), ?)
            ON CONFLICT (discord_guild_id, discord_user_id) DO UPDATE SET
                frequency = COALESCE(?, digest_settings.frequency),
                delivery_time = COALESCE(excluded.delivery_time, digest_settings.delivery_time)
            RETURNING frequency, delivery_time
        """, (str(guild_id), str(user_id), frequency, delivery_time, frequency)).fetchone()
    return freq, time


def mark_digest_checked(guild_id, user_ids, day):
    """Record a scheduled check without changing any saved preferences."""
    with closing(sqlite3.connect(DATABASE_PATH)) as conn, conn:
        conn.executemany("""
            INSERT INTO digest_settings
                (discord_guild_id, discord_user_id, last_scheduled_day)
            VALUES (?, ?, ?)
            ON CONFLICT (discord_guild_id, discord_user_id) DO UPDATE SET
                last_scheduled_day = excluded.last_scheduled_day
        """, [(str(guild_id), str(user_id), day) for user_id in user_ids])


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


def save_game_genres(store, link, labels):
    """Save genre metadata for one store listing."""
    labels = genres.clean_genres(labels)

    if not labels:
        return

    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO game_genres (store, link, genres)
                VALUES (?, ?, ?)
                ON CONFLICT(store, link)
                DO UPDATE SET genres = excluded.genres
                """,
                (store, link, json.dumps(labels))
            )


def populate_game_genres(store, name, link):
    """Fetch genres only when no useful genres are saved."""
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        row = conn.execute(
            """
            SELECT genres
            FROM game_genres
            WHERE store=? AND link=?
            """,
            (store, link)
        ).fetchone()

    if row:
        try:
            existing = genres.clean_genres(json.loads(row[0]))
            if existing:
                return existing
        except (TypeError, ValueError):
            pass

    labels = genres.lookup(store, name, link)

    if labels:
        save_game_genres(store, link, labels)

    return labels


def get_wishlist_with_genres(guild_id, user_id):
    """Return a user's games with genre metadata."""
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        return conn.execute(
            """
            SELECT
                w.game,
                w.store,
                w.link,
                COALESCE(g.genres, '[]')
            FROM wishlist AS w
            LEFT JOIN game_genres AS g
              ON g.store = w.store
              AND g.link = w.link
            WHERE w.discord_guild_id = ?
              AND w.discord_user_id = ?
            ORDER BY w.game COLLATE NOCASE, w.store, w.link
            """,
            (str(guild_id), str(user_id))
        ).fetchall()


def get_server_wishlist_with_genres(guild_id):
    """Return server games, user counts, and genres."""
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        return conn.execute(
            """
            SELECT
                MIN(w.game),
                w.store,
                w.link,
                COUNT(DISTINCT w.discord_user_id),
                COALESCE(g.genres, '[]')
            FROM wishlist AS w
            LEFT JOIN game_genres AS g
              ON g.store = w.store
              AND g.link = w.link
            WHERE w.discord_guild_id = ?
            GROUP BY w.store, w.link
            ORDER BY MIN(w.game) COLLATE NOCASE,
                     w.store, w.link
            """,
            (str(guild_id),)
        ).fetchall()

# THERE ARE CURRENTLY GAMES IN WIHSLIST WITH NO GENRE< THIS FIX
def games_missing_genres():
    """Find unique games that still need genre metadata."""
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        return conn.execute(
            """
            SELECT
                w.store,
                w.link,
                MIN(w.game)
            FROM wishlist AS w
            LEFT JOIN game_genres AS g
              ON g.store = w.store
              AND g.link = w.link
            WHERE g.genres IS NULL
               OR g.genres = '[]'
            GROUP BY w.store, w.link
            ORDER BY MIN(w.game) COLLATE NOCASE
            """
        ).fetchall()


