# Ottoneu Values

Two stdlib-only scripts (no pandas — your default Python 3.15 is an alpha with no
wheels for it; these run on 3.13 via `py -3.13`).

- **`value.py`** — prices every player in two layers, writes per-player value and
  surplus plus a per-team cap ledger.
- **`backtest.py`** — scores a projection snapshot against what actually
  happened, so changes to the valuation logic get measured rather than argued.
- **`marcel.py`** — builds Marcel projections from MLB statsapi for ten seasons,
  so pricing changes are scored on ten samples instead of the one FanGraphs
  snapshot we happen to have. Deliberately a worse projection than Steamer; it
  tests pricing *shape*, not projection quality, so compare Marcel years to each
  other and never to the Steamer run. Caches to `data/mlb/` (77MB, gitignored).

```
py -3.13 value.py            # FGPts
py -3.13 value.py --sabr     # SABR points
py -3.13 value.py --selftest

py -3.13 backtest.py --start 2025-05-24 --end 2025-09-30   # scores Steamer (the floor)
py -3.13 backtest.py --dollars                            # scores value.py's pricing
py -3.13 backtest.py --selftest

py -3.13 marcel.py                # ten seasons of Marcel -> out/backtest_YYYY.csv
py -3.13 backtest.py --dollars --backtest out/backtest_2024.csv
```

`--dollars` reads `out/backtest.csv` and needs no network. It prices the
projection side with `value.py`'s layer 1 and reports realized points above
replacement per dollar, by price tier and by decile. Flat = pricing is right.
Read the curvature table in `NEXT_STEPS.md` Task 1 before interpreting the
shape — the obvious reading of the direction is backwards.

Outputs `out/players.csv`, `out/teams.csv`, `out/backtest.csv`.

## League settings

Everything that varies between Ottoneu points leagues lives in `data/league.csv`
as `key,value` rows — **point the tool at a different league by editing that one
file.** Delete it and the Ottoneu standard defaults apply. An unknown key is
reported rather than silently ignored.

| key | default | notes |
|---|---|---|
| `teams` | `0` | 0 = infer from the roster export |
| `format` | `h2h` | `season` warns: season-long is governed by a team innings cap, not a weekly GS cap, and pitcher values would be wrong |
| `scoring` | `FPTS` | or `SPTS`; `--sabr` overrides |
| `cap` | `400` | base salary cap per team |
| `roster_max` | `40` | the cap-relevant limit, not the number a team page shows in-season |
| `catcher_slots` | `1` | **pull per league.** H2H is commonly 1, some formats require 2; doubling C depth moves catcher values more than any other lineup change |
| `games_cap` | `0` | **pull per league.** Seasonal games per position player (162 standard, 810 across the OF slots); 0 = none. Non-zero warns — the cap is not modelled yet |
| `arb_method` | `allocations` | `voteoff` and `none` are reported unmodelled rather than guessed |
| `arb_budget` | `25` | dollars each team distributes |
| `arb_min` / `arb_max` | `1` / `3` | per opposing team, so a roster's take is bounded to `arb_min x (teams-1)` .. `arb_max x (teams-1)` |
| `keeper_discount` | `0.5` | **a preference, not a league setting** — weight on each keeper season relative to this one in `keeper_npv` (next season 0.5, then 0.25, 0.125, 0.0625), so NPV is in this season's dollars. Rosters turn over; raise it toward 1.0 if you're rebuilding |

League 1297's values: 12 teams, $400, 40-man, FGPts, H2H, **1 catcher slot, no
position cap**, allocations arbitration at $25/$1-3.

`BASE_RP` is gone. RP depth is `RP_SLOTS = 6` — roster practice rather than the
lineup's 5 slots, because a reliever appears in only ~40% of games. `BASE_SP` is
gone too: every Ottoneu H2H league caps starts at 10 a week, so SP depth is a
rule (`GS_CAP`), and nothing in the engine is fitted to salaries.

`RELIABILITY` in `value.py` shrinks projected PAR per role where the projection
is least trusted — the slope of realized on projected PAR over the ten-season
bed, printed by `py -3.13 backtest.py --measure "out/backtest_20*.csv"`. It
describes the **projection**, not the league, so re-measure it if you swap
projection sources.

> **See [`APPROACH.md`](APPROACH.md)** for the methodology, the design rationale,
> and the running list of traps to avoid. This file is how to run it; that one is
> why it works the way it does. Update it when a decision changes or a new trap
> gets found. [`NEXT_STEPS.md`](NEXT_STEPS.md) is the current work queue.

## The two layers

**Layer 1 — base value.** What a player is worth in a generic 12-team Ottoneu
FGPts league. No roster data enters this at all.

1. **Depth** — roster spots per team that carry real value; **nothing here is
   fitted to salaries.** The hitter shape is the lineup rule (1 C — a league
   setting — 1 1B, 1 2B, 1 3B, 1 SS, 5 OF, a middle-infield slot split across
   2B/SS, and Util). Util is a *leftovers* slot: a second pass fills what the
   position-less hitters don't take with the best spare hitters, and its
   replacement is the best undrafted hitter of any position — which is why a DH
   is worth his bat but not his scarcity. H2H has no SP slots, so SP depth comes
   from the 10-start weekly cap; `RP_SLOTS` is 6, roster practice rather than the
   lineup's 5, because a reliever appears in only ~40% of games.
2. **Replacement** — fill every spot best-player-first, then replacement at a
   position is the best *undrafted* player eligible there. That's what the $1
   tier actually offers you.
3. **PAR** = points − replacement, at the player's best eligible position,
   shrunk by the measured `RELIABILITY` slope for his role (projection side
   only).
4. **Dollars** — every spot costs ≥ $1, so `teams × (cap − roster_max)` is the surplus
   pool, split proportionally to PAR.

**Layer 2 — league value.** What he's worth in *your* league, given who's
already locked up and how much money is actually loose.

Layer 1 assumes the whole universe is gettable. In a keeper league most of it
isn't, so the best *free* catcher is a different and worse player than the best
catcher — and that's what a replacement-level catcher is worth to you. Layer 2
re-solves replacement against the available pool and rescales to real free money.

It deliberately does **not** apply a flat inflation multiplier. A scalar prorate
preserves the base ranking exactly, so it could never surface that catchers are
scarce in your league — which is the entire reason the layer exists. Validated
against a simulated keeper deadline: inflation came out position-specific (2B
1.35×, OF 1.25×, RP 1.22×), which a scalar cannot produce, and the top-300 league
values summed to $1,695 against $1,690 of free money.

Layer 2 reports "no open market" and emits no values when rosters are full — as
they are mid-season. It's fundamentally an offseason/auction tool.

## Refreshing data

All input is local CSVs in `data/`. **Automated pulls do not work**: Ottoneu's
`rosterexport`/`averageValues` and `fangraphs.com/api/projections` all sit behind
Cloudflare and 403 any non-browser client. Verified — pybaseball's
`batting_stats()` fails identically, and the `fangraphs` / `baseball_scraper` PyPI
packages were last published in 2021 and 2020. No library shortcut exists; only a
real browser gets through.

MLB's own data is open and needs none of this: `statsapi.mlb.com` and Baseball
Savant answer plain scripted requests, which is why `backtest.py` fetches
directly.

### `data/rosterexport.csv`
`https://ottoneu.fangraphs.com/1297/rosterexport?csv=1` in a browser.

### `data/average_values.csv` — cross-league check, optional
`https://ottoneu.fangraphs.com/averageValues`, pick the league's format in the
Game Type box (H2H FanGraphs Points is `gameType=5`), then "Export as .csv".
Browser only. Score it with `py -3.13 backtest.py --market`.

### `data/steamer_bat.csv`, `data/steamer_pit.csv`
FanGraphs' Data Export is members-only, so build them from the JSON their
projections page already calls. On https://www.fangraphs.com/projections, in the
devtools console:

```js
const cols = {bat: ['playerid','PlayerName','Team','minpos','Pos','G','PA','FPTS','SPTS','xMLBAMID'],
              pit: ['playerid','PlayerName','Team','G','GS','IP','SV','HLD','FPTS','SPTS','xMLBAMID']};
for (const s of ['bat','pit']) {
  const j = await (await fetch(`/api/projections?pos=all&stats=${s}&type=steamer`)).json();
  const esc = v => v == null ? '' : (/[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g,'""')}"` : String(v));
  const csv = [cols[s].join(',')].concat(j.map(r => cols[s].map(c => esc(r[c])).join(','))).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], {type:'text/csv'}));
  a.download = `steamer_${s}.csv`; a.click();
}
```

Chrome blocks the second file until you allow multiple downloads for the site; a
fresh tab also resets it. Swap `steamer` for `zips`, `atc`, `thebat`, `thebatx`,
or `fangraphsdc`.

`xMLBAMID` is what joins a projection to statsapi. After refreshing, run
`py -3.13 marcel.py --aging`: it re-measures the aging table
(`data/aging.csv`) and fetches birthdates for any new ids
(`data/birthdates.csv`). Without them `keeper_npv` is left blank.
`py -3.13 marcel.py --npv` backtests `keeper_npv` out of sample on the bed.

### `data/teams_cap.csv` — required for layer 2
**The roster export cannot produce cap space.** Three things live only on the
team page, and all three break a naive $400/40 assumption:

- **Loans** — teams trade cap dollars in-season. One team's real cap is $633.
- **Cap penalties** — 50% of a dropped player's salary, money that buys nobody.
  $436 league-wide here.
- **Roster max** — 43, not 40, because in-season IL slots stop counting.

Run this on any page of your league (it walks the standings for team ids):

```js
const L = '1297';
const sd = new DOMParser().parseFromString(await (await fetch(`/${L}/standings`)).text(),'text/html');
const ids=[...new Set([...sd.querySelectorAll('a')].map(a=>a.getAttribute('href')||'')
  .map(h=>(h.match(new RegExp(`/${L}/team/(\\d+)`))||[])[1]).filter(Boolean))];
const rows=[];
for (const id of ids) {
  const d = new DOMParser().parseFromString(await (await fetch(`/${L}/team/`+id)).text(),'text/html');
  const t=(d.body.textContent||'').replace(/\s+/g,' ');           // textContent, not innerText
  const g=(re,i=1)=>{const m=t.match(re); return m?m[i].replace(/,/g,''):''};
  rows.push([id,(d.title.split(' - ').pop()||'').trim(),
    g(/Roster\s*(\d+)\s*of\s*(\d+)/i), g(/Roster\s*(\d+)\s*of\s*(\d+)/i,2),
    g(/Salary\s*Cap\s*\$([\d,]+)\s*\(base\)/i),
    g(/\+\s*\$([\d,]+)\s*\(loans in\)/i)||'0', g(/-\s*\$([\d,]+)\s*\(loans out\)/i)||'0',
    g(/Cap\s*Used\s*\$([\d,]+)\s*\(salary\)/i), g(/\+\s*\$([\d,]+)\s*\(cap penalties\)/i)||'0']);
}
copy(['team_id,team_name,roster,roster_max,base_cap,loans_in,loans_out,salary,penalties']
  .concat(rows.map(r=>r.map(v=>/[",]/.test(v)?`"${v.replace(/"/g,'""')}"`:v).join(','))).join('\n'));
```

`copy()` puts it on the clipboard (downloads are blocked on this origin); paste
into `data/teams_cap.csv`. Two integrity checks worth running after: base caps
should total `teams × $400`, and loans in minus loans out should be exactly $0.
Both hold on the current file.

Without this file layer 2 is skipped and the cap columns in `teams.csv` are left
blank rather than filled with a wrong $400/40 guess.

## Rules coverage

What `Ottoneu h2h points rules.md` says, and whether the code honours it. The
un-modelled rows are deliberate omissions, not oversights — they're listed so
nobody assumes otherwise.

| Rule | Status |
|---|---|
| 40-man roster max | modelled |
| 60-day IL / suspended / opt-out spots don't count in-season, and grant **no** extra cap space (line 46) | modelled — team pages report 41-47, but the $1-per-open-spot reserve is measured against 40 |
| $1 of cap room per open roster spot, up to the 40-man max (line 45) | modelled in layer 2 |
| Retention raise: +$2 with MLB service, +$1 for a pure prospect (line 51) | modelled — `keeper_salary` / `keeper_surplus`, and compounded every year in `keeper_npv` |
| In-season cut leaves 50% of salary as a cap penalty until claimed (line 84) | modelled — `cut_penalty` / `cut_gain` |
| Off-season cuts carry no penalty (line 87) | modelled — `cut_gain(..., in_season=False)` |
| Cap loans traded in-season | modelled, from `teams_cap.csv` |
| Arbitration, allocations method: $25 per team, $1-3 to each other team (line 60) | modelled — `arb_allocations`, folded into `keeper_salary`; per-player split is an assumption, see `NEXT_STEPS.md` |
| Arbitration, vote-off method (+$5 RFA re-bid discount) | **not modelled** — league 1297 uses allocations |
| FA bid on a previously-dropped player must be ≥50% of prior salary (line 86) | **not modelled** — a price floor the model doesn't know about |
| 30-day re-bid ban after dropping a player | **not modelled** |
| Post-keeper-deadline cap of $360 + roster size (line 47) | **not modelled** |
| Weekly GS cap (line 21) | **partly modelled** — it sets SP depth via `gs_cap`, but marginal starts are still priced at full value: your 10th starter's starts are worth less than your 1st's |
| Two starts per pitcher per day | **not modelled** |
| Utility lineup slot (line 20) | modelled as a *leftovers* slot — DH-only hitters are priced at Util against the best spare hitter of any position |
| Positional eligibility, pitchers: SP with 5+ starts (line 22) | modelled from **projected** starts; Ottoneu's current eligibility is deliberately overruled for pitchers (`resolve_positions`) |
| Seasonal games caps (162/hitter, 810 OF) | **not modelled** |
| Vickrey auction (pay $1 over second-highest bid) | **not modelled** — values are worth-it prices, not bid advice |
| Playoff lineup (1 C, 2 SP or weekly GS cap) | **not modelled** |

Two of these changed the headline output once applied:

- **Retention makes most cheap keepers not worth keeping.** Across the 147
  rostered players at $1-3, mean surplus is +$0.4 against today's salary but
  **−$1.6 against next year's**. Measuring surplus against the current salary
  systematically flatters exactly the players it's easiest to be wrong about.
- **Raw negative surplus is not a cut list.** 40 rostered players look like bad
  contracts by `value − salary` but should *not* be cut in-season, because a cut
  frees only about half the salary while costing all of the production. José
  Ramírez ($50 salary, $32 value) frees $25 and loses $32 — hold and shop him.
  The real cut candidates are cheap-ish players with no value at all, like
  Spencer Schwellenbach ($18 salary, $1 value, net +$8).

## Calibration, and how much to trust it

Against this league's 432 rostered players: `pearson(value, salary) = 0.838`, and
the top 480 base values total $4,798 against the $4,800 cap.

**This is a sanity check and nothing more.** Salaries are what the market
believes, not what players are worth, and a model tuned to fit price would just
predict the market and find no edge by construction. The real yardstick is
`marcel.py` + `backtest.py --dollars` over ten seasons of realized production.

That distinction is not academic here. Relievers used to come out **+$3.4 above
market**, the largest positive gap of any position, and that was recorded for
months as the model reproducing the documented Ottoneu points-league reliever
edge. Ten seasons of realized production said the opposite — relievers
*underdelivered* per dollar in 10 seasons out of 10 — and the model was simply
overpaying them. It is fixed by `RELIABILITY`, and the episode is written up in
`APPROACH.md` §2 and §6.28 because it is the clearest illustration in the project
of why market agreement proves nothing.

## Traps this code already fell into

All of these produced confident, completely wrong leaderboards:

- **Charging multi-eligible players to their scarcest position runs away.**
  Charging every 2B/SS to SS is exactly what makes SS the deepest position.
- **Recomputing replacement from the currently-assigned pool oscillates.**
  Players pile onto whichever spot is momentarily cheaper, emptying the other and
  flipping the incentive next pass. One descending draft sweep has no feedback loop.
- **A swingman must be a starter.** Left dual-eligible, SP/RP arms arbitrage into
  the cheaper pool and get paid twice for the same innings — which put four
  actual starting pitchers atop the "best relievers" list.
- **Salary is a bad depth proxy at RP.** It works everywhere else, but reliever
  prices are compressed against the $1 floor, so filtering by salary measured
  what relievers cost rather than how many teams carry. It cut RP depth to
  1.6/team against a real 5-7 and priced good relievers at nothing.

## Backtest

Both sides are computed from raw components with the documented FGPts weights;
FanGraphs' own `FPTS` column is deliberately ignored, since it doesn't reproduce
exactly from the components they export (~1% off) and mixing two formulas would
bake that gap into every score. Weights confirmed by least squares over 473
projected hitters — every other counting stat lands within ±0.5 of zero, so
there's no missing term. Actuals come from statsapi over the same window, joined
on MLBAM id (the FanGraphs export carries `MLBAMID`, so no crosswalk needed).

Steamer's rest-of-season snapshot from 2025-05-24, scored against the rest of that
season. This is the floor a valuation model has to beat:

| pool | n | spearman | MAE | bias |
|---|---|---|---|---|
| all | 873 | 0.643 | 114.0 | +4.4% |
| hitters | 390 | 0.708 | 115.0 | +12.7% |
| SP | 189 | 0.515 | 130.3 | −3.1% |
| RP | 294 | 0.391 | 102.1 | −6.6% |

The +12.7% hitter bias is mostly playing time — projected PA exceeds actual once
injuries and demotions land.

## Known limits

- **Sub-$5 pricing is bracketed, not settled.** Raw and bust-floored realized
  PAR are bounds (`APPROACH.md` §6.18); `--dollars` now also reports `rPAR~`,
  the refill basis in between. Cheap tiers still look underpriced per dollar
  on it, and that is mostly the intercept arithmetic of §6.29, not mispricing.
  The option cushion is measured but not priced (§6.30).
- Layer 2 is untested against a real open market — only a simulated keeper
  deadline, because the live league is mid-season with 0 open spots and $227 free.
- The weekly GS cap isn't modelled, so SP value is season totals rather than
  points-per-start against the starts you can actually use.
- Hitters aren't valued against the seasonal games cap (162, 810 OF).
- Prospects with no projection get no value, though they still count against the
  team's cap.
- `keeper_npv` looks four seasons ahead on a measured aging table, but it is
  in-sample, has no out-of-sample backtest yet, and solves keep-or-cut on
  expected values — a floor for volatile players, pitchers most
  (`NEXT_STEPS.md` Task 7). Base values are still single-season.
- `RELIABILITY` was measured on Marcel, whose reliever projections are its
  weakest part. It describes the **projection**, not the league — re-measure it
  with `--measure` if you swap projection sources.
- The cross-league check (`--market`) is a *market* comparison — a sanity check,
  not validation (`APPROACH.md` §2).
