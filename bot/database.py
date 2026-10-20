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
                discord_user_id TEXT NOT NULL,
                game TEXT NOT NULL,
                store TEXT NOT NULL
                    CHECK (store IN ('steam', 'epic', 'gog')),
                link TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (discord_user_id, store, link)
            )
        """)

        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    create_tables()
    print(f"Database ready: {DATABASE_PATH}")
