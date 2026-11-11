import sqlite3 
from pathlib import Path

#Create a database, implement triggers/functions to 
#store wishlist data and apply acceptance criteria 
DATABASE_PATH = Path(__file__).resolve().parent / "wishlist.db"


def create_tables():
    connection = sqlite3.connect(DATABASE_PATH)

    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS wishlist (
                id INTEGER PRIMARY KEY,
                discord_guild_id TEXT NOT NULL,
                discord_user_id TEXT NOT NULL,
                game TEXT NOT NULL,
                store TEXT NOT NULL
                    CHECK (store IN ('steam', 'epic', 'gog')),
                link TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (discord_guild_id, discord_user_id, store, link)
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_wishlist_server_game
            ON wishlist (discord_guild_id, store, link)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS price_watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_guild_id TEXT NOT NULL,
                discord_user_id TEXT NOT NULL,
                game_key TEXT NOT NULL,
                game TEXT NOT NULL,
                store TEXT NOT NULL CHECK (store IN ('steam', 'epic', 'gog')),
                link TEXT NOT NULL,
                steam_id INTEGER,
                catalog_id TEXT,
                target_cents INTEGER NOT NULL CHECK (target_cents >= 0),
                notified_cents INTEGER,
                last_checked_day TEXT,
                revision INTEGER NOT NULL DEFAULT 1,
                UNIQUE (discord_guild_id, discord_user_id, game_key)
            )
        """)

        connection.commit()
    finally:
        connection.close()



if __name__ == "__main__":
    create_tables()
    print(f"Database ready: {DATABASE_PATH}")
