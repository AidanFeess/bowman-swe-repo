# Server deployment

## Running service

- Host: `172.25.255.101` (Debian 12); SSH key login as `root`.
- Service: `game-night-bot.service`, enabled on boot with `Restart=on-failure`.
- Process account: `game-night-bot`, a system account without an interactive shell.
- Code: `/opt/game-night-bot/repo`, tracking GitHub `main`.
- Python environment: `/opt/game-night-bot/venv`.
- Settings: `/etc/game-night-bot.env`, mode `0600`, owned by root. The service reads
  it through systemd's `EnvironmentFile`; it is not committed to Git.
- Persistent data: `/var/lib/game-night-bot/wishlist.db`. The application's
  `bot/wishlist.db` is a symlink to this file. The database includes wishlist and
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

## Updating and backing up

On the server as root, fetch first, stop the bot, and back up its database:

```sh
git -C /opt/game-night-bot/repo fetch origin main
systemctl stop game-night-bot
install -d -m 0700 /var/backups/game-night-bot
cp -p /var/lib/game-night-bot/wishlist.db /var/backups/game-night-bot/wishlist-$(date -u +%Y%m%dT%H%M%SZ).db
git -C /opt/game-night-bot/repo merge --ff-only origin/main
/opt/game-night-bot/venv/bin/pip install -r /opt/game-night-bot/repo/bot/requirements.txt
systemctl start game-night-bot
git -C /opt/game-night-bot/repo rev-parse HEAD
journalctl -u game-night-bot -n 30 --no-pager
```

If an update step fails, resolve it before starting the bot. Keep database schema
changes in mind when rolling code back. Test new code in a separate checkout:
some existing database tests write into that checkout's `bot/wishlist.db`, so
do not run the full suite against the production database symlink.

## Deployment verification — November 4, 2026

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
