from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import bot
import pricing


class PullPricingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.interaction = SimpleNamespace(
            guild_id=1,
            response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        self.lookup = AsyncMock()
        patcher = patch("bot.pricing.lookup_prices", self.lookup)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.link = "https://store.steampowered.com/app/292030/"

    async def test_dm_returns_exact_message_without_lookup(self):
        self.interaction.guild_id = None
        await bot.pullpricing.callback(self.interaction, self.link)
        self.interaction.response.send_message.assert_awaited_once_with(
            "Use this command in a server", ephemeral=True
        )
        self.lookup.assert_not_awaited()
        self.interaction.response.defer.assert_not_awaited()
        self.assertFalse(bot.pullpricing.guild_only)

    async def test_invalid_input_returns_exact_message_without_lookup(self):
        await bot.pullpricing.callback(self.interaction, "not a link")
        self.interaction.response.send_message.assert_awaited_once_with(
            "That is not a valid store link", ephemeral=True
        )
        self.lookup.assert_not_awaited()

    async def test_no_prices_returns_exact_message(self):
        self.lookup.return_value = pricing.PriceResult("Unknown game")
        await bot.pullpricing.callback(self.interaction, self.link)
        self.interaction.followup.send.assert_awaited_once_with("No prices found for this game")

    async def test_source_failure_returns_exact_message(self):
        self.lookup.side_effect = pricing.PriceSourceError()
        await bot.pullpricing.callback(self.interaction, self.link)
        self.interaction.followup.send.assert_awaited_once_with(
            "Prices are temporarily unavailable, try again later"
        )

    async def test_embed_has_game_and_every_offer_field(self):
        self.lookup.return_value = pricing.PriceResult("The Witcher 3", (
            pricing.Offer("Steam", Decimal("39.99"), Decimal("39.99"), self.link),
            pricing.Offer("GOG", Decimal("9.99"), Decimal("39.99"), "https://www.cheapshark.com/redirect?dealID=abc"),
            pricing.Offer("Epic Games Store", Decimal("0"), Decimal("39.99"), "https://www.cheapshark.com/redirect?dealID=free"),
        ))

        async def lookup_after_defer(app_id):
            self.interaction.response.defer.assert_awaited_once()
            return self.lookup.return_value

        self.lookup.side_effect = lookup_after_defer
        await bot.pullpricing.callback(self.interaction, self.link)
        self.lookup.assert_awaited_once_with(292030)
        kwargs = self.interaction.followup.send.call_args.kwargs
        embed = kwargs["embed"]
        self.assertEqual(embed.title, "The Witcher 3")
        self.assertIn("USD", embed.description)
        self.assertEqual(len(embed.fields), 3)
        for field, offer in zip(embed.fields, self.lookup.return_value.offers):
            self.assertEqual(field.name, offer.store)
            self.assertIn(f"Original price: ${offer.original:.2f}", field.value)
            self.assertIn(f"Discount: {offer.discount}%", field.value)
            self.assertIn(offer.link, field.value)
        self.assertIn("Current price: **$39.99**", embed.fields[0].value)
        self.assertIn("Discount: 0%", embed.fields[0].value)
        self.assertIn("Current price: **Free**", embed.fields[2].value)
        self.assertFalse(kwargs["allowed_mentions"].everyone)

    async def test_command_is_registered_with_required_link(self):
        command = bot.bot.tree.get_command("pullpricing")
        self.assertIs(command, bot.pullpricing)
        self.assertEqual(command.parameters[0].name, "link")
        self.assertTrue(command.parameters[0].required)


if __name__ == "__main__":
    unittest.main()
