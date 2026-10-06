"""Waiver-wire suggestions: who to add, who to drop, and what it's worth.

Players are valued on this week + next week's projections ("two-week value"),
so a one-week fluke doesn't win and a star on bye isn't dumped. Drops never
touch highly ranked players (or, in keeper/dynasty leagues, anyone with real
long-term value) and never leave a required position empty.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from .models import SLOT_POSITIONS, Lineup, Player, Team
from .optimizer import optimal_lineup

MAX_SUGGESTIONS = 3
MIN_TWO_WEEK_GAIN = 4.0   # points over two weeks for a depth upgrade
MIN_WEEK_GAIN = 2.0       # points in this week's best lineup
HOT_ADDS = 100_000        # 24h adds that make a player a "hot pickup" you'd rather keep
MIN_TOUGH_WEEK_GAIN = 5.0 # a "tough call" drop must buy at least this much this week
CANDIDATES = 25           # best free agents to evaluate per league


@dataclass
class Pickup:
    add: Player
    drop: Player | None
    week_gain: float       # improvement to this week's best lineup
    two_week_gain: float   # add's two-week value minus drop's
    tough: str | None = None  # why the drop hurts, when every option has a catch
    after: list[Player] = dataclasses.field(default_factory=list)  # earlier adds this assumes

    @property
    def reason(self) -> str:
        if self.week_gain >= MIN_WEEK_GAIN:
            text = f"Would start this week (+{self.week_gain:.1f} to your best lineup)"
        else:
            text = f"Better depth: +{self.two_week_gain:.1f} pts over this week and next"
        if self.tough:
            text += f". Tough call: {self.tough}"
        if self.after:
            text += f". Assumes you also add {', '.join(p.name for p in self.after)}"
        return text


def _protected(p: Player, long_term: bool) -> bool:
    """Players too valuable to suggest dropping."""
    if p.rank is not None and p.rank <= (300 if long_term else 150):
        return True
    if p.owned_pct is not None and p.owned_pct >= (40 if long_term else 60):
        return True
    return False


def _soft_reason(p: Player) -> str | None:
    """Why a droppable player is still worth keeping, if anything."""
    if p.trending and p.trending >= HOT_ADDS:
        return f"{p.name} is one of this week's hottest pickups ({p.trending:,} adds in 24h)"
    return None


def _required(slots: list[str]) -> dict[str, int]:
    """How many players each position must keep for its dedicated slots (QB, K, DEF...)."""
    need: dict[str, int] = {}
    for slot in slots:
        allowed = SLOT_POSITIONS.get(slot, set())
        if len(allowed) == 1:
            pos = next(iter(allowed))
            need[pos] = need.get(pos, 0) + 1
    return need


def _score(o: Pickup) -> tuple:
    # Clean drops first; then this week's lineup gain counts double next to two-week depth.
    return (o.tough is not None, -(2 * o.week_gain + o.two_week_gain))


def _best_option(team: Team, need: dict[str, int], taken: set[str]) -> Pickup | None:
    baseline = optimal_lineup(team).total
    counts: dict[str, int] = {}
    for p in team.roster:
        counts[p.position] = counts.get(p.position, 0) + 1

    def droppable(p: Player, add: Player) -> bool:
        if p.id in taken or _protected(p, team.long_term):
            return False
        return p.position == add.position or counts.get(p.position, 0) - 1 >= need.get(p.position, 0)

    best = None
    free = [p for p in team.free_agents if p.id not in taken]
    for add in sorted(free, key=lambda p: -p.two_week)[:CANDIDATES]:
        drops = [p for p in team.roster if droppable(p, add)]
        if not drops:
            continue
        # Prefer drops with no catch; fall back to a "tough call" only if that's all there is.
        drop = min(drops, key=lambda p: (_soft_reason(p) is not None, p.two_week, -(p.rank or 10**9)))
        trial = _swap(team, add, drop)
        week_gain = round(optimal_lineup(trial).total - baseline, 2)
        two_week_gain = round(add.two_week - drop.two_week, 2)
        tough = _soft_reason(drop)
        worth_it = (week_gain >= MIN_TOUGH_WEEK_GAIN if tough
                    else week_gain >= MIN_WEEK_GAIN or two_week_gain >= MIN_TWO_WEEK_GAIN)
        if worth_it:
            option = Pickup(add, drop, week_gain, two_week_gain, tough)
            if best is None or _score(option) < _score(best):
                best = option
    return best


def _swap(team: Team, add: Player, drop: Player) -> Team:
    return dataclasses.replace(
        team,
        roster=[p for p in team.roster if p is not drop] + [add],
        current=Lineup(team.current.slots, [None if p is drop else p for p in team.current.players]),
        free_agents=[p for p in team.free_agents if p is not add],
    )


def suggest(team: Team) -> list[Pickup]:
    """Up to MAX_SUGGESTIONS moves, each judged on the roster after the ones before it."""
    if not team.free_agents or not team.roster:
        return []
    need = _required(team.slots)
    chosen: list[Pickup] = []
    taken: set[str] = set()  # players already used by an earlier suggestion
    while len(chosen) < MAX_SUGGESTIONS:
        option = _best_option(team, need, taken)
        if option is None:
            break
        # Point back only to earlier adds this drop relies on (e.g. dropping your only DEF
        # is fine once an earlier suggestion brings in another DEF).
        option.after = [c.add for c in chosen if c.add.position == option.drop.position]
        chosen.append(option)
        taken.update({option.add.id, option.drop.id})
        team = _swap(team, option.add, option.drop)
    return chosen
