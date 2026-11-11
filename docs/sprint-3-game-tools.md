# Sprint 3 game tools

## Commands

| Command | Behavior |
| --- | --- |
| `/random` | Picks one unique store/game entry from this server's wishlist. |
| `/random user:@member` | Picks from that member's wishlist in this server. |
| `/watch game:Portal 2 price:9.99` | Watches the selected game for a price of $9.99 USD or less. |
| `/watch game:Hades price:10 store:gog` | Searches GOG-carried games, then tracks the selected game's available supported-store offers. |
| `/watchlist` | Privately lists your targets in the current server. |
| `/unwatch game:portal` | Removes a selected alert from your own watchlist. |
| `/status` | Shows runtime health privately; requires Discord Administrator permission. |

All these commands require a server. `/help` picks them up automatically from the
registered command tree. Restart the bot to sync the new commands after deployment.

## Choosing a game

Plain game names in `/wishlist`, `/pullpricing`, and `/watch` use the same search
and selection UI. Steam is the default search store; each command also offers
Epic Games Store and GOG as a store choice. Exact normalized titles appear first,
followed by other results in provider order. Searches are capped at ten choices.
When Steam returns no results, the catalog can supply exact Steam app IDs for
compact queries such as `darksouls`.

If multiple games match, the bot sends a private menu and waits. It does not add,
price, or watch a result just because it was first. A single result proceeds
immediately. The selected app/catalog ID is retained for pricing, so a second
name search cannot silently select a different edition. Epic/GOG results must
have an offer on the selected search store before they appear in the menu.

`/remove` searches only your wishlist in the current server; `/unwatch` searches
only your watches there. Both support compact/partial names and the same picker.
Removing a wishlist game retains the existing behavior of removing all store
copies with that full name. Removing a watch leaves the wishlist unchanged.
`/list` and `/random` use Discord's native server-member picker for their `user`
option.

Menus are usable only by the requesting user in the original server, expire after
120 seconds, and have a Cancel button. Expiry, cancellation, invalid choices, and
repeat clicks do not perform the action. Name-search responses are private. The
existing Steam-link pricing path and store-link wishlist path keep their normal
public replies. Steam links do not need a selection; Epic/GOG links supplied to
`/watch` resolve through the catalog and may ask the user to choose a result.

Each network phase has a 10-second deadline. Time spent choosing a game does not
consume the price lookup's network budget. This replaces the previous automatic
top-result behavior for interactive name commands. Source failures return the
temporary-unavailability message, and an empty successful search returns
`Game not found`.

## Random picks

Each unique store/link entry gets one chance. A game requested by ten members
does not get ten chances, and different store versions remain separate entries.
The result includes the selected title, store link, and available price details,
including free/full-price offers. An empty wishlist gets a clear reply. A pricing
outage or unavailable price still returns the selected game with a clear price
message. A database failure does not return a made-up pick. Only a member of the
current server can be selected.

## Daily price watches

Checks run at 4 PM in `America/Chicago`, including daylight-saving changes. This
schedule is independent of the daily wishlist digest and does not change any
teammate's digest settings. The bot must be online at the scheduled time. There
is no immediate DM on watch creation; the next daily check handles it.

Targets use integer cents in SQLite and must be nonnegative USD amounts with at
most two decimal places. A target of `0` means free. Users may keep up to 25
watches per server. Setting an existing watch updates its target rather than
creating another copy with the same game ID. No wishlist entry is required.

The checker compares the cheapest available supported-store offer with the target:

- At or below the target: send the first DM, or another DM if the price falls
  below the last notified price.
- Above the target: re-arm the alert for a future sale.
- Missing prices or source failure: keep the existing state and try at the next
  daily check; a missing price is never interpreted as free.
- Closed DMs or delivery failure: do not mark the alert as delivered. Other
  watches continue, and the failed alert can be tried on a later daily check.

Notification state and the last checked date persist across restarts, preventing
routine duplicate daily alerts. A crash after Discord accepts a DM but before
SQLite records it can still cause a repeat; Discord and SQLite do not share a
transaction. Concurrent runs are prevented, shared game lookups are cached within
each run, and changed/deleted watches are rechecked before delivery. Users who
left a server are not notified for watches in that server.

`price_watches` is added with `CREATE TABLE IF NOT EXISTS`; existing wishlist and
digest rows are preserved. `/watchlist` and `/unwatch` are scoped to both the user
and server. The existing deployment's persistent SQLite file also stores watches.

## Admin status

Discord registers `/status` with Administrator as its default permission, and
the callback checks Administrator again at runtime. Manage Server permission by
itself is insufficient, even if command permissions have been customized.

The private reply shows the running revision, uptime, Discord connection/latency,
database availability and this server's counts, last successful price lookup,
last Steam/CheapShark HTTP results, and daily-watch status. Health observations
are kept in memory and reset on restart. `not checked` means no relevant request
has completed since startup, not that the provider is down. It does not perform
new pricing requests just to display status or expose tokens, environment values,
other servers' data, game queries, or raw error details.

## Local validation

On November 11, 2026, all 279 bot tests and all 4 project-skeleton tests passed
locally. The bot suite includes 61 tests for these Sprint 3 features.

From `bot/`:

```text
python -m unittest -q
python -m unittest -v test_game_search test_game_picker test_game_commands test_watch_db test_watches
```

Tests use temporary databases and mocked store/Discord responses. They cover
selection and exact IDs, compact names, store filtering, deadlines, forged values,
owner/server isolation, double clicks, cancellation, expiry, random-pick scope,
missing prices, admin permission enforcement, target validation, persistence,
deduplication, lower-price alerts, re-arming, stale updates, failed DMs, concurrent
checks, and daylight-saving behavior. The older database insertion tests were
also isolated so the suite does not populate a developer's real wishlist file.

No live Discord session or production deployment was performed for these features.
After deployment, check the menu layout/cancel button, a selected game in each
name command, `/random` with and without a member, `/watchlist` and `/unwatch`,
and `/status` as both an administrator and an ordinary member. Use mocks for
controlled price drops and failures rather than waiting for actual store sales.
