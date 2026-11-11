"""Run on Linux: python3 -m unittest discover -s deploy -p test_update.py -v."""

import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("updater", Path(__file__).with_name("game-night-bot-update.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
OLD = "a" * 40
NEW = "b" * 40


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.db = root / "wishlist.db"
        self.backups = root / "backups"
        self.backups.mkdir()
        self.u = module.Updater(root, self.db, self.backups)
        self.u.releases.mkdir()
        self.old = self.u.releases / "old"
        self.new = self.u.releases / "new"
        for path, revision in ((self.old, OLD), (self.new, NEW)):
            path.mkdir()
            (path / "REVISION").write_text(revision)
        self.u.current.symlink_to(self.old, target_is_directory=True)
        with sqlite3.connect(self.db) as c:
            c.execute("create table wishlist (name text)")
            c.execute("insert into wishlist values ('Portal 2')")
        self.command = patch.object(module, "command").start()
        self.addCleanup(patch.stopall)

    def configure_run(self, revision=NEW):
        self.command.side_effect = [module.REMOTE, "", revision]
        self.u.active = Mock(return_value=True)
        self.u.build = Mock(return_value=self.new)
        self.u.activate = Mock(return_value=self.old)
        self.u.prune = Mock()

    def test_unchanged_commit_does_not_build_or_restart(self):
        self.configure_run(OLD)
        self.u.run()
        self.u.build.assert_not_called()
        self.u.activate.assert_not_called()

    def test_manually_stopped_bot_stays_stopped(self):
        self.u.active = Mock(return_value=False)
        self.u.run()
        self.command.assert_not_called()

    def test_fetch_failure_leaves_current_untouched(self):
        self.configure_run()
        self.command.side_effect = [module.REMOTE, RuntimeError("network down")]
        with self.assertRaisesRegex(RuntimeError, "network down"):
            self.u.run()
        self.assertEqual(self.u.current.resolve(), self.old)
        self.u.build.assert_not_called()
        self.u.activate.assert_not_called()

    def test_failed_dependency_install_or_tests_do_not_stop_bot(self):
        self.configure_run()
        self.u.build.side_effect = RuntimeError("candidate failed checks")
        with self.assertRaisesRegex(RuntimeError, "candidate failed checks"):
            self.u.run()
        self.assertEqual(self.u.current.resolve(), self.old)
        self.u.activate.assert_not_called()

    def test_stop_during_build_is_respected(self):
        self.configure_run()
        self.u.active.side_effect = [True, False]
        self.u.run()
        self.u.activate.assert_not_called()
        self.assertFalse(self.new.exists())
        self.assertEqual(self.u.current.resolve(), self.old)

    def test_success_switches_code_and_keeps_database(self):
        self.u.start = Mock()
        self.u.wait_ready = Mock()
        previous = self.u.activate(self.new, NEW)
        self.assertEqual(previous, self.old)
        self.assertEqual(self.u.current.resolve(), self.new)
        self.assertEqual(len(list(self.backups.glob("*.db"))), 1)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("select name from wishlist").fetchall(), [("Portal 2",)])

    def test_startup_failure_restores_code_data_and_schema(self):
        def start():
            if self.u.current.resolve() == self.new:
                with sqlite3.connect(self.db) as c:
                    c.execute("alter table wishlist add column broken integer")
                    c.execute("delete from wishlist")

        self.u.start = Mock(side_effect=start)
        self.u.wait_ready = Mock(side_effect=[RuntimeError("no Discord ready"), None])
        with self.assertRaisesRegex(RuntimeError, "no Discord ready"):
            self.u.activate(self.new, NEW)
        self.assertEqual(self.u.current.resolve(), self.old)
        self.assertEqual(self.u.start.call_count, 2)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("select * from wishlist").fetchall(), [("Portal 2",)])
            self.assertEqual(c.execute("pragma integrity_check").fetchone()[0], "ok")

    def test_failed_backup_never_switches_code(self):
        self.u.backup = Mock(side_effect=RuntimeError("disk full"))
        self.u.start = Mock()
        self.u.wait_ready = Mock()
        with self.assertRaisesRegex(RuntimeError, "disk full"):
            self.u.activate(self.new, NEW)
        self.assertEqual(self.u.current.resolve(), self.old)
        self.u.start.assert_called_once()

    def test_cleanup_cannot_delete_current_or_outside_release(self):
        with self.assertRaises(RuntimeError):
            self.u.remove_release(self.old)
        with self.assertRaises(RuntimeError):
            self.u.remove_release(self.backups)
        self.assertTrue(self.old.exists())
        self.assertTrue(self.backups.exists())


if __name__ == "__main__":
    unittest.main()
