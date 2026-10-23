import asyncio
import os

import discord
from discord import app_commands
from dotenv import load_dotenv

import db
import handler
import pricing

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
@app_commands.describe(game="Game name or Steam store link, e.g. Portal 2")
@app_commands.guild_only()
async def wishlist(interaction: discord.Interaction, game: str):
    # Steam lookups can take longer than Discord's 3 second limit, so acknowledge first
    await interaction.response.defer()
    status, message = await asyncio.to_thread(
        handler.add_to_wishlist, interaction.guild_id, interaction.user.id, game
    )
    await interaction.followup.send(message)

@bot.tree.command(name="list", description="Show the games on your wishlist")
@app_commands.guild_only()
async def list_wishlist(interaction: discord.Interaction):
    # Database calls are synchronous, run query off event loop
    await interaction.response.defer()

    try:
        # Only this user's games are loaded, so nobody sees anyone else's list
        games = await asyncio.to_thread(db.get_wishlist, interaction.user.id)
    except Exception as e: # if wishlist cant be loaded
        print(f"wishlist list error: {e}")
        await interaction.followup.send("Sorry, I couldn't load your wishlist right now.")
        return

    if not games: # no games in list
        embed = discord.Embed(
            title="Your Wishlist",
            description="No games yet! Use `/wishlist` to add one.",
            color=discord.Color.blurple(),
        )
        await interaction.followup.send(embed=embed)
        return

    # Every row comes from wishlist.db: (game name, store, store link).
    # formatting
    lines = []
    for number, (game, store, link) in enumerate(games, start=1):
        safe_name = discord.utils.escape_markdown(game)
        lines.append(f"**{number}. {safe_name}** — [View on {store.upper()}]({link})")

    # Discord embeds have a 4096-character description limit. (handling large wishlist items)
    # making the print out wishlist
    pages = []
    current_lines = []
    current_length = 0
    for line in lines:
        if current_lines and current_length + len(line) + 1 > 3500:
            pages.append("\n".join(current_lines))
            current_lines = []
            current_length = 0
        current_lines.append(line)
        current_length += len(line) + 1
    if current_lines:
        pages.append("\n".join(current_lines))

    # final message
    for page_number, description in enumerate(pages, start=1):
        embed = discord.Embed(
            title="Your Wishlist",
            description=description,
            color=discord.Color.blurple(),
        )
        embed.set_footer(
            text=f"{len(games)} game(s) • Page {page_number}/{len(pages)}"
        )
        await interaction.followup.send(
            embed=embed, allowed_mentions=discord.AllowedMentions.none()
        )

@bot.tree.command(name="pullpricing", description="Compare a game's prices across stores")
@app_commands.describe(link="Steam store link, e.g. https://store.steampowered.com/app/620/")
async def pullpricing(interaction: discord.Interaction, link: str):
    # Keep this command available in DMs so it can return the required message.
    if interaction.guild_id is None:
        await interaction.response.send_message(pricing.SERVER_ONLY, ephemeral=True)
        return
    app_id = pricing.parse_steam_link(link)
    if app_id is None:
        await interaction.response.send_message(pricing.INVALID_LINK, ephemeral=True)
        return

    await interaction.response.defer()
    try:
        result = await pricing.lookup_prices(app_id)
    except pricing.PriceSourceError:
        await interaction.followup.send(pricing.UNAVAILABLE)
        return
    if not result.offers:
        await interaction.followup.send(pricing.NO_PRICES)
        return

    embed = discord.Embed(
        title=discord.utils.escape_markdown(result.name)[:256],
        description="Prices in USD (US region).",
        color=discord.Color.blurple(),
    )
    for offer in result.offers:
        embed.add_field(name=offer.store, value=pricing.format_offer(offer), inline=False)
    embed.set_footer(text="Sources: Steam and CheapShark • Prices can change before checkout")
    await interaction.followup.send(
        embed=embed, allowed_mentions=discord.AllowedMentions.none()
    )


if __name__ == "__main__":
    bot.run(TOKEN)
