import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
import db
import handler
import stores


class ParseEpicLinkTests(unittest.TestCase):

    def test_valid_epic_links(self):
        expected = ("epic", "Borderlands 3", "https://store.epicgames.com/en-US/p/borderlands-3")
        for link in (
            "https://store.epicgames.com/en-US/p/borderlands-3",
            "https://store.epicgames.com/p/borderlands-3",
            " https://store.epicgames.com/de/p/borderlands-3/ ",
            "https://store.epicgames.com/en-US/p/borderlands-3?utm_source=share#top",
            "https://STORE.EPICGAMES.COM/en-US/p/Borderlands-3",
            "https://www.epicgames.com/store/en-US/p/borderlands-3",
            "http://store.epicgames.com/en-US/p/borderlands-3",
        ):
            with self.subTest(link=link):
                self.assertEqual(stores.parse_store_link(link), expected)

    def test_epic_name_is_made_from_the_link(self):
        _, name, _ = stores.parse_store_link("https://store.epicgames.com/en-US/p/the-witcher-3-wild-hunt")
        self.assertEqual(name, "The Witcher 3 Wild Hunt")

    def test_invalid_epic_links(self):
        for link in (
            "https://store.epicgames.com/",
            "https://store.epicgames.com/en-US/",
            "https://store.epicgames.com/en-US/browse",
            "https://store.epicgames.com/en-US/bundles/some-bundle",
            "https://store.epicgames.com/en-US/p/",
            "https://store.epicgames.com/en-US/p/a/b",
            "https://store.epicgames.com.evil.com/en-US/p/borderlands-3",
            "https://evil.com/store.epicgames.com/en-US/p/borderlands-3",
            "https://store.epicgames.com@evil.com/en-US/p/borderlands-3",
            "https://user@store.epicgames.com/en-US/p/borderlands-3",
            "https://store.epicgames.com:8080/en-US/p/borderlands-3",
            "https://store.epicgames.com:bad/en-US/p/borderlands-3",
            "https://store.epicgames.com/en-US/p/border lands",
            "https://store.epicgames.com/en-US/p/borderlands-3 extra",
            "store.epicgames.com/en-US/p/borderlands-3",
            "ftp://store.epicgames.com/en-US/p/borderlands-3",
            "file://store.epicgames.com/en-US/p/borderlands-3",
        ):
            with self.subTest(link=link):
                self.assertIsNone(stores.parse_store_link(link))


class ParseGogLinkTests(unittest.TestCase):

    def test_valid_gog_links(self):
        expected = ("gog", "Cyberpunk 2077", "https://www.gog.com/en/game/cyberpunk_2077")
        for link in (
            "https://www.gog.com/en/game/cyberpunk_2077",
            "https://www.gog.com/game/cyberpunk_2077",
            "https://gog.com/game/cyberpunk_2077/",
            " https://www.gog.com/de/game/cyberpunk_2077 ",
            "https://www.gog.com/en/game/cyberpunk_2077?pp=abc#reviews",
            "https://WWW.GOG.COM/en/game/Cyberpunk_2077",
            "http://www.gog.com/game/cyberpunk_2077",
        ):
            with self.subTest(link=link):
                self.assertEqual(stores.parse_store_link(link), expected)

    def test_gog_name_is_made_from_the_link(self):
        _, name, _ = stores.parse_store_link("https://www.gog.com/en/game/the_witcher_3_wild_hunt")
        self.assertEqual(name, "The Witcher 3 Wild Hunt")

    def test_invalid_gog_links(self):
        for link in (
            "https://www.gog.com/",
            "https://www.gog.com/en/games",
            "https://www.gog.com/en/game/",
            "https://www.gog.com/en/game/a/b",
            "https://www.gog.com/en/game/some-game",
            "https://www.gog.com.evil.com/en/game/cyberpunk_2077",
            "https://evil.com/www.gog.com/en/game/cyberpunk_2077",
            "https://www.gog.com@evil.com/en/game/cyberpunk_2077",
            "https://user@www.gog.com/en/game/cyberpunk_2077",
            "https://www.gog.com:8080/en/game/cyberpunk_2077",
            "https://www.gog.com/en/game/cyber punk",
            "www.gog.com/en/game/cyberpunk_2077",
            "ftp://www.gog.com/en/game/cyberpunk_2077",
        ):
            with self.subTest(link=link):
                self.assertIsNone(stores.parse_store_link(link))


class NotAStoreLinkTests(unittest.TestCase):

    def test_other_inputs_are_not_store_links(self):
        for value in (
            None, "", "   ", "portal 2", 620,
            "https://store.steampowered.com/app/620/Portal_2/",
            "https://google.com",
            "https://store.epicgames.com",
        ):
            with self.subTest(value=value):
                self.assertIsNone(stores.parse_store_link(value))


class NameFromSlugTests(unittest.TestCase):

    def test_hyphens_and_underscores(self):
        self.assertEqual(stores.name_from_slug("hades"), "Hades")
        self.assertEqual(stores.name_from_slug("the-witcher-3"), "The Witcher 3")
        self.assertEqual(stores.name_from_slug("the_witcher_3"), "The Witcher 3")

    def test_double_hyphens_do_not_leave_gaps(self):
        self.assertEqual(stores.name_from_slug("borderlands-3--deluxe"), "Borderlands 3 Deluxe")


class WishlistWithStoreLinksTests(unittest.TestCase):
    """The real handler and database together, using a throwaway database file."""

    def setUp(self):
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

    def test_epic_game_is_saved_with_its_store_and_link(self):
        status, msg = handler.add_to_wishlist(1, 2, "https://store.epicgames.com/en-US/p/borderlands-3")
        self.assertEqual(status, "added")
        self.assertIn("Borderlands 3", msg)
        self.assertIn("Epic Games Store", msg)
        self.assertEqual(
            db.get_wishlist(1, 2),
            [("Borderlands 3", "epic", "https://store.epicgames.com/en-US/p/borderlands-3")],
        )

    def test_gog_game_is_saved_with_its_store_and_link(self):
        status, msg = handler.add_to_wishlist(1, 2, "https://www.gog.com/en/game/cyberpunk_2077")
        self.assertEqual(status, "added")
        self.assertIn("GOG", msg)
        self.assertEqual(
            db.get_wishlist(1, 2),
            [("Cyberpunk 2077", "gog", "https://www.gog.com/en/game/cyberpunk_2077")],
        )

    def test_same_game_twice_is_a_duplicate_even_with_a_different_link_form(self):
        handler.add_to_wishlist(1, 2, "https://store.epicgames.com/en-US/p/borderlands-3")
        status, msg = handler.add_to_wishlist(1, 2, "https://store.epicgames.com/de/p/borderlands-3?x=1")
        self.assertEqual(status, "duplicate")
        self.assertIn("already", msg)
        self.assertEqual(len(db.get_wishlist(1, 2)), 1)

    def test_another_user_can_add_the_same_game(self):
        handler.add_to_wishlist(1, 2, "https://www.gog.com/game/cyberpunk_2077")
        status, _ = handler.add_to_wishlist(1, 3, "https://www.gog.com/game/cyberpunk_2077")
        self.assertEqual(status, "added")

    def test_same_game_on_steam_and_epic_are_both_kept(self):
        db.add_game(1, 2, 397540, "Borderlands 3")
        status, _ = handler.add_to_wishlist(1, 2, "https://store.epicgames.com/en-US/p/borderlands-3")
        self.assertEqual(status, "added")
        self.assertEqual([row[1] for row in db.get_wishlist(1, 2)], ["epic", "steam"])

    def test_epic_and_gog_games_show_in_the_server_wishlist(self):
        handler.add_to_wishlist(1, 2, "https://store.epicgames.com/en-US/p/borderlands-3")
        handler.add_to_wishlist(1, 3, "https://store.epicgames.com/en-US/p/borderlands-3")
        handler.add_to_wishlist(1, 3, "https://www.gog.com/en/game/cyberpunk_2077")
        self.assertEqual(db.get_server_wishlist(1), [
            ("Borderlands 3", "epic", "https://store.epicgames.com/en-US/p/borderlands-3", 2),
            ("Cyberpunk 2077", "gog", "https://www.gog.com/en/game/cyberpunk_2077", 1),
        ])

    def test_epic_and_gog_games_can_be_removed_by_name(self):
        handler.add_to_wishlist(1, 2, "https://store.epicgames.com/en-US/p/borderlands-3")
        self.assertEqual(db.remove_game(1, 2, "borderlands 3"), "Borderlands 3")
        self.assertEqual(db.get_wishlist(1, 2), [])

    def test_bad_store_links_are_not_saved(self):
        for link in ("https://store.epicgames.com/en-US/browse", "https://www.gog.com/en/games"):
            with self.subTest(link=link):
                status, _ = handler.add_to_wishlist(1, 2, link)
                self.assertEqual(status, "bad_link")
        self.assertEqual(db.get_wishlist(1, 2), [])


if __name__ == "__main__":
    unittest.main()