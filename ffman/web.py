"""The ffman website.

Design: a night-black performance spec sheet (after the Vektr template). One signal-orange
accent for anything you act on, wide all-caps Archivo headlines, tiny Martian Mono labels,
hairline panels. Three tabs live in the top bar: "This week" (hero readout, game plan by
deadline, waiver ideas), "Recap" (how last weeks went vs. ffman's lineup) and "Leagues"
(each league's best lineup). `render_dashboard` builds the page body; `serve` runs a
small local site.
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

LOGO = ('<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M4 7h6.2L16 19.8V26.5z" fill="#f2f1ed"/>'
        '<path d="M28 7h-6.2L16 19.8V26.5z" fill="#ff5a1f"/></svg>')

STYLE = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,300..900&family=Martian+Mono:wght@400;500&display=swap">
<style>
/* Layout: a performance spec sheet for your lineups. Night-black stage, one signal-orange
   accent for anything you act on, wide caps headlines, tiny mono instrument labels.
   (--surface/--line/--turf/--bg/--ink/--muted/--bad are also used by the login page.) */
:root {
  --bg: #050607; --surface: #0b0c0d; --panel-2: #111214; --line: #222325; --line-2: #2e3032;
  --ink: #f2f1ed; --muted: #8d8e8b; --faint: #55575a; --turf: #ff5a1f; --signal: #ff5a1f;
  --signal-soft: rgba(255,90,31,.14); --bad: #ff8a7a; --warn: #f5b84a;
  --display: "Archivo", "Arial Narrow", Arial, sans-serif;
  --body: "Archivo", "Helvetica Neue", Arial, sans-serif;
  --mono: "Martian Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
  color-scheme: dark;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body { background: var(--bg); color: var(--ink); font: 400 15px/1.55 var(--body); margin: 0;
  font-variant-numeric: tabular-nums; -webkit-font-smoothing: antialiased; }
a { color: inherit; }
:focus-visible { outline: 2px solid var(--signal); outline-offset: 3px; }
.wrap { max-width: 1120px; margin: 0 auto; padding-inline: 20px; }
.mono { font-family: var(--mono); font-size: 10.5px; letter-spacing: .14em; text-transform: uppercase; }
.dim { color: var(--muted); }
.sig { color: var(--signal); }
.up { color: var(--signal); } .down { color: var(--bad); }

/* top bar with tabs */
nav.top { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 10; background: rgba(5,6,7,.86);
  backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px); border-bottom: 1px solid var(--line); }
nav.top .wrap { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 12px; min-height: 58px; }
.logo { display: flex; align-items: center; gap: 10px; text-decoration: none; font: 800 15px var(--display);
  font-stretch: 125%; letter-spacing: .12em; }
.logo svg { width: 22px; height: 22px; }
.tabs { display: flex; gap: 4px; border: 1px solid var(--line-2); border-radius: 999px; padding: 4px; background: var(--surface); }
.tabs button { all: unset; cursor: pointer; font: 400 10.5px var(--mono); letter-spacing: .14em; text-transform: uppercase;
  color: var(--muted); padding: 8px 14px; border-radius: 999px; white-space: nowrap; }
.tabs button:hover { color: var(--ink); }
.tabs button[aria-selected="true"] { background: var(--signal); color: var(--bg); }
.tabs button:focus-visible { outline: 2px solid var(--signal); outline-offset: 2px; }
.tabs .n { opacity: .75; margin-left: 4px; }
.right { display: flex; justify-content: flex-end; align-items: center; gap: 10px; }
.pill { display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--line-2); border-radius: 999px;
  padding: 7px 13px; background: var(--surface); white-space: nowrap; color: var(--ink); text-decoration: none; }
.pill .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--signal); }
.ghost { all: unset; cursor: pointer; color: var(--muted); font: 400 10.5px var(--mono); letter-spacing: .14em;
  text-transform: uppercase; }
.ghost:hover { color: var(--ink); }
.weekform { display: flex; gap: 6px; align-items: center; }
.weekform select, .weekform button { font: 400 11px var(--mono); padding: 6px 8px; border-radius: 999px;
  border: 1px solid var(--line-2); background: var(--surface); color: var(--ink); }

/* hero */
.hero { position: relative; overflow: hidden; padding-block: 34px 0;
  background: radial-gradient(ellipse 70% 55% at 50% 62%, rgba(255,90,31,.16), transparent 70%), var(--bg); }
.kicker { text-align: center; }
h1 { font: 900 clamp(46px, 10.5vw, 118px)/.9 var(--display); font-stretch: 125%; text-transform: uppercase;
  text-align: center; margin: 14px 0 0; letter-spacing: -.01em;
  background: linear-gradient(180deg, var(--ink) 30%, #9c9b97 100%); -webkit-background-clip: text; background-clip: text;
  color: transparent; text-wrap: balance; }
.stage { display: grid; grid-template-columns: 210px minmax(0, 1fr) 210px; gap: 20px; align-items: center;
  margin-top: 26px; padding-bottom: 26px; }
.hud { display: grid; gap: 16px; }
.hud .big { font: 700 44px/1 var(--display); font-stretch: 110%; }
.hud .big.sm { font-size: 30px; }
.hud .big small { font: 400 11px var(--mono); color: var(--muted); margin-left: 6px; letter-spacing: .1em; }
.meter { display: grid; gap: 6px; }
.meter .row { display: flex; justify-content: space-between; }
.meter .bar { height: 2px; background: var(--line-2); position: relative; }
.meter .bar i { position: absolute; inset: 0 auto 0 0; background: var(--signal); }
.segs { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; }
.segs i { height: 3px; background: var(--line-2); }
.segs i.on { background: var(--signal); }
.field { position: relative; aspect-ratio: 16 / 9; max-width: 100%; }
.field svg { width: 100%; height: 100%; display: block; }
.bracket { position: absolute; width: 14px; height: 14px; border-color: var(--line-2); border-style: solid; }
.bracket.tl { top: 0; left: 0; border-width: 1px 0 0 1px; } .bracket.tr { top: 0; right: 0; border-width: 1px 1px 0 0; }
.bracket.bl { bottom: 0; left: 0; border-width: 0 0 1px 1px; } .bracket.br { bottom: 0; right: 0; border-width: 0 1px 1px 0; }
.under { display: flex; justify-content: space-between; gap: 12px; border-top: 1px solid var(--line); padding-block: 14px;
  flex-wrap: wrap; }
.under details { display: inline; }
.under summary { display: inline; cursor: pointer; color: var(--signal); list-style: none; }
.under summary::-webkit-details-marker { display: none; }
.schedule { margin-top: 10px; padding: 12px 14px; border: 1px solid var(--line); background: var(--surface);
  text-transform: none; letter-spacing: 0; font: 400 13px var(--body); color: var(--ink); max-width: 420px; }
.schedule ul { margin: 4px 0 8px; padding-left: 18px; }
.schedule p { margin: 0; color: var(--muted); }
.schedule a { color: var(--signal); }

/* ticker */
.ticker { border-block: 1px solid var(--line); overflow: hidden; }
.ticker .track { display: flex; width: max-content; animation: slide 50s linear infinite; }
.ticker span { font: 800 clamp(20px, 3vw, 30px) var(--display); font-stretch: 125%; text-transform: uppercase;
  white-space: nowrap; padding: 16px 0; }
.ticker span.fade { color: var(--faint); }
.ticker span.sep { color: var(--signal); padding-inline: 26px; }
@keyframes slide { to { transform: translateX(-50%); } }
@media (prefers-reduced-motion: reduce) { .ticker .track { animation: none; } }

/* sections */
section.s { padding-block: 84px 0; }
.eyebrow { display: flex; align-items: center; gap: 14px; }
.eyebrow::after { content: ""; width: 34px; height: 1px; background: var(--line-2); order: 1; }
.eyebrow .num { color: var(--signal); }
.eyebrow .l { order: 2; }
.head { display: grid; grid-template-columns: 1.3fr 1fr; gap: 24px; align-items: end; margin-top: 16px; }
h2 { font: 800 clamp(34px, 5.6vw, 64px)/.98 var(--display); font-stretch: 112%; margin: 0; letter-spacing: -.015em;
  text-wrap: balance; }
.head p { color: var(--muted); max-width: 42ch; margin: 0; justify-self: end; font-size: 14px; }
.notice { border: 1px solid var(--line-2); background: var(--surface); padding: 12px 16px; margin-top: 18px; font-size: 13.5px; }
.notice.bad { border-color: rgba(255,138,122,.4); }
.notice ul { margin: 4px 0 0; padding-left: 18px; }
.empty { color: var(--muted); }

/* game plan */
.plan { margin-top: 40px; border: 1px solid var(--line); background: var(--surface); }
.when { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px 20px;
  border-bottom: 1px solid var(--line); background: var(--panel-2); }
.when .t { color: var(--signal); }
.move { display: grid; grid-template-columns: 26px 1.1fr 1.3fr auto; gap: 18px; align-items: center; padding: 16px 20px;
  border-bottom: 1px solid var(--line); }
.plan > .move:last-child { border-bottom: 0; }
.move input { appearance: none; -webkit-appearance: none; width: 18px; height: 18px; border: 1px solid var(--line-2);
  border-radius: 50%; margin: 0; cursor: pointer; display: grid; place-items: center; background: none; }
.move input:checked { background: var(--signal); border-color: var(--signal); }
.move input:checked::after { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--bg); }
.move.ticked .what, .move.ticked .why, .move.ticked .gain { opacity: .35; }
.move .what { font: 600 18px/1.25 var(--display); font-stretch: 105%; min-width: 0; overflow-wrap: anywhere; }
.move .what s { text-decoration: none; color: var(--muted); font-weight: 400; }
.move .why { color: var(--muted); font-size: 13.5px; min-width: 0; }
.move .gain { font: 700 26px var(--display); font-stretch: 110%; text-align: right; white-space: nowrap; }
.move .gain small { display: block; font: 400 10px var(--mono); letter-spacing: .12em; color: var(--muted); text-transform: uppercase; }
.move .gain.close { color: var(--muted); }
.move.alert { grid-template-columns: 26px 1fr; }
.move.alert .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--bad); justify-self: center; }
.move.alert.watch .dot { background: var(--warn); }
.allset { color: var(--muted); font-size: 13.5px; margin: 14px 0 0; }
.allset b { color: var(--ink); font-weight: 600; }

/* waiver cards */
.feat { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1px; background: var(--line);
  border: 1px solid var(--line); margin-top: 40px; }
.feat article { padding: 22px 20px; display: grid; gap: 10px; align-content: start; min-width: 0; background: var(--bg); }
.feat svg { width: 18px; height: 18px; color: var(--signal); }
.feat h3 { margin: 0; font: 700 17px/1.2 var(--display); font-stretch: 105%; }
.feat h3 span { color: var(--muted); font-weight: 400; }
.feat p { margin: 0; color: var(--muted); font-size: 13.5px; }
.feat .v { font: 700 24px var(--display); font-stretch: 110%; color: var(--signal); }
.feat .v small { font: 400 10px var(--mono); color: var(--muted); letter-spacing: .12em; margin-left: 4px; text-transform: uppercase; }
.feat article.tough .v { color: var(--warn); }

/* leagues */
.lgwrap { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 28px; margin-top: 40px; align-items: start; }
.modes { border-top: 1px solid var(--line); }
.modes button { all: unset; box-sizing: border-box; width: 100%; display: grid; grid-template-columns: 34px 1fr auto;
  gap: 8px; align-items: baseline; padding: 18px 0; border-bottom: 1px solid var(--line); cursor: pointer; }
.modes button:focus-visible { outline: 2px solid var(--signal); outline-offset: -2px; }
.modes .nm { font: 800 19px/1.15 var(--display); font-stretch: 118%; text-transform: uppercase; color: var(--faint); }
.modes .st { color: var(--faint); }
.modes button[aria-selected="true"] .nm { color: var(--ink); }
.modes button[aria-selected="true"] .st { color: var(--signal); }
.modes .sub { grid-column: 2 / 4; color: var(--muted); font-size: 13px; display: none; }
.modes button[aria-selected="true"] .sub { display: block; }
.card { border: 1px solid var(--line); background: var(--surface); min-width: 0; }
.card .ch { display: flex; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid var(--line); gap: 12px; flex-wrap: wrap; }
.nums { display: grid; grid-template-columns: repeat(3, 1fr); border-top: 1px solid var(--line); }
.nums div { padding: 14px 18px; display: grid; gap: 4px; }
.nums div + div { border-left: 1px solid var(--line); }
.nums b { font: 700 30px/1 var(--display); font-stretch: 110%; }
.nums b small { font: 400 10px var(--mono); color: var(--muted); margin-left: 4px; }
.tablewrap { overflow-x: auto; }
table.lu { width: 100%; border-collapse: collapse; font-size: 14px; }
table.lu td { padding: 11px 18px; border-bottom: 1px solid var(--line); vertical-align: top; }
table.lu tr:last-child td { border-bottom: 0; }
table.lu td.slot { width: 74px; color: var(--muted); font: 400 10.5px var(--mono); letter-spacing: .12em; padding-top: 14px; }
table.lu td.p { font-weight: 600; }
table.lu .m { display: block; font-weight: 400; color: var(--muted); font-size: 12.5px; margin-top: 2px; }
table.lu .was { display: block; font-weight: 400; color: var(--signal); font-size: 12.5px; margin-top: 2px; }
table.lu td.n { text-align: right; font: 500 14px var(--mono); white-space: nowrap; }
table.lu tr.new td.p::before { content: "IN"; font: 500 9.5px var(--mono); letter-spacing: .14em; color: var(--bg);
  background: var(--signal); padding: 2px 5px; margin-right: 8px; vertical-align: 2px; }
.tag { font: 500 9.5px var(--mono); letter-spacing: .12em; padding: 2px 5px; margin-left: 8px; vertical-align: 2px;
  border: 1px solid var(--line-2); color: var(--muted); }
.tag.bad { border-color: rgba(255,138,122,.5); color: var(--bad); }
.tag.warn { border-color: rgba(245,184,74,.5); color: var(--warn); }
details.src { font-size: 11.5px; color: var(--faint); margin-top: 3px; }
details.src summary { cursor: pointer; list-style: none; font-family: var(--mono); }
details.src summary::-webkit-details-marker { display: none; }
details.src .vals { display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 4px; }
details.src .vals span i { font-style: normal; color: var(--ink); margin-left: 4px; }
.lgnote { padding: 12px 18px; border-top: 1px solid var(--line); color: var(--muted); font-size: 13px; }

/* recap */
.specs { display: grid; grid-template-columns: repeat(4, 1fr); border: 1px solid var(--line); margin-top: 40px; }
.specs div { padding: 18px 20px; display: grid; gap: 6px; }
.specs div + div { border-left: 1px solid var(--line); }
.specs b { font: 800 clamp(32px, 5vw, 54px)/1 var(--display); font-stretch: 115%; }
.specs b small { font: 400 11px var(--mono); color: var(--signal); margin-left: 6px; letter-spacing: .08em; }
.recapgrid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 28px; margin-top: 28px; align-items: start; }
.chart { border: 1px solid var(--line); background: var(--surface); padding: 16px 18px 12px; min-width: 0; }
.chart .ct { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.chart svg { width: 100%; height: auto; display: block; margin-top: 10px; }
.legend { display: flex; gap: 18px; margin-top: 6px; flex-wrap: wrap; }
.legend span { display: inline-flex; align-items: center; gap: 8px; }
.legend i { width: 14px; height: 2px; background: var(--muted); display: inline-block; }
.legend i.ff { background: var(--signal); }
.legend i.best { background: none; border-top: 1px dashed var(--faint); }
.segbtns { display: flex; gap: 6px; flex-wrap: wrap; }
.segbtns button { all: unset; cursor: pointer; border: 1px solid var(--line-2); border-radius: 999px; padding: 6px 12px;
  font: 400 10px var(--mono); letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
.segbtns button[aria-pressed="true"] { border-color: var(--signal); color: var(--ink); background: var(--signal-soft); }
.segbtns button:focus-visible { outline: 2px solid var(--signal); outline-offset: 2px; }
.sheet { border: 1px solid var(--line); background: var(--surface); }
.sheet h4 { margin: 0; padding: 14px 18px 10px; }
.sheet .r { display: flex; justify-content: space-between; gap: 12px; padding: 10px 18px; border-top: 1px solid var(--line); font-size: 13.5px; }
.sheet .r span:first-child { color: var(--muted); }
.latest { margin-top: 28px; border: 1px solid var(--line); background: var(--surface); }
.latest .item { padding: 16px 20px; border-top: 1px solid var(--line); display: grid; gap: 6px; }
.latest .item:first-child { border-top: 0; }
.latest .verdict { font: 600 17px/1.3 var(--display); font-stretch: 105%; }
.result { font: 500 10px var(--mono); letter-spacing: .1em; padding: 3px 7px; border: 1px solid var(--line-2); white-space: nowrap; }
.result.W { border-color: rgba(255,90,31,.6); color: var(--signal); }
.result.L { border-color: rgba(255,138,122,.5); color: var(--bad); }
details.more summary { cursor: pointer; color: var(--signal); font: 400 10.5px var(--mono); letter-spacing: .12em; text-transform: uppercase; }
details.more ul { margin: 8px 0 0; padding-left: 18px; font-size: 13.5px; color: var(--muted); }
.footnote { color: var(--faint); font-size: 12.5px; margin-top: 14px; }

/* footer */
footer { margin-top: 110px; border-top: 1px solid var(--line); padding-block: 44px 0; overflow: hidden; }
footer .cols { display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 24px; }
footer p { color: var(--muted); max-width: 40ch; font-size: 13.5px; }
footer ul { list-style: none; padding: 0; margin: 12px 0 0; display: grid; gap: 8px; font-size: 13.5px; }
.wordmark { font: 900 clamp(90px, 24vw, 300px)/.8 var(--display); font-stretch: 125%; color: #0e0f10;
  text-align: center; margin-top: 40px; letter-spacing: -.02em; user-select: none; }
.legal { display: flex; justify-content: space-between; gap: 12px; border-top: 1px solid var(--line); padding-block: 16px 22px;
  flex-wrap: wrap; }

/* responsive */
@media (max-width: 920px) {
  nav.top .wrap { grid-template-columns: 1fr auto; padding-block: 8px; }
  .tabs { grid-column: 1 / -1; grid-row: 2; justify-content: center; }
  .tabs button { flex: 1; text-align: center; padding: 8px 6px; }
  .stage { grid-template-columns: 1fr; }
  .hud { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .head { grid-template-columns: 1fr; } .head p { justify-self: start; }
  .lgwrap, .recapgrid { grid-template-columns: 1fr; }
  .specs { grid-template-columns: repeat(2, 1fr); }
  .specs div:nth-child(3) { border-left: 0; } .specs div:nth-child(n+3) { border-top: 1px solid var(--line); }
  footer .cols { grid-template-columns: 1fr 1fr; } footer .cols > div:first-child { grid-column: 1 / -1; }
}
@media (max-width: 560px) {
  .move { grid-template-columns: 22px minmax(0, 1fr) auto; gap: 12px; padding: 14px 16px; }
  .move .why { grid-column: 2 / 4; }
  .move .gain { grid-row: 1; grid-column: 3; font-size: 22px; }
  .when { padding: 12px 16px; }
  .nums b { font-size: 24px; }
  .hud .big { font-size: 36px; }
  section.s { padding-block: 64px 0; }
  .weekform { display: none; }
}
</style>
"""

SCRIPT = """
<script>
(function () {
  var tabs = document.querySelectorAll('.tabs button');
  function show(id) {
    tabs.forEach(function (t) {
      var on = t.dataset.tab === id;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
      var panel = document.getElementById(t.dataset.tab);
      if (panel) panel.hidden = !on;
    });
  }
  tabs.forEach(function (t, i) {
    t.addEventListener('click', function () {
      show(t.dataset.tab);
      try { history.replaceState(null, '', '#' + t.dataset.tab); } catch (e) {}
      window.scrollTo({ top: 0 });
    });
    t.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      var next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      next.click(); next.focus();
    });
  });
  var start = (location.hash || '').slice(1);
  show(document.getElementById(start) && document.querySelector('.tabs [data-tab="' + start + '"]') ? start : 'week');

  // Pick-one lists: leagues (role=tab) and recap league buttons (aria-pressed).
  function picker(listSel, attr) {
    document.querySelectorAll(listSel).forEach(function (list) {
      var btns = list.querySelectorAll('button');
      btns.forEach(function (b) {
        b.addEventListener('click', function () {
          btns.forEach(function (o) {
            var on = o === b;
            o.setAttribute(attr, on ? 'true' : 'false');
            document.querySelectorAll('[data-pane="' + o.dataset.target + '"]').forEach(function (p) { p.hidden = !on; });
          });
        });
      });
    });
  }
  picker('.modes', 'aria-selected');
  picker('.segbtns', 'aria-pressed');

  // Tick-off checkboxes, remembered on this device for the week.
  var key = 'ffman-done-' + (document.body.dataset.week || '');
  var done = {};
  try { done = JSON.parse(localStorage.getItem(key) || '{}'); } catch (e) {}
  document.querySelectorAll('input[data-done]').forEach(function (box) {
    var row = box.closest('.move');
    box.checked = !!done[box.dataset.done];
    row.classList.toggle('ticked', box.checked);
    box.addEventListener('change', function () {
      row.classList.toggle('ticked', box.checked);
      if (box.checked) done[box.dataset.done] = 1; else delete done[box.dataset.done];
      try { localStorage.setItem(key, JSON.stringify(done)); } catch (e) {}
    });
  });
})();
</script>
"""

LOCK_BUTTON = (
    '<button type="button" class="ghost" '
    "onclick=\"try{localStorage.removeItem('ffman-key')}catch(e){};location.reload()\">"
    "Log out</button>"
)

ICONS = [
    '<path d="M3 12h18M12 3v18" stroke="currentColor" stroke-width="1.6" fill="none"/>',
    '<circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.6" fill="none"/>'
    '<path d="M12 8v8M8 12h8" stroke="currentColor" stroke-width="1.6"/>',
    '<path d="M4 18l6-6 4 4 6-8" stroke="currentColor" stroke-width="1.6" fill="none"/>',
    '<path d="M5 12l4 4 10-10" stroke="currentColor" stroke-width="1.6" fill="none"/>',
]


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _when(moment: dt.datetime) -> str:
    hour = moment.hour % 12 or 12
    return f"{moment:%a %b} {moment.day}, {hour}:{moment:%M %p} {moment:%Z}".strip()


def _slug(text: str, i: int) -> str:
    return f"l{i}-" + "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")[:40]


def _status_tag(p: Player) -> str:
    if p.bye:
        return '<span class="tag bad">BYE</span>'
    if p.is_out:
        return f'<span class="tag bad">{_e((p.status_label or "").upper())}</span>'
    if p.status_label:
        return f'<span class="tag warn">{_e(p.status_label.upper())}</span>'
    return ""


def _why_out(p: Player | None, start: Player) -> str:
    """Short reason a benched player is being replaced."""
    if p is None:
        return "Fills an empty slot"
    if p.bye:
        return f"{p.name} is on bye"
    if p.status_label:
        return f"{p.name} is {p.status_label}"
    return f"{start.effective_projection:.1f} vs {p.effective_projection:.1f} projected"


def _game(p: Player) -> str:
    if p.bye or not p.kickoff:
        return ""
    return f"{p.matchup}, {'under way' if p.locked else fmt_time(p.kickoff)}"


def _sources(p: Player) -> str:
    """Spread of the projection sources behind a player's number, values on tap."""
    rng = p.source_range
    if not rng:
        return ""
    vals = dict(p.sources)
    if p.platform_projection is not None:
        vals["Platform"] = p.platform_projection
    items = "".join(f"<span>{_e(k)}<i>{v:.1f}</i></span>"
                    for k, v in sorted(vals.items(), key=lambda kv: -kv[1]))
    return (f'<details class="src"><summary>{len(vals)} projections: {rng[0]:.1f}–{rng[1]:.1f}</summary>'
            f'<div class="vals">{items}</div></details>')


# ------------------------------------------------------------------------------ This week

def _hero(reports: list[LeagueReport], week: int | None, generated: dt.datetime,
          next_updates: list[dt.datetime], run_url: str | None) -> str:
    plan = game_plan(reports)
    gain = sum(r.gain for r in reports if r.needs_changes)
    moves = len(plan.moves)
    deadlines = [m.deadline for _, m in plan.moves if m.deadline]
    first = min(deadlines) if deadlines else None
    sources = max((len(r.team.sources_used) for r in reports), default=0) or 1
    ideas = len(plan.waivers)
    set_count = sum(1 for r in reports if not r.needs_changes)
    title = "Set the<br>lineup." if moves else "Lineups<br>locked in."
    platforms = sorted({r.team.platform for r in reports})

    # Field: before/after bars per league on a perspective field.
    n = max(len(reports), 1)
    top = max([r.best.total for r in reports] + [r.team.current.total for r in reports] + [1])
    bars = []
    for i, r in enumerate(reports):
        cx = 20 + 600 / n * (i + .5)
        w = min(22, 600 / n / 3)
        h1, h0 = r.best.total / top * 220, r.team.current.total / top * 220
        label = r.team.league_name.upper()
        label = label if len(label) <= 14 else label[:13] + "…"
        bars.append(
            f'<rect x="{cx - w - 2:.1f}" y="{330 - h1:.1f}" width="{w:.1f}" height="{h1:.1f}" fill="#ff5a1f"/>'
            f'<rect x="{cx + 2:.1f}" y="{330 - h0:.1f}" width="{w:.1f}" height="{h0:.1f}" fill="#3a3c3f"/>'
            f'<text x="{cx:.1f}" y="{322 - h1:.1f}" fill="#f2f1ed" font-family="Martian Mono, monospace" '
            f'font-size="11" text-anchor="middle">{r.best.total:.0f}</text>'
            f'<text x="{cx:.1f}" y="350" fill="#8d8e8b" font-family="Martian Mono, monospace" font-size="9" '
            f'letter-spacing="1" text-anchor="middle">{_e(label)}</text>')
    yards = "".join(f'<line x1="{150 + 34 * k}" y1="70" x2="{20 + 60 * k}" y2="330"/>' for k in range(1, 10))
    field = (
        '<div class="field" role="img" aria-label="Projected points per league: orange with ffman\'s moves, grey as set">'
        '<span class="bracket tl"></span><span class="bracket tr"></span><span class="bracket bl"></span><span class="bracket br"></span>'
        '<svg viewBox="0 0 640 360" aria-hidden="true"><defs><linearGradient id="turfg" x1="0" x2="0" y1="0" y2="1">'
        '<stop offset="0" stop-color="#0b0c0d"/><stop offset="1" stop-color="#121315"/></linearGradient></defs>'
        '<polygon points="150,70 490,70 620,330 20,330" fill="url(#turfg)" stroke="#2e3032"/>'
        f'<g stroke="#1e1f21">{yards}</g><line x1="20" y1="330" x2="620" y2="330" stroke="#2e3032"/>'
        f'{"".join(bars)}</svg></div>')

    seg_on = min(sources, 7)
    segs = "".join(f'<i class="{"on" if k < seg_on else ""}"></i>' for k in range(7))
    idea_on = min(ideas, 7)
    idea_segs = "".join(f'<i class="{"on" if k < idea_on else ""}"></i>' for k in range(7))
    if first:
        local = first.astimezone()
        first_html = f'{local:%a} {local.hour % 12 or 12}:{local:%M}<small>{local:%p}</small>'
    else:
        first_html = "All set"
    leagues_pct = set_count / n * 100

    schedule = ""
    if next_updates:
        items = "".join(f"<li>{_e(fmt_time(t))}</li>" for t in next_updates)
        now = (f' <a href="{_e(run_url)}" target="_blank" rel="noopener">Update now</a> (GitHub, Run workflow).'
               if run_url else "")
        schedule = (f'<details><summary>Next update ~{_e(fmt_time(next_updates[0]))}</summary>'
                    f'<div class="schedule"><ul>{items}</ul><p>Every morning around 9 AM, Tuesday night before waivers, '
                    f'every 30 minutes on Sundays and before Thursday and Monday night games. GitHub sometimes '
                    f'starts a few minutes late.{now}</p></div></details>')

    return (
        '<header class="hero"><div class="wrap">'
        f'<div class="kicker mono dim">Week {week or "–"} <span class="sig">/</span> {len(reports)} '
        f'league{"s" if len(reports) != 1 else ""} <span class="sig">/</span> {_e(" + ".join(platforms) or "No leagues")}</div>'
        f'<h1>{title}</h1>'
        '<div class="stage"><div class="hud">'
        f'<div><div class="mono dim">Points on the table</div><div class="big">+{gain:.1f}<small>PTS</small></div></div>'
        f'<div class="meter"><div class="row mono dim"><span>Moves</span><span>{moves}</span></div>'
        f'<div class="bar"><i style="width:{100 if moves else 0}%"></i></div></div>'
        f'<div class="meter"><div class="row mono dim"><span>Leagues set</span><span>{set_count} / {len(reports)}</span></div>'
        f'<div class="bar"><i style="width:{leagues_pct:.0f}%"></i></div></div>'
        f'</div>{field}<div class="hud">'
        f'<div><div class="mono dim">First deadline</div><div class="big sm">{first_html}</div></div>'
        f'<div class="meter"><div class="row mono dim"><span>Sources</span><span>{sources}</span></div><div class="segs">{segs}</div></div>'
        f'<div class="meter"><div class="row mono dim"><span>Waiver ideas</span><span>{ideas}</span></div><div class="segs">{idea_segs}</div></div>'
        '</div></div>'
        f'<div class="under mono dim"><span>Updated {_e(_when(generated))}</span>{schedule}</div>'
        '</div></header>')


def _ticker(reports: list[LeagueReport]) -> str:
    plan = game_plan(reports)
    items = [f"{m.player.name} +{m.gain:.1f}" for _, m in plan.moves]
    items += [f"Add {w.add.name}" for _, w in plan.waivers]
    if not items:
        items = ["All lineups set", "Check back before kickoff"]
    spans = "".join(f'<span class="{"fade" if i % 3 == 1 else ""}">{_e(t)}</span><span class="sep">&bull;</span>'
                    for i, t in enumerate(items))
    return f'<div class="ticker" aria-hidden="true"><div class="track">{spans}{spans}</div></div>'


def _plan(reports: list[LeagueReport]) -> str:
    plan = game_plan(reports)
    rows = []
    current = None
    for r, m in plan.moves:
        label = deadline_label(m.deadline)
        if label != current:
            first_game = _game(m.player) if m.player.kickoff == m.deadline else (_game(m.benched) if m.benched else "")
            rows.append(f'<div class="when"><span class="mono t">{_e(label)}</span>'
                        f'<span class="mono dim">{_e(first_game)}</span></div>')
            current = label
        p, b = m.player, m.benched
        done_id = f"{r.team.league_name}|{p.id}|{b.id if b else ''}"
        why = _why_out(b, p)
        game = _game(p)
        detail = f"{why}. {p.name} {p.effective_projection:.1f}{', ' + game if game else ''}"
        rows.append(
            f'<div class="move"><input type="checkbox" data-done="{_e(done_id)}" aria-label="Mark done: start {_e(p.name)}">'
            f'<div><div class="mono dim">{_e(r.team.league_name)}</div>'
            f'<div class="what">Start {_e(p.name)} <s>{"for " + _e(b.name) if b else "in the empty slot"}</s></div></div>'
            f'<div class="why">{_e(detail)}</div>'
            f'<div class="gain{" close" if m.close_call else ""}">+{m.gain:.1f}<small>{"close call" if m.close_call else "pts"}</small></div></div>')
    for r, a in plan.pickups + plan.watch:
        cls = "watch" if a.level == "warn" else ""
        rows.append(f'<div class="move alert {cls}"><span class="dot"></span>'
                    f'<div><div class="mono dim">{_e(r.team.league_name)}</div><div class="why">{_e(a.text)}</div></div></div>')
    if not rows:
        body = '<div class="move alert"><span class="dot" style="background:var(--signal)"></span><div class="why">Every lineup is already set. Nothing to change right now.</div></div>'
    else:
        body = "".join(rows)
    allset = ""
    if plan.all_set and plan.moves:
        allset = f'<p class="allset"><b>Already set:</b> {_e(", ".join(r.team.league_name for r in plan.all_set))}</p>'
    return (
        '<section class="s" aria-labelledby="plan-h"><div class="wrap">'
        '<div class="eyebrow mono"><span class="num">01</span><span class="l dim">Game plan</span></div>'
        '<div class="head"><h2 id="plan-h">Every move,<br>by kickoff.</h2>'
        '<p>Moves across all your leagues, soonest deadline first. Tick them off as you make them; '
        'nothing is ever changed for you.</p></div>'
        f'<div class="plan">{body}</div>{allset}</div></section>')


def _waivers(reports: list[LeagueReport]) -> str:
    plan = game_plan(reports)
    if not plan.waivers:
        cards = '<article><p>No pickups clear the bar right now. Your benches are covered.</p></article>'
    else:
        cards = []
        for i, (r, w) in enumerate(plan.waivers):
            add = w.add
            this_week = w.week_gain >= 2
            value, unit = (w.week_gain, "this wk") if this_week else (w.two_week_gain, "2 wks")
            facts = [f"{add.effective_projection:.1f} this week, {add.next_projection:.1f} next"]
            if add.trending:
                facts.append(f"{add.trending:,} adds in 24h")
            if add.owned_pct is not None:
                facts.append(f"{add.owned_pct:.0f}% rostered")
            if r.team.waiver_note:
                facts.append(r.team.waiver_note)
            extra = ""
            if w.tough:
                extra += f" Tough call: {w.tough}."
            if w.after:
                extra += f" After adding {', '.join(x.name for x in w.after)}."
            meta = add.position + (f", {add.team}" if add.team else "")
            cards.append(
                f'<article class="{"tough" if w.tough else ""}"><svg viewBox="0 0 24 24" aria-hidden="true">{ICONS[i % len(ICONS)]}</svg>'
                f'<span class="mono dim">{_e(r.team.league_name)}</span>'
                f'<h3>Add {_e(add.name)} <span>({_e(meta)})</span></h3>'
                f'<p>{"Drop " + _e(w.drop.name) + ". " if w.drop else ""}{_e(". ".join(facts))}.{_e(extra)}</p>'
                f'<div class="v">+{value:.1f}<small>{unit}</small></div></article>')
        cards = "".join(cards)
    return (
        '<section class="s" aria-labelledby="wv-h"><div class="wrap">'
        '<div class="eyebrow mono"><span class="num">02</span><span class="l dim">Waivers</span></div>'
        '<div class="head"><h2 id="wv-h">Pickups worth<br>a roster spot.</h2>'
        '<p>Judged on this week and next, so a one-week fluke never wins. Highly ranked players are never '
        'suggested as drops.</p></div>'
        f'<div class="feat">{cards}</div></div></section>')


# ------------------------------------------------------------------------------ Recap

def _chart(weeks: list[WeekRecap]) -> str:
    W, H, L, R, T, B = 560, 260, 42, 14, 16, 34
    vals = [v for w in weeks for v in (w.actual, w.ffman, w.perfect)]
    lo = int((min(vals) - 10) // 20 * 20)
    hi = int(-(-(max(vals) + 5) // 20) * 20)
    span = max(len(weeks) - 1, 1)

    def x(i):
        return L + (W - L - R) * (i / span) if len(weeks) > 1 else (L + W - R) / 2

    def y(v):
        return T + (H - T - B) * (1 - (v - lo) / (hi - lo))

    out = []
    for v in range(lo, hi + 1, 20):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#1d1e20"/>'
                   f'<text x="{L - 8}" y="{y(v) + 3.5:.1f}" fill="#55575a" font-family="Martian Mono, monospace" '
                   f'font-size="9.5" text-anchor="end">{v}</text>')
    for i, w in enumerate(weeks):
        out.append(f'<text x="{x(i):.1f}" y="{H - 12}" fill="#8d8e8b" font-family="Martian Mono, monospace" '
                   f'font-size="9.5" letter-spacing="1" text-anchor="middle">WK {w.week}</text>')

    def path(attr):
        return " ".join(f'{"L" if i else "M"}{x(i):.1f},{y(getattr(w, attr)):.1f}' for i, w in enumerate(weeks))

    area = path("ffman") + f" L{x(len(weeks) - 1):.1f},{y(lo):.1f} L{x(0):.1f},{y(lo):.1f} Z"
    out.append(f'<path d="{area}" fill="#ff5a1f" fill-opacity=".14"/>')
    out.append(f'<path d="{path("perfect")}" fill="none" stroke="#55575a" stroke-width="1.2" stroke-dasharray="4 4"/>')
    out.append(f'<path d="{path("actual")}" fill="none" stroke="#8d8e8b" stroke-width="1.6"/>')
    out.append(f'<path d="{path("ffman")}" fill="none" stroke="#ff5a1f" stroke-width="2"/>')
    for i, w in enumerate(weeks):
        out.append(f'<circle cx="{x(i):.1f}" cy="{y(w.ffman):.1f}" r="3.5" fill="#ff5a1f"/>'
                   f'<circle cx="{x(i):.1f}" cy="{y(w.actual):.1f}" r="3" fill="#8d8e8b"/>')
    return f'<svg viewBox="0 0 {W} {H}" aria-hidden="true">{"".join(out)}</svg>'


def _sheet(league: str, weeks: list[WeekRecap]) -> str:
    rows = []
    for w in weeks:
        res = f"{w.result} {w.actual:.1f}–{w.opponent:.1f}" if w.result else f"{w.actual:.1f}"
        flip = f' <span class="sig">&rarr; {w.ffman_result} with ffman</span>' if w.flipped else ""
        cls = "up" if w.gain > 0 else "down" if w.gain < 0 else ""
        rows.append(f'<div class="r"><span>Wk {w.week} · {_e(res)}{flip}</span><span class="{cls}">{w.gain:+.1f}</span></div>')
    total = sum(w.gain for w in weeks)
    rows.append(f'<div class="r"><span>Season, ffman vs you</span><span class="{"up" if total >= 0 else "down"}">'
                f'<b>{total:+.1f}</b></span></div>')
    return f'<h4 class="mono"><span class="sig">{_e(league)}</span> <span class="dim">/ week by week</span></h4>{"".join(rows)}'


def _verdict(w: WeekRecap) -> str:
    if not w.swaps:
        text = "You started ffman's lineup."
    elif abs(w.gain) < 0.05:
        text = "ffman's changes would have broken even."
    elif w.gain > 0:
        text = f'ffman\'s lineup would have scored <span class="up">+{w.gain:.1f}</span> more.'
    else:
        text = f'Your lineup beat ffman\'s by <span class="up">{-w.gain:.1f}</span>.'
    res = ""
    if w.result:
        res = f' <span class="result {w.result}">{w.result} {w.actual:.1f}–{w.opponent:.1f}</span>'
        if w.flipped:
            res += f' &rarr; <span class="result {w.ffman_result}">{w.ffman_result} with ffman</span>'
    swaps = ""
    if w.swaps:
        items = "".join(
            f"<li>{_e(s.start.name)} ({s.start.actual or 0:.1f}) over "
            f"{_e(s.sit.name) if s.sit else 'an empty slot'} ({(s.sit.actual or 0) if s.sit else 0:.1f}): "
            f'<span class="{"up" if s.delta >= 0 else "down"}">{s.delta:+.1f}</span></li>' for s in w.swaps)
        swaps = f'<details class="more"><summary>What ffman would have changed</summary><ul>{items}</ul></details>'
    return (f'<div class="item"><span class="mono dim">{_e(w.league_name)}</span>'
            f'<div class="verdict">{text}{res}</div>{swaps}</div>')


def _recap(recap: SeasonRecap | None) -> str:
    head = ('<div class="eyebrow mono"><span class="num">01</span><span class="l dim">Recap</span></div>'
            '<div class="head"><h2 id="rc-h">Every week,<br>on one page.</h2>'
            '<p>Your real score next to what ffman\'s lineup would have scored and the best lineup in hindsight. '
            'ffman\'s lineup is rebuilt from each week\'s final pre-game projections.</p></div>')
    if not recap or not recap.weeks:
        return (f'<section class="s" aria-labelledby="rc-h"><div class="wrap">{head}'
                '<p class="empty">The recap appears once a week of games is finished.</p></div></section>')
    by_league = recap.by_league()
    weeks_n = len({w.week for w in recap.weeks})
    gain = recap.gain
    specs = ('<div class="specs">'
             f'<div><span class="mono dim">Following ffman</span><b class="{"" if gain >= 0 else "down"}">{gain:+.1f}<small>PTS</small></b></div>'
             f'<div><span class="mono dim">Losses it would have won</span><b>{recap.flips_to_wins}</b></div>'
             f'<div><span class="mono dim">Wins it would have lost</span><b>{recap.flips_to_losses}</b></div>'
             f'<div><span class="mono dim">League-weeks checked</span><b>{len(recap.weeks)}</b></div></div>')
    names = list(by_league)
    buttons = "".join(
        f'<button type="button" aria-pressed="{"true" if i == 0 else "false"}" data-target="rc{i}">{_e(n)}</button>'
        for i, n in enumerate(names))
    charts = "".join(f'<div data-pane="rc{i}"{"" if i == 0 else " hidden"}>{_chart(by_league[n])}</div>'
                     for i, n in enumerate(names))
    sheets = "".join(f'<div class="sheet" data-pane="rc{i}"{"" if i == 0 else " hidden"}>{_sheet(n, by_league[n])}</div>'
                     for i, n in enumerate(names))
    latest = recap.latest()
    last_week = latest[0].week if latest else ""
    return (
        f'<section class="s" aria-labelledby="rc-h"><div class="wrap">{head}{specs}'
        '<div class="recapgrid"><div class="chart"><div class="ct"><span class="mono dim">Points by week</span>'
        f'<div class="segbtns" role="group" aria-label="League">{buttons}</div></div>{charts}'
        '<div class="legend mono dim"><span><i></i>You</span><span><i class="ff"></i>ffman</span>'
        f'<span><i class="best"></i>Best possible</span></div></div><div>{sheets}</div></div>'
        f'<div class="eyebrow mono" style="margin-top:56px"><span class="num">02</span><span class="l dim">Week {last_week}</span></div>'
        f'<div class="latest">{"".join(_verdict(w) for w in sorted(latest, key=lambda w: -abs(w.gain)))}</div>'
        f'<p class="footnote">{weeks_n} week{"s" if weeks_n != 1 else ""} so far. Projections may differ slightly '
        'from what the page showed at the time.</p></div></section>')


# ------------------------------------------------------------------------------ Leagues

def _league_card(r: LeagueReport, pane: str) -> str:
    t = r.team
    replaces = {m.player.id: m.benched for m in r.start}
    rows = []
    for slot, p in zip(r.best.slots, r.best.players):
        label = SLOT_LABEL.get(slot, slot)
        if p is None:
            rows.append(f'<tr><td class="slot">{_e(label)}</td><td class="p">Empty</td><td class="n">–</td></tr>')
            continue
        lock = '<span class="tag">LOCKED</span>' if p.locked else ""
        game = _game(p)
        was = ""
        if p.id in replaces:
            b = replaces[p.id]
            was = f'<span class="was">In for {_e(b.name) if b else "an empty slot"}</span>'
        cls = ' class="new"' if p.id in replaces else ""
        rows.append(
            f'<tr{cls}><td class="slot">{_e(label)}</td>'
            f'<td class="p">{_e(p.name)}{_status_tag(p)}{lock}'
            f'<span class="m">{_e(p.position)}{" · " + _e(p.team) if p.team else ""}{" · " + _e(game) if game else ""}</span>'
            f'{was}{_sources(p)}</td>'
            f'<td class="n">{p.effective_projection:.1f}</td></tr>')
    note = f'<div class="lgnote">{_e(t.waiver_note)}</div>' if t.waiver_note else ""
    state = (f"{len(r.start)} move{'s' if len(r.start) != 1 else ''}" if r.needs_changes else "Set")
    return (
        f'<div class="card" data-pane="{pane}" role="tabpanel">'
        f'<div class="ch"><span class="mono dim">{_e(t.league_name)} · {_e(t.platform)}</span>'
        f'<span class="mono sig">Best lineup / {_e(state)}</span></div>'
        f'<div class="tablewrap"><table class="lu">{"".join(rows)}</table></div>'
        f'<div class="nums"><div><span class="mono dim">As set</span><b>{t.current.total:.1f}<small>PTS</small></b></div>'
        f'<div><span class="mono dim">Best</span><b>{r.best.total:.1f}<small>PTS</small></b></div>'
        f'<div><span class="mono dim">Gain</span><b class="sig">+{max(r.gain, 0):.1f}</b></div></div>{note}</div>')


def _leagues(reports: list[LeagueReport]) -> str:
    head = ('<div class="eyebrow mono"><span class="num">01</span><span class="l dim">Leagues</span></div>'
            f'<div class="head"><h2 id="lg-h">{len(reports)} league{"s" if len(reports) != 1 else ""}.<br>One lineup each.</h2>'
            '<p>Pick a league to see its best lineup. New starters are marked IN; tap a projection range '
            'to see every source\'s number.</p></div>')
    if not reports:
        return (f'<section class="s" aria-labelledby="lg-h"><div class="wrap">{head}'
                '<p class="empty">No leagues found. Check your config.</p></div></section>')
    buttons, cards = [], []
    for i, r in enumerate(reports):
        pane = _slug(r.team.league_name, i)
        n_in = len(r.start) if r.needs_changes else 0
        sub = " · ".join(x for x in (r.team.platform, r.team.team_name, r.team.waiver_note) if x)
        buttons.append(
            f'<button role="tab" aria-selected="{"true" if i == 0 else "false"}" data-target="{pane}">'
            f'<span class="mono dim">{i + 1:02d}</span><span class="nm">{_e(r.team.league_name)}</span>'
            f'<span class="mono st">{f"{n_in} in" if n_in else "set"}</span><span class="sub">{_e(sub)}</span></button>')
        card = _league_card(r, pane)
        if i:
            card = card.replace('role="tabpanel">', 'role="tabpanel" hidden>', 1)
        cards.append(card)
    return (f'<section class="s" aria-labelledby="lg-h"><div class="wrap">{head}'
            f'<div class="lgwrap"><div class="modes" role="tablist" aria-label="Leagues">{"".join(buttons)}</div>'
            f'<div>{"".join(cards)}</div></div></div></section>')


# ------------------------------------------------------------------------------ Page

def _stale(next_updates: list[dt.datetime], run_url: str | None) -> str:
    if not next_updates:
        return ""
    due = int(next_updates[0].timestamp() * 1000)
    link = f' or <a href="{_e(run_url)}" target="_blank" rel="noopener">update it now</a>' if run_url else ""
    return (f'<div class="wrap"><div class="notice" id="stale" hidden>This page was due to update at '
            f'{_e(fmt_time(next_updates[0]))} and hasn\'t yet, so it may be out of date. '
            f'Check back in a few minutes{link}.</div></div>'
            f'<script>(function(){{if(Date.now()>{due}+45*60*1000){{'
            'var el=document.getElementById("stale");if(el)el.hidden=false;}})();</script>')


def render_dashboard(reports: list[LeagueReport], week: int | None, errors: list[str],
                     generated: dt.datetime | None = None, week_picker: bool = False,
                     logout: bool = False, next_updates: list[dt.datetime] | None = None,
                     run_url: str | None = None, recap: SeasonRecap | None = None,
                     sources_note: str | None = None) -> str:
    """The page body: <title>, styles and content (no <html>/<body> wrapper)."""
    generated = generated or dt.datetime.now().astimezone()
    next_updates = next_updates or []
    ordered = sorted(reports, key=lambda r: (not r.needs_changes, -r.gain))
    plan = game_plan(ordered)
    todo = len(plan.moves) + len(plan.waivers)

    right = []
    if week_picker:
        options = "".join(f'<option value="{w}"{" selected" if w == week else ""}>Week {w}</option>'
                          for w in range(1, 19))
        right.append('<form class="weekform" method="get"><label for="week" hidden>Week</label>'
                     f'<select id="week" name="week">{options}</select><button type="submit">Go</button></form>')
    right.append(f'<span class="pill mono"><span class="dot"></span>{len(plan.moves)} move'
                 f'{"s" if len(plan.moves) != 1 else ""}</span>')
    if logout:
        right.append(LOCK_BUTTON)

    out = ["<title>ffman Lineups</title>", STYLE,
           '<nav class="top" aria-label="Main"><div class="wrap">'
           f'<a class="logo" href="#week" aria-label="ffman">{LOGO}FFMAN</a>'
           '<div class="tabs" role="tablist" aria-label="Sections">'
           f'<button type="button" role="tab" data-tab="week" aria-selected="true">This week'
           f'{f"<span class=n>{todo}</span>" if todo else ""}</button>'
           '<button type="button" role="tab" data-tab="recap" aria-selected="false">Recap</button>'
           f'<button type="button" role="tab" data-tab="leagues" aria-selected="false">Leagues<span class="n">{len(ordered)}</span></button>'
           f'</div><div class="right">{"".join(right)}</div></div></nav>',
           _stale(next_updates, run_url)]
    if errors:
        out.append('<div class="wrap"><div class="notice bad">Some data couldn\'t be loaded:<ul>'
                   + "".join(f"<li>{_e(e)}</li>" for e in errors) + "</ul></div></div>")

    out.append('<main>')
    out.append('<div id="week" role="tabpanel">'
               + _hero(ordered, week, generated, next_updates, run_url)
               + _ticker(ordered) + _plan(ordered) + _waivers(ordered) + '</div>')
    out.append(f'<div id="recap" role="tabpanel">{_recap(recap)}</div>')
    out.append(f'<div id="leagues" role="tabpanel">{_leagues(ordered)}</div>')
    out.append('</main>')

    sources = (_e(sources_note) if sources_note else
               "Projections from Sleeper (scored with each league's settings) and ESPN.")
    out.append(
        '<footer><div class="wrap"><div class="cols">'
        f'<div><span class="logo">{LOGO}FFMAN</span><p>A read-only lineup advisor for your Sleeper and ESPN '
        'leagues. It recommends; you make the moves.</p></div>'
        '<div><span class="mono dim">Updates</span><ul><li>Daily ~9 AM</li><li>Tue ~9 PM, before waivers</li>'
        '<li>Sun every 30 min</li><li>Thu &amp; Mon before kickoff</li></ul></div>'
        f'<div><span class="mono dim">Data</span><ul><li>{sources}</li><li>Game times from ESPN, shown in '
        f'{_e(generated.strftime("%Z") or "local time")}</li><li>Check injury news before kickoff</li></ul></div></div>'
        '<div class="wordmark" aria-hidden="true">FFMAN</div>'
        f'<div class="legal mono dim"><span>Updated {_e(_when(generated))}</span>'
        '<span>Suggestions only</span><a href="#week">Back to top</a></div></div></footer>')
    out.append(f'<script>document.body.dataset.week="{week or ""}";</script>' + SCRIPT)
    return "\n".join(out)


def full_page(body: str, week: int | None = None) -> str:
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            '<meta name="theme-color" content="#050607">'
            f"</head><body>{body}</body></html>")


def serve(build, host: str = "127.0.0.1", port: int = 8000, cache_seconds: int = 300) -> None:
    """Run the local website. `build(week)` returns (reports, week, errors, recap, sources note)."""
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
                reports, shown, errors, recap, note = build(week)
                page = full_page(render_dashboard(reports, shown, errors, week_picker=True, recap=recap,
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
