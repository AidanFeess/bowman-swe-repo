import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import requests
from discord import app_commands

import bot
import database
import db
import handler
import stores
from game_search import GameChoice


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


def found(*games):
    """CheapShark's answer to a search by name."""
    return [{"gameID": gid, "external": title} for gid, title in games]


def game_on(*store_ids, title=None):
    """CheapShark's answer for one game: which stores have an offer."""
    return {
        "info": {"title": title} if title else {},
        "deals": [{"storeID": store_id, "dealID": f"deal{store_id}"} for store_id in store_ids],
    }


class SearchStoreGameTests(unittest.TestCase):

    def search(self, name, store, *responses):
        with patch("stores._get_json", side_effect=list(responses)) as get:
            return stores.search_store_game(name, store), get

    def test_game_sold_on_epic_is_found(self):
        result, get = self.search(
            "borderlands 3", "epic",
            found(("100", "Borderlands 3")), game_on("1", "25", title="Borderlands 3"),
        )
        self.assertEqual(result, (
            "Borderlands 3", "https://store.epicgames.com/en-US/browse?q=Borderlands%203",
        ))
        self.assertEqual(get.call_args_list[0].args, (stores.GAMES_URL, {"title": "borderlands 3", "limit": 20}))
        self.assertEqual(get.call_args_list[1].args, (stores.GAMES_URL, {"id": "100"}))

    def test_game_sold_on_gog_is_found(self):
        result, _ = self.search(
            "Cyberpunk 2077", "gog",
            found(("200", "Cyberpunk 2077")), game_on("1", "7", title="Cyberpunk 2077"),
        )
        self.assertEqual(result, (
            "Cyberpunk 2077", "https://www.gog.com/en/games?query=Cyberpunk%202077",
        ))

    def test_title_comes_from_the_store_data_not_the_typed_name(self):
        result, _ = self.search(
            "witcher 3", "gog",
            found(("300", "witcher 3")), game_on("7", title="The Witcher 3: Wild Hunt"),
        )
        self.assertEqual(result[0], "The Witcher 3: Wild Hunt")
        self.assertIn("The%20Witcher%203%3A%20Wild%20Hunt", result[1])

    def test_exact_title_is_checked_before_other_matches(self):
        result, get = self.search(
            "Hades", "gog",
            found(("1", "Hades II"), ("2", "Hades")), game_on("7", title="Hades"),
        )
        self.assertEqual(result[0], "Hades")
        self.assertEqual(get.call_args_list[1].args[1], {"id": "2"})

    def test_a_match_that_is_not_sold_on_the_store_is_skipped(self):
        result, get = self.search(
            "Portal", "epic",
            found(("1", "Portal"), ("2", "Portal 2")),
            game_on("1"),                       # Portal is not on Epic
            game_on("25", title="Portal 2"),    # Portal 2 is
        )
        self.assertEqual(result[0], "Portal 2")
        self.assertEqual(get.call_count, 3)

    def test_no_match_sold_on_the_store_returns_none(self):
        result, _ = self.search("Portal", "epic", found(("1", "Portal")), game_on("1"))
        self.assertIsNone(result)

    def test_no_search_results_returns_none_without_more_requests(self):
        result, get = self.search("asdfghjkl", "gog", [])
        self.assertIsNone(result)
        self.assertEqual(get.call_count, 1)

    def test_only_a_few_matches_are_checked(self):
        many = found(*[(str(i), f"Game {i}") for i in range(1, 15)])
        responses = [many] + [game_on("1")] * stores.MAX_CANDIDATES
        result, get = self.search("Game", "epic", *responses)
        self.assertIsNone(result)
        self.assertEqual(get.call_count, 1 + stores.MAX_CANDIDATES)

    def test_empty_name_makes_no_request(self):
        with patch("stores._get_json") as get:
            self.assertIsNone(stores.search_store_game("   ", "epic"))
        get.assert_not_called()

    def test_unsupported_store_is_refused(self):
        with self.assertRaises(ValueError):
            stores.search_store_game("Portal 2", "steam")

    def test_bad_responses_raise_a_search_error(self):
        for first in (None, {}, [None], [{"gameID": "abc", "external": "X"}],
                      [{"gameID": "1", "external": ""}], [{"gameID": "1"}]):
            with self.subTest(first=first):
                with self.assertRaises(stores.StoreSearchError):
                    self.search("Portal", "epic", first)
        for second in (None, [], {"deals": None}, {"deals": [None]}):
            with self.subTest(second=second):
                with self.assertRaises(stores.StoreSearchError):
                    self.search("Portal", "epic", found(("1", "Portal")), second)

    def test_web_errors_are_passed_up(self):
        with patch("stores.requests.get", side_effect=requests.ConnectionError("down")):
            with self.assertRaises(requests.ConnectionError):
                stores.search_store_game("Portal", "epic")


class WishlistByNameTests(unittest.TestCase):
    """Typing a name and choosing Epic Games Store or GOG, with a throwaway database file."""

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
        self.epic_link = "https://store.epicgames.com/en-US/browse?q=Borderlands%203"

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    @patch("handler.stores.search_store_game", return_value=("Borderlands 3", "https://store.epicgames.com/en-US/browse?q=Borderlands%203"))
    def test_name_on_epic_is_saved(self, search):
        status, msg = handler.add_to_wishlist(1, 2, " borderlands 3 ", "epic")
        self.assertEqual(status, "added")
        self.assertIn("Borderlands 3", msg)
        self.assertIn("Epic Games Store", msg)
        search.assert_called_once_with("borderlands 3", "epic")
        self.assertEqual(db.get_wishlist(1, 2), [("Borderlands 3", "epic", self.epic_link)])

    @patch("handler.stores.search_store_game", return_value=("Cyberpunk 2077", "https://www.gog.com/en/games?query=Cyberpunk%202077"))
    def test_name_on_gog_is_saved(self, search):
        status, msg = handler.add_to_wishlist(1, 2, "cyberpunk", "gog")
        self.assertEqual(status, "added")
        self.assertIn("GOG", msg)
        self.assertEqual(db.get_wishlist(1, 2)[0][1], "gog")

    @patch("handler.stores.search_store_game", return_value=("Borderlands 3", "https://store.epicgames.com/en-US/browse?q=Borderlands%203"))
    def test_same_name_twice_is_a_duplicate(self, search):
        handler.add_to_wishlist(1, 2, "borderlands 3", "epic")
        status, msg = handler.add_to_wishlist(1, 2, "Borderlands 3", "epic")
        self.assertEqual(status, "duplicate")
        self.assertIn("already", msg)
        self.assertEqual(len(db.get_wishlist(1, 2)), 1)

    @patch("handler.stores.search_store_game", return_value=None)
    def test_name_not_found_on_the_store(self, search):
        status, msg = handler.add_to_wishlist(1, 2, "asdfghjkl", "gog")
        self.assertEqual(status, "not_found")
        self.assertIn("GOG", msg)
        self.assertEqual(db.get_wishlist(1, 2), [])

    @patch("handler.stores.search_store_game", side_effect=requests.ConnectionError("down"))
    def test_search_failure_does_not_crash(self, search):
        status, _ = handler.add_to_wishlist(1, 2, "Portal 2", "epic")
        self.assertEqual(status, "error")
        self.assertEqual(db.get_wishlist(1, 2), [])

    @patch("handler.steam.search_game", return_value=(620, "Portal 2"))
    @patch("handler.stores.search_store_game")
    def test_steam_is_still_the_default(self, search, steam_search):
        status, _ = handler.add_to_wishlist(1, 2, "portal 2")
        self.assertEqual(status, "added")
        search.assert_not_called()
        self.assertEqual(db.get_wishlist(1, 2)[0][1], "steam")

    @patch("handler.stores.search_store_game")
    def test_a_pasted_link_wins_over_the_chosen_store(self, search):
        status, _ = handler.add_to_wishlist(1, 2, "https://www.gog.com/en/game/cyberpunk_2077", "epic")
        self.assertEqual(status, "added")
        search.assert_not_called()
        self.assertEqual(db.get_wishlist(1, 2)[0][1], "gog")

    @patch("handler.stores.search_store_game")
    @patch("handler.steam.get_game_name", return_value="Portal 2")
    @patch("handler.steam.get_app_id", return_value=620)
    def test_a_steam_link_is_not_searched_on_the_chosen_store(self, get_id, get_name, search):
        status, _ = handler.add_to_wishlist(1, 2, "https://store.steampowered.com/app/620/", "epic")
        self.assertEqual(status, "added")
        search.assert_not_called()
        self.assertEqual(db.get_wishlist(1, 2)[0][1], "steam")


class WishlistCommandTests(unittest.IsolatedAsyncioTestCase):

    def interaction(self):
        return SimpleNamespace(
            guild_id=1,
            user=SimpleNamespace(id=2),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

    async def test_store_choice_is_passed_to_search_and_selected_game_is_saved(self):
        interaction = self.interaction()
        choice = GameChoice("Borderlands 3", "epic", "https://store.epicgames.com/en-US/p/borderlands-3", catalog_id="123")
        with patch("game_search.search_games", AsyncMock(return_value=[choice])) as search, \
                patch("db.add_store_game", return_value=True) as add:
            await bot.wishlist.callback(
                interaction, "Borderlands 3", app_commands.Choice(name="Epic Games Store", value="epic")
            )
        search.assert_awaited_once_with("Borderlands 3", "epic")
        add.assert_called_once_with(1, 2, "epic", choice.link, "Borderlands 3")
        self.assertIn("Added **Borderlands 3**", interaction.followup.send.call_args.args[0])

    async def test_no_store_choice_means_steam(self):
        interaction = self.interaction()
        with patch("game_search.search_games", AsyncMock(return_value=[])) as search:
            await bot.wishlist.callback(interaction, "Portal 2", None)
        search.assert_awaited_once_with("Portal 2", "steam")

    def test_store_is_an_optional_choice_of_the_three_stores(self):
        store = next(p for p in bot.wishlist.parameters if p.name == "store")
        self.assertFalse(store.required)
        self.assertEqual([c.value for c in store.choices], ["steam", "epic", "gog"])
        self.assertIn("/wishlist <game> [store]", bot.build_help_embed().description)


if __name__ == "__main__":
    unittest.main()
