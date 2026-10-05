# ffman: fantasy football manager

ffman keeps an eye on all of your fantasy football leagues and tells you who to start.
**It never changes your lineups.** It only reads your leagues and recommends.

For each league it:

1. Pulls your roster, the league's lineup slots and its scoring settings.
2. Gets this week's projections. On Sleeper these are scored with *your league's* rules
   (PPR, TE premium and so on). On ESPN it uses ESPN's own league-scored projections.
3. Works out the best possible legal lineup. This handles FLEX, SUPERFLEX, WR/TE and RB/WR
   flex slots and IDP. Players listed **Out**/IR count as 0 points and **Doubtful** players
   are discounted.
4. Tells you what to change and flags anything to watch, such as Questionable starters,
   starters projected for 0 (bye weeks) and slots nobody on your roster can fill.

Supported: **Sleeper** (finds every league for your username) and **ESPN** (public or private leagues).

## Example output

```
# Lineup recommendations - Week 5

**2 of 2 leagues have changes to make.** Nothing has been changed for you - these are suggestions only.

## Dynasty Bros (Sleeper) - Tony's Team
Projected **51.4 -> 65.9** (+14.5) if you make these moves:
- START Bijan Robinson (RB, ATL) 14.5 over Christian McCaffrey (RB, SF) [Out] 0.0

## Work league (ESPN) - Big Dogs
Projected **45.7 -> 54.5** (+8.8) if you make these moves:
- START Kareem Hunt (RB, KC) 9.8 over Isiah Pacheco (RB, KC) [Doubtful] 1.0

- Heads up: Xavier Worthy (WR, KC) is Questionable - check news before kickoff.
```

Each league also includes a table showing the full best lineup.

## Setup

You need Python 3.11 or newer. There are no other dependencies.

```bash
pip install .            # or skip this and use `python -m ffman` from this folder
ffman init               # writes ~/.config/ffman/config.toml
```

Edit the config. ffman uses `./config.toml` in the folder you run it from if there is one,
otherwise `~/.config/ffman/config.toml`. Leave cookies out of it, because a `config.toml`
in the repo gets committed:

- **Sleeper:** enter your username. Every league you're in this season is checked.
- **ESPN:** add one `[[espn]]` block per league with its `league_id` and your `team_id`,
  both of which appear in the URL of your team page. **Private** ESPN leagues also need
  two browser cookies. Log in at espn.com, open DevTools → Application → Cookies, and copy
  `espn_s2` and `SWID`. Put them in environment variables with those same names
  (`ESPN_S2` / `ESPN_SWID` also work) rather than in the file.

Then run:

```bash
ffman                    # check every league for the current week
ffman --week 6           # a specific week
ffman --league work      # only leagues whose name contains "work"
ffman --output report.md # also save the report
ffman --notify           # also send a summary to your phone or Discord
```

## The website

ffman also has a dashboard page. It shows every league as a card, with leagues that need
moves listed first. Each card shows START/SIT pairs and the points each move gains, flags for
bye weeks and injuries, and the full best lineup.

```bash
ffman serve                    # open http://127.0.0.1:8000
ffman serve --host 0.0.0.0     # also reachable from your phone on the same Wi-Fi
ffman --html lineups.html      # save a one-off copy of the page instead
```

`ffman serve` pulls fresh data when you load the page. It reuses results for up to 5 minutes
so refreshing doesn't flood the APIs. The week picker in the top corner switches weeks.

### Tuning

`min_gain` under `[settings]` (default 0.5) is the smallest projected improvement worth
telling you about. It stops coin-flip swaps from cluttering the report.

## GitHub website

GitHub can host the dashboard for free at `https://<your-username>.github.io/ffman/` and keep
it fresh. The `Website` workflow rebuilds it every morning, on Thursday before TNF, and twice
on Sunday (after inactives and before the late games).

One-time setup:

1. **Settings → Pages → Build and deployment → Source:** choose **GitHub Actions**.
2. **Settings → Secrets and variables → Actions → New repository secret.** Add these only for
   private ESPN leagues:
   - `ESPN_S2`: your espn_s2 cookie
   - `ESPN_SWID`: your SWID cookie, including the `{ }`
3. **Actions → Website → Run workflow** builds it the first time. After that it runs on its own.

Leagues come from `config.toml` in the repo. To keep them out of a public repo, add an
`FFMAN_CONFIG` secret containing the whole config instead. The site itself is public: anyone
with the link can see your rosters and recommendations, but never your cookies.

For phone alerts on the Thursday and Sunday runs, install the free [ntfy](https://ntfy.sh)
app, subscribe to a topic name that's hard to guess, and set `ntfy_topic` under `[notify]`.
For Discord, add a `DISCORD_WEBHOOK` secret and set `discord_webhook = "env:DISCORD_WEBHOOK"`.

## Notes and limits

- Projections are estimates. Always check late injury news before kickoff.
- Sleeper's projections endpoint is public but undocumented, so it could change. (Verified against live data for the 2026 season: scoring matches Sleeper's own PPR totals within rounding.)
- ESPN cookies expire every few months. If a private league starts failing, copy fresh ones.
- Yahoo isn't supported yet because it requires registering an OAuth app.

## Development

```bash
python -m unittest -v
```
