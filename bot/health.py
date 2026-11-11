"""Small, in-memory health summary; never stores tokens, URLs, or game names."""

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import re
import subprocess
import time

STARTED = time.monotonic()


@dataclass
class SourceHealth:
    last_attempt: datetime | None = None
    last_success: datetime | None = None
    last_failure: datetime | None = None
    outcome: str = "not checked"


SOURCES = {name: SourceHealth() for name in ("Steam", "CheapShark")}
LOOKUPS = SourceHealth()


def record(source, success):
    _record(SOURCES[source], success)


def record_lookup(success):
    _record(LOOKUPS, success)


def _record(state, success):
    now = datetime.now(timezone.utc)
    state.last_attempt = now
    state.outcome = "ok" if success else "failed"
    if success:
        state.last_success = now
    else:
        state.last_failure = now


@lru_cache(maxsize=1)
def version():
    root = Path(__file__).resolve().parent.parent
    try:
        marker = root / "REVISION"
        revision = marker.read_text().strip() if marker.is_file() else subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True,
            stderr=subprocess.DEVNULL, timeout=2,
        ).strip()
        return revision[:12] if re.fullmatch(r"[0-9a-f]{40}", revision) else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"
