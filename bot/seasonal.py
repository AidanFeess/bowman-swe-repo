"""Steam seasonal sale calendar and the /seasonal countdown."""

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import discord


# Steam sales start and end at 10:00 AM Pacific Time.
STEAM_TIMEZONE = ZoneInfo("America/Los_Angeles")
SALE_HOUR = 10

NO_UPCOMING = (
    "No upcoming sale is on my calendar yet. "
    "Check store.steampowered.com for the latest schedule."
)


@dataclass(frozen=True)
class Sale:
    name: str
    start: datetime.datetime
    end: datetime.datetime


def make_sale(name, start, end):
    """start and end are (year, month, day) in Steam's time zone."""
    return Sale(
        name,
        datetime.datetime(*start, SALE_HOUR, tzinfo=STEAM_TIMEZONE),
        datetime.datetime(*end, SALE_HOUR, tzinfo=STEAM_TIMEZONE),
    )


# The one place to update when Valve announces new dates.
# Source: Valve's published sale schedule (Steamworks), as listed on steamdb.info/sales/history.
# Add the next Autumn Sale here once Valve announces it.
SALES = (
    make_sale("Spring Sale 2026", (2026, 3, 19), (2026, 3, 26)),
    make_sale("Summer Sale 2026", (2026, 6, 25), (2026, 7, 9)),
    make_sale("Autumn Sale 2026", (2026, 10, 1), (2026, 10, 8)),
    make_sale("Winter Sale 2026", (2026, 12, 17), (2027, 1, 4)),
    make_sale("Spring Sale 2027", (2027, 3, 18), (2027, 3, 25)),
    make_sale("Summer Sale 2027", (2027, 6, 24), (2027, 7, 8)),
)


@dataclass(frozen=True)
class Status:
    running: Sale | None  # the sale that is on right now, if any
    upcoming: tuple  # sales that have not started yet, soonest first


def get_status(now=None, sales=SALES):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    running = next((sale for sale in sales if sale.start <= now < sale.end), None)
    upcoming = tuple(sorted((sale for sale in sales if sale.start > now), key=lambda sale: sale.start))
    return Status(running, upcoming)


def plural(number, word):
    return f"{number} {word}" + ("" if number == 1 else "s")


def time_left(delta):
    """Plain-words length of time, like '46 days, 3 hours' or '5 hours, 12 minutes'."""
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "less than a minute"
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{plural(days, 'day')}, {plural(hours, 'hour')}" if hours else plural(days, "day")
    if hours:
        return f"{plural(hours, 'hour')}, {plural(minutes, 'minute')}" if minutes else plural(hours, "hour")
    return plural(minutes, "minute")


def stamp(moment):
    """Discord shows this in each reader's own time zone."""
    return f"<t:{int(moment.timestamp())}:F>"


def build_embed(now=None, sales=SALES):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    status = get_status(now, sales)
    embed = discord.Embed(color=discord.Color.blurple())

    if status.running:
        sale = status.running
        embed.title = f"{sale.name} is on now!"
        embed.description = f"Ends in **{time_left(sale.end - now)}**.\n{stamp(sale.end)}"
        coming = status.upcoming
        heading = "Coming up"
    elif status.upcoming:
        sale = status.upcoming[0]
        embed.title = f"Next Steam sale: {sale.name}"
        embed.description = f"Starts in **{time_left(sale.start - now)}**.\n{stamp(sale.start)}"
        coming = status.upcoming[1:]
        heading = "After that"
    else:
        embed.title = "Steam seasonal sales"
        embed.description = NO_UPCOMING
        coming = ()
        heading = ""

    if coming:
        embed.add_field(
            name=heading,
            value="\n".join(
                f"**{sale.name}**: in {time_left(sale.start - now)} ({stamp(sale.start)})"
                for sale in coming
            ),
            inline=False,
        )

    embed.set_footer(text="Sales start at 10 AM Pacific Time • Dates can change")
    return embed