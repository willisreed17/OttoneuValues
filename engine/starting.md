# Ottoneu Player Valuation App

## Goal

Build a tool that calculates real player values for Ottoneu fantasy baseball leagues, improving on existing tools (e.g. OttoValues) by accounting for league-specific context that pure projection-based valuations ignore:

- Which players are already kept/rostered and at what salary
- How much cap space each team actually has available to spend
- Resulting surplus value (projected value vs. actual cost) per player and per team

Phase 1 is for personal use in my own Ottoneu league(s). If the approach works, phase 2 is to generalize it into an app other Ottoneu players can use with their own league ID.

## Data Sources

### Ottoneu (no official API, but stable unauthenticated CSV/XML export endpoints)

- Roster export (players, salaries, positions, per team): `https://ottoneu.fangraphs.com/{leagueID}/rosterexport?csv=1`
  - Columns: TeamID, Team Name, ottoneu ID, FG MajorLeagueID, FG MinorLeagueID, Name, MLB Team, Position(s), Salary
- Standings: `https://ottoneu.fangraphs.com/{leagueID}/standings`
- League-wide average auction values across all OPL leagues (by position/scoring format): `https://ottoneu.fangraphs.com/averageValues?gameType={N}&export=csv`
- Free agents are derived, not a direct export: full player universe minus whoever is rostered.

Etiquette: no official API — cache responses, pull on a schedule (e.g. daily), don't poll. Ottoneu has said they'll rate-limit/IP-block excessive automated requests.

### FanGraphs (also no official public API, but a working unauthenticated JSON endpoint powers their own projections page)

- Batters: `https://www.fangraphs.com/api/projections?pos=all&stats=bat&type={system}`
- Pitchers: `https://www.fangraphs.com/api/projections?pos=all&stats=pit&type={system}`
- `{system}` = projection system, e.g. `steamer`, `zips`, `atc`, `thebat`, `thebatx`, or FanGraphs' blended Depth Charts projections (confirm exact string by watching the dropdown on fangraphs.com/projections).
- Returns JSON arrays of player objects. Batters include AVG/OBP/SLG/wOBA/wRC+/WAR/fantasy points; pitchers include ERA/WHIP/K-9/FIP/WAR/SV/HLD/QS, etc.

Caveat: FanGraphs' Terms of Service prohibit accessing the service by means other than their provided interface and restrict redistributing site content. Fine for personal use / small-scale tools (this is how existing community projects like pybaseball, baseballr, and OttoValues operate), but before any public release to other users, reach out to FanGraphs for permission since Ottoneu is a FanGraphs product.

## The Key Join

Ottoneu's roster export includes `FG MajorLeagueID` / `FG MinorLeagueID` for each player — this is the same ID as the `playerid` field in the FanGraphs projections JSON. Join on this ID rather than player name (names differ across sources, e.g. "Nate Lowe" vs "Nathaniel Lowe").

## Core Calculation

1. Pull current rosters + salaries for the target league (`rosterexport`).
2. Pull projections for the chosen system(s) and scoring format (points or roto).
3. Join projections to rostered/free-agent players via FanGraphs player ID.
4. Compute a projected dollar value per player (replacement-level z-score method, similar to OttoValues' approach, is a reasonable starting point).
5. **New piece OttoValues doesn't do:** compute surplus value = projected value − actual salary, for every kept/rostered player, and compute each team's remaining cap space (league cap minus sum of current salaries).
6. Surface: best keeper values, worst (cut candidates), and effective "buying power" per team heading into an auction/draft.

## Open Questions / Decisions Still Needed

- Which league(s) — need Ottoneu league ID(s).
- Scoring format: points vs. 4x4/5x5 roto (affects which averageValues gameType and valuation formula to use).
- Which projection system(s) to support (single system vs. blended).
- Output/interface: script + spreadsheet output first, or a proper app UI from the start.
- Refresh cadence (daily during the season is reasonable).
- Longer-term: multi-league support and public distribution, gated on FanGraphs permission.
