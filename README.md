# Game Night Deal Tracker

A Discord bot that lets a server keep game wishlists. Built for Dr. Bowman's Software Engineering class (CSC 4033, Louisiana Tech).

## Commands
- `/wishlist game:<name or Steam link>` adds a game to your wishlist.
- `/list` shows your own wishlist. Other users' games are not shown.
- `/pullpricing link:<Steam store link>` compares available Steam, Epic Games Store,
  and GOG prices in USD (US region). No wishlist entry is needed.

Example: `/pullpricing link:https://store.steampowered.com/app/292030/`

The reply includes the game name and each available store's current price,
original price, discount percentage, and purchase link. Free offers show `Free`.
Story 3 accepts **Steam app links only**; Epic and GOG are comparison stores,
not accepted input links. See [pricing documentation](docs/pullpricing.md) for
matching rules, error messages, and the manual test checklist.

## Setup
1. Install Python 3.10 or newer (CI uses Python 3.12).
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
   Pricing uses public Steam and CheapShark endpoints; no pricing API key is needed.
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
The automated tests mock pricing services and Discord interactions, so no bot
token is needed. GitHub Actions runs both the bot tests and the project skeleton
tests. Run just Story 3 tests with `python -m unittest -v test_pricing test_pullpricing`.

## Folder layout
- `bot/` has the bot code and tests.
  - `bot.py` has the Discord commands.
  - `handler.py` has the wishlist logic.
  - `steam.py` looks up games on Steam.
  - `pricing.py` matches Steam app IDs to cross-store prices and formats offers.
  - `db.py` and `database.py` save games in SQLite.
  - `view_database.py` prints everything in the database.
- `docs/` has the project documents (contract, learning plan, backlog, stakeholders).

## Team
- Aidan
- Alayna
- Grayson
- Hunter
