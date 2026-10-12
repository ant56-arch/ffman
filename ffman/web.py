"""The ffman website.

Three tabs: "This week" (a to-do list, soonest deadline first), "Recap" (how
last week went vs. ffman's lineup) and "Leagues" (full lineups, folded away).
`render_dashboard` builds the page body; `serve` runs a small local site.
"""

from __future__ import annotations

import datetime as dt
import html
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .models import Player, fmt_time
from .recap import SeasonRecap, WeekRecap
from .report import LeagueReport, deadline_label, game_plan

SLOT_LABEL = {"SUPER_FLEX": "SFLX", "REC_FLEX": "W/T", "WRRB_FLEX": "W/R", "IDP_FLEX": "IDP"}

STYLE = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@600;700&family=Source+Sans+3:wght@400;600;700&display=swap">
<style>
/* Layout: one calm column. A to-do list first, details folded away.
   One accent (turf green); amber/red only for things that need attention. */
:root {
  --bg: #f5f6f3; --surface: #ffffff; --ink: #151b17; --muted: #68726b; --line: #e2e6df;
  --turf: #1d6a3b; --turf-soft: #e6f1e9; --warn: #8f5a00; --warn-soft: #fbf1dc;
  --bad: #b3261e; --bad-soft: #fbe6e4;
  --display: "Saira Condensed", "Arial Narrow", sans-serif;
  --body: "Source Sans 3", "Segoe UI", system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #101411; --surface: #171d19; --ink: #e8ece9; --muted: #96a29a; --line: #27302a;
  --turf: #62c287; --turf-soft: #1b2e21; --warn: #e6b555; --warn-soft: #33291a;
  --bad: #f08a82; --bad-soft: #3a1f1d; color-scheme: dark;
} }
:root[data-theme="dark"] {
  --bg: #101411; --surface: #171d19; --ink: #e8ece9; --muted: #96a29a; --line: #27302a;
  --turf: #62c287; --turf-soft: #1b2e21; --warn: #e6b555; --warn-soft: #33291a;
  --bad: #f08a82; --bad-soft: #3a1f1d; color-scheme: dark;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { background: var(--bg); color: var(--ink); font: 400 16px/1.5 var(--body); margin: 0;
  font-variant-numeric: tabular-nums; }
.wrap { max-width: 760px; margin: 0 auto; padding-inline: 16px; padding-block: 28px 56px;
  display: grid; gap: 20px; }
a { color: var(--turf); }
:focus-visible { outline: 2px solid var(--turf); outline-offset: 2px; }

header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
h1 { font: 700 clamp(34px, 7vw, 48px)/1 var(--display); margin: 0; letter-spacing: .01em; }
.sub { color: var(--muted); font-size: 14px; margin-top: 6px; }
.sub details { display: inline; }
.sub summary { display: inline; cursor: pointer; color: var(--turf); text-decoration: underline;
  text-underline-offset: 2px; list-style: none; }
.sub summary::-webkit-details-marker { display: none; }
.schedule { margin-top: 8px; padding: 10px 14px; background: var(--surface); border: 1px solid var(--line);
  border-radius: 10px; color: var(--ink); font-size: 14px; }
.schedule ul { margin: 4px 0 6px; padding-left: 18px; }
.schedule p { margin: 0; color: var(--muted); }
.ghost { font: inherit; font-size: 14px; background: none; border: 0; color: var(--muted); cursor: pointer;
  padding: 6px 0; text-decoration: underline; text-underline-offset: 2px; }
.weekform { display: flex; gap: 8px; align-items: center; font-size: 14px; }
.weekform select, .weekform button { font: inherit; font-size: 14px; padding: 5px 9px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--surface); color: var(--ink); }

.tabs { display: flex; gap: 4px; background: var(--surface); border: 1px solid var(--line);
  border-radius: 12px; padding: 4px; position: sticky; top: env(safe-area-inset-top, 0px); z-index: 2; }
.tabs button { flex: 1; font: 600 15px var(--body); padding: 9px 8px; border: 0; border-radius: 9px;
  background: none; color: var(--muted); cursor: pointer; white-space: nowrap; }
.tabs button[aria-selected="true"] { background: var(--turf); color: var(--surface); }
.tabs .count { font-weight: 400; opacity: .8; }

.lede { font-size: 18px; margin: 0; text-wrap: pretty; }
.lede b { color: var(--turf); }
.group { display: grid; gap: 8px; }
.group h2 { font: 700 15px var(--display); text-transform: uppercase; letter-spacing: .08em;
  color: var(--muted); margin: 8px 0 0; }
.group h2.urgent { color: var(--warn); }
.list { list-style: none; margin: 0; padding: 0; background: var(--surface); border: 1px solid var(--line);
  border-radius: 12px; }
.row { display: grid; grid-template-columns: 1fr auto; gap: 2px 14px; padding: 12px 16px; align-items: center; }
.row + .row { border-top: 1px solid var(--line); }
.row .league { font-size: 12px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
  color: var(--muted); }
.row .main { min-width: 0; overflow-wrap: anywhere; }
.row .main b { font-weight: 700; }
.row .meta { color: var(--muted); font-size: 14px; }
.row .pts { font-weight: 700; color: var(--turf); white-space: nowrap; text-align: right; }
.row .pts small { display: block; font-weight: 400; color: var(--muted); font-size: 12px; }
.row.attn { box-shadow: inset 3px 0 0 var(--bad); }
.row.watch { box-shadow: inset 3px 0 0 var(--warn); }
.empty { color: var(--muted); margin: 0; }
.done { color: var(--muted); font-size: 14px; margin: 0; }
.done b { color: var(--ink); font-weight: 600; }

.season { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px;
  background: var(--line); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
.season div { background: var(--surface); padding: 12px 16px; }
.season b { display: block; font: 700 28px/1.1 var(--display); }
.season small { color: var(--muted); font-size: 13px; }
.up { color: var(--turf); } .down { color: var(--bad); }
.bars { display: grid; gap: 4px; margin-top: 6px; font-size: 13px; color: var(--muted); }
.bar { display: grid; grid-template-columns: 74px 1fr 52px; gap: 8px; align-items: center; }
.bar i { display: block; height: 6px; border-radius: 3px; background: var(--line); position: relative; }
.bar i span { position: absolute; inset: 0 auto 0 0; border-radius: 3px; background: var(--muted); }
.bar.ff i span { background: var(--turf); }
.bar em { font-style: normal; text-align: right; color: var(--ink); }
.result { font-weight: 700; font-size: 13px; padding: 1px 7px; border-radius: 999px; white-space: nowrap; }
.result.W { background: var(--turf-soft); color: var(--turf); }
.result.L { background: var(--bad-soft); color: var(--bad); }
.result.T { background: var(--bg); color: var(--muted); }
details.more > summary { cursor: pointer; color: var(--turf); font-size: 14px; margin-top: 4px; }
details.more ul { margin: 6px 0 0; padding-left: 18px; font-size: 14px; }
.weektable { overflow-x: auto; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; }
.weektable table { border-collapse: collapse; width: 100%; font-size: 14px; }
.weektable th, .weektable td { padding: 8px 12px; text-align: right; border-top: 1px solid var(--line); white-space: nowrap; }
.weektable th:first-child, .weektable td:first-child { text-align: left; }
.weektable thead th { border-top: 0; color: var(--muted); font-weight: 600; }

details.lg { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; }
details.lg > summary { cursor: pointer; padding: 14px 16px; display: grid; grid-template-columns: 1fr auto;
  gap: 2px 12px; list-style: none; }
details.lg > summary::-webkit-details-marker { display: none; }
details.lg > summary .name { font: 700 20px/1.15 var(--display); }
details.lg > summary .meta { color: var(--muted); font-size: 14px; }
details.lg > summary .state { font-weight: 700; font-size: 14px; color: var(--turf); align-self: center; }
details.lg > summary .state.todo { color: var(--warn); }
details.lg[open] > summary { border-bottom: 1px solid var(--line); }
.lineup { width: 100%; border-collapse: collapse; font-size: 15px; }
.lineup td { padding: 8px 16px; border-top: 1px solid var(--line); vertical-align: top; }
.lineup tr:first-child td { border-top: 0; }
.lineup td.slot { color: var(--muted); font-size: 13px; font-weight: 700; width: 64px; }
.lineup td.num { text-align: right; white-space: nowrap; }
.lineup tr.new td { background: var(--turf-soft); }
.lineup .meta { display: block; color: var(--muted); font-size: 13px; }
.tag { font-size: 12px; font-weight: 700; padding: 0 6px; border-radius: 4px; margin-left: 6px; }
.tag.bad { background: var(--bad-soft); color: var(--bad); }
.tag.warn { background: var(--warn-soft); color: var(--warn); }
.tag.lock { background: var(--bg); color: var(--muted); }
.lgnote { padding: 10px 16px; color: var(--muted); font-size: 14px; border-top: 1px solid var(--line); }

.notice { background: var(--warn-soft); border-radius: 10px; padding: 10px 14px; font-size: 14px; }
.notice.bad { background: var(--bad-soft); }
.notice ul { margin: 4px 0 0; padding-left: 18px; }
footer { color: var(--muted); font-size: 13px; }
@media (max-width: 520px) {
  .row { padding: 12px 14px; }
  .tabs button { font-size: 14px; padding: 9px 4px; }
  .season div { padding: 10px 12px; }
  .season b { font-size: 22px; }
  .bar { grid-template-columns: 60px 1fr 46px; }
}
</style>
"""

TAB_SCRIPT = """
<script>
(function () {
  var tabs = document.querySelectorAll('.tabs button');
  function show(id) {
    tabs.forEach(function (t) {
      var on = t.dataset.tab === id;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      document.getElementById(t.dataset.tab).hidden = !on;
    });
  }
  tabs.forEach(function (t) {
    t.addEventListener('click', function () {
      show(t.dataset.tab);
      try { history.replaceState(null, '', '#' + t.dataset.tab); } catch (e) {}
    });
  });
  var start = (location.hash || '').slice(1);
  show(document.getElementById(start) && start !== '' ? start : 'week');
})();
</script>
"""

LOCK_BUTTON = (
    '<button type="button" class="ghost" '
    "onclick=\"try{localStorage.removeItem('ffman-key')}catch(e){};location.reload()\">"
    "Log out</button>"
)


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _when(moment: dt.datetime) -> str:
    hour = moment.hour % 12 or 12
    return f"{moment:%a %b} {moment.day}, {hour}:{moment:%M %p} {moment:%Z}".strip()


def _status_tag(p: Player) -> str:
    if p.bye:
        return '<span class="tag bad">BYE</span>'
    if p.is_out:
        return f'<span class="tag bad">{_e(p.status_label)}</span>'
    if p.status_label:
        return f'<span class="tag warn">{_e(p.status_label)}</span>'
    return ""


def _why_out(p: Player | None, start: Player) -> str:
    """Short reason a benched player is being replaced, if there's an obvious one."""
    if p is None:
        return "fills an empty slot"
    if p.bye:
        return f"{p.name} is on bye"
    if p.is_out:
        return f"{p.name} is {p.status_label}"
    if p.status_label:
        return f"{p.name} is {p.status_label}"
    return f"{start.effective_projection:.1f} vs {p.effective_projection:.1f} projected"


def _game(p: Player) -> str:
    if p.bye or not p.kickoff:
        return ""
    return f"{p.matchup}, {'under way' if p.locked else fmt_time(p.kickoff)}"


# --------------------------------------------------------------------------- This week

def _this_week(reports: list[LeagueReport]) -> str:
    plan = game_plan(reports)
    gain = sum(r.gain for r in reports if r.needs_changes)
    leagues = len({id(r) for r, _ in plan.moves})
    out = []
    if plan.moves:
        out.append(f'<p class="lede">{len(plan.moves)} lineup move{"s" if len(plan.moves) != 1 else ""} '
                   f'in {leagues} league{"s" if leagues != 1 else ""}, worth about <b>+{gain:.1f} pts</b>.</p>')
    else:
        out.append('<p class="lede">Every lineup is set. <b>Nothing to change</b> right now.</p>')

    current = None
    for r, m in plan.moves:
        label = deadline_label(m.deadline)
        if label != current:
            if current is not None:
                out.append("</ul></section>")
            out.append(f'<section class="group"><h2 class="urgent">{_e(label)}</h2><ul class="list">')
            current = label
        p, b = m.player, m.benched
        meta = [f"{p.position}", _game(p), _why_out(b, p)]
        if m.close_call:
            meta.append("close call")
        out.append(
            f'<li class="row"><div class="main"><div class="league">{_e(r.team.league_name)}</div>'
            f'Start <b>{_e(p.name)}</b>{" for " + _e(b.name) if b else ""}'
            f'<div class="meta">{_e(" · ".join(x for x in meta if x))}</div></div>'
            f'<div class="pts">+{m.gain:.1f}</div></li>')
    if current is not None:
        out.append("</ul></section>")

    rows = []
    for r, a in plan.pickups:
        if not any(w for rr, w in plan.waivers if rr is r):  # a waiver idea below already covers it
            rows.append(f'<li class="row attn"><div class="main"><div class="league">{_e(r.team.league_name)}'
                        f'</div>{_e(a.text)}</div><div></div></li>')
    for r, w in plan.waivers:
        add = w.add
        bits = [add.position + (f", {add.team}" if add.team else ""),
                f"{add.effective_projection:.1f} this week, {add.next_projection:.1f} next"]
        if w.tough:
            bits.append(f"tough call: {w.drop.name} is a hot pickup")
        if w.after:
            bits.append(f"after adding {', '.join(x.name for x in w.after)}")
        if r.team.waiver_note:
            bits.append(r.team.waiver_note)
        label = "this week" if w.week_gain >= 2 else "2 weeks"
        value = w.week_gain if w.week_gain >= 2 else w.two_week_gain
        rows.append(
            f'<li class="row{" watch" if w.tough else ""}"><div class="main">'
            f'<div class="league">{_e(r.team.league_name)}</div>'
            f'Add <b>{_e(add.name)}</b>{", drop " + _e(w.drop.name) if w.drop else ""}'
            f'<div class="meta">{_e(" · ".join(bits))}</div></div>'
            f'<div class="pts">+{value:.1f}<small>{label}</small></div></li>')
    if rows:
        out.append('<section class="group"><h2>Waiver ideas</h2><ul class="list">' + "".join(rows) + "</ul></section>")

    if plan.watch:
        out.append('<section class="group"><h2>Keep an eye on</h2><ul class="list">' + "".join(
            f'<li class="row watch"><div class="main"><div class="league">{_e(r.team.league_name)}</div>'
            f'{_e(a.text)}</div><div></div></li>' for r, a in plan.watch) + "</ul></section>")

    if plan.all_set and plan.moves:
        out.append('<p class="done"><b>Already set:</b> '
                   + _e(", ".join(r.team.league_name for r in plan.all_set)) + "</p>")
    return "".join(out)


# --------------------------------------------------------------------------- Recap

def _bars(w: WeekRecap) -> str:
    scale = max(w.perfect, w.actual, w.ffman, 1)
    rows = [("You", w.actual, ""), ("ffman", w.ffman, " ff"), ("Best", w.perfect, "")]
    return '<div class="bars">' + "".join(
        f'<div class="bar{cls}"><span>{label}</span><i><span style="width:{v / scale * 100:.1f}%"></span></i>'
        f'<em>{v:.1f}</em></div>' for label, v, cls in rows) + "</div>"


def _recap_row(w: WeekRecap) -> str:
    if w.result:
        res = f'<span class="result {w.result}">{w.result} {w.actual:.1f}–{w.opponent:.1f}</span>'
        if w.flipped:
            res += f' &rarr; <span class="result {w.ffman_result}">{w.ffman_result} with ffman</span>'
    else:
        res = ""
    if not w.swaps:
        verdict = "You started ffman's lineup."
    elif abs(w.gain) < 0.05:
        verdict = "ffman's changes would have broken even."
    elif w.gain > 0:
        verdict = f'ffman\'s lineup would have scored <span class="up">+{w.gain:.1f}</span> more.'
    else:
        verdict = f'Your lineup beat ffman\'s by <span class="up">{-w.gain:.1f}</span>.'
    swaps = ""
    if w.swaps:
        items = "".join(
            f"<li>{_e(s.start.name)} ({s.start.actual or 0:.1f}) over "
            f"{_e(s.sit.name) if s.sit else 'an empty slot'} ({(s.sit.actual or 0) if s.sit else 0:.1f}): "
            f'<span class="{"up" if s.delta >= 0 else "down"}">{s.delta:+.1f}</span></li>' for s in w.swaps)
        swaps = f'<details class="more"><summary>What ffman would have changed</summary><ul>{items}</ul></details>'
    return (f'<li class="row"><div class="main"><div class="league">{_e(w.league_name)}</div>'
            f'{verdict} {res}{_bars(w)}{swaps}</div><div></div></li>')


def _recap(recap: SeasonRecap | None) -> str:
    if not recap or not recap.weeks:
        return '<p class="empty">The recap appears once a week of games is finished.</p>'
    latest = recap.latest()
    week = latest[0].week
    gain = recap.gain
    weeks = len({w.week for w in recap.weeks})
    out = [f'<p class="lede">Week {week}: your lineups vs. ffman\'s lineup vs. the best possible one.</p>',
           '<div class="season">'
           f'<div><small>ffman over {weeks} week{"s" if weeks != 1 else ""}</small>'
           f'<b class="{"up" if gain >= 0 else "down"}">{gain:+.1f} pts</b></div>'
           f'<div><small>Losses → wins</small><b>{recap.flips_to_wins}</b></div>'
           f'<div><small>Wins → losses</small><b>{recap.flips_to_losses}</b></div></div>',
           f'<section class="group"><h2>Week {week}</h2><ul class="list">'
           + "".join(_recap_row(w) for w in sorted(latest, key=lambda w: -abs(w.gain))) + "</ul></section>"]

    by_league = recap.by_league()
    week_nums = sorted({w.week for w in recap.weeks})
    head = "".join(f"<th>Wk {n}</th>" for n in week_nums)
    body = []
    for league, items in by_league.items():
        cells = {w.week: w for w in items}
        tds = "".join(
            (f'<td class="{"up" if cells[n].gain > 0 else "down" if cells[n].gain < 0 else ""}">'
             f'{cells[n].gain:+.1f}{" *" if cells[n].flipped else ""}</td>') if n in cells else "<td>–</td>"
            for n in week_nums)
        total = sum(w.gain for w in items)
        body.append(f"<tr><td>{_e(league)}</td>{tds}<td><b>{total:+.1f}</b></td></tr>")
    out.append('<section class="group"><h2>Season, week by week</h2><div class="weektable"><table>'
               f'<thead><tr><th>Points ffman would have added</th>{head}<th>Total</th></tr></thead>'
               f'<tbody>{"".join(body)}</tbody></table></div>'
               '<p class="done">* ffman\'s lineup would have changed the result. Based on each week\'s '
               'final pre-game projections, which may differ slightly from what the page showed at the time.</p>'
               '</section>')
    return "".join(out)


# --------------------------------------------------------------------------- Leagues

def _league(r: LeagueReport) -> str:
    t = r.team
    state = (f'<span class="state todo">{len(r.start)} move{"s" if len(r.start) != 1 else ""}</span>'
             if r.needs_changes else '<span class="state">Set</span>')
    proj = (f"{t.current.total:.1f} → {r.best.total:.1f} projected" if r.needs_changes
            else f"{t.current.total:.1f} projected")
    new_ids = {m.player.id for m in r.start}
    rows = []
    for slot, p in zip(r.best.slots, r.best.players):
        label = SLOT_LABEL.get(slot, slot)
        if p is None:
            rows.append(f'<tr><td class="slot">{_e(label)}</td><td>Empty</td><td class="num">–</td></tr>')
            continue
        lock = '<span class="tag lock">LOCKED</span>' if p.locked else ""
        game = _game(p)
        cls = ' class="new"' if p.id in new_ids else ""
        rows.append(
            f'<tr{cls}><td class="slot">{_e(label)}</td>'
            f'<td>{_e(p.name)}{_status_tag(p)}{lock}'
            f'<span class="meta">{_e(p.position)}{", " + _e(p.team) if p.team else ""}'
            f'{" · " + _e(game) if game else ""}</span></td>'
            f'<td class="num">{p.effective_projection:.1f}</td></tr>')
    note = f'<div class="lgnote">{_e(t.waiver_note)}</div>' if t.waiver_note else ""
    return (f'<details class="lg"><summary><span class="name">{_e(t.league_name)}</span>{state}'
            f'<span class="meta">{_e(t.platform)} · {_e(t.team_name)} · {_e(proj)}</span></summary>'
            f'<table class="lineup">{"".join(rows)}</table>{note}</details>')


# --------------------------------------------------------------------------- Page

def _schedule(next_updates: list[dt.datetime], run_url: str | None) -> str:
    if not next_updates:
        return ""
    times = "".join(f"<li>{_e(fmt_time(t))}</li>" for t in next_updates)
    now = (f' <a href="{_e(run_url)}" target="_blank" rel="noopener">Update now</a> '
           '(GitHub &rarr; Run workflow).' if run_url else "")
    return (f' · next about {_e(fmt_time(next_updates[0]))} '
            '<details><summary>schedule</summary><div class="schedule"><ul>' + times + '</ul>'
            '<p>Every morning around 9 AM, Tuesday night before waivers, every 30 minutes on Sundays '
            '(about 9 AM to 8 PM) and before Thursday and Monday night games. GitHub sometimes starts '
            f'a few minutes late.{now}</p></div></details>')


def _stale(next_updates: list[dt.datetime], run_url: str | None) -> str:
    if not next_updates:
        return ""
    due = int(next_updates[0].timestamp() * 1000)
    link = f' or <a href="{_e(run_url)}" target="_blank" rel="noopener">update it now</a>' if run_url else ""
    return (f'<div class="notice" id="stale" hidden>This page was due to update at '
            f'{_e(fmt_time(next_updates[0]))} and hasn\'t yet, so it may be out of date. '
            f'Check back in a few minutes{link}.</div>'
            f'<script>(function(){{if(Date.now()>{due}+45*60*1000){{'
            'var el=document.getElementById("stale");if(el)el.hidden=false;}})();</script>')


def render_dashboard(reports: list[LeagueReport], week: int | None, errors: list[str],
                     generated: dt.datetime | None = None, week_picker: bool = False,
                     logout: bool = False, next_updates: list[dt.datetime] | None = None,
                     run_url: str | None = None, recap: SeasonRecap | None = None) -> str:
    """The page body: <title>, styles and content (no <html>/<body> wrapper)."""
    generated = generated or dt.datetime.now().astimezone()
    next_updates = next_updates or []
    ordered = sorted(reports, key=lambda r: (not r.needs_changes, -r.gain))
    moves = sum(len(r.start) for r in ordered if r.needs_changes)
    ideas = sum(len(r.waivers) for r in ordered)

    out = ["<title>ffman Lineups</title>", STYLE, '<main class="wrap">', "<header><div>",
           f"<h1>Week {week}</h1>" if week else "<h1>Lineups</h1>",
           f'<div class="sub">Updated {_e(_when(generated))}{_schedule(next_updates, run_url)}</div></div>']
    right = []
    if week_picker:
        options = "".join(f'<option value="{w}"{" selected" if w == week else ""}>Week {w}</option>'
                          for w in range(1, 19))
        right.append('<form class="weekform" method="get"><label for="week" hidden>Week</label>'
                     f'<select id="week" name="week">{options}</select><button type="submit">Go</button></form>')
    if logout:
        right.append(LOCK_BUTTON)
    out.append(f"<div>{''.join(right)}</div></header>")
    out.append(_stale(next_updates, run_url))
    if errors:
        out.append('<div class="notice bad">Some data couldn\'t be loaded:<ul>'
                   + "".join(f"<li>{_e(e)}</li>" for e in errors) + "</ul></div>")

    out.append('<nav class="tabs" role="tablist">'
               f'<button type="button" role="tab" data-tab="week" aria-selected="true">This week'
               f'{f" <span class=count>{moves + ideas}</span>" if moves + ideas else ""}</button>'
               '<button type="button" role="tab" data-tab="recap" aria-selected="false">Recap</button>'
               '<button type="button" role="tab" data-tab="leagues" aria-selected="false">Leagues'
               f' <span class="count">{len(ordered)}</span></button></nav>')
    out.append(f'<section id="week" class="group" role="tabpanel">{_this_week(ordered)}</section>')
    out.append(f'<section id="recap" class="group" role="tabpanel">{_recap(recap)}</section>')
    out.append('<section id="leagues" class="group" role="tabpanel">'
               + ("".join(_league(r) for r in ordered) or '<p class="empty">No leagues found. Check your config.</p>')
               + "</section>")
    out.append('<footer>Suggestions only: nothing is ever changed in your leagues. Projections from '
               'Sleeper (scored with each league\'s settings) and ESPN; game times from ESPN, shown in '
               f'{_e(generated.strftime("%Z") or "local time")}. Check injury news before kickoff.</footer>')
    out.append("</main>" + TAB_SCRIPT)
    return "\n".join(out)


def full_page(body: str) -> str:
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            f"</head><body>{body}</body></html>")


def serve(build, host: str = "127.0.0.1", port: int = 8000, cache_seconds: int = 300) -> None:
    """Run the local website. `build(week)` returns (reports, week, errors, recap)."""
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
                reports, shown, errors, recap = build(week)
                page = full_page(render_dashboard(reports, shown, errors, week_picker=True, recap=recap))
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
