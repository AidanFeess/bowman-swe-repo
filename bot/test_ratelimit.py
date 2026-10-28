import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord

import bot
from ratelimit import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_limiter(clock, **options):
    return RateLimiter(clock=clock, **options)


class TestRateLimiter(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.limiter = make_limiter(self.clock)

    def run_same(self, count, user=1, command="list", wait=0):
        results = []
        for _ in range(count):
            results.append(self.limiter.check(user, command)[0])
            self.clock.now += wait
        return results

    def test_normal_use_is_allowed(self):
        self.assertEqual(self.run_same(6, wait=8), ["ok"] * 6)

    def test_warning_comes_before_the_block(self):
        results = self.run_same(7, wait=8)  # 7th run of the same command in 56 seconds
        self.assertEqual(results, ["ok"] * 6 + ["slow"])

    def test_warned_user_is_blocked_much_sooner(self):
        self.run_same(7, wait=8)
        self.assertEqual(self.limiter.check(1, "list")[0], "ok")
        self.assertEqual(self.limiter.check(1, "list")[0], "ok")
        self.assertEqual(self.limiter.check(1, "list"), ("block", 10))

    def test_without_a_warning_the_limit_is_higher(self):
        # same number of commands, but the flag was never turned on, so more are allowed
        results = self.run_same(9, wait=6)
        self.assertEqual(results.count("block"), 0)

    def test_fast_spam_is_warned_then_blocked(self):
        results = self.run_same(12)
        self.assertEqual(results[:5], ["ok"] * 5)
        self.assertEqual(results[5], "slow")
        self.assertIn("block", results)

    def test_different_commands_are_counted_separately(self):
        for _ in range(3):
            for name in ("list", "wishlist", "remove"):
                self.assertEqual(self.limiter.check(1, name)[0], "ok")
                self.clock.now += 5

    def test_block_message_is_only_given_once(self):
        self.run_same(12)
        self.clock.now += 3
        status, seconds = self.limiter.check(1, "list")
        self.assertEqual(status, "blocked")
        self.assertLessEqual(seconds, 10)

    def test_block_is_short(self):
        self.run_same(12)
        self.clock.now += 10
        self.assertEqual(self.limiter.check(1, "list")[0], "ok")

    def test_flag_turns_off_after_a_minute(self):
        self.run_same(7, wait=8)
        self.assertTrue(self.limiter.is_slow_flagged(1))
        self.clock.now += 60
        self.assertFalse(self.limiter.is_slow_flagged(1))
        self.assertEqual(self.limiter.check(1, "list")[0], "ok")

    def test_slow_use_is_never_blocked(self):
        for _ in range(50):
            self.assertEqual(self.limiter.check(1, "list")[0], "ok")
            self.clock.now += 15

    def test_users_are_counted_separately(self):
        self.run_same(12)
        self.assertEqual(self.limiter.check(2, "list"), ("ok", 0))

    def test_whole_bot_busy_limit(self):
        limiter = make_limiter(self.clock, global_max=6)
        for user in range(6):
            self.assertEqual(limiter.check(user, "list"), ("ok", 0))
        self.assertEqual(limiter.check(99, "list"), ("busy", 10))

    def test_busy_does_not_block_the_user(self):
        limiter = make_limiter(self.clock, global_max=2)
        limiter.check(1, "list")
        limiter.check(2, "list")
        self.assertEqual(limiter.check(3, "list")[0], "busy")
        self.clock.now += 10
        self.assertEqual(limiter.check(3, "list"), ("ok", 0))


def make_interaction(kind=discord.InteractionType.application_command, user_id=1, command="list"):
    interaction = MagicMock()
    interaction.type = kind
    interaction.data = {"name": command}
    interaction.user.id = user_id
    interaction.user.mention = "<@1>"
    interaction.response.send_message = AsyncMock()
    interaction.channel.send = AsyncMock()
    return interaction


class TestTreeCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.tmp = tempfile.TemporaryDirectory()
        self.image = Path(self.tmp.name) / "slow_down.png"
        self.image.write_bytes(b"not a real picture")
        # discord.File is replaced with a fake so no file is ever opened (Windows cannot delete open files)
        self.file_patch = patch.object(bot.discord, "File")
        self.patches = [
            patch.object(bot, "limiter", make_limiter(self.clock)),
            patch.object(bot, "SLOW_DOWN_IMAGE", self.image),
            self.file_patch,
        ]
        for p in self.patches[:-1]:
            p.start()
        self.file_class = self.file_patch.start()
        self.tree = bot.bot.tree

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    async def test_normal_command_runs(self):
        interaction = make_interaction()
        self.assertTrue(await self.tree.interaction_check(interaction))
        interaction.response.send_message.assert_not_called()

    async def test_warning_runs_the_command_and_posts_a_heads_up(self):
        for _ in range(5):
            await self.tree.interaction_check(make_interaction())
        interaction = make_interaction()
        interaction.channel.send = AsyncMock()
        self.assertTrue(await self.tree.interaction_check(interaction))
        await asyncio.sleep(0)
        interaction.channel.send.assert_awaited_once()
        interaction.response.send_message.assert_not_called()

    async def test_flooding_posts_the_picture_once_and_stops_the_command(self):
        for _ in range(6):
            await self.tree.interaction_check(make_interaction())
        for _ in range(2):
            await self.tree.interaction_check(make_interaction())
        interaction = make_interaction()
        self.assertFalse(await self.tree.interaction_check(interaction))
        interaction.response.send_message.assert_awaited_once()
        self.assertIn("file", interaction.response.send_message.await_args.kwargs)
        self.file_class.assert_called_once_with(self.image)

    async def test_same_command_repeated_slowly_still_posts_the_picture(self):
        picture = None
        for _ in range(12):
            interaction = make_interaction()
            if not await self.tree.interaction_check(interaction):
                picture = interaction
                break
            self.clock.now += 5
        self.assertIsNotNone(picture)
        self.assertIn("file", picture.response.send_message.await_args.kwargs)

    async def test_blocked_user_gets_a_quiet_reply_without_the_picture(self):
        for _ in range(9):
            await self.tree.interaction_check(make_interaction())
        interaction = make_interaction()
        self.assertFalse(await self.tree.interaction_check(interaction))
        kwargs = interaction.response.send_message.await_args.kwargs
        self.assertTrue(kwargs["ephemeral"])
        self.assertNotIn("file", kwargs)

    async def test_missing_picture_still_sends_the_warning(self):
        with patch.object(bot, "SLOW_DOWN_IMAGE", Path(self.tmp.name) / "missing.png"):
            for _ in range(8):
                await self.tree.interaction_check(make_interaction())
            interaction = make_interaction()
            self.assertFalse(await self.tree.interaction_check(interaction))
        kwargs = interaction.response.send_message.await_args.kwargs
        self.assertNotIn("file", kwargs)

    async def test_suggestions_while_typing_are_not_counted(self):
        for _ in range(20):
            typing = make_interaction(kind=discord.InteractionType.autocomplete)
            self.assertTrue(await self.tree.interaction_check(typing))
        self.assertTrue(await self.tree.interaction_check(make_interaction()))


if __name__ == "__main__":
    unittest.main()