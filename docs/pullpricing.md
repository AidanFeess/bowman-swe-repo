# Story 3: Checking Game Prices

## Usage and scope

In a server, run:

```text
/pullpricing link:https://store.steampowered.com/app/292030/The_Witcher_3/
```

The command is independent of the wishlist. It accepts one HTTP or HTTPS Steam
app URL, with an optional title, query string, and fragment. Names, Steam bundles,
lookalike domains, and other stores' input links are rejected. This implements the
story task's Steam-link input scope; Epic/GOG link parsing is not implemented.

Selected comparison stores are Steam, Epic Games Store, and GOG. Each available
store gets one field showing current price, original price, discount (rounded to
the nearest whole percent), and a purchase link. Prices use USD and US-region
availability; they can differ by region and change before checkout. A current
price of zero displays `Free`; the original price stays numeric. A permanently
free game shows original price `$0.00` and discount `0%`.

## Lookup and matching

1. Strictly parse the Steam hostname and app ID without requesting the user's URL.
2. Ask Steam's public store endpoint for the name, free status, and US price.
3. Search CheapShark using `steamAppID`, never a similar title. Follow a result
   only when there is exactly one distinct matching CheapShark game ID.
4. Verify the returned game's Steam app ID again before using its store offers.
5. Keep only the selected stores (CheapShark IDs 1, 25, and 7). Prefer Steam's
   direct price; otherwise use a matched CheapShark offer. Keep the cheapest
   valid offer if a store has multiple entries for the matched game.

Missing, negative, nonnumeric, or inconsistent prices are omitted, never treated
as zero. Unmatched or ambiguous CheapShark games contribute no comparison offers;
Steam can still supply its own price. This avoids guessing between editions,
although catalog matching ultimately depends on the provider's data. No match
and no available prices use the same `No prices found for this game` response.

CheapShark purchase links use its redirect endpoint as required by its
[API documentation](https://apidocs.cheapshark.com/). Its
[game lookup](https://www.postman.com/cheapshark/cheapshark-s-public-workspace/request/qra189o/game-lookup)
returns the offers for the matched game. No API keys are needed. The client sends
a descriptive User-Agent because CheapShark rejects generic clients.

The bot acknowledges a valid server request before doing network I/O. All source
calls share one 10-second deadline, with asynchronous cancellation and session
cleanup. A timeout, connection failure, HTTP error (including rate limiting), bad
JSON, or invalid response structure returns the unavailable message even if an
earlier source returned a price. There are no retries extending the deadline.

## Exact error messages

| Situation | Reply |
| --- | --- |
| DM invocation | `Use this command in a server` |
| Invalid or unsupported input link | `That is not a valid store link` |
| Unknown game or successful lookup with no available prices | `No prices found for this game` |
| Source failure or lookup exceeds 10 seconds | `Prices are temporarily unavailable, try again later` |

DM validation happens first and makes no network request. The command intentionally
has no `guild_only` decorator so Discord can deliver a DM invocation to the bot.
When `TEST_GUILD_ID` is set, commands are synced only to that server. To test actual
DM invocation, clear `TEST_GUILD_ID`, restart for global command sync, and allow
Discord time to propagate it. The application must be installed with the bot and
application-command scopes and the server channel must allow messages and embeds.

## Automated validation

From `bot/`:

```text
python -m unittest -v
python -m unittest -v test_pricing test_pullpricing
```

Tests use mock source responses and Discord interactions. Coverage includes all
seven acceptance criteria, exact ID matching, ambiguous editions, spoofed URLs,
missing or corrupt prices, duplicate/unselected store offers, source errors,
HTTP status handling, and cancellation under one total deadline. The deadline
test shortens the clock to 0.06 seconds while checking the production constant is
10; individually fast requests whose combined time exceeds the budget must fail.
The command test checks that deferral occurs before lookup and that the actual
registered callback sends the required embed or exact message. CI runs these
tests without credentials or live API access.

## Manual Discord checklist

Start the bot using the setup in the root README, then:

| Check | Action | Expected |
| --- | --- | --- |
| Popular game / comparisons | Paste the Witcher 3 Steam link above | Game name, every available selected store, both prices, percent, clickable purchase link |
| No discount | Use a game currently at full price | Equal current/original prices and `0%` |
| Free | Use `https://store.steampowered.com/app/440/` (Team Fortress 2) | Steam current price `Free` |
| Invalid text | Submit `not a link` | Exact invalid-link message |
| Unknown game | Use `https://store.steampowered.com/app/99999999/` | Exact no-prices message if Steam reports unknown |
| Failure | Disconnect network after connecting the bot, then invoke | Exact unavailable message when the service request fails; Discord delivery needs connectivity |
| DM | Invoke the globally registered command in a bot DM | Exact server-only message |

Use automated fixtures for temporary giveaways, no-price responses, and slow
sources; real store availability cannot be controlled. Open each returned link
and check the edition and checkout price before accepting a live comparison.

## Local validation record (2026-10-21)

- Full bot suite: 52 tests passed; 24 cover Story 3.
- Live service smoke checks succeeded for The Witcher 3 (Steam app 292030) and
  Team Fortress 2 (440), using the implemented lookup and formatter.
- The Witcher 3 returned Steam `$49.99` / `$49.99` / `0%`, and GOG `$24.99` /
  `$49.99` / `50%`. No Epic offer was returned for this game. These are observed
  snapshots, not test expectations.
- Team Fortress 2 returned Steam `Free` / `$0.00` / `0%`.
- An actual Discord server/DM session has not been exercised: this clone has no
  configured bot credentials. Discord behavior is covered by callback tests;
  the manual checklist remains for a configured bot.
