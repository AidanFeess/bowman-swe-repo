"""Price comparisons by Steam link or game name, independent of wishlists and Discord."""

import asyncio
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from urllib.parse import quote, unquote, urlsplit

import aiohttp

INVALID_LINK = "That is not a valid store link"
EMPTY_INPUT = "Enter a game name or Steam store link"
GAME_NOT_FOUND = "Game not found"
NO_PRICES = "No prices found for this game"
UNAVAILABLE = "Prices are temporarily unavailable, try again later"
SERVER_ONLY = "Use this command in a server"
LOOKUP_TIMEOUT = 10
STEAM_URL = "https://store.steampowered.com/api/appdetails"
SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
GAMES_URL = "https://www.cheapshark.com/api/1.0/games"
USER_AGENT = "GameNightDealTracker/1.0 (https://github.com/AidanFeess/bowman-swe-repo)"
# CheapShark store IDs. Input links are limited to Steam; Epic and GOG are comparison stores.
SUPPORTED_STORES = {"1": "Steam", "25": "Epic Games Store", "7": "GOG"}
STORE_IDS = {"epic": "25", "gog": "7"}  # wishlist store name -> CheapShark store ID
MAX_STORE_MATCHES = 3  # how many same-title games to check for a store price


class PriceSourceError(Exception):
    """A price service failed, timed out, or returned an invalid response."""


class GameNotFound(Exception):
    """The Steam search worked, but no game matched the name."""


@dataclass(frozen=True)
class Offer:
    store: str
    current: Decimal
    original: Decimal
    link: str

    @property
    def discount(self):
        if self.original == 0:
            return 0
        return int(((self.original - self.current) * 100 / self.original).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        ))


@dataclass(frozen=True)
class PriceResult:
    name: str
    offers: tuple[Offer, ...] = ()


def looks_like_link(text):
    """True when the input is meant as a web address, so it is checked as a link and not searched as a name."""
    if not isinstance(text, str):
        return False
    text = text.strip()
    if "://" in text or text.startswith("//"):
        return True
    if any(char.isspace() for char in text):
        return False  # game names have spaces, and a link never does
    return bool(re.match(r"(?i)www\.", text) or re.match(r"[\w-]+(\.[\w-]+)+/", text))


def parse_steam_link(text):
    """Accept real Steam app URLs, never a substring or a lookalike hostname."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if any(char.isspace() or ord(char) < 32 for char in text):
        return None
    try:
        url = urlsplit(text)
        if (url.scheme not in ("http", "https")
                or url.hostname != "store.steampowered.com"
                or url.username is not None or url.password is not None
                or url.port is not None):
            return None
        match = re.fullmatch(r"/app/([0-9]{1,10})(?:/[^/]*)?/?", url.path)
        app_id = int(match.group(1)) if match else 0
        return app_id if 0 < app_id <= 4294967295 else None
    except ValueError:
        return None


def _plain_title(title):
    """Lowercase letters and digits only, so "The Witcher 3: Wild Hunt" matches "the witcher 3 wild hunt"."""
    return re.sub(r"[\W_]+", "", title.casefold())


def _money(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or not 0 <= amount <= Decimal("1000000"):
            return None
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def _offer(store, current, original, link):
    current, original = _money(current), _money(original)
    # Missing prices are not free, and inconsistent values are not reliable offers.
    if current is None or original is None or current > original:
        return None
    return Offer(store, current, original, link)


def _steam_offer(data, app_id):
    link = f"https://store.steampowered.com/app/{app_id}/"
    price = data.get("price_overview")
    if isinstance(price, dict) and price.get("currency") == "USD":
        current, original = _money(price.get("final")), _money(price.get("initial"))
        if current is not None and original is not None:
            return _offer("Steam", current / 100, original / 100, link)
    if data.get("is_free") is True:
        return _offer("Steam", 0, 0, link)
    return None


async def _get_json(session, url, params):
    async with session.get(url, params=params) as response:
        response.raise_for_status()
        return await response.json()


async def _find_app_id(session, name):
    """Search Steam by name. An exact title wins, otherwise the top game result is used."""
    payload = await _get_json(session, SEARCH_URL, {"term": name, "cc": "us", "l": "english"})
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise PriceSourceError("Invalid Steam search response")

    games = []
    for item in payload["items"]:
        if not isinstance(item, dict):
            raise PriceSourceError("Invalid Steam search result")
        app_id, title = item.get("id"), item.get("name")
        # A damaged result is a source failure, not proof that the game does not exist.
        if (type(app_id) is not int or not 0 < app_id <= 4294967295
                or not isinstance(title, str) or not title.strip()):
            raise PriceSourceError("Invalid Steam search result")
        if item.get("type") == "app":  # skip bundles, packages, and other non-game results
            games.append((app_id, title))

    if not games:
        raise GameNotFound()
    wanted = name.strip().casefold()
    for app_id, title in games:
        if title.strip().casefold() == wanted:
            return app_id
    return games[0][0]


async def _lookup(session, app_id):
    payload = await _get_json(session, STEAM_URL, {
        "appids": app_id, "filters": "basic,price_overview", "cc": "us", "l": "english",
    })
    if not isinstance(payload, dict) or not isinstance(payload.get(str(app_id)), dict):
        raise PriceSourceError("Invalid Steam response")
    entry = payload[str(app_id)]
    if entry.get("success") is False:
        return PriceResult("")
    data = entry.get("data")
    if (entry.get("success") is not True or not isinstance(data, dict)
            or not isinstance(data.get("name"), str) or not data["name"].strip()
            or str(data.get("steam_appid")) != str(app_id)):
        raise PriceSourceError("Invalid Steam game details")

    offers = {}
    steam_offer = _steam_offer(data, app_id)
    if steam_offer:
        offers["1"] = steam_offer

    games = await _get_json(session, GAMES_URL, {"steamAppID": app_id})
    if not isinstance(games, list) or any(not isinstance(g, dict) for g in games):
        raise PriceSourceError("Invalid CheapShark search response")
    # Never fall back to fuzzy title matching or choose among ambiguous editions.
    ids = {str(g["gameID"]) for g in games
           if str(g.get("steamAppID")) == str(app_id)
           and str(g.get("gameID", "")).isdigit()}
    if len(ids) == 1:
        game = await _get_json(session, GAMES_URL, {"id": ids.pop()})
        if (not isinstance(game, dict) or not isinstance(game.get("info"), dict)
                or not isinstance(game.get("deals"), list)):
            raise PriceSourceError("Invalid CheapShark game response")
        if str(game["info"].get("steamAppID")) == str(app_id):
            for deal in game["deals"]:
                if not isinstance(deal, dict):
                    raise PriceSourceError("Invalid CheapShark deal")
                store_id = str(deal.get("storeID"))
                deal_id = deal.get("dealID")
                if (store_id not in SUPPORTED_STORES or not isinstance(deal_id, str)
                        or not deal_id or len(deal_id) > 256):
                    continue
                if store_id == "1" and steam_offer:
                    continue  # Prefer Steam's current price over the aggregator's snapshot.
                # CheapShark IDs arrive URL encoded. Normalize once to avoid double encoding.
                link = "https://www.cheapshark.com/redirect?dealID=" + quote(unquote(deal_id), safe="")
                offer = _offer(SUPPORTED_STORES[store_id], deal.get("price"),
                               deal.get("retailPrice"), link)
                if offer and (store_id not in offers or offer.current < offers[store_id].current):
                    offers[store_id] = offer
    return PriceResult(data["name"], tuple(offers[s] for s in SUPPORTED_STORES if s in offers))


async def _search_and_lookup(session, query):
    if type(query) is int:
        app_id = query
    else:
        if not isinstance(query, str) or not query.strip():
            raise GameNotFound()
        app_id = await _find_app_id(session, query.strip())
    return await _lookup(session, app_id)


async def _lookup_store(session, name, store):
    """Find a game by its exact title on CheapShark and return its price on one store."""
    store_id = STORE_IDS[store]
    found = await _get_json(session, GAMES_URL, {"title": name, "limit": 20})
    if not isinstance(found, list) or any(not isinstance(g, dict) for g in found):
        raise PriceSourceError("Invalid CheapShark search response")

    wanted = _plain_title(name)
    game_ids = []
    for game in found:
        game_id, title = str(game.get("gameID", "")), game.get("external")
        if not game_id.isdigit() or not isinstance(title, str):
            raise PriceSourceError("Invalid CheapShark search result")
        # Only the same title counts. A close match (Hades II for Hades) is a different game.
        if wanted and _plain_title(title) == wanted:
            game_ids.append(game_id)

    best, best_title = None, name
    for game_id in game_ids[:MAX_STORE_MATCHES]:
        game = await _get_json(session, GAMES_URL, {"id": game_id})
        if not isinstance(game, dict) or not isinstance(game.get("deals"), list):
            raise PriceSourceError("Invalid CheapShark game response")
        info = game.get("info")
        for deal in game["deals"]:
            if not isinstance(deal, dict):
                raise PriceSourceError("Invalid CheapShark deal")
            deal_id = deal.get("dealID")
            if (str(deal.get("storeID")) != store_id or not isinstance(deal_id, str)
                    or not deal_id or len(deal_id) > 256):
                continue
            link = "https://www.cheapshark.com/redirect?dealID=" + quote(unquote(deal_id), safe="")
            offer = _offer(SUPPORTED_STORES[store_id], deal.get("price"), deal.get("retailPrice"), link)
            if offer and (best is None or offer.current < best.current):
                best = offer
                if isinstance(info, dict) and isinstance(info.get("title"), str) and info["title"].strip():
                    best_title = info["title"].strip()
    return PriceResult(best_title, (best,) if best else ())


async def lookup_store_prices(name, store):
    """Look up the price of a game on the Epic Games Store ("epic") or GOG ("gog") by its title.

    Returns a PriceResult with one offer, or none when that store has no price for a game
    with exactly this title. Uses the same 10-second budget as lookup_prices."""
    if store not in STORE_IDS:
        raise ValueError(f"unsupported store: {store}")
    if not isinstance(name, str) or not name.strip():
        return PriceResult("")
    try:
        async with aiohttp.ClientSession(
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=LOOKUP_TIMEOUT),
        ) as session:
            return await asyncio.wait_for(_lookup_store(session, name.strip(), store), timeout=LOOKUP_TIMEOUT)
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as exc:
        raise PriceSourceError("Price lookup failed") from exc


async def lookup_prices(query):
    """Look up prices by Steam app ID (a number) or by game name (text).

    One cancellable, 10-second budget covers the whole lookup, the search included, not each step.
    The session is opened before the clock starts, so only the web requests use up the budget."""
    try:
        async with aiohttp.ClientSession(
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=LOOKUP_TIMEOUT),
        ) as session:
            return await asyncio.wait_for(_search_and_lookup(session, query), timeout=LOOKUP_TIMEOUT)
    except (asyncio.TimeoutError, aiohttp.ClientError, ValueError) as exc:
        raise PriceSourceError("Price lookup failed") from exc


def format_offer(offer):
    current = "Free" if offer.current == 0 else f"${offer.current:.2f}"
    return (f"Current price: **{current}**\n"
            f"Original price: ${offer.original:.2f}\n"
            f"Discount: {offer.discount}%\n"
            f"[Buy on {offer.store}]({offer.link})")