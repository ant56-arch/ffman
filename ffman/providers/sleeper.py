"""Sleeper (public API, no login needed).

Docs: https://docs.sleeper.com. Projections come from Sleeper's public
projections endpoint and are scored with each league's own scoring settings.
"""

from __future__ import annotations

from ..http import FetchError, get_json, get_json_cached
from ..models import Lineup, Player, Team, eligible_slots

BASE = "https://api.sleeper.app/v1"
PROJECTION_POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB"]
NON_STARTING = {"BN", "IR", "TAXI"}
# Sleeper roster_positions -> normalized slot names (identity for the rest).
SLOT_ALIASES = {"WRRB_WRT": "FLEX"}


def nfl_state() -> dict:
    return get_json(f"{BASE}/state/nfl")


def load_players() -> dict:
    # ~5MB; Sleeper asks callers to fetch it at most once a day.
    return get_json_cached("sleeper_players.json", f"{BASE}/players/nfl", max_age_hours=24)


def load_projections(season: int, week: int) -> tuple[dict[str, dict], dict[str, str | None]]:
    """Return ({player_id: projected stats}, {player_id: live injury status}).

    The api.sleeper.com endpoint has full stat lines plus up-to-the-minute
    injury designations; the older v1 endpoint is only a fallback.
    """
    try:
        rows = get_json(f"https://api.sleeper.com/projections/nfl/{season}/{week}",
                        params={"season_type": "regular", "position[]": PROJECTION_POSITIONS})
    except FetchError:
        rows = None
    if isinstance(rows, list) and rows:
        stats = {str(r["player_id"]): r.get("stats") or {} for r in rows if "player_id" in r}
        statuses = {str(r["player_id"]): (r.get("player") or {}).get("injury_status")
                    for r in rows if "player_id" in r and isinstance(r.get("player"), dict)}
        return stats, statuses
    data = get_json(f"{BASE}/projections/nfl/regular/{season}/{week}") or {}
    return {str(pid): s or {} for pid, s in data.items()}, {}


# Projected stats that are context, not scoring categories.
_NOT_SCORED = {"gp", "pts_allow", "yds_allow", "adp_dd_ppr", "pos_adp_dd_ppr",
               "pts_ppr", "pts_half_ppr", "pts_std"}


def score(stats: dict, scoring: dict) -> float:
    """Apply a league's scoring settings to a projected stat line.

    Sleeper's projections already carry bonus keys (bonus_rec_te, buckets like
    pts_allow_14_20), so a straight dot product honours TE premium etc.
    """
    total = 0.0
    for key, value in stats.items():
        if key in scoring and key not in _NOT_SCORED and isinstance(value, (int, float)):
            total += value * scoring[key]
    if total == 0:
        ppr = scoring.get("rec", 0)
        key = "pts_ppr" if ppr >= 1 else "pts_half_ppr" if ppr >= 0.5 else "pts_std"
        total = float(stats.get(key) or 0)
    return round(total, 2)


def _player(pid: str, players: dict, projections: dict, statuses: dict, scoring: dict) -> Player:
    info = players.get(pid, {})
    positions = set(info.get("fantasy_positions") or [info.get("position") or "?"])
    if pid.isalpha() and pid.isupper():  # team defenses are keyed by abbreviation
        positions = {"DEF"}
    name = info.get("full_name") or " ".join(
        part for part in (info.get("first_name"), info.get("last_name")) if part
    ) or pid
    return Player(
        id=pid,
        name=name,
        position=info.get("position") or next(iter(positions)),
        team=info.get("team") or (pid if positions == {"DEF"} else None),
        eligible=eligible_slots(positions),
        projection=score(projections.get(pid, {}), scoring),
        injury_status=statuses[pid] if pid in statuses else info.get("injury_status"),
    )


def fetch_teams(config: dict, season: int, week: int) -> list[Team]:
    username = config.get("username")
    if not username:
        raise FetchError("Sleeper config needs your username to find your teams")
    user = get_json(f"{BASE}/user/{username}")
    if not user:
        raise FetchError(f"Sleeper user '{username}' not found")
    user_id = user["user_id"]
    league_ids = [str(x) for x in config.get("league_ids", [])]
    if not league_ids:
        leagues = get_json(f"{BASE}/user/{user_id}/leagues/nfl/{season}") or []
        league_ids = [lg["league_id"] for lg in leagues]
    if not league_ids:
        return []

    players = load_players()
    projections, statuses = load_projections(season, week)
    teams = []
    for league_id in league_ids:
        league = get_json(f"{BASE}/league/{league_id}")
        rosters = get_json(f"{BASE}/league/{league_id}/rosters")
        mine = next(
            (r for r in rosters
             if r.get("owner_id") == user_id or user_id in (r.get("co_owners") or [])),
            None,
        )
        if mine is None:
            continue
        teams.append(build_team(league, mine, players, projections, week, statuses))
    return teams


def build_team(league: dict, roster: dict, players: dict, projections: dict, week: int,
               statuses: dict | None = None) -> Team:
    scoring = league.get("scoring_settings") or {}
    slots = [SLOT_ALIASES.get(s, s) for s in league.get("roster_positions", []) if s not in NON_STARTING]
    unavailable = set(roster.get("reserve") or []) | set(roster.get("taxi") or [])
    all_ids = [pid for pid in (roster.get("players") or []) if pid not in unavailable]
    by_id = {pid: _player(pid, players, projections, statuses or {}, scoring) for pid in all_ids}

    starters = list(roster.get("starters") or [])
    starters += ["0"] * (len(slots) - len(starters))
    current = Lineup(slots, [by_id.get(pid) for pid in starters[: len(slots)]])

    meta = roster.get("metadata") or {}
    return Team(
        platform="Sleeper",
        league_name=league.get("name", league.get("league_id", "Sleeper league")),
        team_name=meta.get("team_name") or "My team",
        week=week,
        slots=slots,
        roster=list(by_id.values()),
        current=current,
    )
