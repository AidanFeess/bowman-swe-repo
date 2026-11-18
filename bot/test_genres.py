import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
import db
import genres
import handler
from backfill_genres import backfill


class GenreTests(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        path = Path(temporary.name) / "test.db"

        for module in (database, db):
            mock = patch.object(module, "DATABASE_PATH", path)
            mock.start()
            self.addCleanup(mock.stop)

        db.init_db()

    def test_genres_shared_by_users_and_counts_preserved(self):
        db.add_game(1, 10, 620, "Portal 2")
        db.add_game(1, 11, 620, "Portal 2")

        with patch("genres.lookup", return_value=["Action", "Puzzle"]):
            db.populate_game_genres(
                "steam",
                "Portal 2",
                "https://store.steampowered.com/app/620/"
            )

        rows = db.get_server_wishlist_with_genres(1)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], 2)
        self.assertEqual(
            json.loads(rows[0][4]),
            ["Action", "Puzzle"]
        )

    def test_multiple_genres(self):
        db.add_game(1, 10, 620, "Portal 2")

        db.save_game_genres(
            "steam",
            "https://store.steampowered.com/app/620/",
            ["Action", "Puzzle"]
        )

        groups = genres.group_rows(
            db.get_server_wishlist_with_genres(1)
        )

        self.assertEqual(
            [name for name, _ in groups],
            ["Action", "Puzzle"]
        )

    def test_unknown_and_server_isolation(self):
        db.add_store_game(
            1, 10, "epic",
            "https://store.epicgames.com/en-US/p/example",
            "Example"
        )

        db.add_game(2, 11, 620, "Portal 2")

        rows = db.get_server_wishlist_with_genres(1)

        self.assertEqual(
            [name for name, _ in genres.group_rows(rows)],
            ["Unknown"]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            db.get_server_wishlist_with_genres(2)[0][3],
            1
        )

    def test_personal_genre_list(self):
        db.add_game(1, 10, 620, "Portal 2")
        db.add_game(1, 11, 440, "Team Fortress 2")

        rows = db.get_wishlist_with_genres(1, 10)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "Portal 2")

    def test_steam_response_parsing(self):
        payload = {
            "620": {
                "success": True,
                "data": {
                    "genres": [
                        {"description": "Action"},
                        {"description": "Puzzle"}
                    ]
                }
            }
        }

        with patch("genres.requests.get") as request:
            request.return_value.json.return_value = payload

            labels = genres.lookup(
                "steam",
                "Portal 2",
                "https://store.steampowered.com/app/620/"
            )

        self.assertEqual(labels, ["Action", "Puzzle"])

    def test_nonsteam_mismatched_game_is_unknown(self):
        with patch(
            "genres.steam.search_game",
            return_value=(620, "Wrong Game")
        ), patch("genres.requests.get") as request:

            labels = genres.lookup(
                "gog",
                "Portal 2",
                "https://www.gog.com/en/game/portal_2"
            )

        self.assertEqual(labels, [])
        request.assert_not_called()

    def test_backfill_does_not_delete_users_or_refetch(self):
        db.add_game(1, 10, 620, "Portal 2")
        db.add_game(1, 11, 620, "Portal 2")

        self.assertEqual(len(db.games_missing_genres()), 1)

        with patch("genres.lookup", return_value=["Puzzle"]), \
             patch("backfill_genres.time.sleep"):
            backfill()

        self.assertEqual(db.games_missing_genres(), [])
        self.assertEqual(
            db.get_server_wishlist(1)[0][3],
            2
        )

    def test_steam_link_addition_saves_genres(self):
        with patch(
            "handler.steam.get_game_name",
            return_value="Portal 2"
        ), patch(
            "genres.lookup",
            return_value=["Action", "Puzzle"]
        ):
            status, _ = handler.add_to_wishlist(
                1, 10,
                "https://store.steampowered.com/app/620/"
            )

        self.assertEqual(status, "added")
        self.assertEqual(
            json.loads(db.get_wishlist_with_genres(1, 10)[0][3]),
            ["Action", "Puzzle"]
        )

    def test_epic_link_addition_survives_missing_genres(self):
        with patch("genres.lookup", return_value=[]):
            status, _ = handler.add_to_wishlist(
                1, 10,
                "https://store.epicgames.com/en-US/p/example"
            )

        self.assertEqual(status, "added")
        self.assertEqual(
            db.get_wishlist_with_genres(1, 10)[0][3],
            "[]"
        )

    def test_cached_genres_skip_lookup(self):
        link = "https://store.steampowered.com/app/620/"
        db.save_game_genres("steam", link, ["Puzzle"])

        with patch("genres.lookup") as lookup:
            result = db.populate_game_genres(
                "steam", "Portal 2", link
            )

        self.assertEqual(result, ["Puzzle"])
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
