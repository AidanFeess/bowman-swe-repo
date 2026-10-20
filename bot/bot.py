import asyncio
import os

import discord
from discord import app_commands
from dotenv import load_dotenv

import db
import handler

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
TEST_GUILD_ID = os.getenv("TEST_GUILD_ID")


class GameNightBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        db.init_db()
        if TEST_GUILD_ID:
            guild = discord.Object(id=int(TEST_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)  # shows up instantly in the test server
        else:
            await self.tree.sync()


bot = GameNightBot()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


@bot.tree.command(name="wishlist", description="Add a Steam game to your wishlist")
@app_commands.describe(link="Steam store link, e.g. https://store.steampowered.com/app/620/")
@app_commands.guild_only()
async def wishlist(interaction: discord.Interaction, link: str):
    # Steam lookups can take longer than Discord's 3 second limit, so acknowledge first
    await interaction.response.defer()
    status, message = await asyncio.to_thread(
        handler.add_to_wishlist, interaction.guild_id, interaction.user.id, link
    )
    await interaction.followup.send(message)


bot.run(TOKEN)