import unittest
import uuid
import tempfile
from pathlib import Path
from unittest.mock import patch
import database
import db


class TestAddGame(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "test.db"
        for module in (db, database):
            patcher = patch.object(module, "DATABASE_PATH", path)
            patcher.start()
            self.addCleanup(patcher.stop)
        db.init_db()
        self.user = uuid.uuid4().int % 10**12
        self.guild = 1

    def test_add_new_game_returns_true(self):
        self.assertTrue(db.add_game(self.guild, self.user, 620, "Portal 2"))

    def test_add_same_game_twice_returns_false(self):
        db.add_game(self.guild, self.user, 620, "Portal 2")
        self.assertFalse(db.add_game(self.guild, self.user, 620, "Portal 2"))

    def test_different_game_same_user_is_added(self):
        db.add_game(self.guild, self.user, 620, "Portal 2")
        self.assertTrue(db.add_game(self.guild, self.user, 440, "Team Fortress 2"))

    def test_same_game_different_user_is_added(self):
        db.add_game(self.guild, self.user, 620, "Portal 2")
        self.assertTrue(db.add_game(self.guild, self.user + 1, 620, "Portal 2"))


if __name__ == "__main__":
    unittest.main()
