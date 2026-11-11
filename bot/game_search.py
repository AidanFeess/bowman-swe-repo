"""Bounded game searches shared by commands, without choosing an ambiguous result."""

import asyncio
from dataclasses import dataclass
import re
from urllib.parse import quote

import aiohttp

import pricing
import stores

MAX_CHOICES = 10


@dataclass(frozen=True)
class GameChoice:
    name: str
    store: str
    link: str
    steam_id: int | None = None
    catalog_id: str | None = None
    reference_id: int | None = None

    @property
    def key(self):
        if self.steam_id is not None:
            return f"steam:{self.steam_id}"
        if self.catalog_id is not None:
            return f"catalog:{self.catalog_id}"
        return f"{self.store}:{self.reference_id or self.link}"


def normalized(text):
    return re.sub(r"[\W_]+", "", text.casefold())


def rank(choices, text):
    wanted = normalized(text)
    return sorted(choices, key=lambda c: (
        normalized(c.name) != wanted, not normalized(c.name).startswith(wanted)
    ))[:MAX_CHOICES]


def saved_matches(choices, text):
    wanted = normalized(text.strip())
    if not wanted:
        return []
    return rank([c for c in choices if wanted in normalized(c.name)], text)


def _steam_choices(items):
    if not isinstance(items, list):
        raise pricing.PriceSourceError("Invalid Steam search response")
    choices, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise pricing.PriceSourceError("Invalid Steam search item")
        if item.get("type") != "app":
            continue
        app_id, title = item.get("id"), item.get("name")
        if (type(app_id) is not int or not 0 < app_id <= 4294967295
                or not isinstance(title, str) or not title.strip()):
            raise pricing.PriceSourceError("Invalid Steam search item")
        if app_id not in seen:
            choices.append(GameChoice(title.strip(), "steam",
                           f"https://store.steampowered.com/app/{app_id}/", steam_id=app_id))
            seen.add(app_id)
    return choices


async def _search(session, text, store):
    if store == "steam":
        payload = await pricing._get_json(session, pricing.SEARCH_URL,
                                         {"term": text, "cc": "us", "l": "english"})
        if not isinstance(payload, dict):
            raise pricing.PriceSourceError("Invalid Steam search response")
        choices = _steam_choices(payload.get("items"))
        if choices:
            return rank(choices, text)

    # CheapShark also handles compact queries such as "darksouls". Steam IDs
    # provide a precise fallback when Steam's own search returns no matches.
    found = await pricing._get_json(session, pricing.GAMES_URL, {"title": text, "limit": 20})
    if not isinstance(found, list):
        raise pricing.PriceSourceError("Invalid catalog search response")
    candidates, seen = [], set()
    for item in found:
        if not isinstance(item, dict):
            raise pricing.PriceSourceError("Invalid catalog result")
        game_id, title = str(item.get("gameID", "")), item.get("external")
        if not game_id.isdigit() or not isinstance(title, str) or not title.strip():
            raise pricing.PriceSourceError("Invalid catalog result")
        if store == "steam":
            app_id = str(item.get("steamAppID", ""))
            if not app_id.isdigit() or not 0 < int(app_id) <= 4294967295:
                continue
            choice = GameChoice(title.strip(), store,
                                f"https://store.steampowered.com/app/{int(app_id)}/", steam_id=int(app_id))
        else:
            choice = GameChoice(title.strip(), store,
                                stores.SEARCH_LINKS[store].format(quote(title.strip(), safe="")),
                                catalog_id=game_id)
        if choice.key not in seen:
            candidates.append(choice)
            seen.add(choice.key)
    candidates = rank(candidates, text)
    if store == "steam":
        return candidates

    # Confirm the chosen store carries each catalog result, within one deadline.
    semaphore = asyncio.Semaphore(3)

    async def carried(choice):
        async with semaphore:
            details = await pricing._get_json(session, pricing.GAMES_URL, {"id": choice.catalog_id})
            if not isinstance(details, dict) or not isinstance(details.get("deals"), list):
                raise pricing.PriceSourceError("Invalid catalog game response")
            if any(not isinstance(d, dict) for d in details["deals"]):
                raise pricing.PriceSourceError("Invalid catalog offer")
            return choice if any(str(d.get("storeID")) == stores.CHEAPSHARK_STORE_IDS[store]
                                 for d in details["deals"]) else None

    jobs = [asyncio.create_task(carried(c)) for c in candidates]
    try:
        return [c for c in await asyncio.gather(*jobs) if c is not None]
    finally:
        for job in jobs:
            if not job.done():
                job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)


async def search_games(text, store="steam"):
    if store not in stores.STORE_NAMES:
        raise ValueError("Unsupported store")
    text = text.strip()
    if not text:
        return []
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": pricing.USER_AGENT},
                                        timeout=aiohttp.ClientTimeout(total=pricing.LOOKUP_TIMEOUT)) as session:
            return await asyncio.wait_for(_search(session, text, store), pricing.LOOKUP_TIMEOUT)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        raise pricing.PriceSourceError("Game search failed") from exc


async def choice_prices(choice):
    if choice.steam_id is not None:
        return await pricing.lookup_prices(choice.steam_id)
    if choice.catalog_id is not None:
        return await pricing.lookup_catalog_prices(choice.catalog_id)
    if choice.store == "steam":
        raise pricing.PriceSourceError("Saved Steam link has no valid app ID")
    return await pricing.lookup_store_prices(choice.name, choice.store)


def wishlist_choice(name, store, link):
    return GameChoice(name, store, link, steam_id=pricing.parse_steam_link(link) if store == "steam" else None)
