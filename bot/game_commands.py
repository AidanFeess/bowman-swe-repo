"""Command behavior for game selection, random picks, watches, and admin status."""

import asyncio
from contextlib import closing
import math
import random
import sqlite3
import time

import discord

import db
import game_picker
import game_search
import health
import pricing
import stores
import watch_db
import watches


async def search_and_choose(interaction, game, store, action):
    try:
        choices = await game_search.search_games(game, store)
    except pricing.PriceSourceError:
        await interaction.followup.send(pricing.UNAVAILABLE, ephemeral=True)
        return
    await game_picker.choose(interaction, choices, action)


async def save_wishlist_choice(interaction, choice):
    try:
        added = await asyncio.to_thread(db.add_store_game, interaction.guild_id, interaction.user.id,
                                       choice.store, choice.link, choice.name)
    except sqlite3.Error:
        await interaction.followup.send("Sorry, I couldn't update your wishlist right now.", ephemeral=True)
        return
    name = discord.utils.escape_markdown(choice.name)[:300]
    label = stores.STORE_NAMES[choice.store]
    text = f"Added **{name}** ({label}) to your wishlist." if added else f"**{name}** ({label}) is already on your wishlist."
    await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


def price_embed(result):
    embed = discord.Embed(title=discord.utils.escape_markdown(result.name)[:256],
                          description="Prices in USD (US region).", color=discord.Color.blurple())
    for offer in result.offers:
        embed.add_field(name=offer.store, value=pricing.format_offer(offer), inline=False)
    embed.set_footer(text="Sources: Steam and CheapShark • Check the edition and price before buying")
    return embed


async def show_choice_prices(interaction, choice):
    try:
        result = await game_search.choice_prices(choice)
    except pricing.PriceSourceError:
        await interaction.followup.send(pricing.UNAVAILABLE, ephemeral=True)
        return
    if not result.offers:
        await interaction.followup.send(pricing.NO_PRICES, ephemeral=True)
        return
    await interaction.followup.send(embed=price_embed(result), ephemeral=True,
                                    allowed_mentions=discord.AllowedMentions.none())


async def remove_game(interaction, game):
    try:
        rows = await asyncio.to_thread(db.get_wishlist, interaction.guild_id, interaction.user.id)
        # /remove keeps its existing behavior of removing all store copies of the selected full name.
        names = dict.fromkeys(row[0] for row in rows)
        choices = game_search.saved_matches(
            [game_search.GameChoice(name, "your wishlist", "") for name in names], game
        )
    except sqlite3.Error:
        await interaction.followup.send("Sorry, I couldn't remove that game right now.", ephemeral=True)
        return

    async def selected(choice):
        try:
            removed = await asyncio.to_thread(db.remove_game, interaction.guild_id, interaction.user.id, choice.name)
        except sqlite3.Error:
            await interaction.followup.send("Sorry, I couldn't remove that game right now.", ephemeral=True)
            return
        text = (f"Removed {discord.utils.escape_markdown(removed)[:300]} from your wishlist."
                if removed else "That game is not on your wishlist.")
        await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    await game_picker.choose(interaction, choices, selected, "That game is not on your wishlist.")


async def random_pick(interaction, user=None):
    if interaction.guild_id is None:
        await interaction.response.send_message(pricing.SERVER_ONLY, ephemeral=True)
        return
    if user is not None and (not isinstance(user, discord.Member) or user.guild.id != interaction.guild_id):
        await interaction.response.send_message("Please select a valid member of this server.", ephemeral=True)
        return
    await interaction.response.defer()
    try:
        rows = await asyncio.to_thread(db.get_server_wishlist, interaction.guild_id) if user is None else await asyncio.to_thread(
            db.get_wishlist, interaction.guild_id, user.id
        )
    except sqlite3.Error:
        await interaction.followup.send("Sorry, I couldn't load the wishlist right now.")
        return
    if not rows:
        await interaction.followup.send("This wishlist is empty. Add a game with /wishlist first.")
        return
    # One chance per store/game, not one chance for every person who added it.
    unique = {(row[1], row[2]): row for row in rows}
    name, store, link, *_ = random.choice(list(unique.values()))
    choice = game_search.wishlist_choice(name, store, link)
    embed = discord.Embed(title=discord.utils.escape_markdown(name)[:256], color=discord.Color.blurple())
    embed.description = f"[View on {stores.STORE_NAMES[store]}]({link})"
    try:
        result = await game_search.choice_prices(choice)
        if result.offers:
            for offer in result.offers:
                embed.add_field(name=offer.store, value=pricing.format_offer(offer), inline=False)
        else:
            embed.add_field(name="Price", value=pricing.NO_PRICES, inline=False)
    except (pricing.PriceSourceError, pricing.GameNotFound):
        embed.add_field(name="Price", value=pricing.UNAVAILABLE, inline=False)
    scope = "Server wishlist" if user is None else f"{user.display_name}'s wishlist"
    embed.set_footer(text=f"{scope} • USD (US region) • Each store/game has an equal chance"[:2048])
    await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def add_watch(interaction, service, game, price, store="steam"):
    if interaction.guild_id is None:
        await interaction.response.send_message(pricing.SERVER_ONLY, ephemeral=True)
        return
    game = game.strip()
    if not game:
        await interaction.response.send_message(pricing.EMPTY_INPUT, ephemeral=True)
        return
    try:
        cents = watch_db.price_cents(price)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return
    app_id = pricing.parse_steam_link(game)
    store_link = stores.parse_store_link(game)
    if pricing.looks_like_link(game) and app_id is None and store_link is None:
        await interaction.response.send_message(pricing.INVALID_LINK, ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    async def selected(choice):
        try:
            await service.save(interaction.guild_id, interaction.user.id, choice, cents)
        except watch_db.WatchLimitReached:
            await interaction.followup.send("You can watch up to 25 games per server. Remove one with /unwatch first.", ephemeral=True)
            return
        except sqlite3.Error:
            await interaction.followup.send("Sorry, I couldn't save that watch right now.", ephemeral=True)
            return
        await interaction.followup.send(
            f"Watching **{discord.utils.escape_markdown(choice.name)[:300]}** at **${cents / 100:.2f} USD** or less at any supported store. "
            f"I'll check {watches.SCHEDULE} and DM you when it reaches your target or drops further.",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
        )

    if app_id is not None:
        try:
            result = await pricing.lookup_prices(app_id)
        except pricing.PriceSourceError:
            await interaction.followup.send(pricing.UNAVAILABLE, ephemeral=True)
            return
        if not result.name:
            await interaction.followup.send(pricing.GAME_NOT_FOUND, ephemeral=True)
            return
        await selected(game_search.GameChoice(result.name, "steam", f"https://store.steampowered.com/app/{app_id}/", steam_id=app_id))
    else:
        if store_link is not None:
            store, game, _ = store_link
        # Non-Steam links resolve to catalog IDs too, so later checks never guess a sequel.
        await search_and_choose(interaction, game, store, selected)


async def watchlist(interaction):
    if interaction.guild_id is None:
        await interaction.response.send_message(pricing.SERVER_ONLY, ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        rows = await asyncio.to_thread(watch_db.rows, interaction.guild_id, interaction.user.id)
    except sqlite3.Error:
        await interaction.followup.send("Sorry, I couldn't load your watches right now.", ephemeral=True)
        return
    if not rows:
        await interaction.followup.send("No watches yet. Use /watch to set a target price.", ephemeral=True)
        return
    for offset in range(0, len(rows), 5):
        lines = [f"**{discord.utils.escape_markdown(r['game'])[:300]}** — ${r['target_cents'] / 100:.2f} USD or less"
                 for r in rows[offset:offset + 5]]
        embed = discord.Embed(title="Your price watches", description="\n".join(lines), color=discord.Color.blurple())
        embed.set_footer(text=f"Checked {watches.SCHEDULE} • Use /unwatch to remove a game")
        await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


async def unwatch(interaction, service, game):
    if interaction.guild_id is None:
        await interaction.response.send_message(pricing.SERVER_ONLY, ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        rows = await asyncio.to_thread(watch_db.rows, interaction.guild_id, interaction.user.id)
    except sqlite3.Error:
        await interaction.followup.send("Sorry, I couldn't load your watches right now.", ephemeral=True)
        return
    choices = game_search.saved_matches([watch_db.choice(row) for row in rows], game)

    async def selected(choice):
        try:
            removed = await service.remove(interaction.guild_id, interaction.user.id, choice.reference_id)
        except sqlite3.Error:
            await interaction.followup.send("Sorry, I couldn't remove that watch right now.", ephemeral=True)
            return
        text = f"Stopped watching {discord.utils.escape_markdown(choice.name)[:300]}." if removed else "That game is not on your watchlist."
        await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    await game_picker.choose(interaction, choices, selected, "That game is not on your watchlist.")


def _database_status(guild_id):
    with closing(sqlite3.connect(db.DATABASE_PATH)) as conn:
        wishes = conn.execute("SELECT COUNT(*) FROM wishlist WHERE discord_guild_id=?", (str(guild_id),)).fetchone()[0]
        alerts = conn.execute("SELECT COUNT(*) FROM price_watches WHERE discord_guild_id=?", (str(guild_id),)).fetchone()[0]
        return f"ok • {wishes} wishlist entries • {alerts} watches in this server"


async def admin_status(interaction, client):
    if interaction.guild_id is None:
        await interaction.response.send_message(pricing.SERVER_ONLY, ephemeral=True)
        return
    if not interaction.permissions.administrator:
        await interaction.response.send_message("You need Administrator permission to use this command.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    seconds = max(0, int(time.monotonic() - health.STARTED))
    latency = client.latency
    embed = discord.Embed(title="Bot status", color=discord.Color.blurple())
    embed.add_field(name="Version", value=health.version())
    embed.add_field(name="Uptime", value=f"{seconds // 86400}d {(seconds % 86400) // 3600}h {(seconds % 3600) // 60}m")
    embed.add_field(name="Discord", value=(f"connected • {latency * 1000:.0f} ms" if client.is_ready() and math.isfinite(latency) else "not ready"))
    try:
        database = await asyncio.to_thread(_database_status, interaction.guild_id)
    except sqlite3.Error:
        database = "unavailable"
    embed.add_field(name="Database", value=database, inline=False)
    last_price = (f"<t:{int(health.LOOKUPS.last_success.timestamp())}:R>"
                  if health.LOOKUPS.last_success else "none since startup")
    embed.add_field(name="Price lookups", value=f"Last result: {health.LOOKUPS.outcome}\nLast success: {last_price}", inline=False)
    for name, state in health.SOURCES.items():
        last = f"<t:{int(state.last_attempt.timestamp())}:R>" if state.last_attempt else "not checked since startup"
        success = f"<t:{int(state.last_success.timestamp())}:R>" if state.last_success else "none since startup"
        embed.add_field(name=name, value=f"Last HTTP request: {state.outcome} ({last})\nLast success: {success}", inline=False)
    service = client.watches
    embed.add_field(name="Daily watches", value=f"{watches.SCHEDULE} • last run: {service.last_outcome}", inline=False)
    await interaction.followup.send(embed=embed, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
