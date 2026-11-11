import steam
import stores
import db

BAD_LINK_MSG = (
    "Type a game name or paste a Steam, Epic Games Store, or GOG link. "
    "Example: https://store.steampowered.com/app/620/Portal_2/"
)


def add_to_wishlist(guild_id, user_id, text, store="steam"):
    """Returns (status, message). Status is one of:
    added, duplicate, not_found, bad_link, error.
    store is where a typed name is searched: steam, epic or gog. A pasted link always wins."""
    text = (text or "").strip()
    if not text:
        return "bad_link", BAD_LINK_MSG

    try:
        store_game = stores.parse_store_link(text)
        if store_game is not None:
            # The user pasted an Epic Games Store or GOG link. The name comes from the link itself.
            return _save_store_game(guild_id, user_id, *store_game)

        is_link = text.lower().startswith(("http://", "https://")) or "steampowered.com" in text.lower()
        if not is_link and store in stores.CHEAPSHARK_STORE_IDS:
            # The user typed a name and chose Epic Games Store or GOG
            match = stores.search_store_game(text, store)
            if match is None:
                label = stores.STORE_NAMES[store]
                return "not_found", (
                    f"I couldn't find a game called \"{text}\" on {label}. "
                    "Try the exact title, or paste its store link."
                )
            title, link = match
            return _save_store_game(guild_id, user_id, store, title, link)

        if is_link:
            # The user pasted a link
            app_id = steam.get_app_id(text)
            if app_id is None:
                return "bad_link", BAD_LINK_MSG
            name = steam.get_game_name(app_id)
            if name is None:
                return "not_found", f"I couldn't find a game with app ID {app_id} on Steam."
        else:
            # The user typed a game name
            match = steam.search_game(text)
            if match is None:
                return "not_found", f"I couldn't find a game called \"{text}\" on Steam."
            app_id, name = match

        if not db.add_game(guild_id, user_id, app_id, name):
            return "duplicate", f"**{name}** is already on your wishlist."

        return "added", f"Added **{name}** to your wishlist."
    except Exception as e:
        print(f"wishlist error: {e}")
        return "error", "Something went wrong looking that up. Try again in a moment."


def _save_store_game(guild_id, user_id, store, name, link):
    label = stores.STORE_NAMES[store]
    if not db.add_store_game(guild_id, user_id, store, link, name):
        return "duplicate", f"**{name}** ({label}) is already on your wishlist."
    return "added", f"Added **{name}** ({label}) to your wishlist."