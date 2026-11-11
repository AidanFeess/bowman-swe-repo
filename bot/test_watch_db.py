from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import database
import db
from game_search import GameChoice
import watch_db

GAME = GameChoice("Portal 2", "steam", "https://store.steampowered.com/app/620/", steam_id=620)


class WatchDatabaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "test.db"
        for module in (database, db):
            p = patch.object(module, "DATABASE_PATH", self.path)
            p.start()
            self.addCleanup(p.stop)
        db.init_db()

    def test_targets_use_exact_cents_and_free_is_allowed(self):
        self.assertEqual(watch_db.price_cents("19.99"), 1999)
        self.assertEqual(watch_db.price_cents("0"), 0)
        for value in ("-1", "NaN", "Infinity", "abc", "1.001", "1000001", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                watch_db.price_cents(value)

    def test_save_update_and_restart_keep_one_watch(self):
        first = watch_db.save(1, 2, GAME, 1000)
        second = watch_db.save(1, 2, GAME, 1200)
        db.init_db()
        self.assertEqual(first, second)
        rows = watch_db.rows(1, 2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_cents"], 1200)
        self.assertEqual(watch_db.choice(rows[0]).steam_id, 620)

    def test_server_and_user_isolation(self):
        own = watch_db.save(1, 2, GAME, 1000)
        other_user = watch_db.save(1, 3, GAME, 2000)
        other_server = watch_db.save(2, 2, GAME, 3000)
        self.assertFalse(watch_db.remove(1, 2, other_user))
        self.assertFalse(watch_db.remove(1, 2, other_server))
        self.assertEqual([r["id"] for r in watch_db.rows(1, 2)], [own])
        self.assertTrue(watch_db.remove(1, 2, own))
        self.assertEqual(len(watch_db.rows()), 2)

    def test_unchanged_target_preserves_alert_state_changed_target_rearms(self):
        watch_id = watch_db.save(1, 2, GAME, 1000)
        row = watch_db.rows(1, 2)[0]
        watch_db.checked(watch_id, row["revision"], "2026-11-11", 900)
        watch_db.save(1, 2, GAME, 1000)
        row = watch_db.rows(1, 2)[0]
        self.assertEqual(row["notified_cents"], 900)
        self.assertEqual(row["last_checked_day"], "2026-11-11")
        watch_db.save(1, 2, GAME, 2000)
        row = watch_db.rows(1, 2)[0]
        self.assertIsNone(row["notified_cents"])
        self.assertIsNone(row["last_checked_day"])

    def test_old_revision_cannot_overwrite_new_target_state(self):
        watch_id = watch_db.save(1, 2, GAME, 1000)
        old = watch_db.rows(1, 2)[0]
        watch_db.save(1, 2, GAME, 500)
        watch_db.checked(watch_id, old["revision"], "2026-11-11", 900)
        self.assertIsNone(watch_db.current(watch_id, old["revision"]))
        self.assertIsNone(watch_db.rows(1, 2)[0]["last_checked_day"])

    def test_limit_allows_updates_and_other_users(self):
        for number in range(watch_db.MAX_WATCHES):
            watch_db.save(1, 2, GameChoice(f"Game {number}", "steam", "url", steam_id=number + 1), 100)
        with self.assertRaises(watch_db.WatchLimitReached):
            watch_db.save(1, 2, GAME, 100)
        watch_db.save(1, 2, GameChoice("Game 0", "steam", "url", steam_id=1), 200)
        watch_db.save(1, 3, GAME, 100)
        self.assertEqual(len(watch_db.rows(1, 2)), watch_db.MAX_WATCHES)

    def test_existing_wishlist_survives_idempotent_initialization(self):
        db.add_game(1, 2, 620, "Portal 2")
        db.init_db()
        db.init_db()
        self.assertEqual(db.get_wishlist(1, 2)[0][0], "Portal 2")
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute("pragma integrity_check").fetchone()[0], "ok")
