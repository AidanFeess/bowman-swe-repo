import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import database
import db
from game_search import GameChoice
import pricing
import watch_db
from watches import CHECK_TIME, WatchService

GAME = GameChoice("Portal 2", "steam", "https://store.steampowered.com/app/620/", steam_id=620)


def price(amount):
    return pricing.PriceResult("Portal 2", (
        pricing.Offer("Steam", Decimal(amount), Decimal("20"), GAME.link),
    ))


class WatchServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "test.db"
        for module in (database, db):
            p = patch.object(module, "DATABASE_PATH", path)
            p.start()
            self.addCleanup(p.stop)
        db.init_db()
        self.member = SimpleNamespace(id=2, bot=False, send=AsyncMock())
        self.guild = SimpleNamespace(id=1, name="test server", get_member=MockMember(self.member), fetch_member=AsyncMock())
        self.bot = SimpleNamespace(get_guild=lambda guild_id: self.guild if guild_id == 1 else None,
                                   wait_until_ready=AsyncMock())
        self.service = WatchService(self.bot)
        self.fetch = AsyncMock(return_value=price("9.99"))
        p = patch("game_search.choice_prices", self.fetch)
        p.start()
        self.addCleanup(p.stop)
        self.watch_id = watch_db.save(1, 2, GAME, 1000)

    async def test_first_qualifying_price_sends_private_alert_and_records_delivery(self):
        await self.service.run_checks("2026-11-11")
        self.member.send.assert_awaited_once()
        embed = self.member.send.call_args.kwargs["embed"]
        self.assertIn("$10.00", embed.description)
        self.assertIn("$9.99", embed.fields[0].value)
        self.assertEqual(watch_db.rows(1, 2)[0]["notified_cents"], 999)

    async def test_no_repeat_same_day_or_after_restart_and_lower_price_alerts(self):
        await self.service.run_checks("2026-11-11")
        self.service = WatchService(self.bot)
        await self.service.run_checks("2026-11-11")
        await self.service.run_checks("2026-11-12")
        self.member.send.assert_awaited_once()
        self.fetch.return_value = price("8.99")
        await self.service.run_checks("2026-11-13")
        self.assertEqual(self.member.send.await_count, 2)

    async def test_price_above_target_rearms_a_later_sale(self):
        await self.service.run_checks("2026-11-11")
        self.fetch.return_value = price("15.00")
        await self.service.run_checks("2026-11-12")
        self.assertIsNone(watch_db.rows(1, 2)[0]["notified_cents"])
        self.fetch.return_value = price("9.99")
        await self.service.run_checks("2026-11-13")
        self.assertEqual(self.member.send.await_count, 2)

    async def test_zero_target_only_triggers_free_and_uses_cheapest_available_store(self):
        watch_db.save(1, 2, GAME, 0)
        await self.service.run_checks("2026-11-11")
        self.member.send.assert_not_awaited()
        self.fetch.return_value = pricing.PriceResult("Portal 2", (
            pricing.Offer("Steam", Decimal("10"), Decimal("20"), GAME.link),
            pricing.Offer("GOG", Decimal("0"), Decimal("20"), "https://www.gog.com/game/portal_2"),
        ))
        await self.service.run_checks("2026-11-12")
        self.assertEqual(self.member.send.call_args.kwargs["embed"].fields[0].name, "GOG")
        self.assertIn("Free", self.member.send.call_args.kwargs["embed"].fields[0].value)

    async def test_source_failure_or_missing_price_does_not_send_or_reset_state(self):
        row = watch_db.rows(1, 2)[0]
        watch_db.checked(row["id"], row["revision"], "2026-11-10", 800)
        self.fetch.side_effect = pricing.PriceSourceError()
        await self.service.run_checks("2026-11-11")
        self.fetch.side_effect = None
        self.fetch.return_value = pricing.PriceResult("Portal 2")
        await self.service.run_checks("2026-11-12")
        self.member.send.assert_not_awaited()
        self.assertEqual(watch_db.rows(1, 2)[0]["notified_cents"], 800)
        self.assertEqual(self.service.last_outcome, "partial failure")

    async def test_failed_dm_is_retried_without_marking_it_delivered(self):
        self.member.send.side_effect = discord.Forbidden(MagicMock(status=403), "closed DMs")
        with self.assertLogs("watches", level="ERROR"):
            await self.service.run_checks("2026-11-11")
        self.assertIsNone(watch_db.rows(1, 2)[0]["notified_cents"])
        self.member.send.side_effect = None
        await self.service.run_checks("2026-11-12")
        self.assertEqual(watch_db.rows(1, 2)[0]["notified_cents"], 999)

    async def test_deleted_watch_during_lookup_does_not_notify(self):
        async def lookup(choice):
            await self.service.remove(1, 2, self.watch_id)
            return price("9.99")
        self.fetch.side_effect = lookup
        await self.service.run_checks("2026-11-11")
        self.member.send.assert_not_awaited()

    async def test_changed_target_during_lookup_is_not_overwritten(self):
        async def lookup(choice):
            await self.service.save(1, 2, choice, 500)
            return price("9.99")
        self.fetch.side_effect = lookup
        await self.service.run_checks("2026-11-11")
        self.member.send.assert_not_awaited()
        self.assertEqual(watch_db.rows(1, 2)[0]["target_cents"], 500)

    async def test_left_member_and_unavailable_guild_are_not_notified(self):
        watch_db.save(999, 2, GAME, 1000)
        self.guild.get_member = lambda user: None
        self.guild.fetch_member.side_effect = discord.NotFound(MagicMock(status=404), "left")
        await self.service.run_checks("2026-11-11")
        self.member.send.assert_not_awaited()
        self.fetch.assert_not_awaited()

    async def test_shared_game_is_fetched_once_for_multiple_users(self):
        second = SimpleNamespace(id=3, bot=False, send=AsyncMock())
        self.guild.get_member = lambda user: self.member if user == 2 else second
        watch_db.save(1, 3, GAME, 1000)
        await self.service.run_checks("2026-11-11")
        self.fetch.assert_awaited_once()
        self.member.send.assert_awaited_once()
        second.send.assert_awaited_once()

    async def test_overlapping_runs_do_not_duplicate_notifications(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def lookup(choice):
            started.set()
            await release.wait()
            return price("9.99")
        self.fetch.side_effect = lookup
        first = asyncio.create_task(self.service.run_checks("2026-11-11"))
        await started.wait()
        await self.service.run_checks("2026-11-11")
        release.set()
        await first
        self.member.send.assert_awaited_once()

    def test_schedule_stays_at_four_pm_central_across_dst(self):
        self.assertEqual(CHECK_TIME.hour, 16)
        self.assertEqual(datetime.combine(date(2026, 7, 1), CHECK_TIME).utcoffset(), timedelta(hours=-5))
        self.assertEqual(datetime.combine(date(2026, 12, 1), CHECK_TIME).utcoffset(), timedelta(hours=-6))


class MockMember:
    def __init__(self, member):
        self.member = member

    def __call__(self, user_id):
        return self.member if user_id == self.member.id else None
