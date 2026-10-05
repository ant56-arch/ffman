"""Turn current vs. optimal lineups into plain-English recommendations."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import RISKY_STATUSES, Lineup, Player, Team
from .optimizer import optimal_lineup


@dataclass
class LeagueReport:
    team: Team
    best: Lineup
    start: list[tuple[Player, Player | None]] = field(default_factory=list)  # (start, in place of)
    warnings: list[str] = field(default_factory=list)
    min_gain: float = 0.5

    @property
    def gain(self) -> float:
        return self.best.total - self.team.current.total

    @property
    def needs_changes(self) -> bool:
        return bool(self.start) and self.gain >= self.min_gain


def analyze(team: Team, min_gain: float = 0.5) -> LeagueReport:
    best = optimal_lineup(team)
    current_ids = {p.id for p in team.current.starters}
    best_ids = {p.id for p in best.starters}

    ins = sorted((p for p in best.starters if p.id not in current_ids),
                 key=lambda p: -p.effective_projection)
    outs = sorted((p for p in team.current.starters if p.id not in best_ids),
                  key=lambda p: -p.effective_projection)
    start = [(p, outs[i] if i < len(outs) else None) for i, p in enumerate(ins)]

    warnings = []
    for slot, player in zip(best.slots, best.players):
        if player is None:
            warnings.append(f"No one on your roster can fill {slot} - grab someone off waivers.")
        elif player.is_out:
            warnings.append(f"{player.label()} is {player.status_label} but is your only {slot} option - check waivers.")
        elif player.effective_projection == 0:
            warnings.append(f"{player.label()} is projected 0 (bye week?) and is your best {slot} option - check waivers.")
        elif (player.injury_status or "").upper() in RISKY_STATUSES:
            warnings.append(f"{player.label()} is {player.status_label} - check news before kickoff.")
    return LeagueReport(team, best, start, warnings, min_gain)


def _pts(value: float) -> str:
    return f"{value:.1f}"


def render(reports: list[LeagueReport], week: int | None = None) -> str:
    lines = [f"# Lineup recommendations{f' - Week {week}' if week else ''}", ""]
    todo = [r for r in reports if r.needs_changes]
    lines.append(f"**{len(todo)} of {len(reports)} leagues have changes to make.** "
                 "Nothing has been changed for you - these are suggestions only.")
    lines.append("")
    for r in sorted(reports, key=lambda r: (not r.needs_changes, -r.gain)):
        lines.extend(render_league(r))
    return "\n".join(lines).rstrip() + "\n"


def render_league(r: LeagueReport) -> list[str]:
    t = r.team
    lines = [f"## {t.league_name} ({t.platform}) - {t.team_name}"]
    if r.needs_changes:
        lines.append(f"Projected **{_pts(t.current.total)} -> {_pts(r.best.total)}** "
                     f"(+{_pts(r.gain)}) if you make these moves:")
        for player, benched in r.start:
            target = (f"over {benched.label(True)} {_pts(benched.effective_projection)}"
                      if benched else "into an empty slot")
            lines.append(f"- START {player.label(True)} {_pts(player.effective_projection)} {target}")
    else:
        lines.append(f"Lineup looks good - projected {_pts(t.current.total)}. No changes needed.")
    if r.warnings:
        lines.append("")
        lines.extend(f"- Heads up: {w}" for w in r.warnings)
    lines.append("")
    lines.append("<details><summary>Best lineup</summary>")
    lines.append("")
    lines.append("| Slot | Player | Proj |")
    lines.append("|---|---|---|")
    for slot, player in zip(r.best.slots, r.best.players):
        if player is None:
            lines.append(f"| {slot} | (empty) | - |")
        else:
            lines.append(f"| {slot} | {player.label(True)} | {_pts(player.effective_projection)} |")
    lines.append("")
    lines.append("</details>")
    lines.append("")
    return lines
