import asyncio
import copy
from decimal import Decimal
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

import pricing


APP_ID = 292030
STEAM = {str(APP_ID): {"success": True, "data": {
    "name": "The Witcher 3: Wild Hunt", "steam_appid": APP_ID, "is_free": False,
    "price_overview": {"currency": "USD", "initial": 3999, "final": 3999},
}}}
GAMES = [{"gameID": "100", "steamAppID": str(APP_ID)}]
DEALS = {"info": {"steamAppID": str(APP_ID)}, "deals": [
    {"storeID": "7", "dealID": "abc%2Bdef%3D", "price": "9.99", "retailPrice": "39.99"},
    {"storeID": "25", "dealID": "epic", "price": "0.00", "retailPrice": "39.99"},
]}


class LinkTests(unittest.TestCase):
    def test_valid_links(self):
        for link in (
            "https://store.steampowered.com/app/292030",
            " https://store.steampowered.com/app/292030/The_Witcher_3/ ",
            "http://store.steampowered.com/app/292030/?l=english#reviews",
            "https://STORE.STEAMPOWERED.COM/app/292030/",
        ):
            with self.subTest(link=link):
                self.assertEqual(pricing.parse_steam_link(link), APP_ID)

    def test_invalid_links(self):
        for link in (
            "", None, "The Witcher 3", "store.steampowered.com/app/292030/",
            "https://store.steampowered.com.evil.com/app/292030/",
            "https://evil.com/store.steampowered.com/app/292030/",
            "https://store.steampowered.com@evil.com/app/292030/",
            "https://user@store.steampowered.com/app/292030/",
            "https://store.steampowered.com:443/app/292030/",
            "https://store.steampowered.com:bad/app/292030/",
            "https://store.steampowered.com/app/292030extra",
            "https://store.steampowered.com/sub/292030/",
            "https://store.steampowered.com/app/0/",
            "https://store.steampowered.com/app/999999999999999/",
            "https://store.steam\npowered.com/app/292030/",
            "https://store.steampowered.com/app/292030/ extra",
            "https://store.epicgames.com/en-US/p/the-witcher-3",
            "file://store.steampowered.com/app/292030/",
        ):
            with self.subTest(link=link):
                self.assertIsNone(pricing.parse_steam_link(link))


class PricingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.steam = copy.deepcopy(STEAM)
        self.deals = copy.deepcopy(DEALS)
        self.fetch = AsyncMock(side_effect=[self.steam, GAMES, self.deals])
        patcher = patch("pricing._get_json", self.fetch)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_exact_game_matching_and_all_selected_stores(self):
        result = await pricing.lookup_prices(APP_ID)
        self.assertEqual(result.name, "The Witcher 3: Wild Hunt")
        self.assertEqual([p.store for p in result.offers], ["Steam", "Epic Games Store", "GOG"])
        self.assertEqual(result.offers[2].current, Decimal("9.99"))
        self.assertEqual(result.offers[2].original, Decimal("39.99"))
        self.assertEqual(result.offers[2].discount, 75)
        self.assertTrue(result.offers[2].link.endswith("dealID=abc%2Bdef%3D"))
        self.assertEqual(self.fetch.call_args_list[1].args[2], {"steamAppID": APP_ID})
        self.assertEqual(self.fetch.call_args_list[2].args[2], {"id": "100"})

    async def test_no_discount(self):
        offer = (await pricing.lookup_prices(APP_ID)).offers[0]
        self.assertEqual(offer.current, offer.original)
        self.assertEqual(offer.discount, 0)
        self.assertIn("Discount: 0%", pricing.format_offer(offer))

    async def test_temporary_giveaway(self):
        offer = (await pricing.lookup_prices(APP_ID)).offers[1]
        self.assertIn("Current price: **Free**", pricing.format_offer(offer))
        self.assertIn("Original price: $39.99", pricing.format_offer(offer))
        self.assertEqual(offer.discount, 100)

    async def test_permanently_free_steam_game(self):
        data = self.steam[str(APP_ID)]["data"]
        del data["price_overview"]
        data["is_free"] = True
        self.fetch.side_effect = [self.steam, []]
        offer = (await pricing.lookup_prices(APP_ID)).offers[0]
        self.assertEqual(offer.current, Decimal("0"))
        self.assertEqual(offer.original, Decimal("0"))
        self.assertEqual(offer.discount, 0)

    async def test_unknown_game_has_no_prices(self):
        self.fetch.side_effect = [{str(APP_ID): {"success": False}}]
        self.assertEqual((await pricing.lookup_prices(APP_ID)).offers, ())
        self.assertEqual(self.fetch.await_count, 1)

    async def test_success_without_any_prices(self):
        del self.steam[str(APP_ID)]["data"]["price_overview"]
        self.deals["deals"] = []
        self.assertEqual((await pricing.lookup_prices(APP_ID)).offers, ())

    async def test_missing_price_is_not_free(self):
        self.deals["deals"][0]["price"] = None
        result = await pricing.lookup_prices(APP_ID)
        self.assertEqual([p.store for p in result.offers], ["Steam", "Epic Games Store"])

    async def test_bad_money_is_omitted(self):
        for value in ("NaN", "Infinity", "-1", "bad", True, "1000000000000", "100"):
            with self.subTest(value=value):
                self.deals["deals"][0]["price"] = value
                self.fetch.side_effect = [self.steam, GAMES, self.deals]
                result = await pricing.lookup_prices(APP_ID)
                self.assertNotIn("GOG", [p.store for p in result.offers])

    async def test_wrong_search_match_is_not_used(self):
        self.fetch.side_effect = [self.steam, [{"gameID": "100", "steamAppID": "123"}]]
        self.assertEqual(len((await pricing.lookup_prices(APP_ID)).offers), 1)
        self.assertEqual(self.fetch.await_count, 2)

    async def test_ambiguous_editions_are_not_guessed(self):
        self.fetch.side_effect = [self.steam, GAMES + [{"gameID": "101", "steamAppID": str(APP_ID)}]]
        self.assertEqual(len((await pricing.lookup_prices(APP_ID)).offers), 1)

    async def test_details_with_wrong_app_id_are_not_used(self):
        self.deals["info"]["steamAppID"] = "123"
        self.assertEqual(len((await pricing.lookup_prices(APP_ID)).offers), 1)

    async def test_unselected_stores_and_duplicate_offers(self):
        self.deals["deals"] += [
            {"storeID": "2", "dealID": "other", "price": "1", "retailPrice": "40"},
            {"storeID": "7", "dealID": "expensive", "price": "20", "retailPrice": "40"},
            {"storeID": "1", "dealID": "stale", "price": "2", "retailPrice": "40"},
        ]
        result = await pricing.lookup_prices(APP_ID)
        self.assertEqual(len(result.offers), 3)
        self.assertEqual(result.offers[0].current, Decimal("39.99"))
        self.assertEqual(result.offers[2].current, Decimal("9.99"))

    async def test_failure_at_any_source_is_unavailable(self):
        for stage in range(3):
            for error in (aiohttp.ClientConnectionError(), ValueError("bad JSON"), asyncio.TimeoutError()):
                with self.subTest(stage=stage, error=type(error).__name__):
                    self.fetch.side_effect = [self.steam, GAMES, self.deals][:stage] + [error]
                    with self.assertRaises(pricing.PriceSourceError):
                        await pricing.lookup_prices(APP_ID)

    async def test_invalid_response_shapes_are_source_failures(self):
        for responses in ([{}], [self.steam, {}], [self.steam, GAMES, {}]):
            with self.subTest(responses=responses):
                self.fetch.side_effect = responses
                with self.assertRaises(pricing.PriceSourceError):
                    await pricing.lookup_prices(APP_ID)

    async def test_ten_second_budget_covers_entire_lookup_and_cancels_io(self):
        self.assertEqual(pricing.LOOKUP_TIMEOUT, 10)
        responses = iter([self.steam, GAMES, self.deals])
        cancelled = asyncio.Event()

        async def slow_fetch(*args):
            try:
                await asyncio.sleep(0.04)
                return next(responses)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        self.fetch.side_effect = slow_fetch
        start = time.monotonic()
        # Each call fits in 0.06 s, but their combined time does not.
        with patch("pricing.LOOKUP_TIMEOUT", 0.06):
            with self.assertRaises(pricing.PriceSourceError):
                await pricing.lookup_prices(APP_ID)
        self.assertTrue(cancelled.is_set())
        self.assertLess(time.monotonic() - start, 0.5)


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_status_checked_before_json(self):
        response = MagicMock()
        response.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=503
        )
        response.json = AsyncMock()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=response)
        context.__aexit__ = AsyncMock(return_value=False)
        session = MagicMock()
        session.get.return_value = context
        with self.assertRaises(aiohttp.ClientResponseError):
            await pricing._get_json(session, pricing.GAMES_URL, {"steamAppID": APP_ID})
        response.json.assert_not_awaited()
        context.__aexit__.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
