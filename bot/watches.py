"""Daily target-price checks and private alerts, independent of the daily digest."""

import asyncio
from datetime import datetime, time
import logging
from zoneinfo import ZoneInfo

import discord
from discord.ext import tasks

import game_search
import pricing
import watch_db

logger = logging.getLogger(__name__)
ZONE = ZoneInfo("America/Chicago")
CHECK_TIME = time(16, 0, tzinfo=ZONE)
SCHEDULE = "daily at 4 PM Central time"


class WatchService:
    def __init__(self, bot):
        self.bot = bot
        self.run_lock = asyncio.Lock()
        # Mutations and final delivery share a lock. A deletion or changed target
        # during a price request is rechecked before any alert is sent.
        self.mutation_lock = asyncio.Lock()
        self.last_run = None
        self.last_outcome = "not checked"

    async def save(self, guild_id, user_id, choice, cents):
        async with self.mutation_lock:
            return await asyncio.to_thread(watch_db.save, guild_id, user_id, choice, cents)

    async def remove(self, guild_id, user_id, watch_id):
        async with self.mutation_lock:
            return await asyncio.to_thread(watch_db.remove, guild_id, user_id, watch_id)

    @tasks.loop(time=CHECK_TIME)
    async def daily_checks(self):
        try:
            await self.run_checks()
        except Exception:
            self.last_outcome = "failed"
            logger.exception("Daily watch check failed")

    @daily_checks.before_loop
    async def before_checks(self):
        await self.bot.wait_until_ready()

    def start(self):
        if not self.daily_checks.is_running():
            self.daily_checks.start()

    def stop(self):
        self.daily_checks.cancel()

    async def run_checks(self, day=None):
        if self.run_lock.locked():
            return
        async with self.run_lock:
            self.last_run = datetime.now(ZONE)
            day = day or self.last_run.date().isoformat()
            self.last_outcome = "running"
            failed = False
            cache = {}
            for row in await asyncio.to_thread(watch_db.rows):
                if row["last_checked_day"] == day:
                    continue
                guild = self.bot.get_guild(int(row["discord_guild_id"]))
                if guild is None:
                    continue
                try:
                    member = guild.get_member(int(row["discord_user_id"]))
                    if member is None:
                        member = await guild.fetch_member(int(row["discord_user_id"]))
                    if member.bot:
                        continue
                    selected = watch_db.choice(row)
                    if selected.key not in cache:
                        try:
                            cache[selected.key] = await game_search.choice_prices(selected)
                        except pricing.PriceSourceError:
                            cache[selected.key] = None
                    result = cache[selected.key]
                    if result is None or not result.offers:
                        failed = True
                        continue  # Missing prices never count as free or reset notification state.
                    cheapest = min(result.offers, key=lambda offer: offer.current)
                    cents = int(cheapest.current * 100)
                    async with self.mutation_lock:
                        fresh = await asyncio.to_thread(watch_db.current, row["id"], row["revision"])
                        if fresh is None or fresh["last_checked_day"] == day:
                            continue
                        notified = fresh["notified_cents"]
                        if cents > fresh["target_cents"]:
                            notified = None  # Re-arm for a later sale that reaches the target again.
                        elif notified is None or cents < notified:
                            embed = discord.Embed(
                                title=discord.utils.escape_markdown(result.name or row["game"])[:256],
                                description=f"Your target of ${fresh['target_cents'] / 100:.2f} USD was reached.",
                                color=discord.Color.green(),
                            )
                            embed.add_field(name=cheapest.store, value=pricing.format_offer(cheapest), inline=False)
                            embed.set_footer(text=f"{guild.name} • US prices • Manage alerts with /watchlist and /unwatch"[:2048])
                            await member.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                            notified = cents  # Record only after Discord accepted the DM.
                        await asyncio.to_thread(watch_db.checked, row["id"], row["revision"], day, notified)
                except discord.NotFound:
                    continue  # A member who left the server must not receive its alerts.
                except Exception:
                    failed = True
                    logger.exception("Watch check or delivery failed")
            self.last_outcome = "partial failure" if failed else "ok"
