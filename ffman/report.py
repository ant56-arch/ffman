"""Turn current vs. optimal lineups into plain-English recommendations."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import NamedTuple

from .consensus import disagreement
from .models import RISKY_STATUSES, Lineup, Player, Team, fmt_time
from .optimizer import optimal_lineup
from .waivers import Pickup, suggest

CLOSE_CALL = 1.5  # projected points; smaller gains are flagged as toss-ups


class Move(NamedTuple):
    player: Player               # start this player...
    benched: Player | None       # ...in place of this one (None = empty slot)

    @property
    def gain(self) -> float:
        return self.player.effective_projection - (self.benched.effective_projection if self.benched else 0)

    @property
    def close_call(self) -> bool:
        return self.gain < CLOSE_CALL

    @property
    def deadline(self) -> dt.datetime | None:
        """The move has to be made before either player's game kicks off."""
        times = [p.kickoff for p in (self.player, self.benched) if p is not None and p.kickoff]
        return min(times) if times else None


class Alert(NamedTuple):
    level: str        # "bad" = needs a waiver pickup, "warn" = monitor the news
    text: str
    player: Player | None = None

    @property
    def deadline(self) -> dt.datetime | None:
        return self.player.kickoff if self.player and not self.player.locked else None


@dataclass
class LeagueReport:
    team: Team
    best: Lineup
    start: list[Move] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    min_gain: float = 0.5
    waivers: list[Pickup] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        return [a.text for a in self.alerts]

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

    ins = [p for p in best.starters if p.id not in current_ids]
    outs = [p for p in team.current.starters if p.id not in best_ids]
    # Pair each new starter with whoever held the same slot, then the rest by projection.
    start: list[Move] = []
    for new, old in zip(best.players, team.current.players):
        if new in ins and old in outs:
            start.append(Move(new, old))
            ins.remove(new)
            outs.remove(old)
    ins.sort(key=lambda p: -p.effective_projection)
    outs.sort(key=lambda p: -p.effective_projection)
    start += [Move(p, outs[i] if i < len(outs) else None) for i, p in enumerate(ins)]
    start.sort(key=lambda m: -m.gain)

    alerts = []
    for slot, player in zip(best.slots, best.players):
        if player is None:
            alerts.append(Alert("bad", f"No one on your roster can fill {slot} - grab someone off waivers."))
        elif player.locked:
            continue  # game under way; nothing to act on
        elif player.is_out:
            alerts.append(Alert("bad", f"{player.label()} is {player.status_label} but is your only {slot} option - pick up a {slot}.", player))
        elif player.bye:
            alerts.append(Alert("bad", f"{player.label()} is on bye and is your only {slot} option - pick up a {slot}.", player))
        elif player.effective_projection == 0:
            others = (f" (other sources average {sum(player.sources.values()) / len(player.sources):.1f},"
                      " so check the news)" if player.sources else "")
            alerts.append(Alert("bad", f"{player.label()} is projected 0{others} and is your best {slot} option"
                                       " - pick up a backup.", player))
        elif (player.injury_status or "").upper() in RISKY_STATUSES:
            when = f" before {fmt_time(player.kickoff)}" if player.kickoff else " before kickoff"
            alerts.append(Alert("warn", f"{player.label()} is {player.status_label} - check the inactive list{when}.", player))
        elif spread := disagreement(player):
            alerts.append(Alert("warn", f"Projections disagree on {player.label()} ({spread}) - check the news.", player))
    return LeagueReport(team, best, start, alerts, min_gain, suggest(team))


@dataclass
class GamePlan:
    """Everything to do across all leagues, soonest deadline first."""

    moves: list[tuple[LeagueReport, Move]]
    pickups: list[tuple[LeagueReport, Alert]]
    watch: list[tuple[LeagueReport, Alert]]
    all_set: list[LeagueReport]
    waivers: list[tuple[LeagueReport, Pickup]] = field(default_factory=list)


def _soonest(moment: dt.datetime | None) -> tuple:
    return (moment is None, moment or dt.datetime.max.replace(tzinfo=dt.timezone.utc))


def game_plan(reports: list[LeagueReport]) -> GamePlan:
    moves = [(r, m) for r in reports if r.needs_changes for m in r.start]
    moves.sort(key=lambda rm: (_soonest(rm[1].deadline), -rm[1].gain))
    pickups = [(r, a) for r in reports for a in r.alerts if a.level == "bad"]
    watch = [(r, a) for r in reports for a in r.alerts if a.level == "warn"]
    watch.sort(key=lambda ra: _soonest(ra[1].deadline))
    waivers = [(r, w) for r in reports for w in r.waivers]
    waivers.sort(key=lambda rw: (-rw[1].week_gain, -rw[1].two_week_gain))
    return GamePlan(moves, pickups, watch, [r for r in reports if not r.needs_changes], waivers)


def deadline_label(moment: dt.datetime | None) -> str:
    return f"Before {fmt_time(moment)}" if moment else "Any time"


def waiver_line(w: Pickup) -> str:
    add = w.add
    extra = [f"{add.effective_projection:.1f} this week, {add.next_projection:.1f} next"]
    if add.trending:
        extra.append(f"{add.trending:,} adds in 24h")
    if add.owned_pct is not None:
        extra.append(f"{add.owned_pct:.0f}% rostered")
    drop = f", drop {w.drop.name} ({w.drop.position})" if w.drop else ""
    return f"Add {add.name} ({add.position}, {add.team or 'FA'}){drop}. {w.reason}. [{'; '.join(extra)}]"


def _pts(value: float) -> str:
    return f"{value:.1f}"


def _with_game(p: Player) -> str:
    game = p.game_label()
    return f"{p.label(True)}{f' ({game})' if game and not p.bye else ''}"


def render(reports: list[LeagueReport], week: int | None = None, sources_note: str | None = None) -> str:
    plan = game_plan(reports)
    lines = [f"# Lineup recommendations{f' - Week {week}' if week else ''}", ""]
    todo = [r for r in reports if r.needs_changes]
    lines.append(f"**{len(todo)} of {len(reports)} leagues have changes to make.** "
                 "Nothing has been changed for you - these are suggestions only.")
    if sources_note:
        lines.append("")
        lines.append(f"_{sources_note}_")
    lines.append("")
    if plan.moves:
        lines.append("## Game plan")
        current = object()
        for r, m in plan.moves:
            label = deadline_label(m.deadline)
            if label != current:
                lines.append(f"\n**{label}**")
                current = label
            lines.append(f"- {r.team.league_name}: START {m.player.name} over "
                         f"{m.benched.name if m.benched else 'empty slot'} (+{_pts(m.gain)})"
                         + (" - close call" if m.close_call else ""))
        lines.append("")
    if plan.pickups:
        lines.append("## Waiver pickups needed")
        lines.extend(f"- {r.team.league_name}: {a.text}" for r, a in plan.pickups)
        lines.append("")
    if plan.waivers:
        lines.append("## Waiver wire")
        lines.extend(f"- {r.team.league_name}: {waiver_line(w)}" for r, w in plan.waivers)
        lines.append("")
    if plan.watch:
        lines.append("## Watch list")
        lines.extend(f"- {r.team.league_name}: {a.text}" for r, a in plan.watch)
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
        for m in r.start:
            target = (f"over {_with_game(m.benched)} {_pts(m.benched.effective_projection)}"
                      if m.benched else "into an empty slot")
            close = " - close call" if m.close_call else ""
            lines.append(f"- START {_with_game(m.player)} {_pts(m.player.effective_projection)} {target}{close}")
    else:
        lines.append(f"Lineup looks good - projected {_pts(t.current.total)}. No changes needed.")
    if r.warnings:
        lines.append("")
        lines.extend(f"- Heads up: {w}" for w in r.warnings)
    lines.append("")
    lines.append("<details><summary>Best lineup</summary>")
    lines.append("")
    lines.append("| Slot | Player | Game | Proj |")
    lines.append("|---|---|---|---|")
    for slot, player in zip(r.best.slots, r.best.players):
        if player is None:
            lines.append(f"| {slot} | (empty) | | - |")
        else:
            spread = player.source_range
            rng = f" ({_pts(spread[0])}-{_pts(spread[1])})" if spread else ""
            lines.append(f"| {slot} | {player.label(True)} | {player.game_label() or ''} | "
                         f"{_pts(player.effective_projection)}{rng} |")
    lines.append("")
    lines.append("</details>")
    lines.append("")
    return lines
