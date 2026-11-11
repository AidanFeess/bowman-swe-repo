# Game Night Deal Tracker

A Discord bot that lets a server keep game wishlists, compare prices, and send each member a daily message about their wishlist games that are on sale. Built for Dr. Bowman's Software Engineering class (CSC 4033, Louisiana Tech).

## Commands
- `/wishlist game:<name or Steam link>` adds a game to your wishlist.
- `/list` shows your own wishlist. Other users' games are not shown.
- `/remove game:<name>` removes a game from your wishlist. Suggestions from your own wishlist appear as you type.
- `/pullpricing game:<name or Steam store link>` compares available Steam, Epic Games Store,
  and GOG prices in USD (US region). No wishlist entry is needed.
- `/digest` sends you a private message with your own wishlist games that are on sale, with prices.
- `/seasonal` shows how long until the next Steam seasonal sale.

Examples: `/pullpricing game:Portal 2` or
`/pullpricing game:https://store.steampowered.com/app/292030/`

The reply includes the game name and each available store's current price,
original price, discount percentage, and purchase link. Free offers show `Free`.
Names prefer an exact Steam title match (ignoring capitalization), otherwise the
top Steam app result. The reply shows the matched game's name. Search and pricing
share one 10-second timeout. Empty input returns `Enter a game name or Steam store link`;
a name with no search results returns `Game not found`. Epic and GOG are comparison
stores, not accepted input links. See [pricing documentation](docs/pullpricing.md) for
matching rules, error messages, and the manual test checklist.

## Daily digest
The bot sends each member a private message (DM) with their own wishlist games that are on sale. Nobody sees anyone else's games, and nothing is posted in a channel.

- **Automatic:** every day at 4 PM Central time the bot checks every member's wishlist. A game on sale is sent once per day, and again the next day while it is still on sale. When the sale ends, the messages stop.
- **On demand:** `/digest` does the same check for you only. It always answers when you run it, and the reply in the server is private. A game you were just sent will not be sent again by the 4 PM run that day.
- **What counts as a sale:** the current price is lower than the original price (a normally paid game that is free for a limited time counts). Games that are always free do not. Only Steam games are checked.
- **Closed DMs:** if direct messages from server members are turned off, the bot cannot send the digest. `/digest` tells you so, and the automatic run tries again the next day.

The automatic run starts only when `DIGEST_GUILD_ID` is set (see Setup). The bot must be running at 4 PM for it to send.

## Seasonal sales
`/seasonal` shows the Steam seasonal sale that is running now, or the next one coming, with the time left and the dates in your own time zone. It also lists the sales after that. It covers the Spring, Summer, Autumn, and Winter sales, and the reply is private.

Steam has no API for sale dates, so the dates are kept in the `SALES` list in `bot/seasonal.py`, taken from Valve's published schedule. Sales start and end at 10 AM Pacific Time. The list currently runs through the Summer Sale 2027. When Valve announces new dates (the next one is the Autumn Sale 2027), add one `make_sale(...)` line to that list. If no sale is left on the calendar, the command says so.

## Rate limiting
To stop command spamming, the bot limits how fast one person can use commands. A person is first warned in the channel. If they keep going they are blocked for 10 seconds, with a "slow down" picture, and then can use commands again. There is also a limit on all users together, so one busy moment cannot overload the bot. The limits are set in `bot/ratelimit.py`.

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
   DIGEST_GUILD_ID=your_server_id
```
   Never commit `.env`.
   - `DISCORD_TOKEN` is the bot token from the Discord Developer Portal.
   - `TEST_GUILD_ID` is the server where commands appear instantly while testing.
   - `DIGEST_GUILD_ID` is the server whose members get the daily digest. Leave it out to turn the automatic digest off (`/digest` still works).
   - Optional: `DIGEST_TIME` (24-hour time, default `16:00`) and `DIGEST_TIMEZONE` (default `America/Chicago`) change when the digest runs. Restart the bot after changing them.

   Pricing uses public Steam and CheapShark endpoints; no pricing API key is needed.
4. Start the bot:
```
   python bot.py
```
   The bot is only online while this is running. The `wishlist.db` file is created automatically on first start.

To receive digest messages, turn on "Direct Messages" from server members in the server's privacy settings.

## Server deployment

The bot is deployed on `172.25.255.101` as `game-night-bot.service`. It starts on
boot and restarts automatically after a crash. `game-night-bot-update.timer`
checks GitHub `main` every 15 minutes. New commits are built and tested separately
before a restart; failed startup restores the previous code and database backup.
An unchanged commit does not restart the bot. Connect with
`ssh root@172.25.255.101`, then use:

```sh
systemctl start game-night-bot
systemctl stop game-night-bot
systemctl restart game-night-bot
systemctl status game-night-bot --no-pager
journalctl -u game-night-bot -f
systemctl start game-night-bot-update
journalctl -u game-night-bot-update -n 40 --no-pager
```

Settings are in `/etc/game-night-bot.env` (root-only). Wishlist and notification
data persist in `/var/lib/game-night-bot/wishlist.db`. See
[deployment instructions](docs/deployment.md) for installation, updates, and backups.

## Tests
In the `bot` folder, run:
```
python -m unittest -v
```
The automated tests mock pricing services and Discord interactions, so no bot
token is needed. GitHub Actions runs both the bot tests and the project skeleton
tests. Run just Story 3 tests with `python -m unittest -v test_pricing test_pullpricing`.
Run just the digest or seasonal tests with `python -m unittest -v test_digest` or `python -m unittest -v test_seasonal`.

## Folder layout
- `bot/` has the bot code and tests.
  - `bot.py` has the Discord commands.
  - `handler.py` has the wishlist logic.
  - `steam.py` looks up games on Steam.
  - `pricing.py` searches game names, matches Steam app IDs to cross-store prices, and formats offers.
  - `digest.py` builds and sends the daily digest and the `/digest` command.
  - `seasonal.py` has the Steam sale calendar and the `/seasonal` countdown.
  - `ratelimit.py` has the command rate limiter (`slow_down.png` is the picture it posts).
  - `db.py` and `database.py` save games in SQLite.
  - `view_database.py` prints everything in the database.
- `docs/` has the project documents (contract, learning plan, backlog, stakeholders).

## Team
- Aidan
- Alayna
- Grayson
- Hunter
