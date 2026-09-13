# Next Steps — resume here

Written 2026-09-08 so this can be picked up cold in a new session. Read
`APPROACH.md` first for the why; this file is the work queue.

**Slated: Task 10, more history to stress-test the weightings.** Weekly lines
are pulled; historical Steamer is pulled, loaded, and `RELIABILITY` is now
measured on it directly (2026-09-12, below) rather than the Marcel proxy. A
synthetic-league Monte Carlo (2026-09-12, Task 11 below) gives the first
outcome-based (wins, not just PAR/dollar) evidence that $value beats naive
drafting -- conditional on Steamer, not on Marcel. A per-position market
review (Task 12) fixed catcher's `RELIABILITY` and logged SP's gap as
unexplained rather than acted on. Prospects with no projection now get a
judgment-call flat value (Task 13); mid-season use is confirmed working with
no code changes, given a rest-of-season projection swap (Task 13). Open: the
refill-vs-floored disagreement on RP (Task 10 targets it, unresolved).
Time-gated: layer 2 at a live auction, the arbitration split (Task 8).

---

## Task 10 — more history for the weightings (started 2026-09-11)

### Weekly lines — pulled

`py -3.13 marcel.py --weekly` caches Monday–Sunday lines for all ten bed seasons
(`data/mlb/YYYY_{hitting,pitching}_weekly.json`): one `stats=byDateRange` call
per week for every player, ~27 a season, instead of a game log per player.
Weeks are calendar weeks, the first starting on opening day. Merging weeks is a
lossless sum, so whatever reads them decides how Ottoneu groups opening week,
All-Star week and overseas openers. The run checks that weekly sums reproduce
statsapi's season totals: **0 players off in every season and group** (27–29
weeks a season; 2018, 2019 and 2024 have overseas openers). Hitter counts fall
from ~1,300 to ~770 from 2022 on, which is the universal DH taking pitchers
out of the batting pool, not a gap. 15 MB, gitignored with the rest of
`data/mlb/`.

### Weekly/daily lineup simulation — built, stress-tested, RP left unresolved (2026-09-12)

`marcel.py --lineup-sim [--steamer]`. No historical Ottoneu roster export
exists for these seasons, so it drafts synthetic 12-team pitching staffs from
the same projected pool the bed already prices (snake draft, ranked by
preseason projection -- SP ~8/team, RP ~6/team, matching `value.base_depth()`
exactly so the player universe and replacement level don't shift under the
comparison), then replays each actual line through a no-hindsight bench
policy. SP starts beyond `GS_CAP` (10) still bench the worst-projected arm's
whole week first, by calendar week -- `GS_CAP` genuinely is weekly. RP was
first built the same way (weekly), then rebuilt at **daily** granularity once
the league owner confirmed Ottoneu allows daily lineup changes: a week-locked
active-5 is stricter than a real GM plays under. `marcel.py --weekly` now also
pulls and validates `data/mlb/YYYY_pitching_daily.json` (one `byDateRange` call
per calendar day, ~180 a season, same trick as the weekly cache) -- 0 players
off season totals in every year.

**Mechanics are validated, the RP number isn't.** Sanity check: RP6 (every
rostered arm active every day, i.e. no bench mechanic) reproduces the
season-total floored `RELIABILITY` ratio almost exactly (0.817 vs measured
0.803 on Steamer) -- confirms the sim is scoring correctly. RP5 (the real
5-of-6 rule) is where it falls apart: the activation signal is a trailing mean
of actual points over the last `TRAILING_DAYS` days, and **that number is
wildly sensitive to the window** -- swept 1 to 90 days on Steamer:

| days | 1 | 3 | 7 | 14 | 21 | 30 | 45 | 90 |
|---|---|---|---|---|---|---|---|---|
| RP5 | 0.634 | 0.526 | 0.573 | 0.661 | 0.691 | 0.709 | 0.730 | 0.746 |

Still climbing at 90 days, no sign of an asymptote short of RP6's 0.817
ceiling. Daily data is sparse (a reliever pitches maybe 40% of days), so a
short trailing window is nearly noise and a long one starts to just re-measure
season-long role -- there is no principled window to pick, and the number
picked determines the conclusion (0.53 to 0.75+ relative to hitters, more than
the RP_SLOTS-5-vs-6 gap in either direction). **Do not fold any single RP5
point into `RELIABILITY`.** The bottleneck isn't weekly-vs-daily granularity
(both are built and both validate against the season-total sanity check) --
it's that a trailing-points average is too weak a proxy for what a real GM
actually knows (probable starters, save/hold situations, closer depth chart),
and no amount of window-tuning fixes that with the data on hand. A better
bench signal (real role/appearance-probability data, if it exists anywhere
open) is the only way to make this number trustworthy; more compute on the
current signal just relocates the noise.

**What the sim DID settle, and stands regardless of the RP5 number:**

- **Task 9 (GS-cap benching), closed with a number:** SP is far less sensitive
  than RP to policy details (its bench rule is fixed preseason rank, no
  trailing signal, and SP's own sensitivity wasn't separately swept but its
  weekly mechanic is simple and its result stable across the earlier daily
  rebuild -- 0.966/0.982 unchanged). The cap costs SP ~1.6-1.7% of relative
  value (0.982→0.966 Steamer, 0.944→0.928 Marcel) -- small, matching Task 9's
  2026-09-11 depth-based prediction.
- **RP_SLOTS 5 vs 6, direction confirmed, magnitude not:** the mandatory
  5-of-6-active rule costs real value beyond what floored assumes -- true at
  every window tested above (RP5 < RP6 always) -- but *how much* depends on
  the same unresolved bench-signal question.

**Refill vs floored on RP:** still open. The sim confirms floored's season-total
RELIABILITY (0.803 Steamer) overstates what a real bench-constrained team can
capture -- direction, not magnitude. Refill's old 0.63 and floored's 0.803
bracket a band this sim narrows only a little (0.53-0.75+ at plausible
windows). Leave `RELIABILITY["RP"]` at 0.803 (season-total, at least an
honest, reproducible measurement) until a real bench signal replaces the
trailing-points proxy -- don't pick a window and call it precision.

### Historical Steamer — loaded, measured, wired into `RELIABILITY` (closed 2026-09-12)

steamerprojections.com stopped working; the substitute was FanGraphs' own
"Historical Projections" Steamer selector (browser pull, BYOD), saved to
`data/Historic Steamer Preseason Projections/{YYYY} {Hitter,Pitchers}.csv`,
2015–2025 (wider than the 2017-19/2021-24 that was needed). Full FanGraphs
export column set, not the trimmed `steamer_{bat,pit}.csv` layout. Both
unknowns resolved: `MLBAMID` is a direct column (joins straight to statsapi,
no Chadwick register), and pitcher files carry `HLD`.

`marcel.py --steamer` builds `out/backtest_YYYY_steamer.csv`: the same bed as
`build()`, but the projected line's raw components (AB/H/2B/.../HLD) come from
the historic Steamer file instead of Marcel, scored through `bt.points()` like
everywhere else rather than trusting the file's own FPTS/SPTS column. Position
eligibility and the realized side are untouched (statsapi), so the two beds
are comparable. `IP` in these files is a real decimal, not statsapi's .1/.2
thirds-encoding — don't route it through `bt.innings()`.

Measured (`backtest.py --measure "out/backtest_20*_steamer.csv"`), against the
old Marcel-proxy numbers:

| | Marcel proxy (old) | Steamer (measured) |
|---|---|---|
| SP | 0.957 | 0.986 |
| RP | 0.61 | 0.803 |

`value.py`'s `RELIABILITY` now holds the Steamer numbers — confirms the old
comment's guess that Steamer handles relievers better, so its RP slope sits
nearer 1. `backtest.py --market` afterward: no monotone-in-price error: SP
model−avg was already +4.6 and stayed +4.5, RP moved +0.6 → +2.9 (relievers
now priced ~30% higher in PAR terms, matching the RP reliability jump) with
every tier and pearson essentially unchanged. This is a measured shift, not
the disproven "relievers are underpriced" market-agreement edge (§4) — don't
conflate the two if RP prices come up again.

`marcel.py --age-check [--steamer]` prints same-season (k=0) realized/
projected PAR by age (APPROACH trap 32). Marcel is steeply monotone (H
1.66→1.25→1.10→0.93 by age bin; P 1.97→1.45→1.02→0.93) — its own age curve.
Steamer is flat by comparison (H 1.15/1.18/1.12/1.17; P 1.42/1.30/1.10/1.21,
not monotone) — **confirms trap 32's hypothesis**: the age-bias the
out-of-sample NPV backtest found belongs to Marcel, not to the source actually
priced. No age-bias factor is needed for Steamer; APPROACH §6.32 can drop the
"can't be measured" caveat.

**Everything below runs on `py -3.13`** (the default 3.15 is an alpha with no
pandas wheels). Verify the tree is healthy before changing anything:

```
cd C:\dev\Ottoneu_Values\OttoneuValues
py -3.13 value.py --selftest      # expect: selftest ok
py -3.13 backtest.py --selftest   # expect: selftest ok
py -3.13 value.py                 # expect: layer 2 says "no open market"
```

---

## Answered 2026-09-09 — arbitration is **allocations**

League 1297 uses the allocations method: each team distributes exactly $25 to the
other teams, $1-$3 to each, stacking on top of the retention raise. Modelled in
`value.py:arb_allocations` and folded into `keeper_salary` / `keeper_surplus`;
`out/players.csv` carries an `arb` column.

Two judgement calls the rules don't settle, both marked in the docstring:

- **How much each roster takes.** Bounded at $11-$33 (11 opponents x $1-3).
  Modelled as the team's share of league-wide surplus, clamped into that band —
  so a roster full of bargains gets taxed hardest.
- **Where it lands inside a roster.** The rules cap the per-*team* total, not the
  per-player one. Modelled proportional to surplus, on the reasoning that 11
  managers choose independently. If the league turns out to concentrate on one
  target per team, switch to greedy — there's a `ponytail:` marker on it.

Effect is smaller than expected on cheap keepers: across the 147 rostered players
at $1-3, mean keeper surplus moved only −1.6 → **−1.8**, because proportional
allocation follows absolute surplus and lands on mid-priced bargains (Ohtani +$9,
Crochet +$8, Rooker +$7) rather than on $1 fliers. $278 of a nominal $300 is
allocated; the rest is eaten by the $33 clamp.

**Still worth confirming at the next arbitration:** whether allocations actually
concentrate (one big hit per team) or spread. That's the one assumption here with
no rule behind it.

---

## Task 11 — synthetic-league Monte Carlo: does $value predict winning? (2026-09-12)

Everything before this measured realized PAR per dollar (a proxy) or agreement
with a market (APPROACH trap 2: validates nothing). This measures the actual
thing: does a $value-drafted roster win more real weekly matchups than a
roster built by a deliberately worse strategy, given the same real subsequent
production? No historical Ottoneu roster export needed -- it's a one-shot
startup auction (no keepers) off the same projected pool the season-total bed
already prices, scored by the real season that followed.

`marcel.py --league-sim [--steamer] [--trials 200]`. Mechanics:

- **Auction, not snake draft** -- matches the $400/team format actually being
  priced. Nominates in descending *true* (scarcity-aware) $value -- best
  player up first, the real convention -- and clears each at $1 over the
  runner-up bid (`clear_price`), capped at the winner's own bid. Every team
  reserves $1 per remaining open roster slot so it can never bid itself out of
  finishing a 40-man roster.
- **Three strategies, 4 teams each, always** (which team *number* carries
  which strategy doesn't matter -- see the code comment): **value** (the real
  $values, scarcity split + `RELIABILITY` shrink, all of it); **points**
  (`naive_dollar_values`: the identical $-conversion math, but one
  undifferentiated position and no reliability shrink -- sized to the SAME
  total priced-slot count as value's own per-position depths, ~318, not the
  full 480-player roster count, so the only difference is scarcity awareness
  and shrink, not market depth); **random** (bids a random amount within its
  affordable room -- the floor).
- **Real weekly scoring.** Hitters: each team's own best lineup that week,
  reusing `value.draft()` scoped to its own roster, with a literal
  middle-infield flex slot (`team_hitter_pos`) rather than the season-total
  depth solver's 50/50 split, which only means something once smoothed over
  12 teams. SP: the validated, low-sensitivity GS_CAP bench (worst-projected
  arm sits first). **RP is deliberately uncapped** (every rostered arm counts
  in full, every week) -- the daily RP bench signal's own magnitude is
  unresolved (Task 10), and importing that noise here would confound a
  different experiment.
- **Monte Carlo over the schedule only** (random weekly pairing each trial)
  plus the random strategy's own draws. Auction outcomes for value/points
  don't need re-drawing -- their bids aren't random, so only `random`'s bids
  and the schedule vary trial to trial; 500 trials converges tightly (100 vs
  500 trials agree to two decimal places).

**Result, Steamer bed, 10 seasons × 500 trials, mean wins per 28-week season
(coin-flip expectation is 14.0):**

| value | points | random |
|---|---|---|
| 15.33 | 13.80 | 12.28 |

Value beats points beats random, in every season but two (2018, 2024 are
statistical ties). **This is the first outcome-based, non-circular evidence
that value.py's adjustments (positional scarcity, Util, `RELIABILITY`) earn
more than a raw-points valuation would** -- not just flatter PAR-per-dollar,
but more actual wins, holding the projection and the season fixed.

**Caveat that matters: this result is conditional on Steamer, and does NOT
hold on the Marcel bed** (value 13.35 < points 14.05 ≈ random 14.00 at 100
trials -- value is the *worst* strategy on Marcel, badly so in some seasons,
e.g. 2021: 10.07 vs points' 16.87). Consistent with `marcel.py`'s own
docstring ("Marcel is deliberately a *worse* projection... never compare a
Marcel number to the Steamer run"): scarcity-aware pricing is a precision
instrument -- it amplifies whatever the underlying per-player projection says,
which pays off against a good projection and backfires against a noisy one.
The model's edge is real but conditional on projection quality; it is not
"prices are right regardless of the input."

**Diagnostic, not a bug:** naive strategies sometimes roster **zero catchers**
(2 of 4 points-teams, one season checked) despite having budget and slots to
spare -- catchers get auctioned early (true value ranks them for scarcity)
and a naive bidder doesn't compete hard enough at that point, then fills all
40 slots with the un-scarce positions it does understand before a cheap
catcher ever reappears. Deliberately left unpatched: giving every strategy a
"never leave a scarce slot empty" floor would hand `points` the exact
positional awareness this test isolates it from having. This is why `points`
sometimes loses to pure `random` -- structured-but-blind can be worse than no
structure at all, which is the sharpest evidence yet for why the engine models
scarcity explicitly rather than leaving it to a market/manager to notice.

Not yet done: a Steamer-equivalent run on the actual league 1297 shape beyond
the defaults tested (this used `cfg` from `data/league.csv` as-is); varying
`--trials` beyond 500 to confirm no further drift; checking whether the
catcher-neglect finding generalizes across seasons or was specific to 2015.

---

## Task 12 — per-position market review: catcher fixed, SP logged (2026-09-12)

Prompted by the owner's flat "no catcher should be worth $10+" pushback.
Reviewed every position the same way: model $value vs cross-league
`average_values.csv`, by price tier, watching for a **monotone-in-price gap
isolated to one position** (APPROACH's own structural-flaw signature).

**Every position's bottom tier reads negative** (model under market by
$1-2.7) -- that's not new, it's the already-documented, deliberately-unpriced
option cushion (trap 30). Ignore it; it's universal, not positional.

**Top-tier gaps varied a lot, and the ranking held a surprise:**

| position | $20+ gap | n |
|---|---|---|
| **SP** | **+$12.2** | **32** |
| C (before fix) | +$9.5 | 2 |
| 2B | +$8.1 | 2 |
| OF | +$6.3 | 32 |
| 1B | +$4.2 | 5 |
| 3B | −$0.8 | 7 |
| SS | −$2.7 | 6 |

Catcher's gap looked biggest by dollar-per-player until the sample sizes came
out: SP's is bigger AND rests on 16x the data. 3B and SS show no top-tier
gap at all -- nothing to do there.

**Catcher: fixed.** Two independent signals agreed -- the market gap above,
*and* the ten-season bed's own floored realized/projected PAR ratio (C 0.852
relative to other hitters, aggregate; noisy per-season, 0.33-1.40, but the
two together are enough where either alone wouldn't be). `RELIABILITY` now
carries `"C": 0.852`, measured via `backtest.py --measure` (extended to break
catcher out of the "H" baseline it used to be pooled into -- see
`backtest.py`'s `measure()`). SP and RP shifted slightly as a side effect
(0.986/0.803 → 0.975/0.794) because "H" no longer includes catcher, not
because either one actually changed. Live effect: Cal Raleigh $32→$28,
William Contreras $25→$22; catcher's overall market residual flattened
$2.0→$0.3 on `backtest.py --market`, nothing else moved.

**SP: investigated, not fixed, logged as open.** Same drill-down as catcher,
three separate checks, all came back clean:
- Bust rate ($20+ tier, realized ≤0): SP 25%, OF 25% -- identical.
- Refill-adjusted ratio (credits back missed time at replacement -- the
  mechanic that exists for exactly this "injury" story): SP 1.193, OF 1.288 --
  SP isn't worse.
- Ratio-of-sums at $20+: 1.035 -- in aggregate, elite SP realize almost
  exactly their projection over 701 pitcher-seasons.
- Re-ran against `Last 10` (current market) instead of the lagging,
  keeper-inflated `avg` salary, in case retention lag was manufacturing the
  gap: barely moved ($12.2 → $10.2).

No second signal, despite genuinely looking for one. **This is the same
shape as the disproven "relievers are underpriced" claim (§4)** -- a real
market disagreement resting on market agreement alone, which validates
nothing by itself. Not acted on. Owner's read: plausibly the market
collectively overrates pitcher injury risk -- a real hypothesis, but "the
market might be wrong" isn't different from "the market agrees with me,"
evidentially, and both are exactly the trap that sank the RP claim. Revisit
if a second, independent signal ever turns up.

**Resimulated the Task 11 synthetic league after the catcher fix** to check
for real impact, not just a cleaner market chart:

| | value | points | random |
|---|---|---|---|
| before | 15.325 | 13.797 | 12.278 |
| after | 15.312 | 13.700 | 12.388 |

Unchanged, within Monte Carlo noise. Expected, not a null result on the fix
itself: one catcher slot out of a 40-man roster is too small a share of total
team value for a single-position correction to move a whole-season win-rate
metric, even a real and correctly-targeted one. The league sim is the right
tool for "does the pricing PHILOSOPHY work," not for detecting a one-position
recalibration -- that's what the per-position market table is for.

---

## Task 13 — prospects, and confirming intraseason use actually works (2026-09-12)

Prompted by walking through three concrete use cases (pre-draft with keepers,
intraseason bid/trade, pre-draft keeper decisions) end to end against the
code rather than asserting confidence.

**Prospects with no Steamer projection: built.** `value.load_prospects()` +
`data/prospects.csv` (optional, BYOD -- a ranked list like FanGraphs' The
Board, row order is the rank). Flat value by tier (`value.PROSPECT_TIERS`:
rank 1-5 $4, 6-10 $3, 11-15 $2, 16-20 $1, 21+ not rostered) -- the owner's
numbers directly, a judgment call and explicitly labelled as one, not a
measurement. A real Steamer projection always wins; this only fills in
players the projection never saw at all, added after layer 1 so it can never
distort a real player's replacement level. No automated pull planned --
manual refresh, same as the mid-season projection swap below (both owner's
call, 2026-09-12: minor-league rankings and rest-of-season projections are
cheap enough for a human to pull that automating either isn't worth it).

**Intraseason (rest-of-season) use: verified working, no code changes
needed.** First pass in this thread said "not ready" for mid-season bid/trade
valuation, pointing at `layer 2` reporting "no open market" whenever rosters
are full (true almost all season). That verdict was too pessimistic --
re-checking against the code: layer 2's "no open market" gate is *correct*
behavior (there genuinely is no market when nobody has a roster spot), not a
bug, and it already comes back to life the rare times a spot opens (`value.py`
selftest's own `il` case). More importantly, **everything that actually
answers a mid-season bid/trade/cut question -- `base_value`, `surplus`,
`cut_gain`, `keeper_npv` -- has no full-season assumption baked in at all.**
They price off whatever `pts` is in `steamer_{bat,pit}.csv`, full-season or
rest-of-season alike. Confirmed two ways:
- `value.py`'s existing selftest already covers layer 2's "full roster, no
  market" vs "one real opening, priced market" cases generically (lines
  ~1071-1095), with point totals that were never claimed to be full-season.
- New check this session: took the real, realistically-sized live pool,
  scaled one expensive preseason ace's (Tarik Skubal, $38 salary) points down
  to a rest-of-season-collapse pace (1154 -> 173, 15%). His `$value` correctly
  crashed to the $1 floor and `cut_gain` came back **+$18** -- a clear, correct
  CUT signal, at realistic replacement-level scale (a small synthetic 4-team
  toy league tried first gave nonsense numbers because replacement level
  needs a realistic pool size to mean anything -- not specific to ROS use,
  just a reminder that a toy-sized scenario tests different things than a
  realistically-sized one).

**What this means for the three use cases asked about:**
- Pre-draft keeper decisions: confident (Task 7's out-of-sample `keeper_npv`
  backtest already covers this; RP reliability magnitude and SP's market gap
  are named uncertainties, not missing mechanisms).
- Pre-draft valuation with keepers (layer 2 inflation): mechanism is real and
  correctly designed, but has never been checked against a real auction --
  needs a live check, not more code (`APPROACH.md` §7).
- Intraseason bid/trade/cut: **now confident** the mechanism handles it once
  a rest-of-season projection is supplied manually. What's still just a
  convenience gap, not a correctness one: no dedicated "compare two players
  side by side" report exists yet -- `surplus`/`keeper_npv` are per-player
  fields in `out/players.csv` today, not a trade-comparison view. Build if it
  turns out to matter in practice.

---

## Task 1 — point the backtest at dollar values — **DONE 2026-09-09**

`py -3.13 backtest.py --dollars` prices the 2025-05-24 projection snapshot with
`value.py`'s layer 1, computes realized points above replacement over the same
window, and reports realized-PAR-per-dollar by price tier and by decile.

**Verdict: pricing is proportional over the range that matters. No large depth
error.** OLS of realized PAR on marginal dollars (`value - 1`) across the 223
players priced at $5+ gives slope 6.19 with intercept **-34.3**; on a
bust-floored basis (see below) slope 5.28, intercept **+20.2**. The two bracket
zero, and |intercept| ~20-35 is small against the $30+ tier's ~200 realized PAR.
Rank correlation between price and PAR-per-marginal-dollar is +0.07 — noise.

So the depth constants (`BASE_SP` 7.7, `BASE_RP` 5.5, the lineup-derived hitter
shape) are not measurably wrong. Task 2 can proceed on a real footing.

### Two things this exposed, both of which matter more than the headline

**1. The curvature mapping written here previously was inverted.** It said
"droop at the top -> stars still underpriced". It is the other way round: low
realized PAR per dollar in a tier means you got less production per dollar
spent there, i.e. that tier is **overpriced**. And the remedy runs the other
way too — shallower depth raises replacement, which *lowers* marginal players'
PAR and moves dollars toward the top. Correct mapping:

| Observation | Diagnosis | Fix direction |
|---|---|---|
| PAR/$ droops at the **top** | stars **over**priced, curve too steep | deeper depth (lower replacement) |
| PAR/$ droops at the **bottom** | marginal players **over**priced, curve too flat | shallower depth (higher replacement) |

**2. Raw realized PAR is not a fair measure below ~$5.** A $2 player who loses
his job scores roughly `-replacement` — several hundred negative points — while
there is no symmetric upside. No owner eats that: you cut him and the spot
reverts to replacement level. The report therefore carries both `mean rPAR` and
`mean rPAR+` (floored at zero, the droppable-option view). Raw says cheap
players are badly overpriced; floored says they are badly underpriced; truth is
between, and neither extreme is evidence. **Any future claim about sub-$5
pricing must show both columns.**

### Remaining confound (not resolved, don't forget it)

Model value is a function of the *projection*, so the highest-priced players are
partly the ones whose projections were most optimistic. Regression to the mean
alone produces a mild droop at the top under perfectly correct pricing. A mild
top droop is therefore not by itself evidence of overpricing — which is one more
reason the +0.07 spearman should be read as "flat", not as a weak signal.

### What this still cannot test

Whether the model beats **the market** — that needs 2025 salaries, and historical
rosters were never confirmed retrievable from Ottoneu (standings go back to 2021,
rosters are current-state only). Park it.

---

## The engine is general. Read this before changing valuation logic.

The goal is an engine that prices **any** Ottoneu points league from projections
plus that league's settings — not a model tuned to league 1297. As of 2026-09-09
the split is:

- **Rules** (retention +$2/+$1, the 50% in-season cut penalty, $1-per-open-spot,
  IL spots granting no money) are identical in every Ottoneu league. Hardcoding
  them is correct.
- **Settings** (teams, cap, roster max, scoring, arbitration method and budget)
  now live in `data/league.csv`, read by both scripts. Delete that file and you
  get the Ottoneu standard defaults. Point the tool at another league by editing
  it and nothing else. An unknown key is reported, not silently ignored.
- **Fitted numbers.** `BASE_RP` is **gone** (5 slots, straight off the lineup
  rules). `BASE_SP` is **gone** too (2026-09-10): the 10-start weekly cap is
  universal across Ottoneu H2H, so SP depth is a rule. Nothing in the
  engine is fitted to anyone's salaries any more.

Task 1 showed pricing is proportional over $5+, but that was 1297 validated on
1297. The ten-season bed (Task 2) is the non-circular check.

---

## Task 2 — DONE 2026-09-09: the test bed exists, and it moved the queue

`marcel.py` builds Marcel projections from statsapi and emits
`out/backtest_YYYY.csv` for ten seasons (2015-19, 2021-25; **2020 skipped as
target and input** — 60 games poisons any season that uses it, which costs 2021
a stale Y-1 of 2019, flagged in the output). ~1050 players a season, cached in
`data/mlb/` so it never refetches. Score any of them with
`backtest.py --dollars --backtest out/backtest_YYYY.csv`.

### The result, across all ten seasons

Realized PAR per **marginal** dollar (`value - 1`), mean and range over 10 seasons:

| tier | raw | floored at 0 |
|---|---|---|
| $30+ | **7.1** (5.8–8.1) | **8.0** (6.8–9.0) |
| $15-30 | **5.4** (3.6–7.4) | **8.2** (6.9–10.0) |
| $5-15 | **−0.2** (−7.1–5.6) | **11.8** (7.9–15.8) |
| $2-5 | **−21.3** (−52.1–7.9) | **37.1** (21.7–49.1) |

**Above $15, pricing is proportional on both bases, in 10 seasons out of 10.**
That is the sturdy result: expensive players are correctly priced relative to
each other however you treat busts, and the depth constants are not badly wrong
where the money is.

**Below $15, the two bases diverge violently — and that divergence is the
finding.** Raw says cheap players return nothing; floored says they return four
times what a star does. Both reproduce monotonically in every single season, so
neither is noise. The gap *is* the option value of a roster spot: a $3 player who
loses his job costs you a waiver claim, not 400 negative points, and the model
prices projected means as if you were obliged to keep him.

---

## Task 3 (+ the Task 6 remainder) — DONE 2026-09-10: one regression

> **Revised the same day by the cross-league check** (below, before Task 8).
> The cushion is measured but no longer priced, and the reliability factor is a
> ratio of sums rather than the regression slope: `RELIABILITY = {"SP": 0.957,
> "RP": 0.61}`. This section is the record of how it got there.

Reliability and option value turned out to be the two coefficients of one
line. Regress realized PAR on projected PAR per role over the bed: the
**slope** is how far the projection can be trusted, the **intercept** is the
option cushion (a player who loses time is refilled from the bench, so every
roster spot banks a few points its projected mean doesn't show).

`value.RELIABILITY` is now `{role: (slope, cushion)}` — slope relative to
hitters (a common scale is a no-op on dollars), cushion as a fraction of the
position's replacement level so it travels to any depth. It is a measurement:

    py -3.13 backtest.py --measure "out/backtest_20*.csv"

Marcel: **H (1.0, .066) · SP (0.886, .133) · RP (0.61, −.026).** Leave-one-
season-out: SP slope 0.84–0.93, RP 0.56–0.69, cushions within ±.02. RP 0.61
recovers the hand-fitted 0.6 without being told to. Hitters are pooled into one
role — per-position hitter slopes swing wildly season to season (3B −0.8 to
2.8) and ten seasons cannot separate them.

### The yardstick needed a third basis

Raw and floored are bounds, and fitting to floored is forbidden, so the
regression runs on **refill** (`backtest.refill`, reported as `rPAR~`): the
share of his projected playing time a player didn't fill is credited back at
replacement level; a healthy player who was simply bad is still charged in full.
It is mechanical, not a knob. 53–61% of bust mass in every tier below $30 is
lost playing time (<50% of projected), which is exactly what refill credits.

### Result, ten seasons (per marginal $, raw / floored / refill)

"Old" is `{"RP": 0.6}` re-scored today on the current tree — it supersedes the
Task 2 table, which predates `gs_cap` 10.

| tier | old | new, same players (old tiers) | new, re-tiered |
|---|---|---|---|
| $30+ | 7.6 / 8.4 / 9.1 | 9.0 / 10.0 / 10.9 | 9.2 / 10.1 / 11.0 |
| $15-30 | 6.4 / 8.9 / 9.8 | 6.8 / 9.4 / 10.4 | 7.2 / 9.7 / 10.6 |
| $5-15 | 1.6 / 12.9 / 12.1 | 1.5 / 11.7 / 11.0 | −0.2 / 12.5 / 11.6 |
| $2-5 | −25.4 / 33.4 / 21.2 | −15.1 / 19.9 / 12.6 | −37.1 / 28.3 / 15.2 |

Against the success criterion, honestly:

- **Converges, on the same players: yes, 10/10 seasons** at both cheap tiers.
  The $2-5 raw-to-floored gap goes 58.8 → 35.0; $5-15 11.3 → 10.3.
- **On the re-tiered table it widens** (58.8 → 65.4). ~50 players a season who
  used to be $1 are now priced $2-5 and bring their busts with them. That's a
  change in who is in the tier, not a pricing failure — but the table
  `backtest.py --dollars` prints is the re-tiered one, so read it knowing that
  (APPROACH trap 29).
- **$15+ tiers: still proportional to each other, but their level moved.** The
  pool is fixed, so the cushion's money comes off the top: the top 36 players
  lose 16% of their dollars (0.83–0.85 in every season), and $30+ realizes
  ~20% more per dollar than before.
- On refill the curve is now nearly flat, **11.0 / 10.6 / 11.6 / 15.2** against
  9.1 / 9.8 / 12.1 / 21.2. $2-5 is still 1.4x — the option to *bench* a healthy
  bad player isn't credited anywhere.
- Floored flattens too (8.4…33.4 → 10.1…28.3). **Raw gets worse** at the bottom.
- Position view changed with the yardstick: RP is 1.03 of hitters on refill
  (was 0.65) but **1.32 on floored** (was 0.99). 3B sits at 0.52 on refill —
  pooled hitters hide it, and n is too small to act on.

### Live league 1297

`pearson(base_value, salary)` **0.838 → 0.825**; players priced above $1 299 →
343; top-480 $4,810 against $4,800. Ohtani $119 → $89, Judge $68 → $56, Skubal
$62 → $50; reliever ceiling $16 → $13.

### The stars — settled by the cross-league check: cushion out

Mean `base_value − salary` in the $30+ salary tier went **0.0 → −6.8**, with the
tiers below roughly unchanged. §2 says a disagreement with the market that is
**monotone in price** points at a structural flaw, not an edge. Two readings,
and the bed can't tell them apart:

1. **The model is right, and the market overpays stars.** The bed says the new
   pricing is flatter on two of three bases.
2. **The fixed pool over-transfers.** The cushion is flat per roster spot, but
   a star also saves a roster spot for another cushion-carrying body, and
   nothing credits that consolidation. That would put the missing dollars back
   on the top.

**Settled:** the cross-league market reproduced the gap (−6.9 at $30+) across
every H2H FGPts league, so it is not a 1297 quirk, and pricing without the
cushion is flat against it. Reading 2 wins — the replacement-level alternative
has the same cushion, so it cancels at the margin. Measured, printed by
`--measure`, not priced (APPROACH trap 30).

---

## Task 4 — DONE 2026-09-09: Util slot

DH-only hitters are real and often excellent, and they were being dropped. They
are now priced at Util, which Ottoneu itself calls them.

Util is modelled as the **leftovers slot it actually is**: a second draft pass
fills whatever Util openings the position-less hitters don't take with the best
spare hitters, and Util's replacement level is *the best undrafted hitter of any
position* — because that is who would otherwise stand in the slot. So a DH keeps
his bat and loses positional scarcity, which is most of what a hitter is paid
for. He ends up worth the same as an equally productive player at the **deepest**
position and strictly less than one anywhere scarcer. That is the discount, and
it falls out of the mechanism rather than being applied by hand.

Doing it as a second pass matters: making every hitter Util-eligible would funnel
the whole league into the scarcest opening (trap §6.1).

Side effects, both good: `pearson(base_value, salary)` went **0.813 -> 0.833**,
and the ten-season tiers were undisturbed ($30+ and $15-30 now sit at an
identical 8.3 on the floored basis).

---

## Task 5 — DONE 2026-09-09: pitcher depth is derived, not fitted

**`BASE_RP` is gone.** Rules line 21 says the H2H lineup is the standard lineup
minus the fixed SP slots, and line 20 says the standard lineup carries 5 RP. It
was never a mystery worth fitting. `RP_SLOTS = 5`.

**`BASE_SP` is now a fallback.** With a `gs_cap` set, SP depth is derived: a team
may use `gs_cap` starts a week, and a starter takes every fifth turn through a
rotation in a week holding ~6.2 team games, so he supplies ~1.25 of them.
`sp_slots = gs_cap * 5 / 6.23`. At `gs_cap` 14 that is 11.2 slots against the
fitted 7.7.

### Be honest about what the test showed

Measured as *SP dollars vs hitter dollars per unit of realized PAR*, where 1.00
means SP are priced in line with hitters:

| basis | mean abs error | beats fitted |
|---|---|---|
| fitted `BASE_SP` 7.7 | 0.199 | — |
| derived, `gs_cap` 12 | 0.185 | 6/10 |
| derived, `gs_cap` 14 | **0.165** | 6/10 |

**The derivation is not measurably more accurate.** Season-to-season swing runs
0.63 to 1.39 — SP-vs-hitter relative value genuinely moves that much year to year
— and it swamps a 0.199-vs-0.165 difference at n=10. The reason to adopt it is
that it comes from the league's own settings instead of one league's salaries.
Do not claim an accuracy win for it.

The ratio does cross 1.00 near `gs_cap` 12 (9.6 slots), which is at least a
coherent place for the fitted 7.7 to have been aiming.

### Answered 2026-09-10 — the GS cap is 10, in every Ottoneu H2H league

`gs_cap,10` gives derived SP depth of **8.0 slots/team**, against the fitted 7.7.
That is corroboration worth noticing: the constant someone fitted to one league's
salaries was approximately recovering the number the league's own GS cap implies.
At that setting SP/hitters is **0.95** over ten seasons. Nothing in the engine is
now fitted to anybody's salaries.

`RP_SLOTS` is **6**, not the lineup's 5: a reliever appears in ~40% of his team's
games, so five arms cannot keep five slots busy, and carrying six is standard
practice across the format. It is neither derived nor fitted but *observed*, and
it describes the format rather than one league. The bed cannot tell 5 from 6
apart (RP/hitters 0.57 vs 0.59), so 6 is chosen because it is true.

### Not done: the seasonal games cap

Still only a warning. `games_cap` is 0 for league 1297, so there is nothing here
to validate it against — building an unvalidatable model of it is how fitted
constants get created. Do it when a league that uses one needs it.

---

## Task 6 — DONE 2026-09-10: relievers, and pitcher role

### Role now comes from the projection, never from eligibility

The "Ottoneu eligibility beats the guess" override was wrong for pitchers in
**both** directions, and both were expensive:

- Musgrove and Steele are projected for 25+ starts but carry RP-only eligibility
  coming back from injury. Demoted, a starter's innings were paid against the
  reliever replacement level — Musgrove came out the league's most valuable
  "reliever" at **$29 against a $5 market price**.
- **28 projected relievers** (Griffin Jax, Clarke Schmidt) carry SP eligibility.
  Promoted, a reliever's innings were measured against the starter replacement
  level, zeroing out every one of them.
- Jake Bauers is a *hitter* with RP eligibility, and was being priced against the
  reliever replacement level with a hitter's points. He escaped only by being bad
  enough that it didn't bite — luck, not correctness.

One rule fixes all three: if the projection says he pitches it decides the role
outright, and the roster export may only ever supply **hitting** positions.

### Reliability shrinkage

`RELIABILITY = {"RP": 0.6}`, applied to projected PAR on the **projection side
only** before dollars are assigned. Result across ten seasons — every position
now within **0.86-1.14** of the hitter rate, no outlier anywhere:

    C 0.90  1B 1.14  2B 1.01  3B 0.86  SS 1.06  OF 1.07  Util 0.90  SP 0.96  RP 0.99

RP went 0.59 -> 0.99 and nothing else moved. The model's reliever ceiling fell
from **$26 to $16** (Miller $16, Díaz $14, Taylor $13, Duran $13, Smith $13),
against a league whose dearest relievers actually cost $14/$13/$13/$12.
`pearson(base_value, salary)` is **0.838**, from 0.813 at the start of the day.

Three independent sources converged here, which is why it was worth doing:
the ten-season bed said 0.6, the league owner said "no reliever above $12-15",
and 1297's actual salaries said ~0.5. **The bed is the only non-circular one of
the three** — market agreement is a sanity check, never the target (§2) — so 0.6
is what shipped, deliberately leaving the model slightly above the market.

Chosen as shrinkage rather than a hard "$15 max RP" cap: a cap hits the same
ceiling while leaving the middle of the reliever curve wrong.

**Re-measure `RELIABILITY` when the projection source changes.** It describes the
projection, not the league. Steamer handles relievers better than Marcel, so 0.6
is the conservative end — the principled version derives it from the regression
slope of realized on projected PAR per position, computed from whatever source is
loaded, which would make it a measurement rather than a constant. **Done
2026-09-10, together with the option value — see Task 3.** The figures in this
section describe `{"RP": 0.6}` on the floored basis and are superseded.

---

## Task 7 — DONE 2026-09-10: keeper NPV

`keeper_npv` (in `out/players.csv`, and "Best keeper NPV" in the console) is the
surplus summed over every season the aging table reaches (four). Salary rises
+$2 a year (arbitration charged once), and a cut is free at any offseason, so
it's solved backward: `V = max(0, surplus + d · V_next)`, `d` = `keeper_discount`. `keeper_surplus` stays as
the one-year, un-aged number.

**Aging** — `py -3.13 marcel.py --aging` writes `data/aging.csv`: realized PAR
k seasons later over realized PAR now, both floored at zero (the `RELIABILITY`
basis), for players Marcel priced, by age and role. It also writes
`data/birthdates.csv` — the Steamer export now carries `xMLBAMID` (README recipe
updated), so birthdates come straight from statsapi: 9,339 of 9,342 dated.

| age | hitters k1/k2/k3/k4 | pitchers k1/k2/k3/k4 |
|---|---|---|
| ≤25 | 0.98 / 0.94 / 0.80 / 0.85 | **0.65** / 0.59 / 0.52 / 0.61 |
| 26-29 | 0.94 / 0.72 / 0.67 / 0.54 | 0.77 / 0.67 / 0.51 / 0.41 |
| 30-33 | 0.72 / 0.54 / 0.36 / 0.21 | 0.75 / 0.62 / 0.49 / 0.37 |
| 34+ | 0.57 / 0.17 / 0.07 / 0.02 | 0.62 / 0.32 / 0.24 / 0.20 |

**Two wrong turns on the way, both now APPROACH trap 31:** ageing *points* and
then subtracting a full replacement level cut 87 of 119 one-year keepers,
including Skenes, Skubal and Ragans — value is convex, and a 22% chance a
pitcher is hurt is not a healthy season at 78%. And chaining a one-year
multiplier overstated later seasons by up to a third, because year-to-year
pairs are mostly survivors.

### Discount — the owner's call, 2026-09-10

Undiscounted, four seasons at full weight over-valued the distant future:
rosters turn over, owners trade, and next year's title is worth more than a
maybe in four. `keeper_discount` (default **0.5**, in `data/league.csv`) weights
each season relative to *this* one — next season 0.5, then 0.25, 0.125, 0.0625 —
so NPV is in this season's dollars. (Owner, same day: next year should already
be worth less than this year. A common scale, so no ranking or cut moved.) It is a *preference*, not a measurement —
raise it toward 1.0 for a rebuild. It sits inside the backward induction, so it
changes when a player is cut, not just the total.

### Live league 1297 (discount 0.5)

Top NPV, in this season's dollars: Maikel Garcia (26, $4) +10.3 · Kurtz (23,
$17) +8.5 · Merrill (23, $10) +8.2 · Crochet (27, $20) +7.3 · Wood (23) +7.2 ·
Sánchez (29, $15) +6.9 · Torres (29, $3) +6.9. Undiscounted the young hitters led
by more — Merrill +24.4, Kurtz +24.2, Wood +18.0. Of 119 players with positive one-year keeper surplus,
**43 have no multi-year surplus** — Skubal, Skenes, Harper (33), deGrom (38),
Y. Díaz (34), Nimmo (33). NPV minus one-year surplus runs from +0.7 for hitters
≤25 to −3.1 at 35+. Ohtani: one-year +$34, **NPV +$1.7** — at 31 he keeps ~73%
of his value next year, against a salary going $71 → $81 → $83.

### What to distrust

- **One noisy cell decides Skenes.** Young pitchers keep 0.65 of their value
  next year against 0.77 at 26-29. Plausible (innings limits, demotions,
  elbows), but it's n = 100.
- **NPV is a floor for volatile players.** Keep-or-cut is solved on expected
  values, but a real owner decides each offseason *knowing* last season.
  Pitchers most. Marked `ponytail:` in `keeper_npv`.
- **NPV 0 at a market salary means "no surplus to protect", not "dump him".**
  Skenes at $41 was bought at market; letting him go and rebuying at auction
  is roughly a wash by construction.
- ~~In-sample, and no NPV backtest yet~~ — done 2026-09-11, next subsection.
  The young-pitcher cell held out of sample (k1 2.02 held-out vs 1.97).
- Horizon four seasons, future arbitration not modelled. At discount 0.5 the
  horizon barely matters (the fourth season weighs 0.0625).

### Out-of-sample backtest — DONE 2026-09-11

`py -3.13 marcel.py --npv`. Each bed season Y is priced as a live season. Its
following seasons are predicted from an aging table measured with every pair
touching Y..Y+h held out, then compared with what they realized. h is the run
of known seasons after Y (2020 ends it, so 2019 and 2025 score nothing). There
are no historical salaries, so it uses two synthetic ones: $1, which scores the
value path, and half the model price, where cuts bite.

**The aging table holds out of sample.** Held-out and in-sample predictions
agree within a few points at k1–k3 in every cell; only the thin k4 cells
(n 21–36) wander.

**The level misses by age, and aging isn't the cause.** Realized over predicted
future PAR, held-out, k1:

| age | H | P |
|---|---|---|
| ≤25 | 1.58 | 2.02 |
| 26-29 | 1.22 | 1.43 |
| 30-33 | 1.04 | 1.06 |
| 34+ | 0.87 | 0.84 |

The same pattern appears at every k, and at k = 0: realized over projected PAR
in the *base* season is H 1.65 / 1.25 / 1.10 / 0.93, P 1.97 / 1.44 / 1.02 / 0.93.
So the aging shape is right, and the error is Marcel's age curve, which
under-projects the young and over-projects the old. Raw PAR runs the same way
(hitters 1.37 → 0.08 from ≤25 to 34+), so flooring convexity doesn't explain
it. It is a property of the projection, like `RELIABILITY`, and it hits this
season's `base_value` exactly as hard as NPV. Whether Steamer carries any of it
can't be measured, because there is no historical Steamer (APPROACH trap 32).

**NPV is a floor, now measured.** Per player, discount 0.5, half-price salary,
as predicted (held-out) / realized under the model's policy / realized with
hindsight:

| age | H | P |
|---|---|---|
| ≤25 | 4.7 / 10.1 / 13.9 | 0.4 / 0.9 / 8.6 |
| 26-29 | 2.9 / 4.4 / 7.8 | 1.4 / 3.2 / 7.4 |
| 30-33 | 1.0 / 1.0 / 4.1 | 1.2 / 0.9 / 4.6 |
| 34+ | 0.2 / −0.7 / 2.1 | 0.5 / −0.2 / 2.2 |

- Under 30, the policy realizes 1.5–2.3x its prediction. That is the projection
  bias above, showing up in keeper form.
- At 34+ the policy loses money, because it keeps players the projection
  overrates. The loss is mild: −$0.7 and −$0.2 a player.
- Hindsight is 2–10x the policy. It's unreachable, but the gap is what
  re-deciding each offseason on what you saw is worth (the `ponytail:` in
  `keeper_npv`), and it is biggest for young pitchers (0.9 vs 8.6).

Nothing in pricing changed; `keeper_npv` was only split so the backtest replays
`keeper_surpluses`, the real path. An age-bias factor could be measured on the
bed, but only for Marcel. Don't port it to Steamer.

---

## Cross-league check — DONE 2026-09-10

`data/average_values.csv` is Ottoneu's averageValues export for H2H FanGraphs
Points (`gameType=5`, browser pull): 1,078 players' salaries averaged across
every league of the format. `py -3.13 backtest.py --market` prices the whole
Steamer universe with layer 1, using the export's Ottoneu eligibility, and
compares.

It is a market comparison, so a sanity check (§2), never validation. What it
can do that 1297 can't is say whether a disagreement belongs to one league. The
rule it applies: error **monotone in price** is a structural flaw; error
confined to one position is a candidate edge.

Four pricings against Last 10 (the last ten transactions — the average salary
carries old auction prices plus retention raises), 423 projected players
rostered in at least half the leagues:

| pricing | pearson | model − market: $30+ / $15-30 / $5-15 / $2-5 / $1 |
|---|---|---|
| no reliability | 0.871 | −1.8 / +0.5 / +1.7 / +0.2 / +0.5 |
| old `{"RP": 0.6}` | 0.878 | +0.1 / +1.1 / +1.5 / 0.0 / +0.3 |
| slope + cushion (Task 3) | 0.860 | **−6.9** / −0.5 / +1.8 / +0.9 / +0.4 |
| **shipped: SP 0.957, RP 0.61** | **0.881** | **+0.3 / +1.0 / +1.5 / 0.0 / +0.3** |

- **The cushion is out.** Its −6.9 at $30+ reproduces 1297's −6.8 across the
  whole format — monotone in price. Without it the residual is flat.
- **The level is fine.** The market spends $4,148 a league against $4,800 of
  cap; 1297 spends $4,137 on players after $436 of cut penalties and $227
  unspent. Layer 1's $4,800 is the auction-time pool; the gap is in-season.
- **The bottom is contract vintage.** The market's 300th player costs $3 and
  its 400th $2 against the model's $1 — a kept $1 player is $3 the year after.
  Not a pricing signal.
- **Position residuals (market avg ≥ $5):** SP +4.6 (n75), OF +4.6 (n55),
  C +2.2, 1B +1.9, RP +0.6, 2B −1.1, 3B −1.8, SS −2.5. Position-specific, so
  candidate edges, not corrections. The 10-start cap is universal in Ottoneu
  H2H, so SP's is not an artefact of an assumed setting.

### A second correction it forced: ratio, not slope

With the cushion gone, the regression slope put SP at 0.886, which made SP
**1.10** of hitters on the bed's floored position table (was 0.98) — 10% cheap.
Its only support was agreeing better with the market, which is not evidence.
What proportional pricing has to equalize is realized over projected PAR in
aggregate, so `--measure` now takes the ratio of sums, on the floored basis the
old 0.6 came from: **SP 0.957 (LOSO 0.92–1.00), RP 0.61 (0.58–0.64).** Bed:
SP 1.02, RP 0.98 of hitters, tiers unchanged. Live 1297: pearson **0.842**,
$30+ salary tier **+$0.0**, reliever ceiling $17.

Still open: on the refill basis RP sits at 0.63 of hitters and 3B at 0.65.
Refill and floored disagree about relievers, and nothing here chooses.

## Task 8 — remaining generality gaps

- ~~Cross-league validation~~ — done 2026-09-10, section above.
- **Layer 2 has never run against a real open market**, only a simulated keeper
  deadline. Needs a live check at the next auction. Time-gated.
- **The arbitration per-player split is an assumption** the rules don't
  constrain. Checkable at the next arbitration. Time-gated.
- **SABR.** `--sabr` now runs end to end and produces sane depth and replacement
  levels, so that gap is closed — *but* `RELIABILITY` was measured on FGPts, and
  SABR weights innings and home runs differently enough to move relievers. Re-
  measure before trusting SABR values.
- **Vote-off arbitration** returns `{}` (reported unmodelled) rather than a
  wrong number. Model it when a league that uses it needs it.
- **Prospects with no projection** get no value though they still consume cap.

---

## Task 9 — marginal starts — **CLOSED 2026-09-11, not built**

The worry: the cap benches your 9th and 10th starters' starts, yet every start
is priced in full. Checked before building, as planned. Two findings, both
against building it:

- **The priced pool has no 9th or 10th starter.** Depth is
  `GS_CAP * ROTATION / GAMES_PER_WEEK` = 8.0 slots, and 8 × 1.25 starts = 10:
  depth is *defined* as the number of starters whose starts fill the cap in an
  average week. Arms past that are below replacement and priced at $1. What's
  left is weekly variance — a two-start-heavy week benches that week's worst
  starts, a thin one sends you streaming — second-order, on the same 8 slots.
- **The bed is blind to it by construction.** `marcel.py` pulls season totals
  (`stats=season`), so realized PAR credits a benched start in full, exactly as
  the projection does. The symptom check planned here could never have seen it;
  that needs weekly game logs and a per-team lineup simulation.

The check ran anyway (within-role price tiers, ten seasons, realized PAR per
marginal $, raw / floored / refill):

| tier | hitters | SP |
|---|---|---|
| $15+ | 7.5 / 8.9 / 9.6 | 6.7 / 8.5 / 9.4 |
| $5-15 | 2.3 / 12.8 / 11.8 | 5.4 / 16.7 / 17.3 |
| $1-5 | −6.9 / 41.0 / 33.7 | −9.0 / 59.1 / 54.7 (n 108) |

It shows the opposite of the predicted symptom: cheap SP return *more* per
dollar than dear SP, beyond what hitters show — $5-15 SP beat $5-15 hitters on
floored in 9 of 10 seasons. Not something to act on: bottom rows are dominated
by the intercept (trap 29), and SP's measured cushion is twice hitters' (.133
vs .066, Task 3), which is deliberately unpriced (trap 30).

Reopen only if weekly data (statsapi game logs are open) gets pulled for some
other reason.

---

## Standing constraints (don't rediscover these)

- **No scripted access to FanGraphs or Ottoneu** — Cloudflare 403s everything,
  including pybaseball. Browser only, BYOD. Don't lift `cf_clearance`, don't use
  TLS-impersonation libraries, don't sweep league IDs.
- **statsapi.mlb.com and Baseball Savant are open** — use them freely.
- Refresh instructions for all four input CSVs are in `README.md`.
- `APPROACH.md` §6 lists 16 specific traps, each with a selftest pinning it. Read
  it before changing valuation logic; several are non-obvious and already cost a
  wrong answer once.

## File map

| File | Role |
|---|---|
| `APPROACH.md` | Methodology, architecture, traps, decisions log |
| `NEXT_STEPS.md` | This file — the work queue |
| `README.md` | How to run it; how to refresh each input CSV |
| `value.py` | Two-layer valuation + rules-aware keeper/cut columns |
| `backtest.py` | Projection-vs-realized yardstick; `--dollars` scores the pricing |
| `marcel.py` | Marcel projections from statsapi -> `out/backtest_YYYY.csv`, ten seasons |
| `data/league.csv` | Per-league settings (teams, cap, catcher slots, arbitration...) |
| `data/mlb/` | Cached statsapi responses, 77MB, gitignored — regenerate with `marcel.py` |
| `data/rosterexport.csv` | League 1297 rosters + salaries (BYOD) |
| `data/steamer_{bat,pit}.csv` | 2026 Steamer projections (BYOD) |
| `data/teams_cap.csv` | Per-team cap, loans, penalties, roster max (BYOD) |
| `data/average_values.csv` | Cross-league averageValues, H2H FGPts (browser pull) |
| `data/aging.csv` | Measured aging table — `marcel.py --aging` |
| `data/birthdates.csv` | Steamer playerid → birthDate via `xMLBAMID` — `marcel.py --aging` |
| `out/players.csv` | age, base_value, league_value, surplus, keeper_surplus, keeper_npv, cut_gain |
| `out/teams.csv` | Per-team cap ledger |
| `out/backtest.csv` | 873 players, projected vs realized 2025 FGPts |
