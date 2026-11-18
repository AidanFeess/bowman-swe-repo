"""Genre metadata and wishlist grouping."""
import json
import re

import requests

import steam


def clean_genres(values):
    """Return unique, nonempty genre names."""
    if not isinstance(values, (list, tuple)):
        return []

    result = []
    seen = set()

    for value in values:
        if not isinstance(value, str):
            continue

        genre = value.strip()

        if (not genre or len(genre) > 60
                or genre.casefold() in seen):
            continue

        result.append(genre)
        seen.add(genre.casefold())

    return result


def _normalized_title(text):
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def lookup(store, name, link):
    """Return genres, or [] if no reliable match exists."""
    try:
        if store == "steam":
            app_id = steam.get_app_id(link)

        elif store in ("epic", "gog"):
            # Reuse Steam genres only for a matching title.
            match = steam.search_game(name)

            app_id = (
                match[0]
                if match and
                _normalized_title(match[1]) == _normalized_title(name)
                else None
            )

        else:
            return []

        if app_id is None:
            return []

        response = requests.get(
            steam.APPDETAILS_URL,
            params={
                "appids": app_id,
                "filters": "genres",
                "cc": "us",
                "l": "english"
            },
            timeout=7
        )

        response.raise_for_status()

        entry = response.json().get(str(app_id), {})
        data = entry.get("data") if entry.get("success") else None

        if not isinstance(data, dict):
            return []

        raw = data.get("genres")

        if not isinstance(raw, list):
            return []

        return clean_genres([
            item.get("description")
            for item in raw
            if isinstance(item, dict)
        ])

    except (
        requests.RequestException,
        KeyError,
        ValueError,
        TypeError,
        AttributeError
    ):
        return []


def group_rows(rows):
    """Group database rows by their final genres column."""
    groups = {}

    for row in rows:
        try:
            labels = clean_genres(json.loads(row[-1]))
        except (TypeError, ValueError):
            labels = []

        for label in labels or ["Unknown"]:
            groups.setdefault(label, []).append(row)

    return sorted(
        groups.items(),
        key=lambda item: (
            item[0] == "Unknown",
            item[0].casefold()
        )
    )
