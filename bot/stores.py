"""Epic Games Store and GOG store links for the wishlist."""

import re
from urllib.parse import quote, urlsplit
import requests

EPIC_HOSTS = {"store.epicgames.com", "www.epicgames.com", "epicgames.com"}
GOG_HOSTS = {"www.gog.com", "gog.com"}

# Epic: /p/<slug>, /en-US/p/<slug>, or the older /store/en-US/p/<slug>
EPIC_PATH = re.compile(r"/(?:store/)?(?:[A-Za-z]{2}(?:-[A-Za-z]{2,4})?/)?p/([A-Za-z0-9_-]{1,100})/?")
# GOG: /game/<slug> or /en/game/<slug>. GOG slugs use underscores.
GOG_PATH = re.compile(r"/(?:[A-Za-z]{2}(?:-[A-Za-z]{2,4})?/)?game/([A-Za-z0-9_]{1,100})/?")

STORE_NAMES = {"steam": "Steam", "epic": "Epic Games Store", "gog": "GOG"}

# Searching by name goes through CheapShark, the same price service /pullpricing uses.
GAMES_URL = "https://www.cheapshark.com/api/1.0/games"
CHEAPSHARK_STORE_IDS = {"epic": "25", "gog": "7"}
# The store's own search page for the exact title. These links stay the same for the same game.
SEARCH_LINKS = {
    "epic": "https://store.epicgames.com/en-US/browse?q={}",
    "gog": "https://www.gog.com/en/games?query={}",
}
MAX_CANDIDATES = 5   # how many matching games to check for the store
TIMEOUT = 10         # seconds for each web request


class StoreSearchError(Exception):
    """CheapShark failed or sent back something that cannot be used."""


def parse_store_link(text):
    """Returns (store, name, link) for a real Epic Games Store or GOG game link, otherwise None.

    The game name is made from the last part of the link, so it can differ a little from the
    store's own title (for example, no colons). The link is rebuilt in one standard form, so the
    same game pasted with different languages or extra text is still caught as a duplicate."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if any(char.isspace() or ord(char) < 32 for char in text):
        return None
    try:
        url = urlsplit(text)
        if (url.scheme not in ("http", "https")
                or url.username is not None or url.password is not None
                or url.port is not None):
            return None
        host = url.hostname
        if host in EPIC_HOSTS:
            match = EPIC_PATH.fullmatch(url.path)
            if not match:
                return None
            slug = match.group(1).lower()
            return "epic", name_from_slug(slug), f"https://store.epicgames.com/en-US/p/{slug}"
        if host in GOG_HOSTS:
            match = GOG_PATH.fullmatch(url.path)
            if not match:
                return None
            slug = match.group(1).lower()
            return "gog", name_from_slug(slug), f"https://www.gog.com/en/game/{slug}"
    except ValueError:
        return None
    return None


def name_from_slug(slug):
    """the-witcher-3-wild-hunt or the_witcher_3_wild_hunt -> The Witcher 3 Wild Hunt"""
    words = [word for word in re.split(r"[-_]+", slug) if word]
    return " ".join(word.capitalize() for word in words) or slug


def search_store_game(name, store):
    """Looks a game up by name on the Epic Games Store or GOG.
    Returns (title, link) for the best match that is sold on that store, or None if there is none.

    CheapShark finds games by name. An exact title match is checked first, then the other
    matches in the order CheapShark gives them. A game only counts if it has an offer on the
    chosen store. The link opens the store's own search for the exact title."""
    if store not in CHEAPSHARK_STORE_IDS:
        raise ValueError(f"unsupported store: {store}")
    name = (name or "").strip()
    if not name:
        return None

    found = _get_json(GAMES_URL, {"title": name, "limit": 20})
    if not isinstance(found, list) or any(not isinstance(g, dict) for g in found):
        raise StoreSearchError("Invalid CheapShark search response")
    candidates = []
    for game in found:
        game_id, title = str(game.get("gameID", "")), game.get("external")
        if not game_id.isdigit() or not isinstance(title, str) or not title.strip():
            raise StoreSearchError("Invalid CheapShark search result")
        candidates.append((game_id, title.strip()))

    wanted = name.casefold()
    exact = [c for c in candidates if c[1].casefold() == wanted]
    others = [c for c in candidates if c[1].casefold() != wanted]
    store_id = CHEAPSHARK_STORE_IDS[store]

    for game_id, title in (exact + others)[:MAX_CANDIDATES]:
        details = _get_json(GAMES_URL, {"id": game_id})
        if (not isinstance(details, dict) or not isinstance(details.get("deals"), list)
                or any(not isinstance(d, dict) for d in details["deals"])):
            raise StoreSearchError("Invalid CheapShark game response")
        if any(str(deal.get("storeID")) == store_id for deal in details["deals"]):
            info = details.get("info")
            real_title = info.get("title") if isinstance(info, dict) else None
            if isinstance(real_title, str) and real_title.strip():
                title = real_title.strip()
            return title, SEARCH_LINKS[store].format(quote(title, safe=""))
    return None


def _get_json(url, params):
    response = requests.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()