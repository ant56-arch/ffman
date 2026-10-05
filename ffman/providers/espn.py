"""ESPN Fantasy Football (read-only).

Public leagues need only the league id. Private leagues also need the
`espn_s2` and `SWID` cookies from a logged-in browser session. Projections
are ESPN's own, already scored with the league's settings.
"""

from __future__ import annotations

import os

from ..http import FetchError, get_json
from ..models import Lineup, Player, Team

BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"

# ESPN lineup slot id -> normalized slot (None = not a starting slot).
SLOTS = {
    0: "QB", 2: "RB", 3: "WRRB_FLEX", 4: "WR", 5: "REC_FLEX", 6: "TE", 7: "SUPER_FLEX",
    8: "DL", 9: "DL", 10: "LB", 11: "DL", 12: "DB", 13: "DB", 14: "DB", 15: "IDP_FLEX",
    16: "DEF", 17: "K", 23: "FLEX",
}
BENCH, IR = 20, 21
POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 7: "P", 9: "DL", 10: "DL",
             11: "LB", 12: "DB", 13: "DB", 16: "DEF"}
PRO_TEAMS = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB",
    10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN", 17: "NE",
    18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF",
    26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}


def _cookie(config: dict, key: str, env_names: tuple[str, ...]) -> str | None:
    """Config value first, else an env var named like the cookie or ESPN_-prefixed."""
    if config.get(key):
        return config[key]
    return next((os.environ[n] for n in env_names if os.environ.get(n)), None)


def cookies_for(config: dict) -> dict:
    return {
        "espn_s2": _cookie(config, "espn_s2", ("ESPN_S2", "espn_s2")),
        "SWID": _cookie(config, "swid", ("ESPN_SWID", "SWID", "swid")),
    }


def fetch_league(config: dict, season: int, week: int | None) -> dict:
    params: dict = {"view": ["mTeam", "mRoster", "mSettings"]}
    if week:
        params["scoringPeriodId"] = week
    cookies = cookies_for(config)
    url = f"{BASE}/seasons/{season}/segments/0/leagues/{config['league_id']}"
    try:
        return get_json(url, params=params, cookies=cookies)
    except FetchError as exc:
        if "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
            raise FetchError(
                f"ESPN league {config['league_id']} is private (or the cookies expired): "
                "set the espn_s2 and SWID environment variables"
            ) from exc
        raise


def _projection(player: dict, week: int) -> float:
    for stat in player.get("stats") or []:
        if stat.get("statSourceId") == 1 and stat.get("scoringPeriodId") == week:
            return round(float(stat.get("appliedTotal") or 0), 2)
    return 0.0


def _player(entry: dict, week: int) -> Player:
    pool = entry.get("playerPoolEntry") or {}
    info = pool.get("player") or {}
    status = info.get("injuryStatus") or entry.get("injuryStatus")
    return Player(
        id=str(info.get("id", entry.get("playerId"))),
        name=info.get("fullName", "Unknown"),
        position=POSITIONS.get(info.get("defaultPositionId"), "?"),
        team=PRO_TEAMS.get(info.get("proTeamId")),
        eligible={SLOTS[s] for s in info.get("eligibleSlots") or [] if s in SLOTS},
        projection=_projection(info, week),
        injury_status=None if status in (None, "ACTIVE", "NORMAL") else status,
    )


def _find_my_team(data: dict, config: dict) -> dict:
    teams = data.get("teams") or []
    if config.get("team_id") is not None:
        for team in teams:
            if team.get("id") == int(config["team_id"]):
                return team
        raise FetchError(f"ESPN league {config['league_id']}: no team with id {config['team_id']}")
    swid = (cookies_for(config)["SWID"] or "").upper()
    for team in teams:
        if swid and swid in [o.upper() for o in team.get("owners") or []]:
            return team
    raise FetchError(f"ESPN league {config['league_id']}: set team_id (or swid) to pick your team")


def build_team(data: dict, config: dict, week: int) -> Team:
    raw = ((data.get("settings") or {}).get("rosterSettings") or {}).get("lineupSlotCounts") or {}
    counts = {int(k): n for k, n in raw.items()}
    slots = [SLOTS[sid] for sid in sorted(counts) if sid in SLOTS for _ in range(counts[sid])]

    team = _find_my_team(data, config)
    roster, filled = [], {}
    for entry in (team.get("roster") or {}).get("entries") or []:
        slot_id = entry.get("lineupSlotId")
        if slot_id == IR:
            continue
        player = _player(entry, week)
        roster.append(player)
        if slot_id in SLOTS:
            filled.setdefault(SLOTS[slot_id], []).append(player)

    current_players = [filled.get(slot, []).pop(0) if filled.get(slot) else None for slot in slots]
    name = team.get("name") or " ".join(
        p for p in (team.get("location"), team.get("nickname")) if p
    ) or f"Team {team.get('id')}"
    return Team(
        platform="ESPN",
        league_name=config.get("name") or (data.get("settings") or {}).get("name") or f"ESPN {config['league_id']}",
        team_name=name,
        week=week,
        slots=slots,
        roster=roster,
        current=Lineup(slots, current_players),
    )


def fetch_team(config: dict, season: int, week: int | None) -> Team:
    data = fetch_league(config, season, week)
    week = week or data.get("scoringPeriodId") or 1
    return build_team(data, config, week)
