import re

import requests

APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
SEARCH_URL = "https://store.steampowered.com/api/storesearch/"


def get_app_id(link):
    m = re.search(r"store\.steampowered\.com/app/(\d+)", link or "")
    return int(m.group(1)) if m else None


def get_game_name(app_id):
    resp = requests.get(
        APPDETAILS_URL,
        params={"appids": app_id, "filters": "basic", "cc": "us", "l": "english"},
        timeout=10,
    )
    resp.raise_for_status()
    entry = resp.json().get(str(app_id))
    if not entry or not entry.get("success"):
        return None
    return entry["data"].get("name")


def search_game(name):
    """Returns (app_id, name) for the best match, or None if Steam finds nothing."""
    resp = requests.get(
        SEARCH_URL,
        params={"term": name, "cc": "us", "l": "english"},
        timeout=10,
    )
    resp.raise_for_status()
    items = [i for i in resp.json().get("items", []) if i.get("type", "app") == "app"]
    if not items:
        return None
    for item in items:                      # prefer an exact name match
        if item["name"].lower() == name.lower():
            return item["id"], item["name"]
    return items[0]["id"], items[0]["name"]  # otherwise the top result