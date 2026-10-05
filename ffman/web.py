"""The ffman website: an HTML dashboard of every league's recommendations.

`render_dashboard` builds the page body (also used for static snapshots);
`serve` runs a small local site that refreshes data on each load.
"""

from __future__ import annotations

import datetime as dt
import html
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .models import RISKY_STATUSES, Player
from .report import LeagueReport

POSITION_CLASS = {"QB": "qb", "RB": "rb", "WR": "wr", "TE": "te", "K": "k", "DEF": "def"}
SLOT_LABEL = {"SUPER_FLEX": "SFLX", "REC_FLEX": "W/T", "WRRB_FLEX": "W/R", "IDP_FLEX": "IDP"}

STYLE = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@600;800&family=Source+Sans+3:wght@400;600;700&family=IBM+Plex+Mono:wght@500&display=swap">
<style>
/* Layout: a coach's sheet. Summary strip up top, then one card per league,
   leagues needing moves first. Position colors follow fantasy-app convention. */
:root {
  --bg: #f3f5f1; --surface: #ffffff; --ink: #18211b; --muted: #5d6a61; --line: #dbe1da;
  --turf: #1f6b3a; --turf-soft: #e1efe5;
  --warn: #9a6200; --warn-soft: #fbf0d9; --bad: #b3261e; --bad-soft: #fbe4e2;
  --qb: #c2414b; --rb: #2f8a57; --wr: #2f6fb3; --te: #c7721c; --k: #7a5bb5; --def: #5b6670;
  --display: "Saira Condensed", "Arial Narrow", sans-serif;
  --body: "Source Sans 3", "Segoe UI", system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #111613; --surface: #19201b; --ink: #e7ece8; --muted: #9aa69e; --line: #2b352e;
  --turf: #5fc184; --turf-soft: #1d3325;
  --warn: #e9b44c; --warn-soft: #3a2f17; --bad: #f2867e; --bad-soft: #3d1f1d;
  --qb: #e57a83; --rb: #6cc595; --wr: #74a9e3; --te: #e8a35c; --k: #ab92dc; --def: #9aa6b0;
  color-scheme: dark;
} }
:root[data-theme="dark"] {
  --bg: #111613; --surface: #19201b; --ink: #e7ece8; --muted: #9aa69e; --line: #2b352e;
  --turf: #5fc184; --turf-soft: #1d3325;
  --warn: #e9b44c; --warn-soft: #3a2f17; --bad: #f2867e; --bad-soft: #3d1f1d;
  --qb: #e57a83; --rb: #6cc595; --wr: #74a9e3; --te: #e8a35c; --k: #ab92dc; --def: #9aa6b0;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--ink); font: 400 15px/1.45 var(--body); margin: 0; }
.wrap { max-width: 980px; margin: 0 auto; padding-inline: 16px; padding-block: 28px 48px;
  display: grid; gap: 22px; }
header { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 12px; }
h1 { font: 800 clamp(30px, 6vw, 44px)/1 var(--display); letter-spacing: .01em; margin: 0;
  text-transform: uppercase; text-wrap: balance; }
h1 span { color: var(--turf); }
.meta { color: var(--muted); font-size: 13px; }
.weekform { display: flex; gap: 8px; align-items: center; font-size: 14px; }
.weekform select, .weekform button { font: inherit; padding: 6px 10px; border-radius: 6px;
  border: 1px solid var(--line); background: var(--surface); color: var(--ink); }
.weekform button { background: var(--turf); border-color: var(--turf); color: var(--surface);
  font-weight: 700; cursor: pointer; }
:focus-visible { outline: 2px solid var(--turf); outline-offset: 2px; }
.strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1px;
  background: var(--line); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
.stat { background: var(--surface); padding: 14px 16px; display: grid; gap: 2px; }
.stat b { font: 800 30px/1 var(--display); font-variant-numeric: tabular-nums; }
.stat small { color: var(--muted); text-transform: uppercase; letter-spacing: .08em; font-size: 11px;
  font-weight: 700; }
.note { color: var(--muted); font-size: 13px; margin: 0; }
.jump { display: flex; flex-wrap: wrap; gap: 6px; }
.jump a { text-decoration: none; color: var(--ink); font-size: 13px; padding: 4px 10px;
  border-radius: 999px; border: 1px solid var(--line); background: var(--surface); }
.jump a .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px;
  background: var(--turf); vertical-align: 1px; }
.jump a.todo .dot { background: var(--warn); }
.league { background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
  padding: 18px; display: grid; gap: 14px; min-width: 0; }
.league.todo { border-top: 4px solid var(--warn); }
.league.ok { border-top: 4px solid var(--turf); }
.lhead { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 10px; align-items: start; }
.lhead h2 { font: 800 24px/1.05 var(--display); margin: 0; text-transform: uppercase; letter-spacing: .01em; }
.lhead .team { color: var(--muted); font-size: 14px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip { font-size: 11px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
  padding: 3px 8px; border-radius: 999px; background: var(--bg); color: var(--muted); }
.chip.todo { background: var(--warn-soft); color: var(--warn); }
.chip.ok { background: var(--turf-soft); color: var(--turf); }
.score { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; font-variant-numeric: tabular-nums; }
.score .now { font: 600 18px var(--mono); color: var(--muted); }
.score .best { font: 800 30px/1 var(--display); }
.score .gain { font: 700 15px var(--mono); color: var(--turf); }
.bar { height: 6px; border-radius: 3px; background: var(--line); position: relative; overflow: hidden; }
.bar i { position: absolute; inset: 0 auto 0 0; background: var(--muted); border-radius: 3px; }
.bar i.add { background: var(--turf); }
.moves { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.move { display: grid; grid-template-columns: 1fr auto 1fr auto; gap: 10px; align-items: center;
  padding: 10px 12px; border-radius: 8px; background: var(--bg); }
.move .in, .move .out { display: grid; gap: 1px; min-width: 0; }
.move .tag { font-size: 10px; font-weight: 800; letter-spacing: .1em; }
.move .in .tag { color: var(--turf); }
.move .out .tag { color: var(--bad); }
.move .name { font-weight: 700; overflow-wrap: anywhere; }
.move .out .name { font-weight: 600; color: var(--muted); }
.move .arrow { color: var(--muted); font-size: 13px; }
.move .delta { font: 700 14px var(--mono); color: var(--turf); white-space: nowrap; }
.pos { display: inline-block; min-width: 34px; text-align: center; font: 700 11px var(--mono);
  padding: 1px 5px; border-radius: 4px; color: var(--surface); background: var(--def); margin-right: 6px; }
.pos.qb { background: var(--qb); } .pos.rb { background: var(--rb); } .pos.wr { background: var(--wr); }
.pos.te { background: var(--te); } .pos.k { background: var(--k); } .pos.def { background: var(--def); }
.proj { font: 500 13px var(--mono); color: var(--muted); font-variant-numeric: tabular-nums; }
.flag { font-size: 11px; font-weight: 700; padding: 1px 6px; border-radius: 4px; margin-left: 6px;
  white-space: nowrap; }
.flag.warn { background: var(--warn-soft); color: var(--warn); }
.flag.bad { background: var(--bad-soft); color: var(--bad); }
.alerts { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.alerts li { padding: 8px 12px; border-radius: 8px; font-size: 14px; background: var(--warn-soft); }
.alerts li.bad { background: var(--bad-soft); }
.good { margin: 0; color: var(--turf); font-weight: 600; }
details summary { cursor: pointer; color: var(--muted); font-size: 13px; font-weight: 600; }
.tablewrap { overflow-x: auto; margin-top: 8px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
td { padding: 6px 8px; border-top: 1px solid var(--line); }
td.slot { font: 700 12px var(--mono); color: var(--muted); width: 56px; }
td.num { text-align: right; font-family: var(--mono); font-variant-numeric: tabular-nums; }
tr.new td { background: var(--turf-soft); }
.problems { background: var(--bad-soft); border-radius: 10px; padding: 12px 16px; }
.problems h2 { font: 800 18px var(--display); text-transform: uppercase; margin: 0 0 4px; color: var(--bad); }
.problems ul { margin: 0; padding-left: 18px; }
footer { color: var(--muted); font-size: 12px; }
.lockbtn { font: inherit; font-size: 13px; padding: 6px 12px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--line); background: var(--surface); color: var(--muted); }
@media (max-width: 560px) {
  .move { grid-template-columns: 1fr auto; }
  .move .arrow { display: none; }
  .move .out { grid-column: 1; }
  .move .delta { grid-row: 1; grid-column: 2; }
}
@media (prefers-reduced-motion: no-preference) { .bar i { transition: width .4s ease; } }
</style>
"""


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _pos(player: Player) -> str:
    return f'<span class="pos {POSITION_CLASS.get(player.position, "def")}">{_e(player.position)}</span>'


def _flag(player: Player) -> str:
    if player.bye:
        return '<span class="flag bad">BYE</span>'
    status = (player.injury_status or "").upper()
    if player.is_out:
        return f'<span class="flag bad">{_e(player.status_label)}</span>'
    if status in RISKY_STATUSES:
        return f'<span class="flag warn">{_e(player.status_label)}</span>'
    return ""


def _player_cell(player: Player) -> str:
    team = f' <span class="proj">{_e(player.team)}</span>' if player.team else ""
    return f'{_pos(player)}<span class="name">{_e(player.name)}</span>{team}{_flag(player)}'


def _when(moment: dt.datetime) -> str:
    hour = moment.hour % 12 or 12
    return f"{moment:%a %b} {moment.day}, {hour}:{moment:%M %p} {moment:%Z}".strip()


def _slug(text: str, index: int) -> str:
    base = "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")
    return f"l{index}-{base}"[:60]


def _league(r: LeagueReport, anchor: str) -> str:
    t = r.team
    state = "todo" if r.needs_changes else "ok"
    chip = (f'<span class="chip todo">{len(r.start)} move{"s" if len(r.start) != 1 else ""}</span>'
            if r.needs_changes else '<span class="chip ok">Set</span>')
    best, now = r.best.total, t.current.total
    scale = max(best, now, 1)
    parts = [f'<section class="league {state}" id="{anchor}">',
             '<div class="lhead"><div>',
             f'<h2>{_e(t.league_name)}</h2><div class="team">{_e(t.team_name)}</div></div>',
             f'<div class="chips"><span class="chip">{_e(t.platform)}</span>{chip}</div></div>']

    if r.needs_changes:
        parts.append(
            f'<div class="score"><span class="now">{now:.1f}</span><span class="arrow">&rarr;</span>'
            f'<span class="best">{best:.1f}</span><span class="gain">+{r.gain:.1f} pts</span></div>'
            f'<div class="bar" role="img" aria-label="Projected {now:.1f} now, {best:.1f} with changes">'
            f'<i class="add" style="width:{best / scale * 100:.1f}%"></i>'
            f'<i style="width:{now / scale * 100:.1f}%"></i></div>')
        parts.append('<ul class="moves">')
        for player, benched in r.start:
            delta = player.effective_projection - (benched.effective_projection if benched else 0)
            out = (f'<span class="tag">SIT</span><span>{_player_cell(benched)}</span>'
                   f'<span class="proj">{benched.effective_projection:.1f} proj</span>'
                   if benched else '<span class="tag">FILLS</span><span class="name">Empty slot</span>')
            parts.append(
                '<li class="move">'
                f'<div class="in"><span class="tag">START</span><span>{_player_cell(player)}</span>'
                f'<span class="proj">{player.effective_projection:.1f} proj</span></div>'
                '<span class="arrow">over</span>'
                f'<div class="out">{out}</div>'
                f'<span class="delta">+{delta:.1f}</span></li>')
        parts.append('</ul>')
    else:
        parts.append(f'<div class="score"><span class="best">{now:.1f}</span>'
                     '<span class="now">projected</span></div>')
        parts.append('<p class="good">Your lineup is already the best one. No changes needed.</p>')

    if r.alerts:
        parts.append('<ul class="alerts">' + "".join(
            f'<li class="{level}">{_e(text)}</li>' for level, text in r.alerts) + '</ul>')

    new_ids = {p.id for p, _ in r.start}
    rows = []
    for slot, player in zip(r.best.slots, r.best.players):
        label = SLOT_LABEL.get(slot, slot)
        if player is None:
            rows.append(f'<tr><td class="slot">{_e(label)}</td><td>Empty</td><td class="num">-</td></tr>')
        else:
            cls = ' class="new"' if player.id in new_ids else ""
            rows.append(f'<tr{cls}><td class="slot">{_e(label)}</td><td>{_player_cell(player)}</td>'
                        f'<td class="num">{player.effective_projection:.1f}</td></tr>')
    parts.append('<details><summary>Best lineup</summary><div class="tablewrap"><table>'
                 + "".join(rows) + '</table></div></details>')
    parts.append('</section>')
    return "".join(parts)


LOCK_BUTTON = (
    '<button type="button" class="lockbtn" '
    "onclick=\"try{localStorage.removeItem('ffman-key')}catch(e){};location.reload()\">"
    "Log out</button>"
)


def render_dashboard(reports: list[LeagueReport], week: int | None, errors: list[str],
                     generated: dt.datetime | None = None, week_picker: bool = False,
                     logout: bool = False) -> str:
    """The page body: <title>, styles and content (no <html>/<body> wrapper)."""
    generated = generated or dt.datetime.now().astimezone()
    ordered = sorted(reports, key=lambda r: (not r.needs_changes, -r.gain))
    todo = [r for r in ordered if r.needs_changes]
    gain = sum(r.gain for r in todo)
    alerts = sum(len(r.warnings) for r in ordered)

    out = ["<title>ffman Lineups</title>", STYLE, '<main class="wrap">', "<header><div>",
           f'<h1>Lineups <span>Week {week}</span></h1>' if week else "<h1>Lineups</h1>",
           f'<div class="meta">Updated {_e(_when(generated))}</div></div>']
    if week_picker:
        options = "".join(f'<option value="{w}"{" selected" if w == week else ""}>Week {w}</option>'
                          for w in range(1, 19))
        out.append('<form class="weekform" method="get"><label for="week">Show</label>'
                   f'<select id="week" name="week">{options}</select>'
                   '<button type="submit">Refresh</button></form>')
    if logout:
        out.append(LOCK_BUTTON)
    out.append("</header>")

    out.append('<div class="strip">'
               f'<div class="stat"><small>Leagues</small><b>{len(ordered)}</b></div>'
               f'<div class="stat"><small>Need changes</small><b>{len(todo)}</b></div>'
               f'<div class="stat"><small>Points to gain</small><b>+{gain:.1f}</b></div>'
               f'<div class="stat"><small>Heads-ups</small><b>{alerts}</b></div></div>')
    out.append('<p class="note">Suggestions only. Nothing has been changed in any of your leagues.</p>')

    anchors = [_slug(r.team.league_name, i) for i, r in enumerate(ordered)]
    if len(ordered) > 1:
        out.append('<nav class="jump" aria-label="Leagues">' + "".join(
            f'<a href="#{a}" class="{"todo" if r.needs_changes else ""}"><span class="dot"></span>'
            f'{_e(r.team.league_name)}</a>' for r, a in zip(ordered, anchors)) + "</nav>")

    if errors:
        out.append('<div class="problems"><h2>Couldn\'t load</h2><ul>'
                   + "".join(f"<li>{_e(e)}</li>" for e in errors) + "</ul></div>")
    out.extend(_league(r, a) for r, a in zip(ordered, anchors))
    if not ordered and not errors:
        out.append('<p class="note">No leagues found. Check your config.</p>')
    out.append('<footer>Projections: Sleeper (scored with each league\'s settings) and ESPN. '
               'Check injury news before kickoff.</footer></main>')
    return "\n".join(out)


def full_page(body: str) -> str:
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            f"</head><body>{body}</body></html>")


def serve(build, host: str = "127.0.0.1", port: int = 8000, cache_seconds: int = 300) -> None:
    """Run the local website. `build(week)` returns (reports, week, errors)."""
    cache: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server naming)
            url = urllib.parse.urlparse(self.path)
            if url.path != "/":
                self.send_error(404)
                return
            query = urllib.parse.parse_qs(url.query)
            week = int(query["week"][0]) if query.get("week", [""])[0].isdigit() else None
            hit = cache.get(week)
            if not hit or time.time() - hit[0] > cache_seconds:
                reports, shown, errors = build(week)
                page = full_page(render_dashboard(reports, shown, errors, week_picker=True))
                hit = cache[week] = (time.time(), page.encode())
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(hit[1])))
            self.end_headers()
            self.wfile.write(hit[1])

        def log_message(self, fmt, *args):
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"ffman is running at http://{host}:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
