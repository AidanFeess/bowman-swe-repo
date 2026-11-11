from decimal import Decimal
from types import SimpleNamespace
import sqlite3
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord import app_commands

import bot
import game_commands as commands
from game_picker import GamePicker
from game_search import GameChoice
import health
import pricing
import watch_db

GAME = GameChoice("Portal 2", "steam", "https://store.steampowered.com/app/620/", steam_id=620)
OTHER = GameChoice("Portal", "steam", "https://store.steampowered.com/app/400/", steam_id=400)


def interaction(admin=False):
    return SimpleNamespace(
        guild_id=1, user=SimpleNamespace(id=2), permissions=discord.Permissions(administrator=admin),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock(), edit_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )


def price():
    return pricing.PriceResult("Portal 2", (pricing.Offer("Steam", Decimal("0"), Decimal("9.99"), GAME.link),))


class RandomTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.i = interaction()
        self.rows = [(GAME.name, GAME.store, GAME.link, 99), (OTHER.name, OTHER.store, OTHER.link, 1)]
        self.list_patch = patch("db.get_server_wishlist", return_value=self.rows)
        self.get_rows = self.list_patch.start()
        self.addCleanup(self.list_patch.stop)
        self.price_patch = patch("game_search.choice_prices", AsyncMock(return_value=price()))
        self.lookup = self.price_patch.start()
        self.addCleanup(self.price_patch.stop)

    async def test_server_selection_is_not_weighted_by_user_count(self):
        with patch("game_commands.random.choice", side_effect=lambda rows: rows[0]) as pick:
            await bot.random_command.callback(self.i)
        self.get_rows.assert_called_once_with(1)
        self.assertEqual(len(pick.call_args.args[0]), 2)
        self.lookup.assert_awaited_once_with(GAME)
        embed = self.i.followup.send.call_args.kwargs["embed"]
        self.assertEqual(embed.title, "Portal 2")
        self.assertIn("Free", embed.fields[0].value)
        self.assertIn(GAME.link, embed.description)

    async def test_chosen_member_queries_only_that_member_in_this_server(self):
        member = MagicMock(spec=discord.Member)
        member.id, member.guild.id, member.display_name = 3, 1, "member"
        with patch("db.get_wishlist", return_value=[self.rows[0][:3]]) as own:
            await bot.random_command.callback(self.i, member)
        own.assert_called_once_with(1, 3)
        self.get_rows.assert_not_called()
        self.assertIn("member", self.i.followup.send.call_args.kwargs["embed"].footer.text)

    async def test_member_from_another_server_is_rejected(self):
        member = MagicMock(spec=discord.Member)
        member.guild.id = 999
        await bot.random_command.callback(self.i, member)
        self.get_rows.assert_not_called()
        self.assertIn("valid member", self.i.response.send_message.call_args.args[0])

    async def test_empty_wishlist_skips_pricing(self):
        self.get_rows.return_value = []
        await bot.random_command.callback(self.i)
        self.lookup.assert_not_awaited()
        self.assertIn("empty", self.i.followup.send.call_args.args[0])

    async def test_price_failure_still_returns_selected_game(self):
        self.lookup.side_effect = pricing.PriceSourceError()
        with patch("game_commands.random.choice", side_effect=lambda rows: rows[0]):
            await bot.random_command.callback(self.i)
        embed = self.i.followup.send.call_args.kwargs["embed"]
        self.assertEqual(embed.title, "Portal 2")
        self.assertIn("temporarily unavailable", embed.fields[0].value)

    async def test_database_failure_has_a_reply(self):
        self.get_rows.side_effect = sqlite3.OperationalError()
        await bot.random_command.callback(self.i)
        self.assertIn("couldn't load", self.i.followup.send.call_args.args[0])


class SelectionCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_wishlist_waits_for_selected_game_and_saves_that_game_only(self):
        i = interaction()
        with patch("game_search.search_games", AsyncMock(return_value=[GAME, OTHER])), \
                patch("db.add_store_game", return_value=True) as save:
            await bot.wishlist.callback(i, "portal")
            save.assert_not_called()
            view = i.followup.send.call_args.kwargs["view"]
            await view.select_value(interaction(), "1")
            save.assert_called_once_with(1, 2, "steam", OTHER.link, "Portal")

    async def test_pullpricing_waits_for_selection_and_uses_its_id(self):
        i = interaction()
        with patch("game_search.search_games", AsyncMock(return_value=[GAME, OTHER])), \
                patch("pricing.lookup_prices", AsyncMock(return_value=price())) as lookup:
            await bot.pullpricing.callback(i, "portal")
            lookup.assert_not_awaited()
            await i.followup.send.call_args.kwargs["view"].select_value(interaction(), "0")
            lookup.assert_awaited_once_with(620)

    async def test_remove_matches_only_own_wishlist_and_removes_selected_full_name(self):
        i = interaction()
        rows = [("Dark Souls", "steam", "one"), ("Dark Souls II", "steam", "two")]
        with patch("db.get_wishlist", return_value=rows) as get, \
                patch("db.remove_game", return_value="Dark Souls II") as remove:
            await bot.remove.callback(i, "darksouls")
            get.assert_called_once_with(1, 2)
            remove.assert_not_called()
            await i.followup.send.call_args.kwargs["view"].select_value(interaction(), "1")
            remove.assert_called_once_with(1, 2, "Dark Souls II")

    async def test_link_wishlist_keeps_existing_path_and_ignores_search_store(self):
        i = interaction()
        with patch("handler.add_to_wishlist", return_value=("added", "Added it")) as add, \
                patch("game_search.search_games", AsyncMock()) as search:
            await bot.wishlist.callback(i, GAME.link, app_commands.Choice(name="GOG", value="gog"))
            add.assert_called_once_with(1, 2, GAME.link, "gog")
            search.assert_not_awaited()

    async def test_invalid_wishlist_link_is_not_searched_or_added(self):
        i = interaction()
        with patch("handler.add_to_wishlist") as add, patch("game_search.search_games", AsyncMock()) as search:
            await bot.wishlist.callback(i, "https://store.steampowered.com.evil.com/app/620/")
        search.assert_not_awaited()
        add.assert_not_called()
        i.response.send_message.assert_awaited_once()


class WatchCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.i = interaction()
        self.service = SimpleNamespace(save=AsyncMock(), remove=AsyncMock(return_value=True))

    async def test_watch_waits_for_choice_and_saves_target_cents(self):
        with patch("game_search.search_games", AsyncMock(return_value=[GAME, OTHER])):
            await commands.add_watch(self.i, self.service, "portal", "19.99")
        self.service.save.assert_not_awaited()
        await self.i.followup.send.call_args.kwargs["view"].select_value(interaction(), "1")
        self.service.save.assert_awaited_once_with(1, 2, OTHER, 1999)
        self.assertIn("daily at 4 PM Central", self.i.followup.send.call_args.args[0])

    async def test_steam_link_is_watched_without_a_name_search(self):
        with patch("pricing.lookup_prices", AsyncMock(return_value=price())), \
                patch("game_search.search_games", AsyncMock()) as search:
            await commands.add_watch(self.i, self.service, GAME.link, "0")
        self.service.save.assert_awaited_once_with(1, 2, GAME, 0)
        search.assert_not_awaited()

    async def test_empty_invalid_price_and_bad_link_never_lookup_or_save(self):
        with patch("game_search.search_games", AsyncMock()) as search, \
                patch("pricing.lookup_prices", AsyncMock()) as lookup:
            for game, price_value in ((" ", "10"), ("Portal", "NaN"), ("Portal", "-1"),
                                      ("Portal", "1.001"), ("https://evil.com/game", "1")):
                await commands.add_watch(self.i, self.service, game, price_value)
        search.assert_not_awaited()
        lookup.assert_not_awaited()
        self.service.save.assert_not_awaited()

    async def test_watch_limit_and_db_failure_are_reported(self):
        with patch("game_search.search_games", AsyncMock(return_value=[GAME])):
            for error, text in ((watch_db.WatchLimitReached(), "25 games"),
                                (sqlite3.OperationalError(), "couldn't save")):
                self.service.save.side_effect = error
                await commands.add_watch(self.i, self.service, "Portal 2", "10")
                self.assertIn(text, self.i.followup.send.call_args.args[0])

    async def test_watchlist_is_private_and_scoped_to_its_owner(self):
        with patch("watch_db.rows", return_value=[{"game": "Portal 2", "target_cents": 999}]) as rows:
            await commands.watchlist(self.i)
        rows.assert_called_once_with(1, 2)
        self.assertTrue(self.i.followup.send.call_args.kwargs["ephemeral"])
        self.assertIn("$9.99", self.i.followup.send.call_args.kwargs["embed"].description)

    async def test_unwatch_selects_only_saved_owned_watch_ids(self):
        rows = [{"id": n, "game": name, "store": "steam", "link": "url", "steam_id": n, "catalog_id": None}
                for n, name in ((101, "Dark Souls"), (102, "Dark Souls II"))]
        with patch("watch_db.rows", return_value=rows) as get:
            await commands.unwatch(self.i, self.service, "darksouls")
        get.assert_called_once_with(1, 2)
        self.service.remove.assert_not_awaited()
        await self.i.followup.send.call_args.kwargs["view"].select_value(interaction(), "1")
        self.service.remove.assert_awaited_once_with(1, 2, 102)

    async def test_dm_commands_reject_before_database_or_search(self):
        self.i.guild_id = None
        with patch("watch_db.rows") as rows, patch("game_search.search_games", AsyncMock()) as search:
            await commands.add_watch(self.i, self.service, "Portal 2", "10")
            await commands.watchlist(self.i)
            await commands.unwatch(self.i, self.service, "Portal 2")
            await commands.random_pick(self.i)
        rows.assert_not_called()
        search.assert_not_awaited()
        self.assertEqual(self.i.response.send_message.await_count, 4)


class StatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_flag_is_required_at_runtime_and_in_registration(self):
        i = interaction()
        i.permissions = discord.Permissions(manage_guild=True)
        with patch("game_commands._database_status") as read:
            await bot.status.callback(i)
        read.assert_not_called()
        i.response.send_message.assert_awaited_once_with("You need Administrator permission to use this command.", ephemeral=True)
        self.assertTrue(bot.status.default_permissions.administrator)

    async def test_admin_gets_private_health_without_credentials_or_other_server_data(self):
        i = interaction(admin=True)
        client = SimpleNamespace(latency=0.025, is_ready=lambda: True,
                                 watches=SimpleNamespace(last_outcome="ok"))
        with patch("health.version", return_value="abcdef123456"), \
                patch("game_commands._database_status", return_value="ok • 2 wishlist entries • 1 watches in this server") as read:
            await commands.admin_status(i, client)
        read.assert_called_once_with(1)
        kwargs = i.followup.send.call_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        embed = kwargs["embed"]
        values = "\n".join(f.value for f in embed.fields)
        self.assertIn("abcdef123456", values)
        self.assertIn("25 ms", values)
        self.assertNotIn("DISCORD_TOKEN", values)

    async def test_database_failure_does_not_hide_other_status(self):
        i = interaction(admin=True)
        client = SimpleNamespace(latency=float("nan"), is_ready=lambda: False,
                                 watches=SimpleNamespace(last_outcome="not checked"))
        with patch("game_commands._database_status", side_effect=sqlite3.OperationalError()):
            await commands.admin_status(i, client)
        values = "\n".join(f.value for f in i.followup.send.call_args.kwargs["embed"].fields)
        self.assertIn("unavailable", values)
        self.assertIn("not ready", values)

    async def test_status_in_dm_is_rejected_even_for_admin(self):
        i = interaction(admin=True)
        i.guild_id = None
        await bot.status.callback(i)
        i.response.send_message.assert_awaited_once_with(pricing.SERVER_ONLY, ephemeral=True)

    def test_all_new_commands_appear_in_help(self):
        text = bot.build_help_embed().description
        for name in ("random", "watch", "watchlist", "unwatch", "status"):
            self.assertIn("/" + name, text)

    def test_source_health_does_not_erase_last_success_after_a_failure(self):
        with patch.dict(health.SOURCES, {"Steam": health.SourceHealth()}):
            health.record("Steam", True)
            previous = health.SOURCES["Steam"].last_success
            health.record("Steam", False)
            self.assertEqual(health.SOURCES["Steam"].last_success, previous)
            self.assertEqual(health.SOURCES["Steam"].outcome, "failed")
