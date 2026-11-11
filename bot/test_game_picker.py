from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from game_picker import GamePicker, choose
from game_search import GameChoice


def interaction(user=10, guild=20):
    return SimpleNamespace(user=SimpleNamespace(id=user), guild_id=guild,
                           response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()),
                           followup=SimpleNamespace(send=AsyncMock()))


class PickerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.choices = [GameChoice("Dark Souls", "steam", "one", steam_id=1),
                        GameChoice("Dark Souls II", "steam", "two", steam_id=2)]
        self.action = AsyncMock()
        self.view = GamePicker(10, 20, self.choices, self.action)

    async def test_only_selected_game_is_used(self):
        self.action.assert_not_awaited()
        i = interaction()
        await self.view.select_value(i, "1")
        self.action.assert_awaited_once_with(self.choices[1])
        self.assertIsNone(i.response.edit_message.call_args.kwargs["view"])

    async def test_other_user_or_server_cannot_select(self):
        for i in (interaction(user=99), interaction(guild=99)):
            await self.view.select_value(i, "0")
            i.response.send_message.assert_awaited_once_with("This selection belongs to someone else.", ephemeral=True)
        self.action.assert_not_awaited()

    async def test_double_submission_acts_once(self):
        await self.view.select_value(interaction(), "0")
        other = interaction()
        await self.view.select_value(other, "1")
        self.action.assert_awaited_once()
        self.assertIn("no longer active", other.response.send_message.call_args.args[0])

    async def test_forged_values_do_not_act(self):
        for value in ("-1", "200", "https://evil.com", "", None, "²", "00", "9" * 5000):
            await self.view.select_value(interaction(), value)
        self.action.assert_not_awaited()
        self.assertFalse(self.view.used)

    async def test_cancel_has_no_side_effect(self):
        i = interaction()
        await self.view.cancelled(i)
        self.action.assert_not_awaited()
        self.assertTrue(self.view.used)
        i.response.edit_message.assert_awaited_once_with(content="Selection cancelled.", view=None)

    async def test_timeout_expires_message_and_rejects_late_selection(self):
        self.view.message = SimpleNamespace(edit=AsyncMock())
        await self.view.on_timeout()
        self.view.message.edit.assert_awaited_once_with(content="Selection expired. Run the command again.", view=None)
        await self.view.select_value(interaction(), "0")
        self.action.assert_not_awaited()

    async def test_multiple_matches_are_private_and_do_not_act_yet(self):
        i = interaction()
        await choose(i, self.choices, self.action)
        self.action.assert_not_awaited()
        self.assertTrue(i.followup.send.call_args.kwargs["ephemeral"])
        self.assertIsInstance(i.followup.send.call_args.kwargs["view"], GamePicker)

    async def test_single_and_empty_results(self):
        i = interaction()
        await choose(i, [self.choices[0]], self.action)
        self.action.assert_awaited_once_with(self.choices[0])
        await choose(i, [], self.action)
        i.followup.send.assert_awaited_once_with("Game not found", ephemeral=True)
