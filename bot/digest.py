"""Manual and scheduled wishlist sale digests."""

import asyncio
import datetime
import logging
import os
import sqlite3
from contextlib import closing
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


DEFAULT_TIMEZONE = "America/Chicago"


def current_day(tz):
    """Today's date in the digest's time zone as text, used to ping each user once per day."""
    return datetime.datetime.now(tz).date().isoformat()


def ensure_notification_table():
    """Remember who was pinged about which game, and on which day."""
    with closing(sqlite3.connect(db.DATABASE_PATH)) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS digest_notifications (
                    discord_user_id TEXT NOT NULL,
                    app_id INTEGER NOT NULL,
                    last_notified TEXT NOT NULL,
                    PRIMARY KEY (discord_user_id, app_id)
                )
                """
            )


def get_notified_today(today):
    """Return the (user id, app id) pairs that were already pinged today."""
    with closing(sqlite3.connect(db.DATABASE_PATH)) as connection:
        rows = connection.execute(
            "SELECT discord_user_id, app_id FROM digest_notifications WHERE last_notified = ?",
            (today,),
        ).fetchall()
    return {(int(user_id), app_id) for user_id, app_id in rows}


def mark_notified(user_ids, app_id, today):
    """Record that these users were pinged about this game today."""
    with closing(sqlite3.connect(db.DATABASE_PATH)) as connection:
        with connection:
            connection.executemany(
                "INSERT OR REPLACE INTO digest_notifications "
                "(discord_user_id, app_id, last_notified) VALUES (?, ?, ?)",
                [(str(user_id), app_id, today) for user_id in user_ids],
            )


class Digest:
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = None
        self.tz = ZoneInfo(DEFAULT_TIMEZONE)

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
            # The daily post time is in the digest time zone (Central by default), so
            # 16:00 stays 4 PM through daylight saving changes.
            time_setting = os.getenv("DIGEST_TIME", "20:00").strip()
            zone_setting = os.getenv("DIGEST_TIMEZONE", DEFAULT_TIMEZONE).strip()

            try:
                self.channel_id = int(channel_setting)
                self.tz = ZoneInfo(zone_setting)
                hour, minute = map(int, time_setting.split(":"))
                run_time = datetime.time(hour=hour, minute=minute, tzinfo=self.tz)
            except (ValueError, ZoneInfoNotFoundError):
                # A typo in the settings should not stop the bot from starting.
                logger.error(
                    "Ignoring the digest schedule: DIGEST_CHANNEL_ID must be a number, "
                    "DIGEST_TIME must look like 16:00, and DIGEST_TIMEZONE must be a "
                    "name like America/Chicago"
                )
                self.channel_id = None
                self.bot.tree.add_command(self.command)
                return

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
        await asyncio.to_thread(ensure_notification_table)
        today = current_day(self.tz)
        already_pinged = await asyncio.to_thread(get_notified_today, today)
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
                    (app_id, result.name, sale_offers, sorted(interested_users))
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

        for app_id, name, offers, user_ids in sale_games:
            # Each user is pinged about a game once per day while it stays on sale.
            to_ping = [
                user_id for user_id in user_ids
                if (user_id, app_id) not in already_pinged
            ]

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

            if not to_ping:
                # Everyone was already pinged today, so show the sale quietly.
                await send(
                    "Everyone who wants this game was already pinged today.",
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                continue

            # Put mentions in ordinary message content so they can notify users.
            # Limit each batch to 50 users to stay within Discord limits.
            for start in range(0, len(to_ping), 50):
                batch = to_ping[start:start + 50]

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

                # Record the ping only after it was sent, so a failed send is retried.
                await asyncio.to_thread(mark_notified, batch, app_id, today)

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