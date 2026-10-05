"""Platform-neutral data model shared by the providers, optimizer and report."""

from __future__ import annotations

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


@dataclass
class Player:
    id: str
    name: str
    position: str
    team: str | None = None
    eligible: set[str] = field(default_factory=set)
    projection: float = 0.0
    injury_status: str | None = None

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

    def label(self, with_status: bool = False) -> str:
        team = f", {self.team}" if self.team else ""
        status = f" [{self.status_label}]" if with_status and self.status_label else ""
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
