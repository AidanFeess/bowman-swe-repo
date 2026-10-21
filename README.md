# Game Night Deal Tracker

A Discord bot that lets a server keep game wishlists. Built for Dr. Bowman's Software Engineering class (CSC 4033, Louisiana Tech).

## Commands
- `/wishlist game:<name or Steam link>` adds a game to your wishlist.
- `/list` shows your own wishlist. Other users' games are not shown.

## Setup
1. Install Python 3.
2. Install the requirements. In the `bot` folder, run:
```
   pip install -r requirements.txt
```
3. Copy `.env.example` to `.env` and fill in your values:
```
   DISCORD_TOKEN=your_bot_token
   TEST_GUILD_ID=your_server_id
```
   Never commit `.env`.
4. Start the bot:
```
   python bot.py
```
   The bot is only online while this is running. The `wishlist.db` file is created automatically on first start.

## Tests
In the `bot` folder, run:
```
python -m unittest -v
```

## Folder layout
- `bot/` has the bot code and tests.
  - `bot.py` has the Discord commands.
  - `handler.py` has the wishlist logic.
  - `steam.py` looks up games on Steam.
  - `db.py` and `database.py` save games in SQLite.
  - `view_database.py` prints everything in the database.
- `docs/` has the project documents (contract, learning plan, backlog, stakeholders).

## Team
- Aidan
- Alayna
- Grayson
- Hunter
