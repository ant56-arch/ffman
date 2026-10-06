"""The ffman website: an HTML dashboard of every league's recommendations.

`render_dashboard` builds the page body (also used for static snapshots);
`serve` runs a small local site that refreshes data on each load.

Design: a printed lineup card. Warm paper, ink-black type, one fountain-pen blue for
anything you act on, and green/amber/red kept strictly for gains, watch items and problems.
Headlines are set in Fraunces; everything you read is Atkinson Hyperlegible, a typeface
drawn for legibility. Position colors were checked for color-blind separation and always
sit next to the position's name, so color is never the only cue.
"""

from __future__ import annotations

import datetime as dt
import html
import math
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .models import RISKY_STATUSES, Player, fmt_time
from .report import LeagueReport, Move, deadline_label, game_plan

POSITION_CLASS = {"QB": "qb", "RB": "rb", "WR": "wr", "TE": "te", "K": "k", "DEF": "def"}
WAIVERS_SHOWN = 4  # the rest fold into "N more waiver ideas"
SLOT_LABEL = {"SUPER_FLEX": "SFLX", "REC_FLEX": "W/T", "WRRB_FLEX": "W/R", "IDP_FLEX": "IDP"}

FONTS = ("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,800"
         "&family=Atkinson+Hyperlegible+Next:wght@400;600;700"
         "&family=Atkinson+Hyperlegible+Mono:wght@500;700&display=swap")

STYLE = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="%FONTS%">
<style>
:root {
  --paper: #f4f0e6; --card: #fffdf8; --ink: #1d1c19; --ink2: #3f3b34; --muted: #6b6559;
  --rule: #ddd5c4; --heavy: #1d1c19;
  --accent: #2b3f9e; --accent-soft: #e4e8f7;
  --good: #1e7a45; --good-soft: #e1f0e4; --warn: #8f5500; --warn-soft: #f8ebcf;
  --bad: #b3261e; --bad-soft: #f8e0dc;
  --qb: #c8432b; --rb: #14895a; --wr: #7a4fc9; --te: #b97a00; --k: #2f68c9; --def: #5e7a21;
  --display: "Fraunces", Georgia, "Times New Roman", serif;
  --body: "Atkinson Hyperlegible Next", "Atkinson Hyperlegible", "Segoe UI", system-ui, sans-serif;
  --mono: "Atkinson Hyperlegible Mono", ui-monospace, "SF Mono", Menlo, monospace;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --paper: #12141a; --card: #1b1e27; --ink: #ece7dc; --ink2: #cfc9bc; --muted: #a39d90;
  --rule: #2f3340; --heavy: #ece7dc;
  --accent: #9daeff; --accent-soft: #252c4a;
  --good: #6acb8e; --good-soft: #1b3126; --warn: #e8b65a; --warn-soft: #382c14;
  --bad: #f28b82; --bad-soft: #3d2120;
  --qb: #e2604b; --rb: #2fa672; --wr: #9479e6; --te: #ba8418; --k: #5b88e0; --def: #7a9634;
  color-scheme: dark;
} }
:root[data-theme="dark"] {
  --paper: #12141a; --card: #1b1e27; --ink: #ece7dc; --ink2: #cfc9bc; --muted: #a39d90;
  --rule: #2f3340; --heavy: #ece7dc;
  --accent: #9daeff; --accent-soft: #252c4a;
  --good: #6acb8e; --good-soft: #1b3126; --warn: #e8b65a; --warn-soft: #382c14;
  --bad: #f28b82; --bad-soft: #3d2120;
  --qb: #e2604b; --rb: #2fa672; --wr: #9479e6; --te: #ba8418; --k: #5b88e0; --def: #7a9634;
  color-scheme: dark;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; scroll-padding-top: 64px; }
body { margin: 0; background: var(--paper); color: var(--ink);
  font: 400 17px/1.55 var(--body); font-variant-numeric: tabular-nums; }
a { color: var(--accent); text-underline-offset: 3px; }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
.wrap { max-width: 920px; margin: 0 auto; padding: 0 16px 64px; }
.num { font-family: var(--mono); font-weight: 500; }

/* Masthead */
.mast { padding: 28px 0 14px; border-bottom: 3px double var(--heavy); display: grid; gap: 6px; }
.mast .top { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.kicker { font: 700 13px/1 var(--body); letter-spacing: .16em; text-transform: uppercase; color: var(--muted); }
.mast h1 { font: 800 clamp(44px, 11vw, 76px)/.95 var(--display); letter-spacing: -.02em; margin: 2px 0 0; }
.mast h1 em { font-style: normal; color: var(--accent); }
.dateline { color: var(--ink2); font-size: 15px; }
.tools { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.btn { font: 600 14px var(--body); padding: 7px 12px; border-radius: 999px; cursor: pointer;
  border: 1.5px solid var(--rule); background: var(--card); color: var(--ink2); }
.btn:hover { border-color: var(--ink2); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--card); }
select.btn { padding-right: 8px; }

/* League jump bar */
.jump { position: sticky; top: 0; z-index: 5; background: var(--paper); border-bottom: 1px solid var(--rule);
  display: flex; gap: 6px; overflow-x: auto; padding: 10px 0; scrollbar-width: none; }
.jump::-webkit-scrollbar { display: none; }
.jump a { flex: none; text-decoration: none; color: var(--ink); font-weight: 600; font-size: 14px;
  padding: 6px 12px; border-radius: 999px; background: var(--card); border: 1.5px solid var(--rule);
  display: inline-flex; gap: 7px; align-items: center; }
.jump a:hover { border-color: var(--ink2); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--good); flex: none; }
.dot.todo { background: var(--accent); }
.dot.bad { background: var(--bad); }

/* The one-sentence summary */
.lede { font: 600 clamp(21px, 4.4vw, 27px)/1.35 var(--display); margin: 26px 0 6px; max-width: 34ch; }
.lede b { color: var(--accent); }
.lede .plus { color: var(--good); }
.sub { color: var(--muted); font-size: 15px; margin: 0 0 8px; }

/* Section heads */
h2.sec { font: 800 15px/1 var(--body); letter-spacing: .14em; text-transform: uppercase; color: var(--ink2);
  margin: 38px 0 12px; display: flex; align-items: center; gap: 12px; }
h2.sec::after { content: ""; flex: 1; border-top: 1.5px solid var(--heavy); }
h3.when { font: 700 14px/1 var(--mono); color: var(--accent); margin: 18px 0 8px; letter-spacing: .02em; }

/* To-do list */
.tasks { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.item { display: grid; grid-template-columns: 28px 1fr auto; gap: 4px 12px; align-items: start;
  background: var(--card); border: 1.5px solid var(--rule); border-radius: 12px; padding: 14px 16px; }
.item input { width: 22px; height: 22px; margin: 3px 0 0; accent-color: var(--accent); cursor: pointer; }
.item .what { min-width: 0; overflow-wrap: anywhere; font-size: 18px; line-height: 1.4; }
.item .lg { display: block; font-size: 13px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 2px; text-decoration: none; }
.item .lg:hover { color: var(--accent); }
.item .why { display: block; color: var(--ink2); font-size: 15px; margin-top: 3px; }
.item .gain { font: 700 22px/1.2 var(--mono); color: var(--good); white-space: nowrap; text-align: right; }
.item .gain small { display: block; font: 600 12px var(--body); color: var(--muted); letter-spacing: .04em; }
.item.done { opacity: .5; }
.item.done .what b { text-decoration: line-through; }
.item.bad { border-color: color-mix(in srgb, var(--bad) 45%, var(--rule)); background: var(--bad-soft); }
.item.warn { background: var(--warn-soft); border-color: color-mix(in srgb, var(--warn) 35%, var(--rule)); }
.item .icon { width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; margin-top: 1px;
  font: 800 14px var(--body); color: var(--card); background: var(--bad); }
.item.warn .icon { background: var(--warn); }
.item.add .icon { background: var(--good); }
.item.tough { background: var(--warn-soft); }
.allset { color: var(--ink2); margin: 14px 0 0; }
.allset b { color: var(--good); }
.tag { display: inline-block; font: 700 12px/1.6 var(--body); letter-spacing: .04em; padding: 0 7px;
  border-radius: 5px; vertical-align: 2px; margin-left: 4px; white-space: nowrap; }
.tag.out, .tag.bye { background: var(--bad-soft); color: var(--bad); }
.tag.q { background: var(--warn-soft); color: var(--warn); }
.tag.close { border: 1.5px dashed var(--rule); color: var(--muted); }
.tag.lock { border: 1.5px solid var(--rule); color: var(--muted); }

/* League cards */
.league { background: var(--card); border: 1.5px solid var(--rule); border-radius: 16px; padding: 22px 20px 18px;
  margin-top: 18px; display: grid; gap: 16px; min-width: 0; }
.lhead { display: flex; justify-content: space-between; gap: 8px 16px; flex-wrap: wrap; align-items: end;
  border-bottom: 1.5px solid var(--heavy); padding-bottom: 12px; }
.lhead h3 { font: 800 clamp(24px, 5vw, 32px)/1.05 var(--display); margin: 0; letter-spacing: -.01em; }
.lhead .team { color: var(--muted); font-size: 15px; margin-top: 4px; }
.lhead .team b { color: var(--ink2); font-weight: 600; }
.total { text-align: right; }
.total .big { font: 700 34px/1 var(--mono); }
.total .cap { display: block; font-size: 14px; color: var(--muted); margin-top: 4px; }
.total .cap b { color: var(--good); }
.verdict { font-size: 17px; margin: 0; }
.verdict.ok { color: var(--good); font-weight: 600; }

/* Lineup card rows */
.card-key { display: grid; grid-template-columns: 54px 1fr 150px 64px; gap: 12px; font-size: 12px; font-weight: 700;
  letter-spacing: .1em; text-transform: uppercase; color: var(--muted); padding: 0 8px; }
.card-key span:last-child, .card-key span:nth-child(3) { text-align: right; }
.rows { list-style: none; margin: 0; padding: 0; }
.row { display: grid; grid-template-columns: 54px 1fr 150px 64px; gap: 4px 12px; align-items: center;
  padding: 11px 8px; border-top: 1px solid var(--rule); }
.row:first-child { border-top: 0; }
.row.in { background: var(--accent-soft); border-radius: 10px; border-top-color: transparent; }
.row.in + .row { border-top-color: transparent; }
.slot { font: 700 13px var(--mono); color: var(--muted); }
.row.in .slot { color: var(--accent); }
.who { min-width: 0; }
.who .name { font-weight: 700; font-size: 17px; }
.who .team { color: var(--muted); font-size: 14px; margin-left: 4px; }
.who .game { display: block; color: var(--muted); font-size: 14px; }
.who .was { display: block; font-size: 14px; color: var(--ink2); margin-top: 2px; }
.who .was s { text-decoration-thickness: 1.5px; }
.badge-in { font: 800 11px/1.7 var(--body); letter-spacing: .1em; color: var(--card); background: var(--accent);
  padding: 0 6px; border-radius: 4px; margin-right: 6px; vertical-align: 2px; }
.pos { display: inline-flex; align-items: center; gap: 5px; font: 700 12px var(--mono); color: var(--ink2);
  margin-right: 7px; vertical-align: 1px; }
.pos i { width: 9px; height: 9px; border-radius: 2px; background: var(--def); }
.pos.qb i { background: var(--qb); } .pos.rb i { background: var(--rb); } .pos.wr i { background: var(--wr); }
.pos.te i { background: var(--te); } .pos.k i { background: var(--k); }
.pts { font: 700 19px var(--mono); text-align: right; }
.pts.zero { color: var(--bad); }

/* Source spread: thin track, a bar from the lowest to the highest source, a dot at the number used */
.spread { position: relative; display: block; height: 28px; outline: none; cursor: help; }
.spread svg { display: block; width: 100%; height: 28px; overflow: visible; }
.spread .track { stroke: var(--rule); stroke-width: 2; stroke-linecap: round; }
.spread .range { stroke: var(--accent); stroke-opacity: .32; stroke-width: 8; stroke-linecap: round; }
.spread .pick { fill: var(--accent); stroke: var(--card); stroke-width: 2; }
.spread .lohi { font: 500 10.5px var(--mono); fill: var(--muted); }
.tip { position: absolute; right: 0; bottom: calc(100% + 6px); z-index: 4; min-width: 200px; max-width: 260px;
  background: var(--ink); color: var(--paper); border-radius: 10px; padding: 10px 12px; font: 500 13px/1.5 var(--body);
  box-shadow: 0 8px 24px rgb(0 0 0 / .18); opacity: 0; transform: translateY(4px); pointer-events: none;
  transition: opacity .12s, transform .12s; }
.tip b { display: block; font-weight: 700; margin-bottom: 4px; }
.tip span { display: flex; justify-content: space-between; gap: 12px; }
.tip span i { font-style: normal; font-family: var(--mono); }
.spread:hover .tip, .spread:focus .tip { opacity: 1; transform: none; }
.nospread { color: var(--muted); font-size: 13px; text-align: right; }

/* Notes inside a card */
.notes { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.notes li { padding: 9px 12px 9px 14px; border-left: 4px solid var(--warn); background: var(--warn-soft);
  border-radius: 0 8px 8px 0; font-size: 15px; }
.notes li.bad { border-left-color: var(--bad); background: var(--bad-soft); }
details.more summary { cursor: pointer; font-weight: 700; font-size: 15px; color: var(--ink2); padding: 4px 0; }
details.more[open] summary { margin-bottom: 6px; }
.bench { list-style: none; margin: 0; padding: 0; columns: 2 260px; column-gap: 24px; }
.bench li { display: flex; justify-content: space-between; gap: 10px; padding: 6px 0; border-top: 1px solid var(--rule);
  break-inside: avoid; font-size: 15px; }
.bench .num { color: var(--ink2); }
.wire { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.wire li { display: grid; grid-template-columns: 1fr auto; gap: 2px 12px; padding: 10px 12px; border-radius: 10px;
  background: var(--good-soft); font-size: 15px; }
.wire li.tough { background: var(--warn-soft); }
.wire .gain { font: 700 17px var(--mono); color: var(--good); }
.wire .why, .wire .facts { grid-column: 1 / -1; color: var(--ink2); font-size: 14px; }
.wire .facts { color: var(--muted); font-family: var(--mono); font-size: 13px; }
.wnote { color: var(--muted); font-size: 14px; }

/* Status boxes */
.box { border-radius: 12px; padding: 12px 16px; margin-top: 16px; font-size: 15px; }
.box.problems { background: var(--bad-soft); }
.box.problems h2 { font: 800 15px var(--body); letter-spacing: .1em; text-transform: uppercase; margin: 0 0 4px; color: var(--bad); }
.box.problems ul { margin: 0; padding-left: 18px; }
.box.stale { background: var(--warn-soft); }
details.updates { margin-top: 12px; font-size: 15px; color: var(--ink2); }
details.updates summary { cursor: pointer; }
details.updates ul { margin: 6px 0; padding-left: 20px; }
details.updates p { margin: 4px 0 0; color: var(--muted); font-size: 14px; }

footer { margin-top: 44px; padding-top: 14px; border-top: 3px double var(--heavy); color: var(--muted);
  font-size: 14px; display: grid; gap: 8px; }
footer p { margin: 0; }

@media (max-width: 620px) {
  body { font-size: 16px; }
  .item { grid-template-columns: 26px 1fr; padding: 13px 14px; }
  .item .gain { grid-column: 2; text-align: left; font-size: 19px; }
  .item .gain small { display: inline; margin-left: 6px; }
  .card-key { display: none; }
  .row { grid-template-columns: 38px 1fr 56px; gap: 2px 10px; padding: 10px 4px; }
  .row .spread, .row .nospread { grid-column: 2 / 4; grid-row: 2; max-width: 240px; }
  .row .nospread { text-align: left; }
  .row .pts { grid-column: 3; grid-row: 1; }
  .tip { left: 0; right: auto; }
  .league { padding: 18px 14px 14px; }
  .total { text-align: left; }
}
@media (prefers-reduced-motion: reduce) { .tip { transition: none; } }
@media print { .jump, .tools, details.updates { display: none; } .league { break-inside: avoid; } }
</style>
""".replace("%FONTS%", FONTS)

SCRIPT = """
<script>
(function () {
  var root = document.documentElement;
  function store(fn) { try { return fn(window.localStorage); } catch (e) { return null; } }
  // Theme: auto -> light -> dark, remembered on this device.
  var saved = store(function (s) { return s.getItem("ffman-theme"); });
  if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  var tb = document.getElementById("theme");
  function label() { if (tb) tb.textContent = "Theme: " + (root.getAttribute("data-theme") || "auto"); }
  label();
  if (tb) tb.addEventListener("click", function () {
    var cur = root.getAttribute("data-theme"), next = cur === "light" ? "dark" : cur === "dark" ? null : "light";
    if (next) root.setAttribute("data-theme", next); else root.removeAttribute("data-theme");
    store(function (s) { next ? s.setItem("ffman-theme", next) : s.removeItem("ffman-theme"); });
    label();
  });
  // To-do checkboxes, remembered per week on this device.
  var key = "ffman-done-" + (document.body.getAttribute("data-week") || "");
  var done = {};
  try { done = JSON.parse(store(function (s) { return s.getItem(key); }) || "{}") || {}; } catch (e) { done = {}; }
  document.querySelectorAll("input[data-done]").forEach(function (box) {
    var id = box.getAttribute("data-done"), item = box.closest(".item");
    function paint() { if (item) item.classList.toggle("done", box.checked); }
    box.checked = !!done[id]; paint();
    box.addEventListener("change", function () {
      if (box.checked) done[id] = 1; else delete done[id];
      store(function (s) { s.setItem(key, JSON.stringify(done)); });
      paint();
    });
  });
})();
</script>
"""


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _pos(player: Player) -> str:
    return (f'<span class="pos {POSITION_CLASS.get(player.position, "def")}"><i aria-hidden="true"></i>'
            f'{_e(player.position)}</span>')


def _flag(player: Player) -> str:
    if player.bye:
        return '<span class="tag bye">BYE</span>'
    status = (player.injury_status or "").upper()
    if player.is_out:
        return f'<span class="tag out">{_e(player.status_label)}</span>'
    if status in RISKY_STATUSES:
        return f'<span class="tag q">{_e(player.status_label)}</span>'
    return ""


def _game(player: Player) -> str:
    if player.bye:
        return '<span class="game">Bye week</span>'
    if not player.kickoff:
        return ""
    when = "game under way" if player.locked else fmt_time(player.kickoff)
    return f'<span class="game">{_e(player.matchup)} &middot; {_e(when)}</span>'


def _name(player: Player) -> str:
    team = f'<span class="team">{_e(player.team)}</span>' if player.team else ""
    lock = '<span class="tag lock">Locked</span>' if player.locked else ""
    return f'{_pos(player)}<span class="name">{_e(player.name)}</span>{team}{_flag(player)}{lock}'


def _spread(player: Player, scale: float) -> str:
    """Where every source landed for this player, drawn on the league's shared scale."""
    spread = player.source_range
    if not spread:
        return '<span class="nospread">1 source</span>'
    lo, hi = spread
    used = player.effective_projection
    x = lambda v: 4 + max(0.0, min(v / scale, 1.0)) * 92  # noqa: E731  (percent of width)
    rows = []
    if player.platform_projection is not None:
        rows.append(("Your league's site", player.platform_projection))
    rows += sorted(player.sources.items(), key=lambda kv: -kv[1])
    tip = "".join(f"<span>{_e(k)}<i>{v:.1f}</i></span>" for k, v in rows)
    label = (f"{player.name}: sources range {lo:.1f} to {hi:.1f}, using {used:.1f} "
             f"from {len(rows)} sources")
    return (f'<span class="spread" tabindex="0" aria-label="{_e(label)}">'
            '<svg aria-hidden="true">'
            '<line class="track" x1="4%" x2="96%" y1="12" y2="12"/>'
            f'<line class="range" x1="{x(lo):.1f}%" x2="{x(hi):.1f}%" y1="12" y2="12"/>'
            f'<circle class="pick" cx="{x(used):.1f}%" cy="12" r="5.5"/>'
            f'<text class="lohi" x="{x(lo):.1f}%" y="27" text-anchor="middle">{lo:.0f}</text>'
            + (f'<text class="lohi" x="{x(hi):.1f}%" y="27" text-anchor="middle">{hi:.0f}</text>'
               if x(hi) - x(lo) > 12 else "")
            + f'</svg><span class="tip" role="tooltip"><b>{len(rows)} projections</b>{tip}</span></span>')


def _when(moment: dt.datetime) -> str:
    hour = moment.hour % 12 or 12
    return f"{moment:%A, %B} {moment.day} &middot; {hour}:{moment:%M %p} {moment:%Z}".strip()


def _slug(text: str, index: int) -> str:
    base = "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")
    return f"l{index}-{base}"[:60]


def _move_id(r: LeagueReport, m: Move) -> str:
    return _e(f"{r.team.league_name}|{m.player.id}|{m.benched.id if m.benched else ''}")


def _benched_text(m: Move) -> str:
    if not m.benched:
        return "into the empty slot"
    b = m.benched
    tag = " (bye)" if b.bye else f" ({b.status_label})" if b.status_label else ""
    return f"instead of {_e(b.name)}{_e(tag)}"


def _league(r: LeagueReport, anchor: str) -> str:
    t = r.team
    moves = {m.player.id: m for m in r.start}
    best, now = r.best.total, t.current.total
    n = len(r.start)
    if r.needs_changes:
        cap = f'<b>+{r.gain:.1f}</b> if you make {n} move{"s" if n != 1 else ""}'
        verdict = (f'<p class="verdict">{n} move{"s" if n != 1 else ""} to make: '
                   'new starters are marked <span class="badge-in">IN</span></p>')
        shown = best
    else:
        cap = "projected, already your best lineup"
        verdict = '<p class="verdict ok">Your lineup is already the best one. Nothing to change.</p>'
        shown = now
    parts = [f'<section class="league" id="{anchor}" aria-labelledby="{anchor}-h">',
             '<div class="lhead"><div>',
             f'<h3 id="{anchor}-h">{_e(t.league_name)}</h3>',
             f'<div class="team"><b>{_e(t.team_name)}</b> &middot; {_e(t.platform)}</div></div>',
             f'<div class="total"><span class="big">{shown:.1f}</span><span class="cap">{cap}</span></div></div>',
             verdict]

    if r.alerts:
        parts.append('<ul class="notes">' + "".join(
            f'<li class="{a.level}">{_e(a.text)}</li>' for a in r.alerts) + '</ul>')

    starters = [p for p in r.best.players if p is not None]
    highs = [p.source_range[1] for p in starters if p.source_range] + [p.effective_projection for p in starters]
    scale = max(10.0, math.ceil(max(highs, default=10) / 5) * 5)
    rows = []
    for slot, player in zip(r.best.slots, r.best.players):
        label = SLOT_LABEL.get(slot, slot)
        if player is None:
            rows.append(f'<li class="row"><span class="slot">{_e(label)}</span>'
                        '<div class="who"><span class="name">Empty</span>'
                        '<span class="game">Nobody on your roster can fill this slot</span></div>'
                        '<span class="nospread"></span><span class="pts zero">0.0</span></li>')
            continue
        m = moves.get(player.id)
        was = ""
        if m:
            if m.benched:
                b = m.benched
                tag = " · bye" if b.bye else f" · {b.status_label}" if b.status_label else ""
                was = (f'<span class="was">instead of <s>{_e(b.name)}</s>{_e(tag)} '
                       f'&middot; <span class="num">{b.effective_projection:.1f}</span></span>')
            else:
                was = '<span class="was">fills an empty slot</span>'
        badge = '<span class="badge-in">IN</span>' if m else ""
        pts = player.effective_projection
        rows.append(f'<li class="row{" in" if m else ""}"><span class="slot">{_e(label)}</span>'
                    f'<div class="who">{badge}{_name(player)}{_game(player)}{was}</div>'
                    f'{_spread(player, scale)}'
                    f'<span class="pts{" zero" if pts == 0 else ""}">{pts:.1f}</span></li>')
    parts.append('<div><div class="card-key" aria-hidden="true"><span>Slot</span><span>Starter</span>'
                 '<span>Source range</span><span>Proj</span></div>'
                 f'<ul class="rows" aria-label="Best lineup">{"".join(rows)}</ul></div>')

    best_ids = {p.id for p in starters}
    bench = sorted((p for p in t.roster if p.id not in best_ids), key=lambda p: -p.effective_projection)
    if bench:
        items = "".join(f'<li><span>{_name(p)}</span><span class="num">{p.effective_projection:.1f}</span></li>'
                        for p in bench)
        parts.append(f'<details class="more"><summary>Bench ({len(bench)})</summary>'
                     f'<ul class="bench">{items}</ul></details>')

    if r.waivers or t.waiver_note:
        note = f' <span class="wnote">&middot; {_e(t.waiver_note)}</span>' if t.waiver_note else ""
        items = "".join(_wire_item(w) for w in r.waivers)
        body = f'<ul class="wire">{items}</ul>' if items else '<p class="wnote">No pickups worth making right now.</p>'
        parts.append(f'<details class="more"{" open" if r.waivers else ""}>'
                     f'<summary>Waiver wire{note}</summary>{body}</details>')
    parts.append('</section>')
    return "".join(parts)


def _facts(w, note: str | None = None) -> list[str]:
    add = w.add
    facts = [f"{add.effective_projection:.1f} this week", f"{add.next_projection:.1f} next"]
    if add.trending:
        facts.append(f"{add.trending:,} adds in 24h")
    if add.owned_pct is not None:
        facts.append(f"{add.owned_pct:.0f}% rostered")
    if add.waiver_status and add.waiver_status != "Available":
        facts.append(add.waiver_status.lower())
    if note:
        facts.append(note)
    return facts


def _wire_gain(w) -> tuple[str, str]:
    """(+points, what they're for): this week's lineup gain, or two-week depth when that's all it is."""
    if w.week_gain > 0.05:
        return f"+{w.week_gain:.1f}", "this week"
    return f"+{max(w.two_week_gain, 0):.1f}", "over 2 weeks"


def _wire_item(w) -> str:
    add = w.add
    game = f", {add.matchup}" if add.matchup else (", bye" if add.bye else "")
    drop = f' &middot; drop <b>{_e(w.drop.name)}</b>' if w.drop else ""
    return (f'<li class="{"tough" if w.tough else ""}"><span>Add <b>{_e(add.name)}</b> '
            f'({_e(add.position)}, {_e(add.team or "FA")}{_e(game)}){drop}</span>'
            f'<span class="gain">{_wire_gain(w)[0]} <small class="wnote">{_wire_gain(w)[1]}</small></span>'
            f'<span class="why">{_e(w.reason)}</span>'
            f'<span class="facts">{_e(" · ".join(_facts(w)))}</span></li>')


def _plan(reports: list[LeagueReport], anchors: dict[int, str]) -> str:
    """Everything to do across leagues: moves by deadline, then pickups, watch items, waivers."""
    plan = game_plan(reports)
    link = lambda r: f'<a class="lg" href="#{anchors[id(r)]}">{_e(r.team.league_name)}</a>'  # noqa: E731
    out = ['<h2 class="sec" id="todo">Your to-do list</h2>']
    if not plan.moves and not plan.pickups:
        out.append('<p class="allset"><b>Every lineup is already set.</b> Nothing to do right now.</p>')
    current = None
    for r, m in plan.moves:
        label = deadline_label(m.deadline)
        if label != current:
            if current is not None:
                out.append("</ul>")
            out.append(f'<h3 class="when">{_e(label)}</h3><ul class="tasks">')
            current = label
        game = (f'<span class="why">{_e(m.player.matchup or "")} &middot; {_e(fmt_time(m.player.kickoff))}</span>'
                if m.player.kickoff else "")
        close = '<span class="tag close">close call</span>' if m.close_call else ""
        out.append(f'<li class="item"><input type="checkbox" data-done="{_move_id(r, m)}" '
                   f'aria-label="Mark done: start {_e(m.player.name)}">'
                   f'<div class="what">{link(r)}Start <b>{_e(m.player.name)}</b> ({_e(m.player.position)}) '
                   f'{_benched_text(m)}{close}{game}</div>'
                   f'<span class="gain">+{m.gain:.1f}<small>points</small></span></li>')
    if current is not None:
        out.append("</ul>")
    if plan.pickups:
        out.append('<h3 class="when">Pick up someone</h3><ul class="tasks">' + "".join(
            f'<li class="item bad"><span class="icon" aria-hidden="true">!</span>'
            f'<div class="what">{link(r)}{_e(a.text)}</div></li>' for r, a in plan.pickups) + "</ul>")
    if plan.watch:
        out.append('<h3 class="when">Keep an eye on</h3><ul class="tasks">' + "".join(
            f'<li class="item warn"><span class="icon" aria-hidden="true">?</span>'
            f'<div class="what">{link(r)}{_e(a.text)}</div></li>' for r, a in plan.watch) + "</ul>")
    if plan.all_set:
        names = ", ".join(_e(r.team.league_name) for r in plan.all_set)
        out.append(f'<p class="allset"><b>Already set:</b> {names}</p>')
    if plan.waivers:
        out.append('<h2 class="sec">Waiver ideas</h2><ul class="tasks">')
        for i, (r, w) in enumerate(plan.waivers):
            if i == WAIVERS_SHOWN:
                out.append(f'</ul><details class="more"><summary>{len(plan.waivers) - i} more waiver '
                           f'idea{"s" if len(plan.waivers) - i != 1 else ""}</summary><ul class="tasks">')
            add = w.add
            drop = f", drop <b>{_e(w.drop.name)}</b>" if w.drop else ""
            out.append(f'<li class="item add{" tough" if w.tough else ""}"><span class="icon" aria-hidden="true">+</span>'
                       f'<div class="what">{link(r)}Add <b>{_e(add.name)}</b> ({_e(add.position)}, '
                       f'{_e(add.team or "FA")}){drop}<span class="why">{_e(w.reason)}</span>'
                       f'<span class="why num">{_e(" · ".join(_facts(w, r.team.waiver_note)))}</span></div>'
                       f'<span class="gain">{_wire_gain(w)[0]}<small>{_wire_gain(w)[1]}</small></span></li>')
        out.append("</ul></details>" if len(plan.waivers) > WAIVERS_SHOWN else "</ul>")
    return "".join(out)


def _updates(next_updates: list[dt.datetime], run_url: str | None) -> str:
    """When the page refreshes next, plus a warning if it's overdue."""
    if not next_updates:
        return ""
    times = "".join(f"<li>{_e(fmt_time(t))}</li>" for t in next_updates)
    now_link = (f' Need it sooner? <a href="{_e(run_url)}" target="_blank" rel="noopener">Update now on GitHub</a>'
                ' (Run workflow).' if run_url else "")
    due = int(next_updates[0].timestamp() * 1000)
    return (
        f'<details class="updates"><summary>Next update about <b>{_e(fmt_time(next_updates[0]))}</b>'
        ' &middot; schedule</summary>'
        f'<ul>{times}</ul>'
        '<p>Updates every morning around 9 AM, Tuesday night before waivers run, every 30 minutes '
        'on Sundays (about 9 AM to 8 PM), and every 30 minutes before Thursday and Monday night '
        'games. Injuries and rosters refresh every time; projection sites about twice a day. '
        f'GitHub sometimes starts updates a few minutes late.{now_link}</p></details>'
        f'<div class="box stale" id="stale" hidden>This page was due to update at '
        f'{_e(fmt_time(next_updates[0]))} and hasn\'t yet, so the info below may be out of date. '
        'Updates sometimes run late; check back in a few minutes'
        f'{f""" or <a href="{_e(run_url)}" target="_blank" rel="noopener">update it now</a>""" if run_url else ""}.</div>'
        f'<script>(function(){{var due={due};'
        'if(Date.now()>due+45*60*1000){var el=document.getElementById("stale");if(el)el.hidden=false;}})();</script>'
    )


LOCK_BUTTON = (
    '<button type="button" class="btn" '
    "onclick=\"try{localStorage.removeItem('ffman-key')}catch(e){};location.reload()\">"
    "Log out</button>"
)


def _lede(ordered: list[LeagueReport]) -> str:
    todo = [r for r in ordered if r.needs_changes]
    moves = sum(len(r.start) for r in todo)
    gain = sum(r.gain for r in todo)
    pickups = sum(1 for r in ordered for a in r.alerts if a.level == "bad")
    n = len(ordered)
    if not ordered:
        return ""
    if moves:
        text = (f'You have <b>{moves} move{"s" if moves != 1 else ""}</b> to make across {n} '
                f'league{"s" if n != 1 else ""}, worth <span class="plus num">+{gain:.1f}</span> points.')
    else:
        text = f'All {n} lineup{"s are" if n != 1 else " is"} set. Nothing to move.'
    if pickups:
        text += f' <b>{pickups} spot{"s" if pickups != 1 else ""}</b> need{"s" if pickups == 1 else ""} a pickup.'
    return f'<p class="lede">{text}</p>'


def render_dashboard(reports: list[LeagueReport], week: int | None, errors: list[str],
                     generated: dt.datetime | None = None, week_picker: bool = False,
                     logout: bool = False, next_updates: list[dt.datetime] | None = None,
                     run_url: str | None = None, sources_note: str | None = None) -> str:
    """The page body: <title>, styles and content (no <html>/<body> wrapper)."""
    generated = generated or dt.datetime.now().astimezone()
    ordered = sorted(reports, key=lambda r: (not r.needs_changes, -r.gain))
    anchors = [_slug(r.team.league_name, i) for i, r in enumerate(ordered)]
    locked = any(p.locked for r in ordered for p in r.team.roster)

    tools = ['<button type="button" class="btn" id="theme">Theme: auto</button>']
    if week_picker:
        options = "".join(f'<option value="{w}"{" selected" if w == week else ""}>Week {w}</option>'
                          for w in range(1, 19))
        tools.insert(0, '<form method="get" class="tools"><label class="kicker" for="week">Week</label>'
                        f'<select class="btn" id="week" name="week">{options}</select>'
                        '<button type="submit" class="btn primary">Refresh</button></form>')
    if logout:
        tools.append(LOCK_BUTTON)

    out = ["<title>ffman Lineups</title>", STYLE, '<div class="wrap">',
           '<header class="mast"><div class="top"><span class="kicker">ffman &middot; lineup card</span>'
           f'<div class="tools">{"".join(tools)}</div></div>',
           f'<h1>Week <em>{week}</em></h1>' if week else "<h1>Lineups</h1>",
           f'<div class="dateline">{_when(generated)}'
           + (f' &middot; next update about {_e(fmt_time(next_updates[0]))}' if next_updates else "")
           + '</div></header>']

    if ordered:
        links = "".join(
            f'<a href="#{a}"><span class="dot{" todo" if r.needs_changes else ""}'
            f'{" bad" if any(x.level == "bad" for x in r.alerts) else ""}" aria-hidden="true"></span>'
            f'{_e(r.team.league_name)}'
            + (f' <span class="num">&middot; {len(r.start)} move{"s" if len(r.start) != 1 else ""}</span>'
               if r.needs_changes else "")
            + '</a>' for r, a in zip(ordered, anchors))
        out.append(f'<nav class="jump" aria-label="Leagues"><a href="#todo">To-do</a>{links}</nav>')

    out.append(_lede(ordered))
    note = "Suggestions only. Nothing has been changed in any of your leagues."
    if locked:
        note += " Players whose games have started are locked and left where they are."
    out.append(f'<p class="sub">{note}</p>')
    out.append(_updates(next_updates or [], run_url))
    if errors:
        out.append('<div class="box problems"><h2>Couldn\'t load</h2><ul>'
                   + "".join(f"<li>{_e(e)}</li>" for e in errors) + "</ul></div>")
    if ordered:
        out.append(_plan(ordered, {id(r): a for r, a in zip(ordered, anchors)}))
        out.append('<h2 class="sec">League by league</h2>')
    out.extend(_league(r, a) for r, a in zip(ordered, anchors))
    if not ordered and not errors:
        out.append('<p class="sub">No leagues found. Check your config.</p>')

    how = ("Each projection is your league site's number averaged with the free sources below, after "
           "shifting each source onto your league's scoring (with 5 or more numbers the highest and lowest "
           "are dropped). On each row the bar runs from the lowest to the highest source and the dot is the "
           "number used; hover or tap it to see every source.")
    sources = _e(sources_note) if sources_note else "Projections: Sleeper (scored with each league's settings) and ESPN."
    out.append(f'<footer><p>{sources}</p><p>{how if sources_note else ""}</p>'
               f'<p>Game times from ESPN\'s NFL schedule, shown in {_e(generated.strftime("%Z") or "local time")}. '
               'Always check injury news before kickoff.</p></footer></div>')
    out.append(SCRIPT)
    return "\n".join(out)


def full_page(body: str, week: int | None = None) -> str:
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            '<meta name="color-scheme" content="light dark">'
            f'</head><body data-week="{week or ""}">{body}</body></html>')


def serve(build, host: str = "127.0.0.1", port: int = 8000, cache_seconds: int = 300) -> None:
    """Run the local website. `build(week)` returns (reports, week, errors, sources note)."""
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
                reports, shown, errors, note = build(week)
                page = full_page(render_dashboard(reports, shown, errors, week_picker=True,
                                                  sources_note=note), shown)
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
