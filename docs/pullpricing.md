# Story 3: Checking Game Prices by Name or Steam Link

## Usage and scope

In a server, run:

```text
/pullpricing game:Portal 2
/pullpricing game:Hades store:gog
/pullpricing game:https://store.steampowered.com/app/292030/The_Witcher_3/
```

The command is independent of the wishlist. It accepts a game name or one HTTP or
HTTPS Steam app URL, with an optional title, query string, and fragment. Leading
and trailing whitespace is trimmed. Steam bundles, lookalike domains, and other
stores' input links are rejected by this command. The optional `store` selects
where to search a name; it defaults to Steam. Epic/GOG names are supported.

Sprint 2 renames the required option from `link` to `game`. Restart the bot to sync
the new command schema before testing. `/help` builds its syntax from registered
commands and will show `/pullpricing <game> [store]` automatically.

Selected comparison stores are Steam, Epic Games Store, and GOG. Each available
store gets one field showing current price, original price, discount (rounded to
the nearest whole percent), and a purchase link. Prices use USD and US-region
availability; they can differ by region and change before checkout. A current
price of zero displays `Free`; the original price stays numeric. A permanently
free game shows original price `$0.00` and discount `0%`.

## Lookup and matching

1. For a link, strictly parse the Steam hostname and app ID without requesting the
   user's URL. For a name, search the selected store and rank exact normalized
   titles first. Multiple results open an owner-only private selection menu;
   only a single result proceeds automatically. An empty successful search
   returns `Game not found`. See [game selection](sprint-3-game-tools.md) for
   compact names, catalog fallback, and cancellation behavior.
2. Ask Steam's public store endpoint for the name, free status, and US price.
3. Search CheapShark using `steamAppID`, never a similar title. Follow a result
   only when there is exactly one distinct matching CheapShark game ID.
4. Verify the returned game's Steam app ID again before using its store offers.
5. Keep only the selected stores (CheapShark IDs 1, 25, and 7). Prefer Steam's
   direct price; otherwise use a matched CheapShark offer. Keep the cheapest
   valid offer if a store has multiple entries for the matched game.

For an Epic/GOG name choice, the selected CheapShark catalog ID is used directly
to retrieve the supported-store offers, without repeating a title search.

Missing, negative, nonnumeric, or inconsistent prices are omitted, never treated
as zero. Unmatched or ambiguous CheapShark games contribute no comparison offers;
Steam can still supply its own price. This avoids guessing between editions,
although catalog matching ultimately depends on the provider's data. A resolved
game with no available prices (or an unknown app ID in a link) returns
`No prices found for this game`. This differs from a name search with no results.
Always check the displayed game title, especially for a partial or misspelled
name: choose the intended game and edition from the selection menu.

Steam's public store-search endpoint is not a documented stable API. Its handling
is isolated in `game_search.py` for interactive searches; malformed responses and rate
limits return the unavailable message, rather than claiming a game was not found.

CheapShark purchase links use its redirect endpoint as required by its
[API documentation](https://apidocs.cheapshark.com/). Its
[game lookup](https://www.postman.com/cheapshark/cheapshark-s-public-workspace/request/qra189o/game-lookup)
returns the offers for the matched game. No API keys are needed. The client sends
a descriptive User-Agent because CheapShark rejects generic clients.

The bot acknowledges a valid server request before doing network I/O. The search
phase and the price lookup after selection each have a 10-second network deadline.
Menus allow 120 seconds for a human choice. Requests are cancelled and sessions
closed on timeout. A connection failure, HTTP error (including rate limiting), bad
JSON, or invalid response structure returns the unavailable message even if an
earlier source returned a price. There are no retries extending the deadline.

## Exact error messages

| Situation | Reply |
| --- | --- |
| DM invocation | `Use this command in a server` |
| Empty input or only whitespace | `Enter a game name or Steam store link` |
| Invalid or unsupported input link | `That is not a valid store link` |
| Name search succeeds with no games | `Game not found` |
| Unknown app ID in a link or resolved game with no prices | `No prices found for this game` |
| Source failure or lookup exceeds 10 seconds | `Prices are temporarily unavailable, try again later` |

DM validation happens first; DM, empty, and invalid-link inputs make no network
request. The command intentionally
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
existing link-based behavior and Sprint 3 selection behavior: exact-name ranking,
owner-only selection, empty/no-result names, search failures,
exact ID matching, ambiguous editions, spoofed URLs,
missing or corrupt prices, duplicate/unselected store offers, source errors,
HTTP status handling, and cancellation under one total deadline. The deadline
tests shorten the clock while checking the production constant is 10. They check
both a stalled interactive search and lower-level search-plus-pricing calls that
share one budget. Pending I/O is cancelled and the session closes.
The command test checks that deferral occurs before lookup and that the actual
registered callback sends the required embed or exact message. CI runs these
tests without credentials or live API access.

## Manual Discord checklist

Live Discord verification is left to the user. Restart the bot using the setup
in the root README so the renamed option is synced, then run these checks at a
normal pace to avoid the existing command rate limiter:

| Check | Action | Expected |
| --- | --- | --- |
| Exact name | `/pullpricing game:Portal 2` (also try `portal 2`) | Exact title is first; choose it if a menu appears, then verify all price fields |
| Partial name | `/pullpricing game:Portal` | A private menu when multiple games match; only the chosen game is priced |
| No name results | `/pullpricing game:zzqvnotarealgame928374` | `Game not found` if Steam returns no games |
| Empty input | Submit spaces in `game` if the client allows it | `Enter a game name or Steam store link`; Discord may reject empty required options before sending them |
| Popular game / comparisons | Paste the Witcher 3 Steam link above | Game name, every available selected store, both prices, percent, clickable purchase link |
| No discount | Use a game currently at full price | Equal current/original prices and `0%` |
| Free | Use `https://store.steampowered.com/app/440/` (Team Fortress 2) | Steam current price `Free` |
| Invalid link | `/pullpricing game:https://example.com/game` | Exact invalid-link message; ordinary text now triggers a name search |
| Unknown game | Use `https://store.steampowered.com/app/99999999/` | Exact no-prices message if Steam reports unknown |
| Command help | `/help` | `/pullpricing <game>` appears instead of `<link>` |
| DM | Invoke the globally registered command in a bot DM | Exact server-only message |

Use automated fixtures for empty strings, temporary giveaways, no-price responses,
source failures, and slow searches; real store availability cannot be controlled.
Failures must return `Prices are temporarily unavailable, try again later` within
the lookup deadline. Open each returned link
and check the edition and checkout price before accepting a live comparison.

## Sprint 2 validation (2026-11-03)

- Full bot suite: 152 tests passed, including 38 pricing/command tests.
- Project skeleton suite: 4 tests passed.
- Mocked tests cover all seven name-search acceptance criteria and preserve the
  existing Steam-link and digest app-ID lookup behavior.
- Steam's live search response for `Portal 2` was inspected to confirm the app
  ID, title, and result-type fields used by the async parser.
- Live Discord testing is pending the user's checklist above. No bot was started
  and no hosting configuration was changed for this work.

## Previous validation record (2026-10-21)

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
