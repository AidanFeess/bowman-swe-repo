import sqlite3
import tempfile
import unittest
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp

import database
import db
import digest
import pricing
from test_digest import FakeServer, link_for, sale

EPIC_LINK = "https://store.epicgames.com/en-US/p/borderlands-3"
GOG_LINK = "https://www.gog.com/en/game/cyberpunk_2077"


def found(*games):
    """CheapShark's answer to a search by title."""
    return [{"gameID": gid, "external": title} for gid, title in games]


def deals(*offers, title=None):
    """CheapShark's answer for one game. Each offer is (store ID, price, regular price)."""
    return {
        "info": {"title": title} if title else {},
        "deals": [
            {"storeID": store_id, "dealID": f"deal{store_id}%2B", "price": price, "retailPrice": retail}
            for store_id, price, retail in offers
        ],
    }


def store_sale(store="Epic Games Store", name="Borderlands 3", current="9.99", original="39.99"):
    offer = pricing.Offer(store, Decimal(current), Decimal(original), "https://www.cheapshark.com/redirect?dealID=x")
    return pricing.PriceResult(name, (offer,))


class StorePricingTests(unittest.IsolatedAsyncioTestCase):

    async def lookup(self, name, store, *responses):
        fetch = AsyncMock(side_effect=list(responses))
        with patch("pricing._get_json", fetch):
            return await pricing.lookup_store_prices(name, store), fetch

    async def test_epic_price_is_found(self):
        result, fetch = await self.lookup(
            "Borderlands 3", "epic",
            found(("100", "Borderlands 3")),
            deals(("1", "19.99", "59.99"), ("25", "9.99", "39.99"), title="Borderlands 3"),
        )
        self.assertEqual(result.name, "Borderlands 3")
        self.assertEqual(len(result.offers), 1)
        offer = result.offers[0]
        self.assertEqual((offer.store, offer.current, offer.original), ("Epic Games Store", Decimal("9.99"), Decimal("39.99")))
        self.assertEqual(offer.discount, 75)
        self.assertEqual(offer.link, "https://www.cheapshark.com/redirect?dealID=deal25%2B")
        self.assertEqual(fetch.call_args_list[0].args[1:], (pricing.GAMES_URL, {"title": "Borderlands 3", "limit": 20}))
        self.assertEqual(fetch.call_args_list[1].args[1:], (pricing.GAMES_URL, {"id": "100"}))

    async def test_gog_price_is_found(self):
        result, _ = await self.lookup(
            "Cyberpunk 2077", "gog",
            found(("200", "Cyberpunk 2077")),
            deals(("25", "29.99", "59.99"), ("7", "17.99", "59.99")),
        )
        self.assertEqual([o.store for o in result.offers], ["GOG"])
        self.assertEqual(result.offers[0].current, Decimal("17.99"))

    async def test_punctuation_and_case_do_not_matter(self):
        # Names made from a pasted link have no colon, but the store title does
        result, _ = await self.lookup(
            "The Witcher 3 Wild Hunt", "gog",
            found(("300", "The Witcher 3: Wild Hunt")),
            deals(("7", "7.99", "39.99"), title="The Witcher 3: Wild Hunt"),
        )
        self.assertEqual(result.name, "The Witcher 3: Wild Hunt")
        self.assertEqual(len(result.offers), 1)

    async def test_a_similar_title_is_a_different_game(self):
        result, fetch = await self.lookup("Hades", "gog", found(("1", "Hades II"), ("2", "Hades Star")))
        self.assertEqual(result.offers, ())
        self.assertEqual(fetch.await_count, 1)  # no game matched, so no price lookups

    async def test_game_not_sold_on_that_store_has_no_offer(self):
        result, _ = await self.lookup("Portal 2", "epic", found(("1", "Portal 2")), deals(("1", "1.99", "9.99")))
        self.assertEqual(result.offers, ())

    async def test_cheapest_of_same_title_games_wins(self):
        result, _ = await self.lookup(
            "Doom", "epic",
            found(("1", "DOOM"), ("2", "Doom")),
            deals(("25", "19.99", "19.99")),
            deals(("25", "4.99", "19.99")),
        )
        self.assertEqual(result.offers[0].current, Decimal("4.99"))

    async def test_a_price_above_the_regular_price_is_not_used(self):
        result, _ = await self.lookup("Doom", "epic", found(("1", "Doom")), deals(("25", "30.00", "20.00")))
        self.assertEqual(result.offers, ())

    async def test_no_search_results(self):
        result, fetch = await self.lookup("asdfghjkl", "gog", [])
        self.assertEqual(result.offers, ())
        self.assertEqual(fetch.await_count, 1)

    async def test_bad_responses_are_a_source_error(self):
        bad_searches = (None, {}, [None], [{"gameID": "x", "external": "Doom"}], [{"gameID": "1", "external": 5}])
        for first in bad_searches:
            with self.subTest(first=first):
                with self.assertRaises(pricing.PriceSourceError):
                    await self.lookup("Doom", "epic", first)
        for second in (None, [], {"deals": None}, {"deals": [None]}):
            with self.subTest(second=second):
                with self.assertRaises(pricing.PriceSourceError):
                    await self.lookup("Doom", "epic", found(("1", "Doom")), second)

    async def test_web_errors_are_a_source_error(self):
        with patch("pricing._get_json", AsyncMock(side_effect=aiohttp.ClientError("down"))):
            with self.assertRaises(pricing.PriceSourceError):
                await pricing.lookup_store_prices("Doom", "epic")

    async def test_empty_name_makes_no_request(self):
        with patch("pricing._get_json", AsyncMock()) as fetch:
            result = await pricing.lookup_store_prices("   ", "epic")
        self.assertEqual(result.offers, ())
        fetch.assert_not_awaited()

    async def test_unsupported_store_is_refused(self):
        with self.assertRaises(ValueError):
            await pricing.lookup_store_prices("Portal 2", "steam")


def add_store_wish(user_id, store, link, game, guild="1"):
    with closing(sqlite3.connect(db.DATABASE_PATH)) as conn:
        with conn:
            conn.execute(
                "INSERT INTO wishlist (discord_guild_id, discord_user_id, game, store, link) VALUES (?, ?, ?, ?, ?)",
                (guild, str(user_id), game, store, link),
            )


class StoreDigestTests(unittest.IsolatedAsyncioTestCase):

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
        self.service = digest.Digest(MagicMock())

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    async def run_digest(self, server, store_lookup=None, steam_lookup=None, day="2026-10-29"):
        report = AsyncMock()
        store_lookup = store_lookup or AsyncMock(return_value=store_sale())
        steam_lookup = steam_lookup or AsyncMock(return_value=sale())
        with patch.object(digest, "current_day", return_value=day), \
             patch.object(pricing, "lookup_store_prices", store_lookup), \
             patch.object(pricing, "lookup_prices", steam_lookup), \
             patch.object(digest, "get_steam_sale_end", AsyncMock(return_value=None)):
            await self.service.generate_digest(server, report)
        return report, store_lookup, steam_lookup

    def sent_embeds(self, server, user_id):
        return [e for call in server.members[user_id].send.await_args_list for e in call.kwargs["embeds"]]

    async def test_epic_game_on_sale_is_in_the_digest(self):
        add_store_wish(10, "epic", EPIC_LINK, "Borderlands 3")
        server = FakeServer({10})
        report, store_lookup, steam_lookup = await self.run_digest(server)
        store_lookup.assert_awaited_once_with("Borderlands 3", "epic")
        steam_lookup.assert_not_awaited()
        embed = self.sent_embeds(server, 10)[0]
        self.assertEqual(embed.title, "Borderlands 3")
        self.assertEqual(embed.fields[0].name, "Epic Games Store")
        self.assertIn("$9.99", embed.fields[0].value)
        self.assertIn("Discount: 75%", embed.fields[0].value)
        self.assertNotIn("Sale end time", embed.fields[0].value)  # CheapShark has no end dates
        self.assertIn("Sent a private message to 1 user(s).", report.await_args.args[0])

    async def test_gog_game_on_sale_is_in_the_digest(self):
        add_store_wish(10, "gog", GOG_LINK, "Cyberpunk 2077")
        server = FakeServer({10})
        lookup = AsyncMock(return_value=store_sale("GOG", "Cyberpunk 2077", "17.99", "59.99"))
        await self.run_digest(server, store_lookup=lookup)
        lookup.assert_awaited_once_with("Cyberpunk 2077", "gog")
        self.assertEqual(self.sent_embeds(server, 10)[0].fields[0].name, "GOG")

    async def test_steam_epic_and_gog_games_arrive_together(self):
        add_store_wish(10, "steam", link_for(620), "Portal 2")
        add_store_wish(10, "epic", EPIC_LINK, "Borderlands 3")
        add_store_wish(10, "gog", GOG_LINK, "Cyberpunk 2077")
        server = FakeServer({10})
        lookup = AsyncMock(side_effect=lambda name, store: store_sale(
            "GOG" if store == "gog" else "Epic Games Store", name))
        await self.run_digest(server, store_lookup=lookup)
        server.members[10].send.assert_awaited_once()
        self.assertEqual({e.title for e in self.sent_embeds(server, 10)},
                         {"Portal 2", "Borderlands 3", "Cyberpunk 2077"})

    async def test_game_not_on_sale_sends_nothing(self):
        add_store_wish(10, "epic", EPIC_LINK, "Borderlands 3")
        server = FakeServer({10})
        report, _, _ = await self.run_digest(
            server, store_lookup=AsyncMock(return_value=store_sale(current="39.99", original="39.99")))
        server.members[10].send.assert_not_called()
        self.assertIn("No wishlist games are on sale", report.await_args.args[0])

    async def test_game_with_no_price_counts_as_unavailable(self):
        add_store_wish(10, "gog", GOG_LINK, "Cyberpunk 2077")
        server = FakeServer({10})
        report, _, _ = await self.run_digest(
            server, store_lookup=AsyncMock(return_value=pricing.PriceResult("Cyberpunk 2077")))
        server.members[10].send.assert_not_called()
        self.assertIn("Prices were unavailable for 1 game(s).", report.await_args.args[0])

    async def test_price_service_failure_does_not_stop_other_games(self):
        add_store_wish(10, "epic", EPIC_LINK, "Borderlands 3")
        add_store_wish(10, "steam", link_for(620), "Portal 2")
        server = FakeServer({10})
        report, _, _ = await self.run_digest(
            server, store_lookup=AsyncMock(side_effect=pricing.PriceSourceError("down")))
        self.assertEqual([e.title for e in self.sent_embeds(server, 10)], ["Portal 2"])
        self.assertIn("Prices were unavailable for 1 game(s).", report.await_args.args[0])

    async def test_same_day_second_run_sends_nothing(self):
        add_store_wish(10, "epic", EPIC_LINK, "Borderlands 3")
        server = FakeServer({10})
        await self.run_digest(server)
        report, _, _ = await self.run_digest(server)
        self.assertEqual(server.members[10].send.await_count, 1)
        self.assertIn("1 user(s) were already messaged today.", report.await_args.args[0])

    async def test_next_day_sends_again_while_still_on_sale(self):
        add_store_wish(10, "gog", GOG_LINK, "Cyberpunk 2077")
        server = FakeServer({10})
        await self.run_digest(server, day="2026-10-29")
        await self.run_digest(server, day="2026-10-30")
        self.assertEqual(server.members[10].send.await_count, 2)

    async def test_the_user_count_includes_everyone_who_wants_the_game(self):
        add_store_wish(10, "epic", EPIC_LINK, "Borderlands 3")
        add_store_wish(11, "epic", EPIC_LINK, "Borderlands 3")
        server = FakeServer({10, 11})
        report, store_lookup, _ = await self.run_digest(server)
        store_lookup.assert_awaited_once()  # one price lookup for both users
        self.assertIn("2 user(s)", self.sent_embeds(server, 10)[0].description)
        server.members[11].send.assert_awaited_once()

    async def test_other_servers_games_are_not_used(self):
        add_store_wish(11, "epic", EPIC_LINK, "Borderlands 3", guild="2")
        server = FakeServer({11})
        report, store_lookup, _ = await self.run_digest(server)
        store_lookup.assert_not_awaited()
        server.members[11].send.assert_not_called()

    async def test_manual_digest_includes_epic_and_gog_games(self):
        add_store_wish(10, "epic", EPIC_LINK, "Borderlands 3")
        server = FakeServer({10})
        interaction = MagicMock()
        interaction.guild = server
        interaction.user.id = 10
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        with patch.object(digest, "current_day", return_value="2026-10-29"), \
             patch.object(pricing, "lookup_store_prices", AsyncMock(return_value=store_sale())):
            await self.service.manual_digest(interaction)
        server.members[10].send.assert_awaited_once()
        self.assertIn("1 game(s) on sale", interaction.followup.send.await_args.args[0])


if __name__ == "__main__":
    unittest.main()