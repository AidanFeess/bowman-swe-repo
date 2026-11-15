"""Steam, Epic Games Store and GOG seasonal sale calendar and the /seasonal countdown."""

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import discord


# Steam sales start and end at 10:00 AM Pacific Time.
STEAM_TIMEZONE = ZoneInfo("America/Los_Angeles")
SALE_HOUR = 10

# The time of day each store's sales start and end: (time zone, hour).
# Epic changes its sales at 11 AM Eastern. GOG's start time here is an estimate (2 PM UTC).
STORE_SCHEDULES = {
    "Steam": (STEAM_TIMEZONE, SALE_HOUR),
    "Epic Games Store": (ZoneInfo("America/New_York"), 11),
    "GOG": (ZoneInfo("UTC"), 14),
}
START_TIMES = {
    "Steam": "10 AM Pacific",
    "Epic Games Store": "11 AM Eastern",
    "GOG": "2 PM UTC",
}

NO_UPCOMING = (
    "No upcoming sale is on my calendar yet. "
    "Check store.steampowered.com for the latest schedule."
)
NO_UPCOMING_STORE = "No upcoming sale is on my calendar yet."


@dataclass(frozen=True)
class Sale:
    name: str
    start: datetime.datetime
    end: datetime.datetime
    store: str = "Steam"
    estimated: bool = False  # True until the store announces the dates


def make_sale(name, start, end, store="Steam", estimated=False):
    """start and end are (year, month, day) in the store's time zone."""
    zone, hour = STORE_SCHEDULES[store]
    return Sale(
        name,
        datetime.datetime(*start, hour, tzinfo=zone),
        datetime.datetime(*end, hour, tzinfo=zone),
        store,
        estimated,
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

# Epic Games Store sales. Epic has not announced these yet, so they are estimates
# based on past years (whenisthenextsale.com). Mark a sale estimated=False once Epic announces it,
# and add the next ones (Spring and MEGA Sale 2027) when the dates are known.
EPIC_SALES = (
    make_sale("Black Friday Sale 2026", (2026, 11, 19), (2026, 12, 1), "Epic Games Store", estimated=True),
    make_sale("Holiday Sale 2026", (2026, 12, 17), (2027, 1, 7), "Epic Games Store", estimated=True),
)

# GOG sales. GOG has not announced these yet either, so they are estimates too.
GOG_SALES = (
    make_sale("Black Friday Sale 2026", (2026, 11, 25), (2026, 12, 3), "GOG", estimated=True),
    make_sale("Winter Sale 2026", (2026, 12, 14), (2027, 1, 2), "GOG", estimated=True),
)

ALL_SALES = SALES + EPIC_SALES + GOG_SALES


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


def store_summary(now, sales):
    """The sale that is on now, and the next one, for one store."""
    status = get_status(now, sales)
    lines = []
    if status.running:
        sale = status.running
        lines.append(f"**{sale.name}** is on now! Ends in {time_left(sale.end - now)} ({stamp(sale.end)})")
        if sale.estimated:
            lines[-1] += " *(estimated)*"
    if status.upcoming:
        sale = status.upcoming[0]
        label = "Next: " if status.running else ""
        lines.append(f"{label}**{sale.name}**: starts in {time_left(sale.start - now)} ({stamp(sale.start)})")
        if sale.estimated:
            lines[-1] += " *(estimated)*"
    return "\n".join(lines) or NO_UPCOMING_STORE


def build_embed(now=None, sales=ALL_SALES):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    steam_sales = tuple(sale for sale in sales if sale.store == "Steam")
    status = get_status(now, steam_sales)
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

    # The next sale for each other store
    shown = ["Steam"]
    for store in STORE_SCHEDULES:
        store_sales = tuple(sale for sale in sales if sale.store == store)
        if store == "Steam" or not store_sales:
            continue
        shown.append(store)
        embed.add_field(name=store, value=store_summary(now, store_sales), inline=False)

    if len(shown) == 1:
        embed.set_footer(text="Sales start at 10 AM Pacific Time • Dates can change")
    else:
        starts = ", ".join(f"{START_TIMES[store]} ({store})" for store in shown)
        embed.set_footer(text=f"Sales start at {starts} • Dates can change")
    return embed