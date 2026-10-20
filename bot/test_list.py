
"""Tests for the shared wishlist query, using an isolated temporary SQLite file."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing

import database
import db


class TestGetWishlist(unittest.TestCase):
    def setUp(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "wishlist.db"
        path_patch = patch.object(database, "DATABASE_PATH", path)
        db_path_patch = patch.object(db, "DATABASE_PATH", path)
        path_patch.start()
        db_path_patch.start()
        self.addCleanup(db_path_patch.stop)
        self.addCleanup(path_patch.stop)
        db.init_db()
        self.path = path

    def test_empty_wishlist(self):
        self.assertEqual(db.get_wishlist(), [])

    def test_games_are_sorted_by_name(self):
        db.add_game(1, 10, 620, "Portal 2")
        db.add_game(1, 10, 440, "Team Fortress 2")
        db.add_game(1, 10, 105600, "terraria")
        self.assertEqual(
            [game for game, store, link in db.get_wishlist()],
            ["Portal 2", "Team Fortress 2", "terraria"],
        )

    def test_game_added_by_multiple_users_is_listed_once(self):
        db.add_game(1, 10, 620, "Portal 2")
        db.add_game(1, 11, 620, "Portal 2")
        self.assertEqual(
            db.get_wishlist(),
            [("Portal 2", "steam", "https://store.steampowered.com/app/620/")],
        )

    def test_other_stores_also_appear(self):
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO wishlist (discord_user_id, game, store, link) VALUES (?, ?, ?, ?)",
                    ("10", "An Epic Game", "epic", "https://store.epicgames.com/example"),
                )

        self.assertEqual(
            db.get_wishlist()[0][0:2],
            ("An Epic Game", "epic")
        )

if __name__ == "__main__":
    unittest.main()