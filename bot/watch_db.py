"""Persistent per-user, per-server target-price alerts."""

from contextlib import closing
from decimal import Decimal, InvalidOperation
import sqlite3

import db
from game_search import GameChoice

MAX_WATCHES = 25


class WatchLimitReached(Exception):
    pass


def price_cents(value):
    try:
        if isinstance(value, bool):
            raise ValueError()
        amount = Decimal(str(value))
        if (not amount.is_finite() or amount < 0 or amount > 1000000
                or amount != amount.quantize(Decimal("0.01"))):
            raise ValueError()
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a USD price from 0 to 1000000 with at most two decimal places.") from None


def save(guild_id, user_id, choice, target_cents):
    with closing(sqlite3.connect(db.DATABASE_PATH)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        owner = (str(guild_id), str(user_id))
        existing = conn.execute(
            "SELECT id FROM price_watches WHERE discord_guild_id=? AND discord_user_id=? AND game_key=?",
            (*owner, choice.key),
        ).fetchone()
        if existing is None and conn.execute(
            "SELECT COUNT(*) FROM price_watches WHERE discord_guild_id=? AND discord_user_id=?", owner
        ).fetchone()[0] >= MAX_WATCHES:
            raise WatchLimitReached()
        conn.execute("""
            INSERT INTO price_watches
                (discord_guild_id, discord_user_id, game_key, game, store, link, steam_id, catalog_id, target_cents)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(discord_guild_id, discord_user_id, game_key) DO UPDATE SET
                game=excluded.game, store=excluded.store, link=excluded.link,
                steam_id=excluded.steam_id, catalog_id=excluded.catalog_id,
                notified_cents=CASE WHEN target_cents != excluded.target_cents THEN NULL ELSE notified_cents END,
                last_checked_day=CASE WHEN target_cents != excluded.target_cents THEN NULL ELSE last_checked_day END,
                target_cents=excluded.target_cents, revision=revision+1
        """, (*owner, choice.key, choice.name, choice.store, choice.link,
              choice.steam_id, choice.catalog_id, target_cents))
        return conn.execute(
            "SELECT id FROM price_watches WHERE discord_guild_id=? AND discord_user_id=? AND game_key=?",
            (*owner, choice.key),
        ).fetchone()[0]


def rows(guild_id=None, user_id=None):
    with closing(sqlite3.connect(db.DATABASE_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        if guild_id is None:
            result = conn.execute("SELECT * FROM price_watches ORDER BY id")
        else:
            result = conn.execute("""SELECT * FROM price_watches
                WHERE discord_guild_id=? AND discord_user_id=? ORDER BY game COLLATE NOCASE, id
            """, (str(guild_id), str(user_id)))
        return [dict(row) for row in result]


def current(watch_id, revision):
    with closing(sqlite3.connect(db.DATABASE_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM price_watches WHERE id=? AND revision=?", (watch_id, revision)).fetchone()
        return dict(row) if row else None


def remove(guild_id, user_id, watch_id):
    with closing(sqlite3.connect(db.DATABASE_PATH)) as conn, conn:
        return conn.execute("DELETE FROM price_watches WHERE id=? AND discord_guild_id=? AND discord_user_id=?",
                            (watch_id, str(guild_id), str(user_id))).rowcount == 1


def checked(watch_id, revision, day, notified_cents):
    with closing(sqlite3.connect(db.DATABASE_PATH)) as conn, conn:
        conn.execute("""UPDATE price_watches SET last_checked_day=?, notified_cents=?
            WHERE id=? AND revision=?""", (day, notified_cents, watch_id, revision))


def choice(row):
    return GameChoice(row["game"], row["store"], row["link"], row["steam_id"],
                      row["catalog_id"], row["id"])
