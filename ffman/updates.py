"""When the website updates next, read straight from the workflow's cron lines.

Only the cron syntax the workflow uses is supported: numbers, lists (1,2),
ranges (1-5) and *. Times in cron are UTC.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

WORKFLOW = Path(".github/workflows/site.yml")


def read_crons(path: Path = WORKFLOW) -> list[str]:
    if not path.exists():
        return []
    return re.findall(r'^\s*-\s*cron:\s*"([^"]+)"', path.read_text(), flags=re.M)


def _field(spec: str, lo: int, hi: int) -> set[int]:
    values: set[int] = set()
    for part in spec.split(","):
        if part == "*":
            values.update(range(lo, hi + 1))
        elif "-" in part:
            a, b = part.split("-")
            values.update(range(int(a), int(b) + 1))
        else:
            values.add(int(part))
    return values


def _matcher(cron: str):
    minute, hour, dom, month, dow = cron.split()
    m, h = _field(minute, 0, 59), _field(hour, 0, 23)
    d, mo, w = _field(dom, 1, 31), _field(month, 1, 12), _field(dow, 0, 6)

    def matches(t: dt.datetime) -> bool:
        cron_dow = (t.weekday() + 1) % 7  # cron: 0 = Sunday
        return t.minute in m and t.hour in h and t.day in d and t.month in mo and cron_dow in w
    return matches


def next_runs(crons: list[str], after: dt.datetime, count: int = 4) -> list[dt.datetime]:
    """The next `count` scheduled run times (UTC) after `after`."""
    if not crons:
        return []
    matchers = [_matcher(c) for c in crons]
    t = after.astimezone(dt.timezone.utc).replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    runs: list[dt.datetime] = []
    for _ in range(8 * 24 * 60):  # look up to 8 days ahead
        if any(match(t) for match in matchers):
            runs.append(t)
            if len(runs) == count:
                break
        t += dt.timedelta(minutes=1)
    return runs
