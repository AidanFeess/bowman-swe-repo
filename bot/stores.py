"""Epic Games Store and GOG store links for the wishlist."""

import re
from urllib.parse import urlsplit

EPIC_HOSTS = {"store.epicgames.com", "www.epicgames.com", "epicgames.com"}
GOG_HOSTS = {"www.gog.com", "gog.com"}

# Epic: /p/<slug>, /en-US/p/<slug>, or the older /store/en-US/p/<slug>
EPIC_PATH = re.compile(r"/(?:store/)?(?:[A-Za-z]{2}(?:-[A-Za-z]{2,4})?/)?p/([A-Za-z0-9_-]{1,100})/?")
# GOG: /game/<slug> or /en/game/<slug>. GOG slugs use underscores.
GOG_PATH = re.compile(r"/(?:[A-Za-z]{2}(?:-[A-Za-z]{2,4})?/)?game/([A-Za-z0-9_]{1,100})/?")

STORE_NAMES = {"steam": "Steam", "epic": "Epic Games Store", "gog": "GOG"}


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