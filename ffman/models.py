"""Platform-neutral data model shared by the providers, optimizer and report."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

# Which player positions may fill each (normalized) starting slot.
SLOT_POSITIONS: dict[str, set[str]] = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "K": {"K"},
    "DEF": {"DEF"},
    "FLEX": {"RB", "WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
    "REC_FLEX": {"WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "DL": {"DL"},
    "LB": {"LB"},
    "DB": {"DB"},
    "IDP_FLEX": {"DL", "LB", "DB"},
}

# Injury designations that mean the player will not play.
OUT_STATUSES = {"OUT", "IR", "INJURY_RESERVE", "PUP", "SUS", "SUSPENSION", "COV", "NA"}
# Designations worth a heads-up, with the multiplier applied to the projection.
RISKY_STATUSES = {"DOUBTFUL": 0.25, "QUESTIONABLE": 1.0}


def eligible_slots(positions: set[str]) -> set[str]:
    return {slot for slot, allowed in SLOT_POSITIONS.items() if positions & allowed}


def fmt_time(moment: dt.datetime) -> str:
    """'Sun 1:00 PM' in the local time zone (TZ env var; the website uses Eastern)."""
    local = moment.astimezone()
    return f"{local:%a} {local.hour % 12 or 12}:{local:%M} {local:%p}"


@dataclass
class Player:
    id: str
    name: str
    position: str
    team: str | None = None
    eligible: set[str] = field(default_factory=set)
    projection: float = 0.0
    injury_status: str | None = None
    bye: bool = False
    # Filled in from the NFL schedule (see schedule.py).
    kickoff: dt.datetime | None = None
    opponent: str | None = None
    home: bool = True
    locked: bool = False  # game already started: can't be moved
    # Used for waiver suggestions.
    next_projection: float = 0.0       # next week's projection
    rank: int | None = None            # platform's overall rank (lower = more valuable)
    owned_pct: float | None = None     # % of leagues where the player is rostered
    trending: int | None = None        # adds in the last 24 hours (Sleeper)
    waiver_status: str | None = None   # "Free agent" / "On waivers", when known
    # Multi-source projections (see consensus.py).
    ppr_projection: float | None = None   # the platform's projection in plain PPR scoring
    platform_projection: float | None = None  # the platform's own number, before averaging
    sources: dict[str, float] = field(default_factory=dict)  # source -> points, league-adjusted

    @property
    def source_range(self) -> tuple[float, float] | None:
        """(low, high) across every projection behind this player's number."""
        values = list(self.sources.values())
        if self.platform_projection is not None:
            values.append(self.platform_projection)
        return (min(values), max(values)) if len(values) > 1 else None

    @property
    def is_out(self) -> bool:
        return (self.injury_status or "").upper() in OUT_STATUSES

    @property
    def effective_projection(self) -> float:
        """Projection adjusted for injury designation (what the optimizer ranks on)."""
        if self.is_out:
            return 0.0
        return self.projection * RISKY_STATUSES.get((self.injury_status or "").upper(), 1.0)

    @property
    def status_label(self) -> str | None:
        status = (self.injury_status or "").replace("_", " ")
        return (status.upper() if len(status) <= 3 else status.title()) or None

    @property
    def two_week(self) -> float:
        """This week (injury-adjusted) plus next week: the waiver value we compare on."""
        return self.effective_projection + self.next_projection

    @property
    def matchup(self) -> str | None:
        """'vs DAL' / '@ DAL', or None if unknown."""
        if self.bye or not self.opponent:
            return None
        return f"{'vs' if self.home else '@'} {self.opponent}"

    def game_label(self) -> str | None:
        """'vs DAL, Sun 1:00 PM' / 'BYE' / None."""
        if self.bye:
            return "BYE"
        if not self.kickoff:
            return None
        when = "in progress/final" if self.locked else fmt_time(self.kickoff)
        return f"{self.matchup}, {when}"

    def label(self, with_status: bool = False) -> str:
        team = f", {self.team}" if self.team else ""
        tag = "Bye" if self.bye else self.status_label
        status = f" [{tag}]" if with_status and tag else ""
        return f"{self.name} ({self.position}{team}){status}"


@dataclass
class Lineup:
    """Ordered starting slots and who fills each one (None = empty)."""

    slots: list[str]
    players: list[Player | None]

    @property
    def starters(self) -> list[Player]:
        return [p for p in self.players if p is not None]

    @property
    def total(self) -> float:
        return sum(p.effective_projection for p in self.starters)


@dataclass
class Team:
    """The user's team in one league, for one week."""

    platform: str
    league_name: str
    team_name: str
    week: int
    slots: list[str]
    # Everyone who could be started (excludes IR / taxi squad).
    roster: list[Player]
    current: Lineup
    # Best available players in this league (filled by providers that support it).
    free_agents: list[Player] = field(default_factory=list)
    waiver_note: str | None = None     # e.g. "FAAB: $72 of $100 left"
    long_term: bool = False            # keeper/dynasty league: be careful dropping players
    sources_used: list[str] = field(default_factory=list)  # projection sources averaged in
