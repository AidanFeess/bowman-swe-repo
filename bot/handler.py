import steam
import db

BAD_LINK_MSG = (
    "Type a game name or paste a Steam store link. "
    "Example: https://store.steampowered.com/app/620/Portal_2/"
)


def add_to_wishlist(guild_id, user_id, text):
    """Returns (status, message). Status is one of:
    added, duplicate, not_found, bad_link, error."""
    text = (text or "").strip()
    if not text:
        return "bad_link", BAD_LINK_MSG

    try:
        if text.lower().startswith(("http://", "https://")) or "steampowered.com" in text.lower():
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