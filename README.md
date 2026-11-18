# Game Night Deal Tracker

A Discord bot that lets a server keep game wishlists, compare prices, and send each member a message about their wishlist games that are on sale. Built for Dr. Bowman's Software Engineering class (CSC 4033, Louisiana Tech).

## Commands
- `/wishlist game:<name or store link> [store:<store>]` adds a game to your wishlist. Use a game name, a Steam link, an Epic Games Store link, or a GOG link. The optional `store` choice (Steam, Epic Games Store, or GOG) limits a name search to one store; press Tab to pick it. With no store chosen, the bot searches Steam.
- `/list` shows your own wishlist grouped by genre. A game with more than one genre is listed under each of them. Games with no recognized genre are listed under Unknown at the bottom. Other users' games are not shown.
- `/remove game:<name>` removes a game from your wishlist. Suggestions from your own wishlist appear as you type.
- `/pullpricing game:<name or Steam store link> [store:<store>]` compares available Steam, Epic Games Store,
  and GOG prices in USD (US region). No wishlist entry is needed.
- `/digest` sends you a private message with your own wishlist games that are on sale, with prices.
- `/digestsettings [frequency:<Daily, Weekly, or Off>] [time:<HH:MM>]` shows or changes when you get the automatic digest. Weekly digests are sent on Mondays. Run it with no options to see your current settings.
- `/seasonal` shows how long until the next Steam, Epic Games Store, and GOG seasonal sales.
- `/random [user:<member>]` picks a game from the server wishlist or a chosen member's wishlist and shows its current prices.
- `/watch game:<name or store link> price:<USD target> [store:<store>]` sets a private target-price alert.
- `/watchlist` shows your price alerts in this server; `/unwatch game:<name>` removes one.
- `/status` privately shows bot health, uptime, version, and price-source status to server administrators.

Examples: `/pullpricing game:Portal 2` or
`/pullpricing game:https://store.steampowered.com/app/292030/`

The reply includes the game name and each available store's current price,
original price, discount percentage, and purchase link. Free offers show `Free`.
Game-name searches show a private selection menu when there is more than one match.
Exact titles appear first; a compact name such as `darksouls` can match `Dark Souls`.
Only the person who ran the command can choose a result, and they can cancel without changing their wishlist or alerts.
The bot acts only on the selected game. Each search and selected-price lookup has
a 10-second network timeout; selection menus expire after two minutes.
Empty input returns `Enter a game name or Steam store link`;
a name with no search results returns `Game not found`. For `/pullpricing`, Epic
and GOG are search/comparison stores; direct input links must still be Steam links.
See [pricing documentation](docs/pullpricing.md) for
matching rules, error messages, and the manual test checklist.

Price watches check **daily at 4 PM Central time** and send DMs when a game reaches
the target or falls below the last notified price. They compare available Steam,
Epic, and GOG offers in USD. Targets and notification state survive restarts.
See [Sprint 3 game tools](docs/sprint-3-game-tools.md) for details and local tests.

## Epic Games Store and GOG
`/wishlist` accepts Epic Games Store and GOG links, and game names through the optional `store` choice. Epic and GOG prices come from CheapShark and are matched by exact game title, so a game is only priced when its title matches a CheapShark listing exactly. Free-to-play games may not be listed.

## Daily digest
The bot sends each member a private message (DM) with their own wishlist games that are on sale. Nobody sees anyone else's games, and nothing is posted in a channel.

- **Automatic:** each member chooses their own schedule with `/digestsettings`: daily, weekly (Mondays), or off, and a delivery time in 24-hour HH:MM. The default is daily at 4 PM Central time. The bot checks every minute for members who are due. A game on sale is sent once per day, and again the next day while it is still on sale. When the sale ends, the messages stop. Settings are saved in the database and survive restarts.
- **On demand:** `/digest` does the same check for you only. It always answers when you run it, even if your schedule is off, and the reply in the server is private. A game you were just sent will not be sent again by the scheduled run that day.
- **What counts as a sale:** the current price is lower than the original price (a normally paid game that is free for a limited time counts). Games that are always free do not. Steam, Epic Games Store, and GOG games are checked, and sale cards for all three arrive in the same private message.
- **Closed DMs:** if direct messages from server members are turned off, the bot cannot send the digest. `/digest` tells you so, and the automatic run tries again the next day.

The automatic run starts only when `DIGEST_GUILD_ID` is set (see Setup). The bot must be running at the delivery time for it to send. Without `DIGEST_GUILD_ID`, `/digestsettings` still saves settings but tells you automatic digests are disabled for the server.

## Seasonal sales
`/seasonal` shows the Steam seasonal sale that is running now, or the next one coming, with the time left and the dates in your own time zone. It also lists the sales after that. It covers the Spring, Summer, Autumn, and Winter Steam sales, and the reply is private.

It also shows the next sale for the Epic Games Store (Black Friday and holiday sales) and GOG (Black Friday and Winter sales), each with a countdown. A store with a sale running shows when it ends and what comes next. Sales start at 10 AM Pacific (Steam), 11 AM Eastern (Epic Games Store), and 2 PM UTC (GOG).

Steam, Epic, and GOG have no API for sale dates, so the dates are kept in lists in `bot/seasonal.py`: `SALES` (Steam, from Valve's published schedule), `EPIC_SALES`, and `GOG_SALES`. Epic and GOG dates are marked "estimated" until each store announces them; update them and clear the `estimated` flag when they do. The Steam list currently runs through the Summer Sale 2027. When new dates are announced, add one `make_sale(...)` line to the right list. If no sale is left on the calendar, the command says so.

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
   - `DIGEST_GUILD_ID` is the server whose members get the automatic digest. Leave it out to turn the automatic digest off (`/digest` still works).
   - Optional: `DIGEST_TIME` (24-hour time, default `16:00`) is the delivery time for members who have not set their own, and `DIGEST_TIMEZONE` (default `America/Chicago`) is the time zone all delivery times use. Restart the bot after changing them.

   Pricing uses public Steam and CheapShark endpoints; no pricing API key is needed.
4. Start the bot:
```
   python bot.py
```
   The bot is only online while this is running. The `wishlist.db` file is created automatically on first start.

To receive digest messages, turn on "Direct Messages" from server members in the server's privacy settings.

## Tests
In the `bot` folder, run:
```
python -m unittest -v
```
The automated tests mock pricing services and Discord interactions, so no bot
token is needed. GitHub Actions runs both the bot tests and the project skeleton
tests. Run just Story 3 tests with `python -m unittest -v test_pricing test_pullpricing`.
Run just the digest or seasonal tests with `python -m unittest -v test_digest` or `python -m unittest -v test_seasonal`.
Run just the Epic and GOG tests with `python -m unittest -v test_stores test_store_pricing`.

## Folder layout
- `bot/` has the bot code and tests.
  - `bot.py` has the Discord commands.
  - `handler.py` has the wishlist logic.
  - `steam.py` looks up games on Steam.
  - `stores.py` reads Epic Games Store and GOG links and searches those stores by game name.
  - `pricing.py` searches game names, matches Steam app IDs to cross-store prices, looks up Epic and GOG prices, and formats offers.
  - `game_search.py`, `game_picker.py`, and `game_commands.py` handle game choices and the new commands.
  - `watch_db.py` and `watches.py` store price targets and run daily checks.
  - `health.py` keeps the runtime health summary for `/status`.
  - `digest.py` builds and sends the digest, and has the `/digest` and `/digestsettings` commands.
  - `seasonal.py` has the Steam, Epic, and GOG sale calendars and the `/seasonal` countdown.
  - `ratelimit.py` has the command rate limiter (`slow_down.png` is the picture it posts).
  - `db.py` and `database.py` save games, price watches, and digest settings in SQLite.
  - `view_database.py` prints everything in the database.
- `docs/` has the project documents (contract, learning plan, backlog, stakeholders).

## Team
- Aidan
- Alayna
- Grayson
- Hunter
