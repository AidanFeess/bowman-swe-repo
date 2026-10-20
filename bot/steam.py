import re

import requests

APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"


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