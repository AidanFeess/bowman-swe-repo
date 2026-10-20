import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import database
import db


class TestGetWishlist(unittest.TestCase):

    def setUp(self):
        # Use a throwaway database file so the real wishlist.db is never touched
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "test.db"
        self.patches = [
            patch.object(database, "DATABASE_PATH", path),
            patch.object(db, "DATABASE_PATH", path),
        ]
        for p in self.patches:
            p.start()
        db.init_db()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_empty_wishlist(self):
        self.assertEqual(db.get_wishlist(1), [])

    def test_user_sees_their_own_games(self):
        db.add_game(0, 1, 1245620, "Elden Ring")
        games = [row[0] for row in db.get_wishlist(1)]
        self.assertEqual(games, ["Elden Ring"])

    def test_user_does_not_see_other_users_games(self):
        db.add_game(0, 1, 1245620, "Elden Ring")
        self.assertEqual(db.get_wishlist(2), [])

    def test_same_game_on_two_wishlists_shows_for_each_user(self):
        db.add_game(0, 1, 620, "Portal 2")
        db.add_game(0, 2, 620, "Portal 2")
        self.assertEqual(len(db.get_wishlist(1)), 1)
        self.assertEqual(len(db.get_wishlist(2)), 1)

    def test_games_are_sorted_by_name(self):
        db.add_game(0, 1, 620, "portal 2")
        db.add_game(0, 1, 1245620, "Elden Ring")
        db.add_game(0, 1, 413150, "Stardew Valley")
        games = [row[0] for row in db.get_wishlist(1)]
        self.assertEqual(games, ["Elden Ring", "portal 2", "Stardew Valley"])

    def test_other_stores_also_appear(self):
        with closing(sqlite3.connect(db.DATABASE_PATH)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO wishlist (discord_user_id, game, store, link) VALUES (?, ?, ?, ?)",
                    ("1", "Hades", "gog", "https://www.gog.com/game/hades"),
                )
        rows = db.get_wishlist(1)
        self.assertEqual(rows[0][:2], ("Hades", "gog"))


if __name__ == "__main__":
    unittest.main()