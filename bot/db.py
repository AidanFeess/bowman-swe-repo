_games = set()


def init_db():
    pass


def add_game(guild_id, user_id, app_id, name):
    key = (guild_id, user_id, app_id)
    if key in _games:
        return False
    _games.add(key)
    return True