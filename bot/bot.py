import asyncio
import os
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

import db
import digest
import handler
import pricing
import ratelimit
import seasonal

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
TEST_GUILD_ID = os.getenv("TEST_GUILD_ID")

# Picture posted when someone floods the bot with commands
SLOW_DOWN_IMAGE = Path(__file__).resolve().parent / "slow_down.png"

# A user is warned at the 7th run of the same command in 60 seconds (or 6 commands in 10 seconds).
# After the warning only 2 more are allowed for a minute, then they are blocked for 10 seconds.
# 30 commands per 10 seconds for everyone together.
limiter = ratelimit.RateLimiter()
_background_tasks = set()


async def send_heads_up(interaction):
    # Plain message in the channel before the block, the command itself still runs
    try:
        await interaction.channel.send(
            f"Slow down, {interaction.user.mention}! Keep spamming and you will be blocked.",
            allowed_mentions=discord.AllowedMentions(users=[interaction.user]),
        )
    except (AttributeError, discord.HTTPException) as e:
        print(f"heads-up failed: {e}")


async def send_slow_down(interaction, seconds):
    text = f"Slow down, {interaction.user.mention}! You are blocked for {seconds} seconds."
    options = {"allowed_mentions": discord.AllowedMentions.none()}
    if SLOW_DOWN_IMAGE.exists():
        options["file"] = discord.File(SLOW_DOWN_IMAGE)
    await interaction.response.send_message(text, **options)


class GameNightTree(app_commands.CommandTree):
    async def interaction_check(self, interaction):
        # Runs before every command. Suggestions while typing are not commands, so they are not counted.
        if interaction.type is not discord.InteractionType.application_command:
            return True

        command = str(interaction.data.get("name", ""))
        status, seconds = limiter.check(interaction.user.id, command)
        if status == "slow":  # warned, but the command still runs
            print(f"rate limit: user {interaction.user.id} used /{command} -> slow")
            task = asyncio.create_task(send_heads_up(interaction))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
            return True
        if status == "ok":
            return True
        print(f"rate limit: user {interaction.user.id} used /{command} -> {status}")

        try:
            if status == "block":  # just went over the limit, post the picture once
                await send_slow_down(interaction, seconds)
            elif status == "blocked":  # still blocked, reply quietly so the bot does not spam too
                await interaction.response.send_message(
                    f"Slow down! Try again in {seconds} seconds.", ephemeral=True
                )
            else:  # the whole bot is too busy
                await interaction.response.send_message(
                    "The bot is busy right now, try again in a few seconds.", ephemeral=True
                )
        except discord.HTTPException as e:
            print(f"rate limit reply failed: {e}")
        return False  # the command does not run


class GameNightBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = GameNightTree(self)

    async def setup_hook(self):
        db.init_db()
        self.digest = digest.setup(self)  # adds /digest, and the daily schedule if it is configured
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

# Formatting for /help message
# Updates as new commands are added
def build_help_embed():
    lines = []

    for command in sorted(bot.tree.get_commands(), key=lambda cmd: cmd.name):
        if not isinstance(command, app_commands.Command):
            continue

        syntax = f"/{command.name}"

        for parameter in command.parameters:
            if parameter.required:
                syntax += f" <{parameter.name}>"
            else:
                syntax += f" [{parameter.name}]"

        lines.append(f"`{syntax}` — {command.description}")

    return discord.Embed(
        title="Game Night Bot Commands",
        description="\n".join(lines),
        color=discord.Color.blurple(),
    )

# /help command
@bot.tree.command(name="help", description="Show all available commands and their usage")
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=build_help_embed(),
        ephemeral=True
    )


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


@bot.tree.command(name="list", description="Show the server wishlist or a specific user's wishlist")
@app_commands.describe(user="Select a server member (leave empty for the whole server)")
@app_commands.guild_only()
async def list_wishlist(interaction: discord.Interaction, user: discord.Member | None = None):
    if interaction.guild_id is None:
        await interaction.response.send_message(
            "Use this command in a server.",
            ephemeral=True
        )
        return

    if user is not None and (
        not isinstance(user, discord.Member)
        or user.guild.id != interaction.guild_id
    ):
        await interaction.response.send_message(
            "Please select a valid member of this server.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    try:
        if user is None:
            games = await asyncio.to_thread(
                db.get_server_wishlist, interaction.guild_id
            )
            title = "Server Wishlist"
        else:
            games = await asyncio.to_thread(
                db.get_wishlist, interaction.guild_id, user.id
            )
            title = f"{user.display_name}'s Wishlist"

    except Exception as e:
        print(f"wishlist list error: {e}")
        await interaction.followup.send(
            "Sorry, I couldn't load the wishlist right now."
        )
        return

    if not games:
        if user is None:
            message = "No games have been wishlisted in this server yet."
        else:
            message = f"{user.display_name} hasn't wishlisted any games yet."

        embed = discord.Embed(
            title=title,
            description=message,
            color=discord.Color.blurple()
        )
        await interaction.followup.send(embed=embed)
        return

    lines = []

    if user is None:
        for number, (game, store, link, count) in enumerate(games, 1):
            safe_name = discord.utils.escape_markdown(game)
            lines.append(
                f"**{number}. {safe_name}** — "
                f"[View on {store.upper()}]({link}) "
                f"— **{count} user(s)**"
            )

        total_wishes = sum(row[3] for row in games)
        footer = (
            f"{len(games)} unique game(s) • "
            f"{total_wishes} total wishlist entries"
        )

    else:
        for number, (game, store, link) in enumerate(games, 1):
            safe_name = discord.utils.escape_markdown(game)
            lines.append(
                f"**{number}. {safe_name}** — "
                f"[View on {store.upper()}]({link})"
            )

        footer = f"{len(games)} game(s)"

    # Split long lists into multiple embeds
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

    for page_number, description in enumerate(pages, 1):
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blurple()
        )

        embed.set_footer(
            text=f"{footer} • Page {page_number}/{len(pages)}"
        )

        await interaction.followup.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none()
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

@bot.tree.command(name="remove", description="Remove a game from your wishlist")
@app_commands.describe(game="Name of the game to remove. Pick one from your wishlist.")
async def remove(interaction: discord.Interaction, game: str):
    # Keep this command available in DMs so it can return the required message.
    if interaction.guild_id is None:
        await interaction.response.send_message("Use this command in a server.")
        return

    # Database calls are synchronous, run them off the event loop
    await interaction.response.defer()
    try:
        removed = await asyncio.to_thread(db.remove_game, interaction.guild_id, interaction.user.id, game)
    except Exception as e:
        print(f"remove error: {e}")
        await interaction.followup.send("Sorry, I couldn't remove that game right now.")
        return

    if removed is None:
        await interaction.followup.send("That game is not on your wishlist.")
        return

    safe_name = discord.utils.escape_markdown(removed)
    await interaction.followup.send(
        f"Removed {safe_name} from your wishlist.",
        allowed_mentions=discord.AllowedMentions.none(),
    )

@bot.tree.command(name="seasonal", description="See how long until the next Steam seasonal sale")
async def seasonal_command(interaction: discord.Interaction):
    # Needs no database or web lookup, so it replies right away and only to the person who asked
    await interaction.response.send_message(embed=seasonal.build_embed(), ephemeral=True)

@remove.autocomplete("game")
async def remove_autocomplete(interaction: discord.Interaction, current: str):
    # Suggest the games on this user's own wishlist as they type
    try:
        if interaction.guild_id is None:
            return []

        games = await asyncio.to_thread(db.get_wishlist, interaction.guild_id, interaction.user.id)
    except Exception as e:
        print(f"remove autocomplete error: {e}")
        return []
    current = current.lower()
    names = []
    for name, store, link in games:
        name = name[:100]  # Discord allows at most 100 characters per suggestion
        if current in name.lower() and name not in names:
            names.append(name)
    return [app_commands.Choice(name=name, value=name) for name in names[:25]]


if __name__ == "__main__":
    bot.run(TOKEN)