import datetime
import sqlite3
import tempfile
import unittest
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord

import database
import db
import digest
import pricing


def link_for(app_id):
    return f"https://store.steampowered.com/app/{app_id}/"


def sale(app_id=620, name="Portal 2", current="4.99", original="9.99"):
    offer = pricing.Offer("Steam", Decimal(current), Decimal(original), link_for(app_id))
    return pricing.PriceResult(name, (offer,))


def add_wish(user_id, app_id=620, game="Portal 2"):
    with closing(sqlite3.connect(db.DATABASE_PATH)) as conn:
        with conn:
            conn.execute(
                "INSERT INTO wishlist (discord_user_id, game, store, link) VALUES (?, ?, 'steam', ?)",
                (str(user_id), game, link_for(app_id)),
            )


class FakeServer:
    """A server whose members are known by id, each with a send() we can inspect."""

    def __init__(self, member_ids):
        self.id = 1
        self.members = {}
        for user_id in member_ids:
            member = MagicMock()
            member.bot = False
            member.send = AsyncMock()
            self.members[user_id] = member
        self.get_member = MagicMock(side_effect=lambda user_id: self.members.get(user_id))
        self.fetch_member = AsyncMock(
            side_effect=discord.NotFound(MagicMock(status=404), "not found")
        )


def forbidden():
    return discord.Forbidden(MagicMock(status=403), "Cannot send messages to this user")


class TestDigest(unittest.IsolatedAsyncioTestCase):
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

    async def run_digest(self, server, lookup=None, day="2026-10-29"):
        report = AsyncMock()
        lookup = lookup or AsyncMock(return_value=sale())
        with patch.object(digest, "current_day", return_value=day), \
             patch.object(pricing, "lookup_prices", lookup):
            await self.service.generate_digest(server, report)
        return report

    def report_text(self, report):
        return report.await_args_list[-1].args[0]

    async def test_user_gets_a_dm_with_the_price(self):
        add_wish(10)
        server = FakeServer({10})
        report = await self.run_digest(server)
        member = server.members[10]
        member.send.assert_awaited_once()
        embeds = member.send.await_args.kwargs["embeds"]
        self.assertEqual(len(embeds), 1)
        self.assertEqual(embeds[0].title, "Portal 2")
        self.assertIn("$4.99", embeds[0].fields[0].value)
        self.assertIn("Sent a private message to 1 user(s).", self.report_text(report))

    async def test_same_day_second_run_sends_nothing(self):
        add_wish(10)
        server = FakeServer({10})
        await self.run_digest(server)
        report = await self.run_digest(server)
        self.assertEqual(server.members[10].send.await_count, 1)
        self.assertIn("1 user(s) were already messaged today.", self.report_text(report))

    async def test_next_day_sends_again_while_still_on_sale(self):
        add_wish(10)
        server = FakeServer({10})
        await self.run_digest(server, day="2026-10-29")
        await self.run_digest(server, day="2026-10-30")
        self.assertEqual(server.members[10].send.await_count, 2)

    async def test_game_not_on_sale_sends_nothing(self):
        add_wish(10)
        server = FakeServer({10})
        report = await self.run_digest(
            server, lookup=AsyncMock(return_value=sale(current="9.99", original="9.99"))
        )
        server.members[10].send.assert_not_called()
        self.assertIn("No wishlist games are on sale", self.report_text(report))

    async def test_permanently_free_game_is_not_a_sale(self):
        add_wish(10)
        server = FakeServer({10})
        await self.run_digest(
            server, lookup=AsyncMock(return_value=sale(current="0", original="0"))
        )
        server.members[10].send.assert_not_called()

    async def test_each_user_gets_only_their_own_games(self):
        add_wish(10, 620, "Portal 2")
        add_wish(11, 730, "Counter-Strike 2")

        async def lookup(app_id):
            return sale(app_id, {620: "Portal 2", 730: "Counter-Strike 2"}[app_id])

        server = FakeServer({10, 11})
        await self.run_digest(server, lookup=lookup)
        titles_10 = [e.title for e in server.members[10].send.await_args.kwargs["embeds"]]
        titles_11 = [e.title for e in server.members[11].send.await_args.kwargs["embeds"]]
        self.assertEqual(titles_10, ["Portal 2"])
        self.assertEqual(titles_11, ["Counter-Strike 2"])

    async def test_two_games_arrive_in_one_message(self):
        add_wish(10, 620, "Portal 2")
        add_wish(10, 730, "Counter-Strike 2")
        lookup = AsyncMock(side_effect=lambda app_id: sale(app_id, f"Game {app_id}"))
        server = FakeServer({10})
        await self.run_digest(server, lookup=lookup)
        server.members[10].send.assert_awaited_once()
        self.assertEqual(len(server.members[10].send.await_args.kwargs["embeds"]), 2)

    async def test_many_games_are_split_into_several_messages(self):
        for app_id in range(1, 8):
            add_wish(10, app_id, f"Game {app_id}")
        lookup = AsyncMock(side_effect=lambda app_id: sale(app_id, f"Game {app_id}"))
        server = FakeServer({10})
        await self.run_digest(server, lookup=lookup)
        sizes = [len(c.kwargs["embeds"]) for c in server.members[10].send.await_args_list]
        self.assertEqual(sizes, [5, 2])

    async def test_new_user_is_messaged_even_if_another_already_was(self):
        add_wish(10)
        server = FakeServer({10, 11})
        await self.run_digest(server)
        add_wish(11)
        await self.run_digest(server)
        self.assertEqual(server.members[10].send.await_count, 1)
        self.assertEqual(server.members[11].send.await_count, 1)
        embed = server.members[11].send.await_args.kwargs["embeds"][0]
        self.assertIn("2 user(s)", embed.description)

    async def test_users_outside_the_server_are_not_messaged(self):
        add_wish(10)
        add_wish(99)
        server = FakeServer({10})
        await self.run_digest(server)
        server.members[10].send.assert_awaited_once()
        server.fetch_member.assert_awaited_once_with(99)

    async def test_closed_dms_are_skipped_and_retried_later(self):
        add_wish(10)
        add_wish(11)
        server = FakeServer({10, 11})
        server.members[10].send.side_effect = forbidden()
        report = await self.run_digest(server)
        self.assertIn("1 user(s) have private messages turned off.", self.report_text(report))
        self.assertIn("Sent a private message to 1 user(s).", self.report_text(report))
        server.members[11].send.assert_awaited_once()

        server.members[10].send.side_effect = None  # the user turns DMs back on
        await self.run_digest(server)
        self.assertEqual(server.members[10].send.await_count, 2)
        self.assertEqual(server.members[11].send.await_count, 1)

    async def test_other_discord_errors_do_not_stop_the_digest(self):
        add_wish(10)
        add_wish(11)
        server = FakeServer({10, 11})
        server.members[10].send.side_effect = discord.HTTPException(MagicMock(status=500), "boom")
        report = await self.run_digest(server)
        server.members[11].send.assert_awaited_once()
        self.assertIn("1 message(s) failed to send.", self.report_text(report))

    async def test_no_wishlist_games_message(self):
        report = await self.run_digest(FakeServer({10}))
        self.assertIn("No supported wishlist games", self.report_text(report))

    def manual(self, server, user_id):
        interaction = MagicMock()
        interaction.guild = server
        interaction.user.id = user_id
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        return interaction

    async def run_manual(self, server, user_id, lookup=None, day="2026-10-29"):
        interaction = self.manual(server, user_id)
        with patch.object(digest, "current_day", return_value=day), \
             patch.object(pricing, "lookup_prices", lookup or AsyncMock(return_value=sale())):
            await self.service.manual_digest(interaction)
        return interaction

    def manual_text(self, interaction):
        return interaction.followup.send.await_args.args[0]

    async def test_manual_digest_messages_only_the_person_who_ran_it(self):
        add_wish(10)
        add_wish(11)
        server = FakeServer({10, 11})
        interaction = await self.run_manual(server, 10)
        server.members[10].send.assert_awaited_once()
        server.members[11].send.assert_not_called()
        self.assertIn("Sent you a private message with 1 game(s) on sale.", self.manual_text(interaction))
        self.assertTrue(interaction.followup.send.await_args.kwargs["ephemeral"])

    async def test_manual_digest_only_checks_the_callers_games(self):
        add_wish(10, 620, "Portal 2")
        add_wish(11, 730, "Counter-Strike 2")
        server = FakeServer({10, 11})
        lookup = AsyncMock(side_effect=lambda app_id: sale(app_id, f"Game {app_id}"))
        await self.run_manual(server, 10, lookup=lookup)
        lookup.assert_awaited_once_with(620)
        titles = [e.title for e in server.members[10].send.await_args.kwargs["embeds"]]
        self.assertEqual(titles, ["Game 620"])

    async def test_manual_digest_works_every_time_it_is_run(self):
        add_wish(10)
        server = FakeServer({10})
        await self.run_manual(server, 10)
        await self.run_manual(server, 10)
        self.assertEqual(server.members[10].send.await_count, 2)

    async def test_manual_digest_stops_the_daily_run_from_repeating_it(self):
        add_wish(10)
        server = FakeServer({10})
        await self.run_manual(server, 10)
        await self.run_digest(server)
        self.assertEqual(server.members[10].send.await_count, 1)

    async def test_manual_digest_says_so_when_nothing_is_on_sale(self):
        add_wish(10)
        server = FakeServer({10})
        interaction = await self.run_manual(
            server, 10, lookup=AsyncMock(return_value=sale(current="9.99", original="9.99"))
        )
        server.members[10].send.assert_not_called()
        self.assertIn("None of your wishlist games are on sale right now.", self.manual_text(interaction))

    async def test_manual_digest_tells_a_user_with_closed_dms(self):
        add_wish(10)
        server = FakeServer({10})
        server.members[10].send.side_effect = forbidden()
        interaction = await self.run_manual(server, 10)
        self.assertIn("direct messages", self.manual_text(interaction))

    async def test_manual_digest_with_an_empty_wishlist(self):
        add_wish(11)
        server = FakeServer({10, 11})
        interaction = await self.run_manual(server, 10)
        server.members[10].send.assert_not_called()
        self.assertIn("/wishlist", self.manual_text(interaction))

    async def test_manual_command_replies_privately(self):
        add_wish(10)
        server = FakeServer({10})
        interaction = MagicMock()
        interaction.guild = server
        interaction.user.id = 10
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        with patch.object(digest, "current_day", return_value="2026-10-29"), \
             patch.object(pricing, "lookup_prices", AsyncMock(return_value=sale())):
            await self.service.manual_digest(interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        self.assertTrue(interaction.followup.send.await_args.kwargs["ephemeral"])
        server.members[10].send.assert_awaited_once()

    async def test_manual_command_in_a_dm_is_refused(self):
        interaction = MagicMock()
        interaction.guild = None
        interaction.response.send_message = AsyncMock()
        await self.service.manual_digest(interaction)
        interaction.response.send_message.assert_awaited_once()


class TestRegister(unittest.TestCase):
    def register(self, env):
        bot = MagicMock()
        with patch.dict("os.environ", env, clear=True), \
             patch.object(type(digest.Digest(MagicMock()).daily_digest), "start", lambda self: None):
            service = digest.Digest(bot)
            service.register()
        return bot, service

    def test_command_is_added_and_no_schedule_without_a_server(self):
        bot, service = self.register({})
        bot.tree.add_command.assert_called_once()
        self.assertEqual(service.command.name, "digest")
        self.assertIsNone(service.guild_id)

    def test_default_schedule_is_4_pm_central_through_daylight_saving(self):
        bot, service = self.register({"DIGEST_GUILD_ID": "123"})
        self.assertEqual(service.guild_id, 123)
        run_time = service.daily_digest.time[0]
        self.assertEqual((run_time.hour, run_time.minute), (16, 0))
        self.assertEqual(run_time.tzinfo.key, "America/Chicago")
        summer = datetime.datetime(2026, 7, 1, tzinfo=run_time.tzinfo).replace(hour=16)
        winter = datetime.datetime(2026, 12, 1, tzinfo=run_time.tzinfo).replace(hour=16)
        utc = datetime.timezone.utc
        self.assertEqual((summer.astimezone(utc).hour, winter.astimezone(utc).hour), (21, 22))

    def test_time_can_be_changed_in_settings(self):
        bot, service = self.register({"DIGEST_GUILD_ID": "123", "DIGEST_TIME": "14:30"})
        run_time = service.daily_digest.time[0]
        self.assertEqual((run_time.hour, run_time.minute), (14, 30))

    def test_bad_timezone_does_not_stop_the_bot(self):
        bot, service = self.register({"DIGEST_GUILD_ID": "123", "DIGEST_TIMEZONE": "Not/AZone"})
        bot.tree.add_command.assert_called_once()
        self.assertIsNone(service.guild_id)

    def test_bad_server_id_does_not_stop_the_bot(self):
        bot, service = self.register({"DIGEST_GUILD_ID": "abc"})
        bot.tree.add_command.assert_called_once()
        self.assertIsNone(service.guild_id)

    def test_bad_time_does_not_stop_the_bot(self):
        bot, service = self.register({"DIGEST_GUILD_ID": "123", "DIGEST_TIME": "4pm"})
        bot.tree.add_command.assert_called_once()
        self.assertIsNone(service.guild_id)


if __name__ == "__main__":
    unittest.main()