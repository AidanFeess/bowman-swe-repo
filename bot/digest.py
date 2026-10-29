"""Manual and scheduled wishlist sale digests."""

import asyncio
import datetime
import logging
import os
import sqlite3
from contextlib import closing

import discord
from discord import app_commands
from discord.ext import tasks

import db
import pricing


logger = logging.getLogger(__name__)


def get_saved_games():
    """Read wishlist entries using the existing database connection path."""
    with closing(sqlite3.connect(db.DATABASE_PATH)) as connection:
        return connection.execute(
            """
            SELECT discord_user_id, link
            FROM wishlist
            ORDER BY id
            """
        ).fetchall()


class Digest:
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = None

        # Prevent manual and scheduled digests from overlapping in one server.
        self.server_locks = {}

        # Save the Command object so it remains attached to this service.
        self.command = app_commands.Command(
            name="digest",
            description="Show wishlist games on sale and notify interested users",
            callback=self.manual_digest,
        )
        self.command.guild_only = True

    def register(self):
        """Register /digest and optionally start the daily schedule."""
        channel_setting = os.getenv("DIGEST_CHANNEL_ID", "").strip()

        if channel_setting:
            self.channel_id = int(channel_setting)

            # Example: 15:00 means 3 PM UTC.
            time_setting = os.getenv("DIGEST_TIME_UTC", "15:00").strip()
            hour, minute = map(int, time_setting.split(":"))

            run_time = datetime.time(
                hour=hour,
                minute=minute,
                tzinfo=datetime.timezone.utc,
            )
            self.daily_digest.change_interval(time=run_time)

        self.bot.tree.add_command(self.command)

        if self.channel_id is not None:
            self.daily_digest.start()

    async def manual_digest(self, interaction: discord.Interaction):
        """Handle /digest."""
        if interaction.guild is None:
            await interaction.response.send_message(
                "Use this command in a server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        try:
            await self.generate_digest(
                interaction.guild,
                interaction.followup.send,
            )
        except Exception:
            logger.exception("Manual digest failed")
            await interaction.followup.send(
                "Sorry, I couldn't finish the digest. Please try again later.",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def generate_digest(self, guild, send):
        """Shared entry point for manual and scheduled runs."""
        lock = self.server_locks.setdefault(guild.id, asyncio.Lock())

        if lock.locked():
            await send(
                "A digest is already being generated for this server.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        async with lock:
            await self._build_and_send(guild, send)

    async def _build_and_send(self, guild, send):
        rows = await asyncio.to_thread(get_saved_games)

        # Find which saved users still belong to this server.
        # fetch_member works without enabling the full members-list intent.
        member_ids = set()
        user_ids = {int(user_id) for user_id, _ in rows}

        for user_id in sorted(user_ids):
            member = guild.get_member(user_id)

            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.NotFound:
                    continue

            if not member.bot:
                member_ids.add(user_id)

        # Group by Steam app ID.
        # A set ensures each user is counted once per game.
        games = {}

        for user_id, link in rows:
            user_id = int(user_id)

            if user_id not in member_ids:
                continue

            app_id = pricing.parse_steam_link(link)

            if app_id is not None:
                games.setdefault(app_id, set()).add(user_id)

        if not games:
            await send(
                "No supported wishlist games were found for members of "
                "this server. Use `/wishlist` to add a Steam game.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        sale_games = []
        unavailable = 0

        # Reuse the same lookup function as /pullpricing.
        for app_id, interested_users in games.items():
            try:
                result = await pricing.lookup_prices(app_id)
            except pricing.PriceSourceError:
                unavailable += 1
                logger.warning("Could not check prices for Steam app %s", app_id)
                continue

            if not result.offers:
                unavailable += 1
                continue

            # A permanently free game is not a sale.
            # A normally paid game temporarily offered for free is a sale.
            sale_offers = [
                offer
                for offer in result.offers
                if offer.current < offer.original
            ]

            if sale_offers:
                sale_games.append(
                    (result.name, sale_offers, sorted(interested_users))
                )

        if sale_games:
            summary = (
                f"**Wishlist Sale Digest**\n"
                f"{len(sale_games)} game(s) on sale.\n"
                "Prices in USD (US region)."
            )
        elif unavailable:
            summary = (
                "**Wishlist Sale Digest**\n"
                "No confirmed sales found among the games checked."
            )
        else:
            summary = (
                "**Wishlist Sale Digest**\n"
                "No wishlist games are on sale right now."
            )

        if unavailable:
            summary += (
                f"\nPrices were unavailable for {unavailable} game(s). "
                "Try again later."
            )

        await send(
            summary,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        for name, offers, user_ids in sale_games:
            # One embed per game keeps the information together.
            embed = discord.Embed(
                title=discord.utils.escape_markdown(name)[:256],
                description=f"**{len(user_ids)} user(s)** want this game.",
                color=discord.Color.green(),
            )

            for offer in offers:
                embed.add_field(
                    name=offer.store,
                    value=pricing.format_offer(offer),
                    inline=False,
                )

            embed.set_footer(
                text="Sources: Steam and CheapShark • Check prices before buying"
            )

            # Put mentions in ordinary message content so they can notify users.
            # Limit each batch to 50 users to stay within Discord limits.
            for start in range(0, len(user_ids), 50):
                batch = user_ids[start:start + 50]

                content = "Sale alert: " + " ".join(
                    f"<@{user_id}>" for user_id in batch
                )

                options = {
                    "allowed_mentions": discord.AllowedMentions(
                        everyone=False,
                        roles=False,
                        users=[
                            discord.Object(id=user_id)
                            for user_id in batch
                        ],
                        replied_user=False,
                    )
                }

                # Show the game's details with each batch of recipients.
                await send(content, embed=embed, **options)

    @tasks.loop(hours=24)
    async def daily_digest(self):
        """Post in the configured channel at the configured daily time."""
        try:
            channel = await self.bot.fetch_channel(self.channel_id)

            if not isinstance(channel, discord.TextChannel):
                logger.error(
                    "DIGEST_CHANNEL_ID must identify a server text channel"
                )
                return

            await self.generate_digest(channel.guild, channel.send)

        except Exception:
            # Log the failure without stopping future daily runs.
            logger.exception("Scheduled digest failed")

    @daily_digest.before_loop
    async def wait_until_ready(self):
        await self.bot.wait_until_ready()

    def stop(self):
        self.daily_digest.cancel()


def setup(bot):
    """Called once from bot.py's setup_hook."""
    service = Digest(bot)
    service.register()
    return service