"""Weekly recap: how your lineup did vs. ffman's lineup vs. the best possible one.

For a finished week we know who you started and what everyone scored. ffman's
lineup is rebuilt from that week's final pre-game projections, then scored
with the real points, so the comparison is "what if you had followed it".
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from .models import Lineup, Player, Team
from .optimizer import optimal_lineup


@dataclass
class Swap:
    start: Player            # ffman would have started this player...
    sit: Player | None       # ...instead of this one
    delta: float             # real points gained (negative = the swap would have cost you)


@dataclass
class WeekRecap:
    league_name: str
    platform: str
    week: int
    actual: float                   # what your lineup scored
    ffman: float                    # what ffman's lineup would have scored
    perfect: float                  # best possible lineup, in hindsight
    opponent: float | None = None   # opponent's score, when known
    swaps: list[Swap] = field(default_factory=list)

    @property
    def gain(self) -> float:
        return round(self.ffman - self.actual, 2)

    @property
    def result(self) -> str | None:
        if self.opponent is None:
            return None
        return "W" if self.actual > self.opponent else "L" if self.actual < self.opponent else "T"

    @property
    def ffman_result(self) -> str | None:
        if self.opponent is None:
            return None
        return "W" if self.ffman > self.opponent else "L" if self.ffman < self.opponent else "T"

    @property
    def flipped(self) -> bool:
        """ffman's lineup would have changed the result."""
        return self.result is not None and self.result != self.ffman_result


def _points(players: list[Player]) -> float:
    return round(sum(p.actual or 0 for p in players), 2)


def summarize(team: Team, week: int, opponent: float | None = None,
              actual_total: float | None = None) -> WeekRecap:
    """Compare a finished week. Players need `projection` (pre-game) and `actual` set."""
    for p in team.roster:
        p.locked = False  # hindsight: every move was still possible before kickoff
    started = team.current.starters
    ffman = optimal_lineup(team)

    by_id = {p.id: dataclasses.replace(p, projection=p.actual or 0, injury_status=None)
             for p in team.roster}
    hindsight = dataclasses.replace(
        team, roster=list(by_id.values()),
        current=Lineup(team.current.slots, [by_id.get(p.id) if p else None for p in team.current.players]))
    perfect = optimal_lineup(hindsight)

    started_ids = {p.id for p in started}
    ffman_ids = {p.id for p in ffman.starters}
    ins = sorted((p for p in ffman.starters if p.id not in started_ids), key=lambda p: -(p.actual or 0))
    outs = sorted((p for p in started if p.id not in ffman_ids), key=lambda p: -(p.actual or 0))
    swaps = [Swap(p, outs[i] if i < len(outs) else None,
                  round((p.actual or 0) - ((outs[i].actual or 0) if i < len(outs) else 0), 2))
             for i, p in enumerate(ins)]
    swaps.sort(key=lambda s: -abs(s.delta))

    actual = round(actual_total, 2) if actual_total is not None else _points(started)
    return WeekRecap(
        league_name=team.league_name, platform=team.platform, week=week,
        actual=actual,
        ffman=round(actual + _points(ffman.starters) - _points(started), 2),
        perfect=round(sum(p.projection for p in perfect.starters), 2),
        opponent=round(opponent, 2) if opponent is not None else None,
        swaps=swaps,
    )


@dataclass
class SeasonRecap:
    weeks: list[WeekRecap]

    @property
    def gain(self) -> float:
        return round(sum(w.gain for w in self.weeks), 2)

    @property
    def flips_to_wins(self) -> int:
        return sum(1 for w in self.weeks if w.flipped and w.ffman_result == "W")

    @property
    def flips_to_losses(self) -> int:
        return sum(1 for w in self.weeks if w.flipped and w.ffman_result == "L")

    def latest(self) -> list[WeekRecap]:
        if not self.weeks:
            return []
        last = max(w.week for w in self.weeks)
        return [w for w in self.weeks if w.week == last]

    def by_league(self) -> dict[str, list[WeekRecap]]:
        out: dict[str, list[WeekRecap]] = {}
        for w in sorted(self.weeks, key=lambda w: w.week):
            out.setdefault(w.league_name, []).append(w)
        return out
