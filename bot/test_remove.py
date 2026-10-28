import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import database
import db


class TestRemoveGame(unittest.TestCase):

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

    def test_remove_game_returns_its_name(self):
        db.add_game(0, 1, 1245620, "Elden Ring")
        self.assertEqual(db.remove_game(1, "Elden Ring"), "Elden Ring")

    def test_removed_game_is_gone_from_the_database(self):
        db.add_game(0, 1, 1245620, "Elden Ring")
        db.remove_game(1, "Elden Ring")
        self.assertEqual(db.get_wishlist(1), [])
        with closing(sqlite3.connect(db.DATABASE_PATH)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM wishlist").fetchone()[0]
        self.assertEqual(count, 0)

    def test_other_games_stay(self):
        db.add_game(0, 1, 1245620, "Elden Ring")
        db.add_game(0, 1, 620, "Portal 2")
        db.remove_game(1, "Elden Ring")
        self.assertEqual([row[0] for row in db.get_wishlist(1)], ["Portal 2"])

    def test_game_not_on_wishlist_returns_none(self):
        db.add_game(0, 1, 620, "Portal 2")
        self.assertIsNone(db.remove_game(1, "Elden Ring"))
        self.assertEqual(len(db.get_wishlist(1)), 1)

    def test_empty_wishlist_returns_none(self):
        self.assertIsNone(db.remove_game(1, "Elden Ring"))

    def test_other_users_copy_stays(self):
        db.add_game(0, 1, 620, "Portal 2")
        db.add_game(0, 2, 620, "Portal 2")
        db.remove_game(1, "Portal 2")
        self.assertEqual(db.get_wishlist(1), [])
        self.assertEqual(len(db.get_wishlist(2)), 1)

    def test_user_cannot_remove_another_users_game(self):
        db.add_game(0, 2, 620, "Portal 2")
        self.assertIsNone(db.remove_game(1, "Portal 2"))
        self.assertEqual(len(db.get_wishlist(2)), 1)

    def test_capitalization_is_ignored(self):
        db.add_game(0, 1, 1245620, "Elden Ring")
        self.assertEqual(db.remove_game(1, "eLdEn rInG"), "Elden Ring")
        self.assertEqual(db.get_wishlist(1), [])

    def test_extra_spaces_around_the_name_are_ignored(self):
        db.add_game(0, 1, 620, "Portal 2")
        self.assertEqual(db.remove_game(1, "  Portal 2  "), "Portal 2")

    def test_empty_name_removes_nothing(self):
        db.add_game(0, 1, 620, "Portal 2")
        self.assertIsNone(db.remove_game(1, ""))
        self.assertIsNone(db.remove_game(1, "   "))
        self.assertEqual(len(db.get_wishlist(1)), 1)

    def test_game_saved_under_two_stores_is_removed_from_both(self):
        db.add_game(0, 1, 620, "Portal 2")
        with closing(sqlite3.connect(db.DATABASE_PATH)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO wishlist (discord_user_id, game, store, link) VALUES (?, ?, ?, ?)",
                    ("1", "Portal 2", "gog", "https://www.gog.com/game/portal_2"),
                )
        self.assertEqual(len(db.get_wishlist(1)), 2)
        db.remove_game(1, "Portal 2")
        self.assertEqual(db.get_wishlist(1), [])

    def test_game_can_be_added_again_after_removal(self):
        db.add_game(0, 1, 620, "Portal 2")
        db.remove_game(1, "Portal 2")
        self.assertTrue(db.add_game(0, 1, 620, "Portal 2"))


if __name__ == "__main__":
    unittest.main()