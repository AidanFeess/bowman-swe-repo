"""Daily wishlist sale digest, sent as a private message to each user."""

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

DEFAULT_TIMEZONE = "America/Chicago"
GAMES_PER_MESSAGE = 5  # one DM holds up to 5 game cards, so it stays under Discord's size limits


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


def current_day(tz):
    """Today's date in the digest's time zone as text, used to message each user once per day."""
    return datetime.datetime.now(tz).date().isoformat()


def ensure_notification_table():
    """Remember who was messaged about which game, and on which day."""
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
    """Return the (user id, app id) pairs that were already messaged today."""
    with closing(sqlite3.connect(db.DATABASE_PATH)) as connection:
        rows = connection.execute(
            "SELECT discord_user_id, app_id FROM digest_notifications WHERE last_notified = ?",
            (today,),
        ).fetchall()
    return {(int(user_id), app_id) for user_id, app_id in rows}


def mark_notified(user_id, app_ids, today):
    """Record that this user was messaged about these games today."""
    with closing(sqlite3.connect(db.DATABASE_PATH)) as connection:
        with connection:
            connection.executemany(
                "INSERT OR REPLACE INTO digest_notifications "
                "(discord_user_id, app_id, last_notified) VALUES (?, ?, ?)",
                [(str(user_id), app_id, today) for app_id in app_ids],
            )


def build_embed(name, offers, wanted_by):
    """One card per game with the sale prices."""
    embed = discord.Embed(
        title=discord.utils.escape_markdown(name)[:256],
        description=f"**{wanted_by} user(s)** want this game.",
        color=discord.Color.green(),
    )
    for offer in offers:
        embed.add_field(
            name=offer.store,
            value=pricing.format_offer(offer),
            inline=False,
        )
    embed.set_footer(text="Sources: Steam and CheapShark • Check prices before buying")
    return embed


class Digest:
    def __init__(self, bot):
        self.bot = bot
        self.guild_id = None
        self.tz = ZoneInfo(DEFAULT_TIMEZONE)

        # Prevent manual and scheduled digests from overlapping in one server.
        self.server_locks = {}

        # Save the Command object so it remains attached to this service.
        self.command = app_commands.Command(
            name="digest",
            description="DM me my wishlist games that are on sale",
            callback=self.manual_digest,
        )
        self.command.guild_only = True

    def register(self):
        """Register /digest and optionally start the daily schedule."""
        guild_setting = os.getenv("DIGEST_GUILD_ID", "").strip()

        if guild_setting:
            # The daily time is in the digest time zone (Central by default), so
            # 16:00 stays 4 PM through daylight saving changes.
            time_setting = os.getenv("DIGEST_TIME", "16:00").strip()
            zone_setting = os.getenv("DIGEST_TIMEZONE", DEFAULT_TIMEZONE).strip()

            try:
                self.guild_id = int(guild_setting)
                self.tz = ZoneInfo(zone_setting)
                hour, minute = map(int, time_setting.split(":"))
                run_time = datetime.time(hour=hour, minute=minute, tzinfo=self.tz)
            except (ValueError, ZoneInfoNotFoundError):
                # A typo in the settings should not stop the bot from starting.
                logger.error(
                    "Ignoring the digest schedule: DIGEST_GUILD_ID must be a number, "
                    "DIGEST_TIME must look like 16:00, and DIGEST_TIMEZONE must be a "
                    "name like America/Chicago"
                )
                self.guild_id = None
                self.bot.tree.add_command(self.command)
                return

            self.daily_digest.change_interval(time=run_time)

        self.bot.tree.add_command(self.command)

        if self.guild_id is not None:
            self.daily_digest.start()

    async def manual_digest(self, interaction: discord.Interaction):
        """Handle /digest: DM the person who ran it their own wishlist games that are on sale."""
        if interaction.guild is None:
            await interaction.response.send_message(
                "Use this command in a server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        async def reply(text):
            await interaction.followup.send(
                text,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        try:
            await self.generate_digest(
                interaction.guild, reply, only_user_id=interaction.user.id
            )
        except Exception:
            logger.exception("Manual digest failed")
            await reply("Sorry, I couldn't finish the digest. Please try again later.")

    async def generate_digest(self, guild, report, only_user_id=None):
        """Shared entry point for manual and scheduled runs.

        report(text) receives a short summary of what happened.
        With only_user_id set (the /digest command), only that user's games are checked
        and only that user is messaged. Without it (the daily run), everyone is."""
        lock = self.server_locks.setdefault((guild.id, only_user_id), asyncio.Lock())

        if lock.locked():
            await report("A digest is already being generated, please wait a moment.")
            return

        async with lock:
            await self._build_and_send(guild, report, only_user_id)

    async def _build_and_send(self, guild, report, only_user_id=None):
        personal = only_user_id is not None
        await asyncio.to_thread(ensure_notification_table)
        today = current_day(self.tz)
        rows = await asyncio.to_thread(get_saved_games)

        if personal:
            # Someone asking for their own sales always gets an answer. The send is still
            # recorded, so the daily run does not send the same sale again today.
            already_sent = set()
            rows = [row for row in rows if int(row[0]) == only_user_id]
        else:
            already_sent = await asyncio.to_thread(get_notified_today, today)

        # Find which saved users still belong to this server.
        # fetch_member works without enabling the full members-list intent.
        members = {}
        user_ids = {int(user_id) for user_id, _ in rows}

        for user_id in sorted(user_ids):
            member = guild.get_member(user_id)

            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except discord.NotFound:
                    continue

            if not member.bot:
                members[user_id] = member

        # Group by Steam app ID.
        # A set ensures each user is counted once per game.
        games = {}

        for user_id, link in rows:
            user_id = int(user_id)

            if user_id not in members:
                continue

            app_id = pricing.parse_steam_link(link)

            if app_id is not None:
                games.setdefault(app_id, set()).add(user_id)

        if not games:
            await report(
                "You don't have any Steam games on your wishlist. Use `/wishlist` to add one."
                if personal
                else "No supported wishlist games were found for members of this server."
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

        # Collect each user's own sale games. A game they were already messaged
        # about today is skipped, so each user hears about a sale once per day.
        per_user = {}
        users_with_sales = set()

        for app_id, name, offers, interested in sale_games:
            embed = build_embed(name, offers, len(interested))

            for user_id in interested:
                users_with_sales.add(user_id)

                if (user_id, app_id) not in already_sent:
                    per_user.setdefault(user_id, []).append((app_id, embed))

        messaged = 0
        dms_closed = 0
        failed = 0

        for user_id, items in per_user.items():
            member = members[user_id]
            delivered = True

            for start in range(0, len(items), GAMES_PER_MESSAGE):
                chunk = items[start:start + GAMES_PER_MESSAGE]
                intro = (
                    "Games on your wishlist are on sale:"
                    if start == 0
                    else "More games on your wishlist are on sale:"
                )

                try:
                    await member.send(intro, embeds=[embed for _, embed in chunk])
                except discord.Forbidden:
                    # The user has DMs from server members turned off.
                    logger.info("Could not DM user %s (DMs closed)", user_id)
                    dms_closed += 1
                    delivered = False
                    break
                except discord.HTTPException:
                    logger.exception("Could not DM user %s", user_id)
                    failed += 1
                    delivered = False
                    break

                # Record the message only after it was sent, so a failed send is retried.
                await asyncio.to_thread(
                    mark_notified, user_id, [app_id for app_id, _ in chunk], today
                )

            if delivered:
                messaged += 1

        if personal:
            lines = []

            if not sale_games:
                lines.append(
                    "No confirmed sales found among your games."
                    if unavailable
                    else "None of your wishlist games are on sale right now."
                )
            elif messaged:
                lines.append(
                    f"Sent you a private message with {len(sale_games)} game(s) on sale."
                )
            elif dms_closed:
                lines.append(
                    "I couldn't send you a private message. Turn on direct messages from "
                    "server members in this server's privacy settings, then try again."
                )
            else:
                lines.append("Sorry, the message failed to send. Please try again later.")

            if unavailable:
                lines.append(
                    f"Prices were unavailable for {unavailable} game(s). Try again later."
                )

            await report("\n".join(lines))
            return

        lines = ["**Wishlist Sale Digest**"]

        if sale_games:
            lines.append(f"{len(sale_games)} game(s) on sale.")
            lines.append(f"Sent a private message to {messaged} user(s).")

            already = len(users_with_sales) - len(per_user)
            if already:
                lines.append(f"{already} user(s) were already messaged today.")
            if dms_closed:
                lines.append(f"{dms_closed} user(s) have private messages turned off.")
            if failed:
                lines.append(f"{failed} message(s) failed to send.")
        elif unavailable:
            lines.append("No confirmed sales found among the games checked.")
        else:
            lines.append("No wishlist games are on sale right now.")

        if unavailable:
            lines.append(f"Prices were unavailable for {unavailable} game(s). Try again later.")

        await report("\n".join(lines))

    async def _log_report(self, text):
        logger.info("Scheduled digest finished: %s", text.replace("\n", " | "))

    @tasks.loop(hours=24)
    async def daily_digest(self):
        """Send the digest to the configured server's users at the configured daily time."""
        try:
            guild = self.bot.get_guild(self.guild_id) or await self.bot.fetch_guild(self.guild_id)
            await self.generate_digest(guild, self._log_report)
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