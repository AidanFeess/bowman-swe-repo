import steam
import db

BAD_LINK_MSG = (
    "That doesn't look like a Steam store link. "
    "Example: https://store.steampowered.com/app/620/Portal_2/"
)


def add_to_wishlist(guild_id, user_id, link):
    """Returns (status, message). Status is one of:
    added, duplicate, not_found, bad_link, error."""
    link = (link or "").strip()

    try:
        app_id = steam.get_app_id(link)
        if app_id is None:
            return "bad_link", BAD_LINK_MSG

        name = steam.get_game_name(app_id)
        if name is None:
            return "not_found", f"I couldn't find a game with app ID {app_id} on Steam."

        if not db.add_game(guild_id, user_id, app_id, name):
            return "duplicate", f"**{name}** is already on your wishlist."

        return "added", f"Added **{name}** to your wishlist."
    except Exception as e:
        print(f"wishlist error: {e}")
        return "error", "Something went wrong looking that up. Try again in a moment."