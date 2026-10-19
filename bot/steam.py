import re


def get_app_id(link):
    m = re.search(r"store\.steampowered\.com/app/(\d+)", link)
    return int(m.group(1)) if m else None


def get_game_name(app_id):
    return {620: "Portal 2", 440: "Team Fortress 2"}.get(app_id)