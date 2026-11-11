#!/usr/bin/python3
"""Stage, test, and activate GitHub main without modifying the live release."""

import fcntl
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time

REMOTE = "https://github.com/AidanFeess/bowman-swe-repo.git"


def log(message):
    print(message, flush=True)


def command(*args, cwd=None, timeout=90, capture=True):
    # The updater/builds never load the bot's EnvironmentFile or inherit credentials.
    env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1", "GIT_TERMINAL_PROMPT": "0",
           "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_CACHE_DIR": "1"}
    process = subprocess.Popen(args, cwd=cwd, env=env, text=True,
                               stdout=subprocess.PIPE if capture else None,
                               stderr=subprocess.STDOUT, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
    except BaseException:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise
    if process.returncode:
        if output:
            log(output[-6000:])
        raise subprocess.CalledProcessError(process.returncode, args)
    return (output or "").strip()


class Updater:
    def __init__(self, root=Path("/opt/game-night-bot"),
                 database=Path("/var/lib/game-night-bot/wishlist.db"),
                 backups=Path("/var/backups/game-night-bot")):
        self.root, self.database, self.backups = root, database, backups
        self.source = root / "repo"
        self.current = root / "current"
        self.releases = root / "releases"
        self.unit = "game-night-bot.service"

    def property(self, name):
        return command("systemctl", "show", self.unit, "-p", name, "--value")

    def active(self):
        return self.property("ActiveState") == "active"

    def switch(self, release):
        link = self.root / "current.next"
        link.unlink(missing_ok=True)
        link.symlink_to(release, target_is_directory=True)
        os.replace(link, self.current)

    def remove_release(self, path):
        # Never follow an unexpected path or delete the running release.
        if (path.is_symlink() or path.parent.resolve() != self.releases.resolve()
                or path.resolve() == self.current.resolve()):
            raise RuntimeError("Refusing to remove an unsafe release path")
        shutil.rmtree(path)

    def build(self, revision):
        self.releases.mkdir(exist_ok=True, mode=0o755)
        release = Path(tempfile.mkdtemp(prefix=revision[:12] + "-", dir=self.releases))
        try:
            archive = release / "source.tar"
            command("git", "-C", str(self.source), "archive", "--format=tar",
                    "--output=" + str(archive), revision)
            command("chown", "-R", "game-night-bot-build:game-night-bot-build", str(release))
            release.chmod(0o755)

            def build_command(*args, timeout=300, cwd=release):
                return command("runuser", "-u", "game-night-bot-build", "--",
                               "sh", "-c", 'umask 022; exec "$@"', "build", *args,
                               cwd=cwd, timeout=timeout, capture=False)

            build_command("tar", "--no-same-owner", "-xf", str(archive))
            archive.unlink()
            for reserved in ("venv", "checks", "REVISION"):
                path = release / reserved
                if path.exists() or path.is_symlink():
                    raise RuntimeError("Source contains reserved deployment path: " + reserved)
            build_command("python3", "-m", "venv", str(release / "venv"))
            python = str(release / "venv/bin/python")
            build_command(python, "-m", "pip", "install", "-r", "bot/requirements.txt")
            # Existing tests write a database next to their source. Keep it away
            # from both the staged runtime and the production database.
            checks = release / "checks"
            shutil.copytree(release / "bot", checks, symlinks=True)
            command("chown", "-hR", "game-night-bot-build:game-night-bot-build", str(checks))
            build_command(python, "-m", "unittest", "discover", "-q", cwd=checks, timeout=120)
            shutil.rmtree(checks)
            # Lock down tested code before exposing the production DB symlink.
            command("chown", "-hR", "root:root", str(release))
            if (release / "REVISION").exists() or (release / "REVISION").is_symlink():
                raise RuntimeError("Build unexpectedly created a revision marker")
            (release / "REVISION").write_text(revision + "\n")
            (release / "REVISION").chmod(0o644)
            db_link = release / "bot/wishlist.db"
            if db_link.exists() or db_link.is_symlink():
                raise RuntimeError("Staged source unexpectedly contains a database")
            db_link.symlink_to(self.database)
            return release
        except BaseException:
            self.remove_release(release)
            raise

    def backup(self, previous):
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        path = self.backups / (stamp + "-" + previous[:12] + ".db")
        with sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(path) as target:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Database backup failed integrity check")
        path.chmod(0o600)
        return path

    def restore(self, snapshot):
        # Service is stopped. SQLite's backup API restores schema and data while
        # retaining ownership/permissions of the production database file.
        with sqlite3.connect(snapshot) as source, sqlite3.connect(self.database) as target:
            source.backup(target)

    def start(self):
        command("systemctl", "reset-failed", self.unit)
        command("systemctl", "start", self.unit)

    def wait_ready(self, seconds=120):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            invocation = self.property("InvocationID")
            if invocation and self.active():
                logs = command("journalctl", "_SYSTEMD_INVOCATION_ID=" + invocation,
                               "--no-pager", "-o", "cat", timeout=10)
                if "Logged in as " in logs:
                    time.sleep(5)
                    if self.active() and self.property("InvocationID") == invocation:
                        return
            time.sleep(2)
        raise RuntimeError("New process did not reach Discord ready within 120 seconds")

    def activate(self, release, revision):
        previous = self.current.resolve(strict=True)
        snapshot = None
        try:
            command("systemctl", "stop", self.unit, timeout=45)
            snapshot = self.backup((previous / "REVISION").read_text().strip())
            self.switch(release)
            self.start()
            self.wait_ready()
        except BaseException:
            log("Update failed; restoring the previous code and database")
            command("systemctl", "stop", self.unit, timeout=45)
            self.switch(previous)
            if snapshot is not None:
                self.restore(snapshot)
            self.start()
            self.wait_ready()
            log("Rollback reconnected to Discord")
            raise
        log("Deployed " + revision + "; Discord ready; database backup: " + str(snapshot))
        return previous

    def prune(self, previous):
        releases = sorted(self.releases.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        keep = {self.current.resolve(), previous, *releases[:3]}
        for path in releases:
            if path not in keep:
                self.remove_release(path)
        for path in sorted(self.backups.glob("*.db"), reverse=True)[10:]:
            path.unlink()

    def run(self):
        if not self.active():
            log("Bot is stopped; leaving it stopped")
            return
        remote = command("git", "-C", str(self.source), "remote", "get-url", "origin")
        if remote != REMOTE:
            raise RuntimeError("Unexpected Git remote")
        command("git", "-C", str(self.source), "fetch", "--no-tags", "origin",
                "+refs/heads/main:refs/remotes/origin/main")
        revision = command("git", "-C", str(self.source), "rev-parse", "origin/main")
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise RuntimeError("Invalid main revision")
        if (self.current / "REVISION").read_text().strip() == revision:
            log("Already on " + revision + "; no restart needed")
            return
        log("Preparing GitHub main " + revision)
        release = self.build(revision)
        if not self.active():
            self.remove_release(release)
            log("Bot was stopped while building; leaving it stopped")
            return
        try:
            previous = self.activate(release, revision)
        except BaseException:
            if self.current.resolve() != release:
                self.remove_release(release)
            raise
        self.prune(previous)


def interrupted(signum, frame):
    raise RuntimeError("Updater interrupted")


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    with open("/run/lock/game-night-bot-update.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("Another update is running")
        else:
            Updater().run()
