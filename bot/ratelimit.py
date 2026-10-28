import math
import time
from collections import deque


class RateLimiter:
    """Stops people from flooding the bot with commands.

    check(user_id, command) returns (status, seconds):
      ok       the command may run
      slow     heads-up: this user is going too fast, the command still runs
      block    this user just went over the limit and is blocked (say so once)
      blocked  this user is still blocked, seconds is how long is left
      busy     the whole bot is getting too many commands at once

    Going too fast means either:
      - the same command many times in repeat_seconds, however slowly, or
      - commands of any kind many times in per_seconds (very fast spam)

    The first time a user reaches the warning level they get a "slow" heads-up and a
    slow-down flag turns on for flag_seconds. While the flag is on the limits drop to the
    warning level plus flag_extra, so a user who was warned and keeps going is blocked sooner.
    """

    def __init__(self, max_commands=10, warn_commands=6, per_seconds=10,
                 repeat_max=12, warn_repeat=7, repeat_seconds=60,
                 block_seconds=10, flag_seconds=60, flag_extra=2, global_max=30, clock=time.monotonic):
        self.max_commands = max_commands      # any commands by one user...
        self.warn_commands = warn_commands    # ...warned at this many...
        self.per_seconds = per_seconds        # ...in this many seconds
        self.repeat_max = repeat_max          # the same command by one user...
        self.warn_repeat = warn_repeat        # ...warned at this many...
        self.repeat_seconds = repeat_seconds  # ...in this many seconds
        self.block_seconds = block_seconds    # how long a block lasts
        self.flag_seconds = flag_seconds      # how long the slow-down flag stays on
        self.flag_extra = flag_extra          # commands a warned user still gets before the block
        self.global_max = global_max          # commands from everyone in per_seconds
        self.clock = clock
        self._recent = {}         # user id -> times of that user's recent commands
        self._repeats = {}        # (user id, command) -> times that user ran that command
        self._blocked_until = {}  # user id -> time the block ends
        self._slow_until = {}     # user id -> time the slow-down flag turns off
        self._everyone = deque()  # times of all recent commands

    @staticmethod
    def _prune(times, now, seconds):
        while times and now - times[0] >= seconds:
            times.popleft()

    def is_slow_flagged(self, user_id):
        return self._slow_until.get(user_id, 0) > self.clock()

    def _block(self, user_id, now):
        self._blocked_until[user_id] = now + self.block_seconds
        self._recent.pop(user_id, None)
        for key in [k for k in self._repeats if k[0] == user_id]:
            del self._repeats[key]
        return "block", self.block_seconds

    def check(self, user_id, command=""):
        now = self.clock()

        until = self._blocked_until.get(user_id)
        if until is not None:
            if now < until:
                return "blocked", math.ceil(until - now)
            del self._blocked_until[user_id]

        recent = self._recent.setdefault(user_id, deque())
        self._prune(recent, now, self.per_seconds)
        repeats = self._repeats.setdefault((user_id, command), deque())
        self._prune(repeats, now, self.repeat_seconds)

        flagged = self._slow_until.get(user_id, 0) > now
        burst_max, repeat_max = self.max_commands, self.repeat_max
        if flagged:  # already warned: the limits drop, only a couple more commands are allowed
            burst_max = min(burst_max, self.warn_commands + self.flag_extra)
            repeat_max = min(repeat_max, self.warn_repeat + self.flag_extra)

        if len(recent) >= burst_max or len(repeats) >= repeat_max:
            return self._block(user_id, now)

        self._prune(self._everyone, now, self.per_seconds)
        if len(self._everyone) >= self.global_max:
            return "busy", self.per_seconds

        recent.append(now)
        repeats.append(now)
        self._everyone.append(now)

        if not flagged and (len(recent) >= self.warn_commands or len(repeats) >= self.warn_repeat):
            self._slow_until[user_id] = now + self.flag_seconds
            return "slow", self.block_seconds
        return "ok", 0