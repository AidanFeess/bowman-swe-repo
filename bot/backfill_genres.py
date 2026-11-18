
"""Fill missing genres for existing wishlist games."""
import time

import db
import genres


def backfill(delay=0.25):
    db.init_db()

    missing = db.games_missing_genres()
    updated = 0

    for store, link, name in missing:
        labels = genres.lookup(store, name, link)

        if labels:
            db.save_game_genres(store, link, labels)
            updated += 1
            print(f"Updated {name}: {', '.join(labels)}")
        else:
            print(f"Still Unknown: {name} ({store})")

        time.sleep(delay)

    print(
        f"Finished: {updated} updated; "
        f"{len(missing) - updated} still Unknown"
    )


if __name__ == "__main__":
    backfill()
