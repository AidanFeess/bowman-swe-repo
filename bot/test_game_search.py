import asyncio
from decimal import Decimal
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp
import game_search as search
import pricing
import health


class SearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fetch = AsyncMock()
        patcher = patch("pricing._get_json", self.fetch)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_multiple_steam_results_are_preserved_and_exact_is_first(self):
        self.fetch.return_value = {"items": [
            {"id": 2, "name": "Dark Souls II", "type": "app"},
            {"id": 1, "name": "Dark Souls", "type": "app"},
            {"id": 1, "name": "Dark Souls duplicate", "type": "app"},
            {"id": 3, "name": "Bundle", "type": "sub"},
        ]}
        choices = await search.search_games("darksouls")
        self.assertEqual([c.steam_id for c in choices], [1, 2])
        self.assertEqual(choices[0].link, "https://store.steampowered.com/app/1/")

    async def test_compact_name_falls_back_to_precise_catalog_steam_ids(self):
        self.fetch.side_effect = [{"items": []}, [
            {"gameID": "100", "external": "Dark Souls Remastered", "steamAppID": "570940"},
            {"gameID": "200", "external": "Dark Souls II", "steamAppID": "335300"},
            {"gameID": "300", "external": "No Steam ID", "steamAppID": None},
        ]]
        choices = await search.search_games("darksouls")
        self.assertEqual([c.steam_id for c in choices], [570940, 335300])
        self.assertEqual(self.fetch.call_args_list[1].args[2]["title"], "darksouls")

    async def test_epic_and_gog_results_only_include_games_carried_by_store(self):
        for store, store_id in (("epic", "25"), ("gog", "7")):
            with self.subTest(store=store):
                async def get(session, url, params):
                    if "title" in params:
                        return [{"gameID": "1", "external": "Hades"}, {"gameID": "2", "external": "Hades II"}]
                    return {"deals": [{"storeID": store_id if params["id"] == "1" else "1"}]}
                self.fetch.side_effect = get
                choices = await search.search_games("hades", store)
                self.assertEqual(len(choices), 1)
                self.assertEqual(choices[0].catalog_id, "1")
                self.assertEqual(choices[0].store, store)

    async def test_empty_and_unknown_names(self):
        self.assertEqual(await search.search_games("  "), [])
        self.fetch.assert_not_awaited()
        self.fetch.side_effect = [{"items": []}, []]
        self.assertEqual(await search.search_games("not a game"), [])

    async def test_results_are_bounded(self):
        self.fetch.return_value = {"items": [{"id": i, "name": f"Game {i}", "type": "app"} for i in range(1, 40)]}
        self.assertEqual(len(await search.search_games("Game")), search.MAX_CHOICES)

    async def test_malformed_response_and_network_failure_are_reported(self):
        for response in (None, {}, {"items": None}, {"items": [None]},
                         {"items": [{"id": True, "name": "Game", "type": "app"}]}):
            with self.subTest(response=response):
                self.fetch.return_value = response
                with self.assertRaises(pricing.PriceSourceError):
                    await search.search_games("game")
        self.fetch.side_effect = aiohttp.ClientConnectionError()
        with self.assertRaises(pricing.PriceSourceError):
            await search.search_games("game")

    async def test_deadline_cancels_a_slow_search(self):
        cancelled = asyncio.Event()
        async def slow(*args):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        self.fetch.side_effect = slow
        with patch("pricing.LOOKUP_TIMEOUT", 0.02):
            with self.assertRaises(pricing.PriceSourceError):
                await search.search_games("game")
        self.assertTrue(cancelled.is_set())

    async def test_chosen_catalog_id_does_not_run_another_name_search(self):
        self.fetch.return_value = {"info": {"title": "Hades"}, "deals": [
            {"storeID": "25", "dealID": "abc%2Bdef%3D", "price": "0", "retailPrice": "24.99"},
            {"storeID": "7", "dealID": "gog", "price": "9.99", "retailPrice": "24.99"},
        ]}
        result = await search.choice_prices(search.GameChoice("Hades", "epic", "link", catalog_id="123"))
        self.assertEqual(self.fetch.call_args.args[2], {"id": "123"})
        self.assertEqual(result.offers[0].current, Decimal("0"))
        self.assertEqual(result.offers[0].discount, 100)
        self.assertTrue(result.offers[0].link.endswith("abc%2Bdef%3D"))

    async def test_lookup_health_tracks_schema_failure_and_preserves_last_success(self):
        with patch.object(health, "LOOKUPS", health.SourceHealth()):
            self.fetch.return_value = {"info": {"title": "Hades"}, "deals": []}
            await pricing.lookup_catalog_prices("123")
            previous = health.LOOKUPS.last_success
            self.assertEqual(health.LOOKUPS.outcome, "ok")
            self.fetch.return_value = {"bad": "payload"}
            with self.assertRaises(pricing.PriceSourceError):
                await pricing.lookup_catalog_prices("123")
            self.assertEqual(health.LOOKUPS.outcome, "failed")
            self.assertEqual(health.LOOKUPS.last_success, previous)

    def test_local_matches_ignore_spacing_and_keep_sequels_separate(self):
        choices = [search.GameChoice(n, "steam", n) for n in ("Dark Souls", "Dark Souls II", "Portal")]
        self.assertEqual([c.name for c in search.saved_matches(choices, "darksouls")], ["Dark Souls", "Dark Souls II"])
        self.assertEqual(search.saved_matches(choices, "  "), [])
