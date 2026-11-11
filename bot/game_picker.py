"""Private, owner-only selection UI reused for all game-name commands."""

import logging
import discord

import stores

logger = logging.getLogger(__name__)


class GamePicker(discord.ui.View):
    def __init__(self, user_id, guild_id, choices, on_choose, timeout=120):
        super().__init__(timeout=timeout)
        self.user_id, self.guild_id = user_id, guild_id
        self.choices, self.on_choose = tuple(choices), on_choose
        self.used = False
        self.message = None
        self.menu = discord.ui.Select(
            placeholder="Choose the game you meant", min_values=1, max_values=1,
            options=[discord.SelectOption(label=c.name[:100], value=str(i),
                     description=stores.STORE_NAMES.get(c.store, c.store)[:100])
                     for i, c in enumerate(self.choices)],
        )
        self.menu.callback = self.selected
        self.add_item(self.menu)
        cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        cancel.callback = self.cancelled
        self.add_item(cancel)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message("This selection belongs to someone else.", ephemeral=True)
            return False
        if self.used:
            await interaction.response.send_message("This selection is no longer active.", ephemeral=True)
            return False
        return True

    async def select_value(self, interaction, value):
        # Check again inside the handler so concurrent clicks cannot both act.
        if not await self.interaction_check(interaction):
            return
        if not isinstance(value, str) or value not in {str(i) for i in range(len(self.choices))}:
            await interaction.response.send_message("Choose one of the listed games.", ephemeral=True)
            return
        self.used = True
        self.stop()
        choice = self.choices[int(value)]
        await interaction.response.edit_message(
            content=f"Selected: {discord.utils.escape_markdown(choice.name)[:300]}",
            view=None, allowed_mentions=discord.AllowedMentions.none(),
        )
        try:
            await self.on_choose(choice)
        except Exception:
            logger.exception("Selected game action failed")
            await interaction.followup.send("Something went wrong. Please run the command again.", ephemeral=True)

    async def selected(self, interaction):
        await self.select_value(interaction, self.menu.values[0])

    async def cancelled(self, interaction):
        if not await self.interaction_check(interaction):
            return
        self.used = True
        self.stop()
        await interaction.response.edit_message(content="Selection cancelled.", view=None)

    async def on_timeout(self):
        if self.used:
            return
        self.used = True
        if self.message is not None:
            try:
                await self.message.edit(content="Selection expired. Run the command again.", view=None)
            except discord.HTTPException:
                pass


async def choose(interaction, choices, on_choose, empty="Game not found"):
    if not choices:
        await interaction.followup.send(empty, ephemeral=True)
    elif len(choices) == 1:
        await on_choose(choices[0])
    else:
        view = GamePicker(interaction.user.id, interaction.guild_id, choices, on_choose)
        view.message = await interaction.followup.send(
            "Choose a game below (up to 10 matches). Refine the name if yours is missing.",
            view=view, ephemeral=True, wait=True,
        )
