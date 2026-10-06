"""Multi-source projections: average several free projection sites with the platform's own.

Every source here is free and needs no account or key:

- ESPN's public projections for every NFL player (standard PPR league defaults)
- Draft Sharks, CBS Sports, Fantasy Football Calculator, FantasyData and FFToday weekly
  projection pages, and StartWho's betting-line projections

The sites publish plain PPR numbers. Each league's platform projection tells us how far its
own scoring (6-point passing TDs, TE premium, half PPR...) moves a player away from plain
PPR, and that offset is added to every site's number before averaging. A source that fails,
or still shows another week, is skipped. The whole table is cached on disk and refreshed at
most every `refresh_hours`, so the sites are visited a couple of times a day, not every run.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, NamedTuple

from .http import FetchError, cache_dir, get_json, get_text
from .models import Player, Team

REFRESH_HOURS = 12
RETRY_HOURS = 2
# A starter whose sources are this many points apart gets a "check the news" alert.
DISAGREE_POINTS = 10.0


class Row(NamedTuple):
    name: str
    position: str
    team: str | None
    points: float


# ---------------------------------------------------------------- name/team matching

TEAM_ALIASES = {"LVR": "LV", "OAK": "LV", "WSH": "WAS", "JAC": "JAX", "LA": "LAR", "STL": "LAR",
                "SD": "LAC", "GNB": "GB", "KAN": "KC", "NWE": "NE", "NOR": "NO", "SFO": "SF",
                "TAM": "TB", "ARZ": "ARI", "HST": "HOU", "BLT": "BAL", "CLV": "CLE"}
TEAM_NAMES = {
    "arizona": "ARI", "atlanta": "ATL", "baltimore": "BAL", "buffalo": "BUF", "carolina": "CAR",
    "chicago": "CHI", "cincinnati": "CIN", "cleveland": "CLE", "dallas": "DAL", "denver": "DEN",
    "detroit": "DET", "green bay": "GB", "houston": "HOU", "indianapolis": "IND",
    "jacksonville": "JAX", "kansas city": "KC", "las vegas": "LV", "los angeles chargers": "LAC",
    "los angeles rams": "LAR", "miami": "MIA", "minnesota": "MIN", "new england": "NE",
    "new orleans": "NO", "new york giants": "NYG", "new york jets": "NYJ", "philadelphia": "PHI",
    "pittsburgh": "PIT", "san francisco": "SF", "seattle": "SEA", "tampa bay": "TB",
    "tennessee": "TEN", "washington": "WAS",
}
NICKNAMES = {
    "cardinals": "ARI", "falcons": "ATL", "ravens": "BAL", "bills": "BUF", "panthers": "CAR",
    "bears": "CHI", "bengals": "CIN", "browns": "CLE", "cowboys": "DAL", "broncos": "DEN",
    "lions": "DET", "packers": "GB", "texans": "HOU", "colts": "IND", "jaguars": "JAX",
    "chiefs": "KC", "raiders": "LV", "chargers": "LAC", "rams": "LAR", "dolphins": "MIA",
    "vikings": "MIN", "patriots": "NE", "saints": "NO", "giants": "NYG", "jets": "NYJ",
    "eagles": "PHI", "steelers": "PIT", "49ers": "SF", "niners": "SF", "seahawks": "SEA",
    "buccaneers": "TB", "titans": "TEN", "commanders": "WAS",
}
POSITION_ALIASES = {"DST": "DEF", "D/ST": "DEF", "D": "DEF", "PK": "K"}
SUFFIXES = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def team_code(value: str | None) -> str | None:
    """'LVR' / 'Las Vegas Raiders' / 'Vikings D/ST' -> Sleeper-style code ('LV', 'MIN')."""
    if not value:
        return None
    text = value.strip()
    if text.upper() == text and len(text) <= 3:
        return TEAM_ALIASES.get(text.upper(), text.upper())
    low = text.lower()
    for name in sorted(TEAM_NAMES, key=len, reverse=True):  # "los angeles rams" before "los angeles"
        if low.startswith(name):
            return TEAM_NAMES[name]
    for word in re.findall(r"[a-z0-9]+", low):
        if word in NICKNAMES:
            return NICKNAMES[word]
    return None


def norm_name(name: str) -> str:
    name = html.unescape(name).lower().replace(".", "").replace("'", "").replace("’", "")
    return re.sub(r"[^a-z]", "", SUFFIXES.sub("", name))


def norm_pos(pos: str) -> str:
    pos = (pos or "").strip().upper()
    return POSITION_ALIASES.get(pos, pos)


def _last(name: str) -> str:
    words = [w for w in SUFFIXES.sub("", html.unescape(name).lower().replace(".", "")).split() if w]
    return re.sub(r"[^a-z]", "", words[-1]) if words else ""


class Table:
    """One source's rows, indexed for lookup by name or (last name, team, position)."""

    def __init__(self, rows: list[Row]):
        self.by_name: dict[tuple[str, str], float] = {}
        self.by_last: dict[tuple[str, str | None, str], list[float]] = {}
        self.by_team_def: dict[str, float] = {}
        for r in rows:
            pos = norm_pos(r.position)
            team = team_code(r.team)
            if pos == "DEF":
                team = team or team_code(r.name)
                if team:
                    self.by_team_def.setdefault(team, r.points)
                continue
            self.by_name.setdefault((norm_name(r.name), pos), r.points)
            self.by_last.setdefault((_last(r.name), team, pos), []).append(r.points)

    def lookup(self, p: Player) -> float | None:
        pos = norm_pos(p.position)
        if pos == "DEF":
            return self.by_team_def.get(team_code(p.team) or "")
        hit = self.by_name.get((norm_name(p.name), pos))
        if hit is not None:
            return hit
        # "Cam Ward" vs "Cameron Ward": same last name, team and position, if unique.
        alts = self.by_last.get((_last(p.name), team_code(p.team), pos), [])
        return alts[0] if len(alts) == 1 else None


# ---------------------------------------------------------------- the sources

def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment)).strip()


def _num(text: str) -> float | None:
    try:
        return float(text.replace(",", "").strip())
    except ValueError:
        return None


def _check_week(page: str, week: int, source: str) -> None:
    found = re.findall(r"Week\s*(\d{1,2})", page[:20000]) or re.findall(r"Week\s*(\d{1,2})", page)
    if found and str(week) not in found[:3]:
        raise FetchError(f"{source} still shows week {found[0]}, not week {week}")


ESPN_POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}
ESPN_TEAMS = {1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB",
              10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN", 17: "NE",
              18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF",
              26: "SEA", 27: "TB", 28: "WAS", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU"}


def parse_espn(data: dict, week: int) -> list[Row]:
    rows = []
    for entry in data.get("players") or []:
        info = entry.get("player") or {}
        pos = ESPN_POSITIONS.get(info.get("defaultPositionId"))
        if not pos:
            continue
        pts = next((s.get("appliedTotal") for s in info.get("stats") or []
                    if s.get("statSourceId") == 1 and s.get("scoringPeriodId") == week), None)
        if pts is not None:
            rows.append(Row(info.get("fullName", ""), pos, ESPN_TEAMS.get(info.get("proTeamId")),
                            round(float(pts), 2)))
    return rows


def fetch_espn(season: int, week: int) -> list[Row]:
    """ESPN's projections for every player, in ESPN's default PPR scoring. No login needed."""
    flt = {"players": {"filterStatsForSourceIds": {"value": [1]},
                       "filterStatsForSplitTypeIds": {"value": [1]},
                       "filterStatsForCurrentSeasonScoringPeriodId": {"value": [week]},
                       "sortPercOwned": {"sortPriority": 1, "sortAsc": False}, "limit": 1000}}
    data = get_json(f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"
                    "/segments/0/leaguedefaults/3",
                    params={"scoringPeriodId": week, "view": "kona_player_info"},
                    headers={"X-Fantasy-Filter": json.dumps(flt)})
    return parse_espn(data, week)


def parse_startwho(data: dict, week: int) -> list[Row]:
    if data.get("weekNumber") not in (None, week):
        raise FetchError(f"StartWho still shows week {data.get('weekNumber')}, not week {week}")
    return [Row(p.get("playerName", ""), p.get("position", ""), p.get("team"),
                float(p["fantasyPoints"]))
            for p in data.get("projections") or [] if p.get("fantasyPoints") is not None]


def fetch_startwho(season: int, week: int) -> list[Row]:
    rows = []
    for pos in ("All", "DEF"):
        data = get_json("https://startwho.com/api/projections",
                        params={"sport": "NFL", "format": "PPR", "position": pos, "week": week},
                        headers={"User-Agent": "Mozilla/5.0"})
        rows += parse_startwho(data, week)
    return rows


def parse_draftsharks(page: str, week: int) -> list[Row]:
    _check_week(page, week, "Draft Sharks")
    rows = []
    for block in page.split("<tbody data-player-row")[1:]:
        name = re.search(r'data-player-name="([^"]*)"', block)
        pos = re.search(r'data-fantasy-position="([^"]*)"', block)
        pts = re.search(r'data-value="([^"]*)" data-attribute="weeklyPts"', block)
        team = re.search(r'player-details-group__team-name">([^<]*)<', block)
        if name and pos and pts and _num(pts.group(1)) is not None:
            rows.append(Row(html.unescape(name.group(1)), pos.group(1),
                            team.group(1).strip() if team else None, _num(pts.group(1))))
    return rows


def fetch_draftsharks(season: int, week: int) -> list[Row]:
    rows = []
    for pos in ("QB", "FLEX", "K", "DEF"):
        rows += parse_draftsharks(get_text(
            "https://www.draftsharks.com/weekly-rankings/load-table"
            f"?pprSuperflexSlug=ppr&fantasyPosition={pos}&week={week}"), week)
    return rows


def parse_cbs(page: str, week: int, position: str) -> list[Row]:
    if f"Week {week} Proj" not in page:
        raise FetchError(f"CBS Sports isn't showing week {week} projections")
    head = page.split("TableBase-bodyTr", 1)[0]
    headers = re.findall(r"<th\b.*?</th>", head[head.rfind("<thead"):], flags=re.S)
    col = next((i for i, th in enumerate(headers) if re.search(r">\s*fpts\s*<", th)), None)
    rows = []
    for tr in re.findall(r'<tr class="TableBase-bodyTr.*?</tr>', page, flags=re.S):
        cells = re.findall(r"<td\b.*?</td>", tr, flags=re.S)
        if not cells:
            continue
        long_name = re.search(r'CellPlayerName--long.*?<a [^>]*>([^<]+)</a>', cells[0], flags=re.S)
        team = re.search(r'CellPlayerName-team">\s*([A-Z]{2,3})', cells[0])
        if long_name:
            name = long_name.group(1)
        else:  # team defenses link to the team page
            link = re.search(r"/nfl/teams/([A-Z]{2,3})/", cells[0])
            if not link:
                continue
            name, team = _text(cells[0]), link
        pts = _num(_text(cells[col])) if col is not None and col < len(cells) else None
        if pts is None:
            pts = _num(_text(cells[-2])) if len(cells) > 2 else None  # fpts, then fppg
        if pts is not None:
            rows.append(Row(name.strip(), position, team.group(1) if team else None, pts))
    return rows


def fetch_cbs(season: int, week: int) -> list[Row]:
    rows = []
    for pos in ("QB", "RB", "WR", "TE", "K", "DST"):
        page = get_text(f"https://www.cbssports.com/fantasy/football/stats/{pos}/{season}/{week}"
                        "/projections/ppr/")
        rows += parse_cbs(page, week, pos)
    return rows


def parse_ffc(page: str, week: int, position: str | None = None) -> list[Row]:
    _check_week(page, week, "Fantasy Football Calculator")
    rows = []
    for tr in re.findall(r"<tr>\s*<td>.*?</tr>", page, flags=re.S):
        cells = [_text(c) for c in re.findall(r"<td\b.*?</td>", tr, flags=re.S)]
        if len(cells) < 5:
            continue
        pts = _num(cells[-1])
        if pts is not None:
            rows.append(Row(cells[1], position or cells[3], cells[2], pts))
    return rows


def fetch_ffc(season: int, week: int) -> list[Row]:
    rows = []
    for slug, pos in (("qb", "QB"), ("rb", "RB"), ("wr", "WR"), ("te", "TE"),
                      ("kicker", "K"), ("defense", "DEF")):
        rows += parse_ffc(get_text(f"https://fantasyfootballcalculator.com/rankings/ppr/{slug}"),
                          week, pos)
    return rows


def parse_fantasydata(page: str, week: int, position: str | None = None) -> list[Row]:
    _check_week(page, week, "FantasyData")
    rows = []
    head, _, body = page.partition("<tbody")
    columns = re.findall(r'<th\b[^>]*data-id="([^"]*)"', head[head.rfind("<thead"):])
    col = next((i for i, c in enumerate(columns) if c.startswith("fpts")), -1)
    for tr in re.findall(r"<tr\b.*?</tr>", body, flags=re.S):
        cells = [_text(c) for c in re.findall(r"<td\b.*?</td>", tr, flags=re.S)]
        if len(cells) < 4 or (col >= 0 and len(cells) != len(columns)):
            continue
        pts = _num(cells[col])
        pos = position or re.sub(r"\d+$", "", cells[4] if len(cells) > 5 else "")
        if pts is not None and pos:
            rows.append(Row(cells[1], pos, cells[2], pts))
    return rows


def fetch_fantasydata(season: int, week: int) -> list[Row]:
    rows = parse_fantasydata(get_text("https://fantasydata.com/nfl/ppr-rankings"), week)
    for slug, pos in (("qb", "QB"), ("rb", "RB"), ("wr", "WR"), ("te", "TE"), ("k", "K"),
                      ("dst", "DEF")):
        try:
            rows += parse_fantasydata(get_text(f"https://fantasydata.com/nfl/ppr-rankings/{slug}"),
                                      week, pos)
        except FetchError:
            continue  # the overall page above still covers the top 100
    return rows


def parse_fftoday(page: str, week: int, position: str) -> list[Row]:
    _check_week(page, week, "FFToday")
    rows = []
    for tr in re.findall(r"<tr>\s*<td class=\"bodycontent\".*?</tr>", page, flags=re.S):
        cells = re.findall(r"<td\b.*?</td>", tr, flags=re.S)
        name = re.search(r'/stats/players/[^"]*">([^<]+)</a>', tr)
        if name and len(cells) > 3:
            pts = _num(_text(cells[-1]))
            if pts is not None:
                rows.append(Row(name.group(1), position, _text(cells[2]), pts))
    return rows


def fetch_fftoday(season: int, week: int) -> list[Row]:
    rows = []
    for pos_id, pos in ((10, "QB"), (20, "RB"), (30, "WR"), (40, "TE"), (80, "K")):
        page = get_text("https://www.fftoday.com/rankings/playerwkproj.php"
                        f"?Season={season}&GameWeek={week}&PosID={pos_id}&LeagueID=107644")
        rows += parse_fftoday(page, week, pos)
    return rows


SOURCES: dict[str, tuple[str, Callable[[int, int], list[Row]]]] = {
    "espn": ("ESPN", fetch_espn),
    "draftsharks": ("Draft Sharks", fetch_draftsharks),
    "cbs": ("CBS Sports", fetch_cbs),
    "ffc": ("Fantasy Football Calculator", fetch_ffc),
    "fantasydata": ("FantasyData", fetch_fantasydata),
    "fftoday": ("FFToday", fetch_fftoday),
    "startwho": ("StartWho", fetch_startwho),
}


# ---------------------------------------------------------------- fetching + cache

class Consensus(NamedTuple):
    tables: dict[str, Table]          # source label -> table
    skipped: dict[str, str]           # source label -> why it was left out
    fetched_at: float


def _wanted(config: dict) -> list[str]:
    chosen = config.get("sources", "all")
    if chosen in ("all", None):
        return list(SOURCES)
    if chosen in ("none", False, []):
        return []
    return [s for s in chosen if s in SOURCES]


def load(season: int, week: int, config: dict | None = None,
         now: float | None = None) -> Consensus:
    """Every source's rows for this week, from the disk cache when it's fresh enough."""
    config = config or {}
    now = now or time.time()
    refresh = float(config.get("refresh_hours", REFRESH_HOURS)) * 3600
    path = cache_dir() / f"consensus_{season}_w{week}.json"
    cached: dict = {}
    if path.exists():
        try:
            cached = json.loads(path.read_text())
        except ValueError:
            cached = {}
    keys = _wanted(config)

    def due(key: str) -> bool:
        entry = cached.get(key, {})
        if "at" in entry and now - entry["at"] <= refresh:
            return False
        # A site that just failed isn't retried on every run, only every couple of hours.
        return "tried" not in entry or now - entry["tried"] > RETRY_HOURS * 3600

    stale = [k for k in keys if due(k)]

    def grab(key: str):
        try:
            rows = SOURCES[key][1](season, week)
            if not rows:
                raise FetchError("no projections found on the page")
            return key, {"at": now, "rows": [list(r) for r in rows]}
        except (FetchError, KeyError, ValueError, TypeError, AttributeError, IndexError) as exc:
            reason = str(exc).split(" failed: ")[-1].replace("<urlopen error", "").strip(" <>")
            old = cached.get(key, {})
            # Keep the last good copy for up to a day; note the failure either way.
            return key, {**old, "error": reason[:160], "tried": now}

    if stale:
        with ThreadPoolExecutor(max_workers=min(len(stale), 7)) as pool:
            for key, entry in pool.map(grab, stale):
                cached[key] = entry
        path.write_text(json.dumps(cached))

    tables, skipped = {}, {}
    for key in keys:
        label = SOURCES[key][0]
        entry = cached.get(key, {})
        if entry.get("rows") and now - entry.get("at", 0) <= max(refresh, 24 * 3600):
            tables[label] = Table([Row(*r) for r in entry["rows"]])
        else:
            skipped[label] = entry.get("error", "not loaded")
    oldest = min((cached[k]["at"] for k in keys if SOURCES[k][0] in tables), default=now)
    return Consensus(tables, skipped, oldest)


# ---------------------------------------------------------------- blending

def _blend(values: list[float]) -> float:
    """Average, dropping the single highest and lowest once there are five or more."""
    values = sorted(values)
    if len(values) >= 5:
        values = values[1:-1]
    return round(sum(values) / len(values), 2)


def apply_player(p: Player, data: Consensus, platform: str) -> None:
    p.platform_projection = p.projection
    if p.bye or p.is_out:
        return
    own = "ESPN" if platform == "ESPN" else None
    ppr_base = p.ppr_projection
    if own and own in data.tables:
        ppr_base = data.tables[own].lookup(p)  # ESPN league: compare with ESPN's own PPR number
    shift = p.projection - ppr_base if ppr_base is not None and p.projection else 0.0
    found = {}
    for label, table in data.tables.items():
        if label == own:
            continue
        pts = table.lookup(p)
        if pts is not None:
            found[label] = round(max(pts + shift, 0.0), 2)
    p.sources = found
    if not found:
        return
    if p.projection == 0 and p.position not in ("DEF", "K"):
        # The platform says he won't score (usually injury news). Trust that, but the
        # disagreement is surfaced as an alert in the report.
        return
    p.projection = _blend(list(found.values()) + [p.projection])


def apply(teams: list[Team], data: Consensus) -> None:
    if not data.tables:
        return
    for t in teams:
        for p in t.roster + t.free_agents:
            apply_player(p, data, t.platform)
        own = "ESPN" if t.platform == "ESPN" else None
        t.sources_used = [t.platform] + [label for label in data.tables if label != own]


def disagreement(p: Player) -> str | None:
    """A short note when the sources are far apart on a player, else None."""
    if p.bye or p.is_out or not p.sources:
        return None
    values = dict(p.sources)
    if p.platform_projection is not None:
        values["platform"] = p.platform_projection
    low = min(values, key=values.get)
    high = max(values, key=values.get)
    if values[high] - values[low] < DISAGREE_POINTS:
        return None
    name = lambda k: "his platform" if k == "platform" else k  # noqa: E731
    return f"{name(low)} {values[low]:.1f}, {name(high)} {values[high]:.1f}"


def describe(data: Consensus) -> str:
    used = ", ".join(data.tables) or "none"
    text = f"Projection sources: platform + {used}."
    if data.skipped:
        text += " Skipped: " + "; ".join(f"{k} ({v})" for k, v in data.skipped.items()) + "."
    when = dt.datetime.fromtimestamp(data.fetched_at).astimezone()
    return text + f" Checked {when:%a %b} {when.day} {when.hour % 12 or 12}:{when:%M %p}."
