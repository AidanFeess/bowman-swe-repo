# Server deployment

## Running service

- Host: `172.25.255.101` (Debian 12); SSH key login as `root`.
- Service: `game-night-bot.service`, enabled on boot with `Restart=on-failure`.
- Process account: `game-night-bot`, a system account without an interactive shell.
- Running release: `/opt/game-night-bot/current`, an atomic symlink to tested code.
- Running version: `cat /opt/game-night-bot/current/REVISION`.
- Python environment: `/opt/game-night-bot/current/venv`, separate for each release.
- Git fetch cache: `/opt/game-night-bot/repo`. Its working-tree HEAD may be older
  than the running release; use `current/REVISION` to check what is deployed.
- Settings: `/etc/game-night-bot.env`, mode `0600`, owned by root. The service reads
  it through systemd's `EnvironmentFile`; it is not committed to Git.
- Persistent data: `/var/lib/game-night-bot/wishlist.db`. The application's
  `current/bot/wishlist.db` is a symlink to this file. The database includes wishlist and
  digest notification tables and remains in place during code updates.

After `ssh root@172.25.255.101`:

```sh
systemctl start game-night-bot
systemctl stop game-night-bot
systemctl restart game-night-bot
systemctl status game-night-bot --no-pager
journalctl -u game-night-bot -f
```

Stopping the service intentionally leaves it stopped; crash recovery does not
override `systemctl stop`. Use `systemctl disable --now game-night-bot` to also
disable boot startup, or `systemctl enable --now game-night-bot` to restore it.
Before maintenance, stop the update timer and any in-progress updater first (see
below), then stop the bot. This prevents an in-progress deployment from racing
with a manual stop.
After changing the environment file, restart the service. A running process is
not by itself proof of a Discord connection: wait for `Logged in as` in its logs.
Repeated quick restarts can delay Discord login while its connection limits reset.

## Fresh installation

Install Git, Python, and venv support on the server, then prepare the code:

```sh
apt-get update
apt-get install -y git python3-venv ca-certificates
useradd --system --user-group --home-dir /var/lib/game-night-bot --shell /usr/sbin/nologin game-night-bot
install -d -m 0755 /opt/game-night-bot
git clone --branch main --single-branch https://github.com/AidanFeess/bowman-swe-repo.git /opt/game-night-bot/repo
python3 -m venv /opt/game-night-bot/venv
/opt/game-night-bot/venv/bin/pip install -r /opt/game-night-bot/repo/bot/requirements.txt
install -d -o game-night-bot -g game-night-bot -m 0700 /var/lib/game-night-bot
ln -s /var/lib/game-night-bot/wishlist.db /opt/game-night-bot/repo/bot/wishlist.db
install -d -m 0755 /opt/game-night-bot/legacy /opt/game-night-bot/releases
ln -s /opt/game-night-bot/repo/bot /opt/game-night-bot/legacy/bot
ln -s /opt/game-night-bot/venv /opt/game-night-bot/legacy/venv
git -C /opt/game-night-bot/repo rev-parse HEAD > /opt/game-night-bot/legacy/REVISION
chmod 0644 /opt/game-night-bot/legacy/REVISION
ln -s /opt/game-night-bot/legacy /opt/game-night-bot/current
```

Copy the supplied `.env` file securely to `/etc/game-night-bot.env`, keeping its
contents unchanged, and apply `chown root:root` and `chmod 600`. It must define
`DISCORD_TOKEN`, with the desired server IDs in `TEST_GUILD_ID` and
`DIGEST_GUILD_ID`. Neither the token nor the environment file belongs in the repo.

Install [the service unit](../deploy/game-night-bot.service) as
`/etc/systemd/system/game-night-bot.service`, then:

```sh
systemd-analyze verify /etc/systemd/system/game-night-bot.service
systemctl daemon-reload
systemctl enable --now game-night-bot
journalctl -u game-night-bot -n 30 --no-pager
```

The service can write its state directory but not its code or environment file.
The VM needs outbound HTTPS and WebSocket access to Discord and the pricing
services; the bot does not need an inbound web port.

## Automatic updates

`game-night-bot-update.timer` checks GitHub `main` every 15 minutes, with up to a
minute of timer scheduling tolerance. It is enabled on boot and catches up on a
missed check after downtime. No running Codex chat or Windows PC is needed.

The updater skips a stopped bot and leaves unchanged commits running. For a new
commit it exports the source into a separate release, installs dependencies in
that release's virtual environment, and runs all bot tests in an isolated copy.
Builds and tests run as `game-night-bot-build`, which cannot read the root-only
environment file or the bot's private database directory. Failed fetches, builds,
or tests leave the running bot untouched.

After checks pass, the updater stops the bot briefly, makes an integrity-checked
SQLite backup, switches `current` atomically, and starts the new version. It waits
up to 120 seconds for this process's `Logged in as` message and checks that it
stays running. Failed startup restores both the previous release and database,
then reconnects the old bot. Failed runs are recorded in the systemd journal and
retried at the next scheduled check. This verifies startup, not every live Discord
command or future background task. A network outage can prevent either version
from reconnecting until the connection recovers.

Backups are root-only files in `/var/backups/game-night-bot` (the newest 10 are
kept). Old release cleanup retains the current and previous releases and the
three newest release directories. The original installation remains in `legacy`.
Updater code and unit files are installed separately and are not executed from
unreviewed changes to `main` as root; deploy those administrative changes explicitly.

```sh
# Run a check now and inspect its result
systemctl start game-night-bot-update
systemctl status game-night-bot-update --no-pager
journalctl -u game-night-bot-update -n 40 --no-pager
systemctl list-timers game-night-bot-update.timer
cat /opt/game-night-bot/current/REVISION

# Pause automatic updates (does not stop the bot)
systemctl disable --now game-night-bot-update.timer
systemctl stop game-night-bot-update.service

# Resume automatic updates
systemctl enable --now game-night-bot-update.timer
```

The update service is a oneshot: `inactive (dead)` with `Result=success` after a
completed check is normal. The timer remains active. Use the commands above to
check for failed updates; the updater does not send Discord notifications.

To install the updater on a freshly configured server, copy the files from this
repository's `deploy/` directory to the server, then as root run:

```sh
useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin game-night-bot-build
install -d -m 0700 /var/backups/game-night-bot
install -m 0755 deploy/game-night-bot-update.py /usr/local/sbin/game-night-bot-update.py
install -m 0644 deploy/game-night-bot-update.service deploy/game-night-bot-update.timer /etc/systemd/system/
systemd-analyze verify /etc/systemd/system/game-night-bot-update.service /etc/systemd/system/game-night-bot-update.timer
systemctl daemon-reload
systemctl start game-night-bot-update
systemctl enable --now game-night-bot-update.timer
```

Run updater tests on Linux with `python3 -m unittest discover -s deploy -p test_update.py -v`.
Run application tests only in a separate checkout: some existing tests write into
the checkout's `bot/wishlist.db`, so never run them against the production symlink.

## Automatic-update verification — November 11, 2026

- The first update deployed `main` revision `9ce3ef183569afb1d7d31778da8f664f0f26fd4e`
  after all 218 bot tests passed in an isolated server checkout.
- Discord login succeeded. A second check recognized the same revision and kept
  the same bot process running.
- Database integrity was `ok`; all 26 wishlist rows and 10 notification rows
  present in the pre-update backup were preserved.
- The build account could not read either the production database or environment file.
- Nine isolated updater tests cover unchanged versions, stopped services, fetch
  and build failures, successful activation, database/schema rollback after a
  simulated startup failure, backup failure, and guarded cleanup.
- The timer is enabled for the quarter-hour schedule. Deployment testing did not
  send Discord messages or execute slash commands as a user.

## Initial deployment verification — November 4, 2026

- Deployed GitHub `main` commit `9f2fdac44730b72b24d16e189a83e55c8cfbe3da`.
- All 155 bot tests passed on the server in an isolated checkout.
- Supplied environment file and installed file matched byte for byte; the
  running process also received the matching settings.
- Discord gateway login succeeded. Both configured guilds were accessible,
  and all seven commands were registered, including `/pullpricing game`.
- Normal restart and a forced `SIGKILL` both recovered to a Discord login.
  Crash recovery incremented systemd's restart counter. The latter Discord
  reconnect took about a minute after the rapid restart checks.
- Database integrity remained `ok`, and the initial empty wishlist remained
  intact across the checks. Boot startup is enabled; the whole VM was not rebooted.
- These checks verify initial operation and recovery, not a 24-hour uptime run
  or manual execution of every command in Discord.
