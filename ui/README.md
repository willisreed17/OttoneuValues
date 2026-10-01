# Web app

From the repo root: `py -3.13 ui/app.py`, then open http://localhost:8000.
Stdlib only. It serves `ui/web/` and reads `engine/out/players.csv`,
`engine/out/teams.csv` and `engine/data/league.csv` (league 1297, no login), plus
`engine/out/next/players.csv` when `engine/next_season.py` has written it. That file is
optional: without it Keepers and Auction use this season. It also reads
`engine/data/average_values.csv` (Market $ on Auction and in the drawer; optional).
Auction's **Re-price** button (`POST /api/reprice`) reruns `value.py`, then
`next_season.py` if `out/next/` exists, on whatever `engine/data/` holds. It runs the
engine and never edits it. It never changes the engine.
If the page says "Could not load data", check for a second, older `app.py` on port
8000 (`netstat -ano | findstr :8000`): Windows lets both bind the port. After rerunning `value.py` (from inside `engine/`),
reload the page.

**Update from Ottoneu** (header button, `POST /api/update`). `app.py` pulls from
Ottoneu directly, about 15 plain requests and ~20 s, no login needed. It takes the team
list from `/api/league?leagueID=1297&output=xml`, then each team page (the README
`teams_cap.csv` patterns), `/1297/rosterexport?csv=1`, and
`/averageValues?export=csv&gameType=5`. It checks the headers and row counts, that loans
in equal loans out, and that team ids match the roster export. Any failure means nothing
is written. Otherwise it backs up the old files to `engine/data/backup/<timestamp>/`
(gitignored), writes the new ones, reruns the engine like Re-price, and the page reloads.
The league id and market game type are constants at the top of `app.py`.

Built: a board home, Rankings, Keepers, Auction, Trades (comparison only, no verdict), player drawer, Update from Ottoneu.
Lineup is a placeholder. A header switch splits the site into **Pre-draft** (Keepers, Auction,
Rankings, Trades on next-season values) and **Post-draft** (Rankings, Trades, Lineup on this-season
values). It is manual and remembered per browser; flip it after your auction. Roadmap: `UI_FUTURE_DEV.md`. Design rules: the UI agent,
`.claude/agents/ui-agent.md`.
