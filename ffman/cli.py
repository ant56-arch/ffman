"""ffman command line: `ffman` (check all leagues) and `ffman init`."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import tomllib
from pathlib import Path

from . import notify, web
from .http import FetchError
from .providers import espn, sleeper
from .report import analyze, render

EXAMPLE_CONFIG = Path(__file__).with_name("config.example.toml")


def _expand(value):
    """Let secrets live in env vars: `espn_s2 = "env:ESPN_S2"`."""
    if isinstance(value, str) and value.startswith("env:"):
        return os.environ.get(value[4:], "")
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def default_config_path() -> str:
    if env := os.environ.get("FFMAN_CONFIG_PATH"):
        return env
    return "config.toml" if Path("config.toml").exists() else "~/.config/ffman/config.toml"


def load_config(path: str) -> dict:
    if inline := os.environ.get("FFMAN_CONFIG"):
        return _expand(tomllib.loads(inline))
    file = Path(path).expanduser()
    if not file.exists():
        sys.exit(f"No config at {file}. Run `ffman init` to create one.")
    return _expand(tomllib.loads(file.read_text()))


def week_from_calendar(season_start: str, today: dt.date) -> int:
    """NFL week whose lineups are still being set: weeks roll over each Tuesday."""
    start = dt.date.fromisoformat(season_start)
    first_tuesday = start - dt.timedelta(days=(start.weekday() - 1) % 7)
    return min(max((today - first_tuesday).days // 7 + 1, 1), 18)


def current_season_and_week() -> tuple[int, int | None]:
    try:
        state = sleeper.nfl_state()
        week = int(state.get("week") or 1)
        if state.get("season_type") == "regular" and state.get("season_start_date"):
            # Sleeper can lag a day or two after Monday night; don't show a finished week.
            week = max(week, week_from_calendar(state["season_start_date"], dt.date.today()))
        return int(state.get("league_season") or state["season"]), week
    except (FetchError, KeyError, ValueError):
        today = dt.date.today()
        return (today.year if today.month >= 8 else today.year - 1), None


def collect_teams(config: dict, season: int, week: int | None, only: str | None):
    teams, errors = [], []
    if config.get("sleeper"):
        try:
            teams += sleeper.fetch_teams(config["sleeper"], season, week or 1)
        except FetchError as exc:
            errors.append(f"Sleeper: {exc}")
    for league in config.get("espn", []):
        try:
            teams.append(espn.fetch_team(league, season, week))
        except FetchError as exc:
            errors.append(f"ESPN {league.get('name') or league.get('league_id')}: {exc}")
    if only:
        teams = [t for t in teams if only.lower() in t.league_name.lower()]
    return teams, errors


def cmd_init(args) -> None:
    target = Path(args.config).expanduser()
    if target.exists():
        sys.exit(f"{target} already exists - edit it directly.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(EXAMPLE_CONFIG.read_text())
    print(f"Wrote {target}. Fill in your leagues, then run `ffman`.")


def build_reports(config: dict, args, week: int | None):
    """Fetch every league and analyze it. Returns (reports, week shown, errors)."""
    settings = config.get("settings", {})
    season, current_week = current_season_and_week()
    season = args.season or settings.get("season") or season
    week = week or current_week
    teams, errors = collect_teams(config, season, week, args.league)
    reports = [analyze(t, float(settings.get("min_gain", 0.5))) for t in teams]
    return reports, week or (teams[0].week if teams else None), errors


def cmd_run(args) -> int:
    config = load_config(args.config)
    reports, shown_week, errors = build_reports(config, args, args.week)
    text = render(reports, shown_week)
    if errors:
        text += "\n## Problems\n" + "\n".join(f"- {e}" for e in errors) + "\n"

    print(text)
    if args.output:
        Path(args.output).write_text(text)
    if args.html:
        Path(args.html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.html).write_text(web.full_page(web.render_dashboard(reports, shown_week, errors)))
        print(f"Wrote {args.html}", file=sys.stderr)
    if summary_file := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_file, "a") as fh:
            fh.write(text)
    if args.notify and reports:
        channels = notify.send(config.get("notify", {}), notify.summary(reports, shown_week))
        print(f"Notified via: {', '.join(channels) or 'nothing configured'}", file=sys.stderr)
    return 1 if errors and not reports else 0


def cmd_serve(args) -> int:
    config = load_config(args.config)
    web.serve(lambda week: build_reports(config, args, week or args.week),
              host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ffman",
        description="Read-only fantasy football lineup advisor. Never changes your lineups.",
    )
    parser.add_argument("--config", default=default_config_path())
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="create a starter config file")
    run = sub.add_parser("run", help="check every league and recommend lineups (default)")
    site = sub.add_parser("serve", help="run the ffman website on this computer")
    site.add_argument("--port", type=int, default=8000)
    site.add_argument("--host", default="127.0.0.1",
                      help="use 0.0.0.0 to open it from your phone on the same Wi-Fi")
    for p, default in ((parser, None), (run, argparse.SUPPRESS), (site, argparse.SUPPRESS)):
        p.add_argument("--week", type=int, default=default, help="NFL week (default: current)")
        p.add_argument("--season", type=int, default=default, help="season year (default: current)")
        p.add_argument("--league", default=default, help="only leagues whose name contains this text")
        p.add_argument("--output", default=default, help="also write the report to this file")
        p.add_argument("--html", default=default, help="also write the dashboard web page to this file")
        p.add_argument("--notify", action="store_true", default=default or False,
                       help="send a summary via ntfy/Discord")
    args = parser.parse_args(argv)
    if args.command == "init":
        cmd_init(args)
        return 0
    if args.command == "serve":
        return cmd_serve(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
