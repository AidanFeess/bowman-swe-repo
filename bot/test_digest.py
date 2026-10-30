import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord

import database
import db
import digest
import pricing

PORTAL_LINK = "https://store.steampowered.com/app/620/"
OTHER_LINK = "https://store.steampowered.com/app/730/"


def sale(name="Portal 2", current="4.99", original="9.99"):
    offer = pricing.Offer("Steam", Decimal(current), Decimal(original), PORTAL_LINK)
    return pricing.PriceResult(name, (offer,))


def add_wish(user_id, link, game="Portal 2"):
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(db.DATABASE_PATH)) as conn:
        with conn:
            conn.execute(
                "INSERT INTO wishlist (discord_user_id, game, store, link) VALUES (?, ?, 'steam', ?)",
                (str(user_id), game, link),
            )


def make_guild(member_ids):
    guild = MagicMock()
    guild.id = 1

    def get_member(user_id):
        if user_id in member_ids:
            member = MagicMock()
            member.bot = False
            return member
        return None

    guild.get_member.side_effect = get_member
    guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "not found"))
    return guild


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

    async def run_digest(self, member_ids, result=None, day="2026-10-29"):
        send = AsyncMock()
        with patch.object(digest, "current_day", return_value=day), \
             patch.object(pricing, "lookup_prices", AsyncMock(return_value=result or sale())):
            await self.service.generate_digest(make_guild(member_ids), send)
        return send

    def pings(self, send):
        return [c for c in send.await_args_list if c.args and c.args[0].startswith("Sale alert")]

    async def test_user_is_pinged_with_the_price(self):
        add_wish(10, PORTAL_LINK)
        send = await self.run_digest({10})
        pings = self.pings(send)
        self.assertEqual(len(pings), 1)
        self.assertIn("<@10>", pings[0].args[0])
        embed = pings[0].kwargs["embed"]
        self.assertIn("$4.99", embed.fields[0].value)
        self.assertIn("1 user(s)", embed.description)

    async def test_same_day_second_run_does_not_ping_again(self):
        add_wish(10, PORTAL_LINK)
        await self.run_digest({10})
        send = await self.run_digest({10})
        self.assertEqual(self.pings(send), [])
        quiet = [c for c in send.await_args_list if "already pinged" in c.args[0]]
        self.assertEqual(len(quiet), 1)
        self.assertIn("embed", quiet[0].kwargs)

    async def test_next_day_pings_again_while_still_on_sale(self):
        add_wish(10, PORTAL_LINK)
        await self.run_digest({10}, day="2026-10-29")
        send = await self.run_digest({10}, day="2026-10-30")
        self.assertEqual(len(self.pings(send)), 1)

    async def test_game_not_on_sale_pings_nobody(self):
        add_wish(10, PORTAL_LINK)
        send = await self.run_digest({10}, result=sale(current="9.99", original="9.99"))
        self.assertEqual(self.pings(send), [])
        self.assertIn("No wishlist games are on sale", send.await_args_list[0].args[0])

    async def test_permanently_free_game_is_not_a_sale(self):
        add_wish(10, PORTAL_LINK)
        send = await self.run_digest({10}, result=sale(current="0", original="0"))
        self.assertEqual(self.pings(send), [])

    async def test_new_user_is_pinged_even_if_another_was_already(self):
        add_wish(10, PORTAL_LINK)
        await self.run_digest({10})
        add_wish(11, PORTAL_LINK)
        send = await self.run_digest({10, 11})
        pings = self.pings(send)
        self.assertEqual(len(pings), 1)
        self.assertIn("<@11>", pings[0].args[0])
        self.assertNotIn("<@10>", pings[0].args[0])
        self.assertIn("2 user(s)", pings[0].kwargs["embed"].description)

    async def test_users_outside_the_server_are_not_pinged(self):
        add_wish(10, PORTAL_LINK)
        add_wish(99, PORTAL_LINK)
        send = await self.run_digest({10})
        text = " ".join(c.args[0] for c in self.pings(send))
        self.assertIn("<@10>", text)
        self.assertNotIn("<@99>", text)

    async def test_failed_send_is_retried_later(self):
        add_wish(10, PORTAL_LINK)
        failing = AsyncMock(side_effect=[None, RuntimeError("discord down")])
        with patch.object(pricing, "lookup_prices", AsyncMock(return_value=sale())):
            with self.assertRaises(RuntimeError):
                await self.service.generate_digest(make_guild({10}), failing)
        send = await self.run_digest({10})
        self.assertEqual(len(self.pings(send)), 1)

    async def test_no_wishlist_games_message(self):
        send = await self.run_digest({10})
        self.assertIn("No supported wishlist games", send.await_args_list[0].args[0])


class TestRegister(unittest.TestCase):
    def test_command_is_added_and_no_schedule_without_a_channel(self):
        bot = MagicMock()
        with patch.dict("os.environ", {}, clear=True):
            service = digest.Digest(bot)
            service.register()
        bot.tree.add_command.assert_called_once()
        self.assertEqual(service.command.name, "digest")
        self.assertIsNone(service.channel_id)

    def test_schedule_runs_at_4_pm_central_through_daylight_saving(self):
        import datetime
        from zoneinfo import ZoneInfo
        bot = MagicMock()
        env = {"DIGEST_CHANNEL_ID": "123"}
        with patch.dict("os.environ", env, clear=True), \
             patch.object(digest.Digest, "daily_digest", create=True):
            service = digest.Digest(bot)
            with patch.object(service.daily_digest, "start"):
                service.register()
        self.assertEqual(service.channel_id, 123)
        central = ZoneInfo("America/Chicago")
        # 4 PM Central is 21:00 UTC in summer and 22:00 UTC in winter
        summer = datetime.datetime(2026, 7, 1, 16, 0, tzinfo=central).astimezone(datetime.timezone.utc)
        winter = datetime.datetime(2026, 12, 1, 16, 0, tzinfo=central).astimezone(datetime.timezone.utc)
        self.assertEqual((summer.hour, winter.hour), (21, 22))
        self.assertEqual(service.tz.key, "America/Chicago")

    def test_bad_timezone_does_not_stop_the_bot(self):
        bot = MagicMock()
        env = {"DIGEST_CHANNEL_ID": "123", "DIGEST_TIMEZONE": "Not/AZone"}
        with patch.dict("os.environ", env, clear=True):
            service = digest.Digest(bot)
            service.register()
        bot.tree.add_command.assert_called_once()
        self.assertIsNone(service.channel_id)

    def test_bad_schedule_settings_do_not_stop_the_bot(self):
        bot = MagicMock()
        with patch.dict("os.environ", {"DIGEST_CHANNEL_ID": "abc"}, clear=True):
            service = digest.Digest(bot)
            service.register()
        bot.tree.add_command.assert_called_once()
        self.assertIsNone(service.channel_id)


if __name__ == "__main__":
    unittest.main()