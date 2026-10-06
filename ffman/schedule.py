"""NFL schedule: kickoff times, opponents and byes for a week.

Comes from ESPN's public pro-team schedule (no login needed) and is applied
to players from every platform, so locks and byes work the same everywhere.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .http import FetchError, get_json
from .models import Player, Team

URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"
# ESPN and Sleeper disagree on a few abbreviations; use one spelling everywhere.
ALIASES = {"WSH": "WAS", "JAC": "JAX", "LA": "LAR"}


def norm_team(abbrev: str | None) -> str | None:
    if not abbrev:
        return None
    abbrev = abbrev.upper()
    return ALIASES.get(abbrev, abbrev)


@dataclass
class Game:
    kickoff: dt.datetime  # timezone-aware
    opponent: str
    home: bool


def load_week(season: int, week: int) -> dict[str, Game | None]:
    """{team: Game} for teams playing, {team: None} for teams on bye."""
    data = get_json(URL.format(season=season), params={"view": "proTeamSchedules_wl"})
    teams = (data.get("settings") or {}).get("proTeams") or []
    abbrev = {t["id"]: norm_team(t.get("abbrev")) for t in teams}
    week_games: dict[str, Game | None] = {}
    for t in teams:
        if not t.get("id"):  # id 0 is "free agent"
            continue
        me = abbrev[t["id"]]
        games = (t.get("proGamesByScoringPeriod") or {}).get(str(week)) or []
        if not games:
            week_games[me] = None
            continue
        g = games[0]
        home = g.get("homeProTeamId") == t["id"]
        other = g.get("awayProTeamId") if home else g.get("homeProTeamId")
        week_games[me] = Game(
            kickoff=dt.datetime.fromtimestamp(g["date"] / 1000, dt.timezone.utc),
            opponent=abbrev.get(other, "?"),
            home=home,
        )
    return week_games


def apply(teams: list[Team], games: dict[str, Game | None], now: dt.datetime) -> None:
    """Attach kickoff/opponent/bye/locked to every rostered player."""
    for team in teams:
        for player in team.roster + team.free_agents:
            annotate(player, games, now)


def annotate(player: Player, games: dict[str, Game | None], now: dt.datetime) -> None:
    team = norm_team(player.team)
    player.team = team
    if team not in games:  # free agent or unknown team: leave as is
        return
    game = games[team]
    if game is None:
        player.bye = True
        return
    player.bye = False
    player.kickoff = game.kickoff
    player.opponent = game.opponent
    player.home = game.home
    player.locked = game.kickoff <= now


def safe_load_week(season: int, week: int) -> tuple[dict[str, Game | None], str | None]:
    try:
        return load_week(season, week), None
    except (FetchError, KeyError, TypeError, ValueError) as exc:
        return {}, f"NFL schedule unavailable ({exc}); game times and locks not shown."
