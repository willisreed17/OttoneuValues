# Approach, Methodology, and Hard-Won Lessons

The durable record for this project: what we're building, how we decide whether
it works, and the specific things that already went wrong so they don't go wrong
twice. `README.md` covers how to *run* it; this file covers *why it is the way it
is*.

Last updated: 2026-09-12. League 1297, 12 teams, Ottoneu H2H FanGraphs Points,
currently mid-season (~week 21). The valuation engine itself is now treated as
locked (`CLAUDE.md`) — Phase 3 is a web UI built by a second developer on top
of it; this file and `README.md` are written to be onboarding for that, not
just a lab notebook for the person who built the engine.

---

## 1. What we're building

A player valuation tool for Ottoneu H2H points leagues that beats generic
projection-based tools (OttoValues et al.) by pricing players **in the context of
an actual league** — who is already rostered, at what salary, and how much money
is genuinely loose.

Phase 1 was personal use for league 1297 (done — see §7 for the verification
record). Phase 2 is generalising it so other Ottoneu managers can point it at
their own league; gated on the data access constraints in §5 and, for public
release, on asking FanGraphs first. Phase 3, now underway, is a web UI — see
`README.md`'s "What `value.py` hands off" for the interface it consumes and
"Intended use" for the three cases it's designed to serve
(pre-draft-with-keepers, pre-draft keeper decisions, intraseason
bid/trade/cut). The UI is a consumer of the engine's output; it is never a
reason to change pricing logic (`CLAUDE.md`).

**Three scripts, stdlib only.** No pandas — the default interpreter here is
Python 3.15 alpha with no wheels for it. Everything runs on `py -3.13`.

- `value.py` — prices players in three layers (base value, league context,
  keeper/cut decisions — `README.md` has the full breakdown), writes
  `out/players.csv` and `out/teams.csv`.
- `backtest.py` — scores projections against realized outcomes. The
  yardstick; written before the valuation logic was touched, on purpose (§2).
- `marcel.py` — builds a ten-season test bed from open MLB statsapi data (a
  deliberately worse projection than Steamer, so pricing *shape* can be
  scored on ten samples instead of the one FanGraphs snapshot available at
  any moment), measures `RELIABILITY`, backtests `keeper_npv` out of sample,
  and runs the synthetic-league Monte Carlo (§7, `NEXT_STEPS.md` Task 11)
  that's the closest thing this project has to a real-money validation
  without an actual auction.

---

## 2. Methodology — the principles we're building around

These are the rules of engagement, and they've each been earned.

**Build the yardstick before tuning the model.** Anything downstream of a
measurement is opinion until the measurement exists. `backtest.py` was written
before the valuation logic was touched, precisely so changes could be scored
rather than argued.

**Calibration against market prices is a sanity check, never the objective.** A
model tuned to match salaries perfectly would just *predict the market* and find
no edge by construction. Market fit is used only to remove errors that are
**monotone in price** — those indicate a structural flaw. Anything
position-specific is a candidate edge and must not be "corrected" away.

**Prefer falsifiable predictions — and then actually falsify them.** The strategy
doc says relievers are systematically underpriced in Ottoneu points leagues. The
model reproduced that prediction, twice failing on real bugs before it passed,
and for months it stood as the project's headline edge (`RP vs market +$3.4`).

**It was wrong, and the way it was wrong is the most useful thing in this file.**
The only evidence for it was agreement with market prices — which is exactly what
the paragraph above says validates nothing. The first non-circular test, ten
seasons of realized production, said the opposite: relievers *underdeliver* per
dollar, in 10 seasons out of 10. The model was overpaying them and the market was
closer to right. See §6.28 and the superseded table in §4.

The lesson is not "be suspicious of relievers". It is that a prediction which has
only ever been checked against the market has not been checked at all, however
many bugs were fixed on the way to reproducing it, and however satisfying the
reproduction felt.

**Every script carries an assert-based `--selftest`.** No frameworks, no
fixtures. It exists to catch the specific reasoning errors that already happened.
Most §6 entries have a test pinning them; the ones that are *findings* rather
than behaviours (§6.25, §6.26) cannot be, and say so.

**State what isn't modelled.** The rules-coverage table in `README.md` lists
every rule and whether the code honours it. Silent omissions become wrong advice.

**Separate what's universal from what's local.** See §3 — the base/league split
exists so league context is an explicit, inspectable layer rather than something
smeared through the whole calculation.

**The target is an engine, not a model of league 1297.** Three different kinds
of number get confused constantly, and only the third is a liability:

| Kind | Example | Where it belongs |
|---|---|---|
| Rule — identical in every Ottoneu league | retention +$2, 50% cut penalty | hardcoded, with the rules-doc line number |
| Setting — varies by league, knowable | teams, cap, roster max, arbitration budget | `data/league.csv`, defaults in `value.py:DEFAULTS` |
| Fitted — derived from one league's prices | *(none left)* — `BASE_RP` and `BASE_SP` both deleted | nowhere; replace with something derived |

A constant fitted to one league is a bug in every other one, and it will not
announce itself — it validates fine against the league it came from. When a
number has to exist because the rules don't supply one, that is a signal the
*format's own constraint* hasn't been modelled yet, not a licence to calibrate.

---

## 3. Architecture

### Layer 1 — base value (league-agnostic)

What a player is worth in a generic 12-team Ottoneu FGPts league. **No roster
data enters this layer at all.**

1. **Depth** — value-carrying roster spots per team, and **nothing here is
   fitted to salaries any more**. The hitter shape is the lineup rules (1 C —
   a league setting — 1 1B, 1 2B, 1 3B, 1 SS, 5 OF, a middle-infield slot split
   across 2B/SS, and Util). Util is a **leftovers slot**: a second draft pass
   fills whatever the position-less hitters don't take with the best spare
   hitters, and its replacement level is the best undrafted hitter *of any
   position*, because that is who would otherwise stand there. That is what
   makes a DH worth his bat but not his scarcity. H2H has no SP slots, so SP
   depth is derived from the 10-start weekly cap (`GS_CAP`, universal in
   Ottoneu H2H); `RP_SLOTS` is 6, roster
   practice rather than the lineup's 5, because a reliever appears in only ~40%
   of games.
2. **Replacement** — fill every spot best-player-first in one descending sweep,
   then replacement at a position is the best **undrafted** player eligible
   there. That's what the $1 tier actually offers you.
3. **PAR** = points − replacement, at the player's best eligible position.
4. **Reliability** — PAR is shrunk per role by `RELIABILITY` (SP 0.957,
   RP 0.61): realized over projected PAR across the ten-season bed, relative to
   hitters (`backtest.py --measure`). Projection side only. The option cushion
   the same measurement finds is deliberately not priced (§6.30).
5. **Dollars** — every spot costs ≥ $1, so `teams × (cap − roster_max)` is the
   discretionary pool, split proportionally to reliability-adjusted PAR.

Scoring comes free: FanGraphs returns `FPTS` and `SPTS` per player, so layer 1
reimplements no formula.

### Layer 2 — league value

What he's worth *here*, given who's locked up and what money is loose.

Layer 1 assumes the entire player universe is gettable. In a keeper league most
of it isn't — so the best **free** catcher is a different and worse player than
the best catcher, and that is what a replacement-level catcher is worth to you.
Layer 2 re-solves replacement against the available pool and rescales to real
free money.

**It is not a flat inflation multiplier, and that's deliberate.** A scalar
prorate preserves the base ranking exactly, so it could never surface that
catchers are scarce in your league — which is the entire reason the layer exists.
Validated against a simulated keeper deadline: inflation came out
position-specific (2B 1.35×, OF 1.25×, RP 1.22×), which a scalar cannot produce,
and the top-300 league values summed to **$1,695 against $1,690** of free money.

Layer 2 requires `data/teams_cap.csv` and reports "no open market" when rosters
are full. It is fundamentally an offseason/auction tool.

### Decision layer (rules-aware outputs)

- `keeper_surplus` — value minus **next year's** salary, after the retention
  raise. Never use current salary for keeper decisions.
- `keeper_npv` — the number to keep or cut on. Surplus over every season the
  measured aging table reaches (four), salary +$2 a year, a cut free at any
  offseason, each further season weighted by `keeper_discount` (0.5), solved
  backward. `keeper_surplus` is its one-year, un-aged
  approximation, and flatters every player over 30.
- `cut_gain` — cap dollars actually freed by a cut, minus production given up.
  In-season a cut leaves 50% of salary as a penalty, so it frees about half.

---

## 4. Current state (reference numbers)

Last measured 2026-09-10. **Supersedes every earlier figure** — if a number
elsewhere in this file or in `NEXT_STEPS.md` disagrees with this table, this
table is right and the other one is a fossil of how it got here.

### Live model, league 1297 (Steamer, `gs_cap` 10)

| Measure | Value |
|---|---|
| `pearson(base_value, salary)`, 432 rostered | **0.842** |
| Top-480 base values vs $4,800 cap | $4,797 |
| Players priced above $1 | 299 |
| $30+ salary tier, mean model − salary | +0.0 |
| Depth | C 12 · 1B 12 · 2B 18 · 3B 12 · SS 18 · OF 60 · Util 12 · SP 96 · RP 72 |
| Replacement | C 515 · 1B 570 · 2B 536 · 3B 561 · SS 561 · OF 471 · Util 570 · SP 553 · RP 351 |
| Model's dearest relievers | $17, $15, $14, $14, $14 |
| League cap total / loans net / penalties | exactly $4,800 / exactly $0 / $436 |
| Layer 2 sim — top-300 vs free money | $1,695 vs $1,690 |

### Ten-season Marcel bed (2015-19, 2021-25; ~1050 players/season)

| Measure | Value |
|---|---|
| `RELIABILITY` (ratio) | SP **0.957** (LOSO 0.92-1.00) · RP **0.61** (0.58-0.64) |
| Realized PAR per marginal $, raw / floored / refill | $30+ 7.6/8.4/9.2 · $15-30 6.4/8.9/9.7 · $5-15 1.6/12.8/12.0 · $2-5 −24.4/34.4/22.3 |
| Per-position ratio to hitters, floored | C 0.90 · 1B 1.16 · 2B 1.03 · 3B 0.82 · SS 1.04 · OF 1.06 · SP 1.02 · RP 0.98 |
| ...the same, refill | RP **0.63**, 3B **0.65**, the rest 0.96-1.10 — refill and floored disagree on RP |

### Cross-league market (averageValues, H2H FGPts, `backtest.py --market`)

A sanity check, not validation (§2) — read it for error that is monotone in price.

| Measure | Value |
|---|---|
| pearson vs Last 10 / avg salary, 423 players rostered in ≥ 50% | **0.881** / 0.887 |
| model − Last 10 by tier, $30+ / $15-30 / $5-15 / $2-5 / $1 | +0.3 / +1.0 / +1.5 / 0.0 / +0.3 — flat |
| Per-league spend on players | $4,148 of $4,800 (1297: $4,137 after penalties and unspent) |
| By position, model − avg, avg ≥ $5 | SP +4.6 · OF +4.6 · C +2.2 · 1B +1.9 · RP +0.6 · 2B −1.1 · 3B −1.8 · SS −2.5 |
| SP/hitters at the real `gs_cap` 10 | **0.95** |
| SP depth: fitted 7.7 vs derived from `gs_cap` | mean abs err **0.199** vs **0.165**, better in only 6/10 — inside the noise |

### Keeper NPV (live, league 1297; aging from `marcel.py --aging`)

| Measure | Value |
|---|---|
| Aging, floored PAR, k=1 / k=4, hitters | ≤25 0.98/0.85 · 26-29 0.94/0.54 · 30-33 0.72/0.21 · 34+ 0.57/0.02 |
| ...pitchers | ≤25 **0.65**/0.61 (n 100) · 26-29 0.77/0.41 · 30-33 0.75/0.37 · 34+ 0.62/0.20 |
| Positive one-year surplus but no multi-year surplus | 43 of 119 — Skubal, Skenes, Harper, deGrom, Y. Díaz, Nimmo |
| Ohtani | one-year +$34 → NPV +$1.7 (this season's dollars, discount 0.5) |
| Out-of-sample (`marcel.py --npv`) | aging holds (held-out ≈ in-sample, k1–k3); level misses by age at k=0 too (H ≤25 1.65 → 34+ 0.93): Marcel's age curve, not aging |
| Half-price salary: policy realized / predicted | ≤29 1.5–2.3x · 30-33 ~1 · 34+ loses money; hindsight 2–10x the policy |

### Superseded — kept so the reasoning isn't repeated

| Claim | Status |
|---|---|
| **"RP vs market +$3.4, the documented edge reproduces"** | **WRONG, and do not restore it.** It was only ever validated against market prices, which §2 says validates nothing. Ten seasons say relievers *underdeliver* per dollar (0.59 of the hitter rate) — the model was overpaying them, and the market was closer to right. Fixed by `RELIABILITY` (§6.28). |
| Slope + cushion: pearson 0.825, top 36 −16%, $30+ tier −6.8, RP ceiling $13 | lived one day; the cross-league market reproduced the monotone gap (§6.30) |
| SP 0.886 | the regression slope; put SP 10% cheap on the bed's own position table (§6.30) |
| `pearson` 0.838, RP ceiling $16, positions 0.86-1.14 on floored | `RELIABILITY = {"RP": 0.6}`, before it was measured |
| Tiers floored 8.0/8.2/11.8/37.1, raw 7.1/5.4/−0.2/−21.3 | pre-`gs_cap` 10; `{"RP": 0.6}` re-scored on today's tree is raw 7.6/6.4/1.6/−25.4, floored 8.4/8.9/12.9/33.4 |
| `pearson` 0.813 | pre-Util, pre-1B-phantom-fix, pre-`gs_cap` |
| RP/hitters 0.59, RP ceiling $26 | before reliability shrinkage |
| Steamer RoS 2025 spearman 0.643/0.708/0.515/0.391 | scores *Steamer*, not the model; the floor to beat, not a model measure |

---

## 5. Data access reality

**Nothing scripted gets into FanGraphs or Ottoneu.** Both sit behind Cloudflare
and 403 any non-browser client. This is settled, not a puzzle to solve:

- `ottoneu.fangraphs.com/{league}/rosterexport`, `averageValues` → 403
- `fangraphs.com/api/projections` → 403
- pybaseball `batting_stats()` → 403 on the same wall
- PyPI `fangraphs` (last published 2021, pins `playwright==1.10.0`) and
  `baseball_scraper` (2020) → both dead; the latter is a pybaseball fork using
  the same blocked path

**MLB's own data is open** and needs none of this. `statsapi.mlb.com` and
Baseball Savant answer plain scripted requests, which is why `backtest.py`
fetches actuals directly. Prefer these wherever they suffice.

**The model is bring-your-own-data, permanently.** League rosters and salaries
are the user's own data and only they can retrieve them. Projections are pulled
through the user's own browser session. This keeps us clear of redistributing
FanGraphs' licensed projections and avoids a single IP hammering the origin.

**Ottoneu and FanGraphs are the same company.** There's no playing one against
the other, and the downside of misbehaving includes the league account. Ask
before any public release.

---

## 6. What to avoid — the expensive lessons

Each of these produced confident, wrong output. Each has a selftest pinning it.

### Valuation logic

1. **Don't charge multi-eligible players to their scarcest position.** It runs
   away: charging every 2B/SS to SS is exactly what *makes* SS the deepest
   position. Result was a leaderboard of nothing but shortstops. Depth takes its
   shape from lineup rules instead.
2. **Don't recompute replacement from the currently-assigned pool.** That
   fixed-point iteration oscillates rather than converging — players pile onto
   whichever spot is momentarily cheaper, emptying the other and flipping the
   incentive next pass. One descending draft sweep has no feedback loop.
3. **A swingman is a starter.** Ottoneu lists many arms as SP/RP. Left
   dual-eligible they arbitrage into the cheaper pool and get paid twice for the
   same innings — which put four actual starting pitchers atop the "best
   relievers" list.
4. **Salary is a bad depth proxy at RP.** It works everywhere else, but reliever
   prices are compressed against the $1 floor, so filtering by salary measures
   what relievers *cost*, not how many teams carry. It cut RP depth to 1.6/team
   against a real 5-7 and priced good relievers at nothing.
5. **Don't chase correlation with salary.** See §2. Fitting the market perfectly
   is how you guarantee zero edge.

### Rules (all of these were in the rules doc and got missed anyway)

6. **Raw negative surplus is not a cut list.** In-season, a cut leaves 50% of
   salary as a cap penalty, so it frees about half. José Ramírez at $50/$32 value
   frees $25 while costing $32 of production — hold and shop him. 40 rostered
   players look like bad contracts but should not be cut.
7. **Current salary is not keeper cost.** Retention adds +$2 (+$1 for pure
   prospects). Across 147 rostered players at $1-3, mean surplus is +$0.4 against
   today's salary but **−$1.6** against next year's.
8. **IL spots grant no cap space.** Team pages report "Roster 43 of 43" because
   60-day IL players stop counting in-season, but those spots come with no money.
   The $1-per-open-spot reserve is measured against 40.
9. **The roster export cannot produce cap space.** Loans (one team's real cap is
   $633, not $400), cap penalties, and the true roster max live *only* on the
   team page. A naive $400/40 assumption produced a team at −$180 cap space.

### Access and tooling

10. **Don't lift `cf_clearance` or use TLS-impersonation libraries.** It's
    bot-protection circumvention — fragile (IP/UA-bound, short-lived) and a
    materially worse legal and relationship posture than being rate-limited.
11. **Don't sweep league IDs.** That's exactly the automated polling Ottoneu says
    it will IP-block. Own league only.
12. **Don't reach for a scraping library.** All three candidates are dead or
    blocked (§5). Only a real browser gets through.
13. **FanGraphs' `FPTS` column doesn't reproduce from their exported
    components** (~1% off). Never mix their column on one side of a comparison
    with a computed formula on the other — compute both sides the same way. The
    documented weights are correct; least squares over 473 hitters recovers them
    and finds no missing term.
14. **`innerText` returns nothing on a `DOMParser` document** — it needs layout.
    Use `textContent`.
15. **Chrome blocks the 2nd+ automatic download per origin.** A fresh tab group
    resets it. For small payloads, skip the download and return the data.
16. **The browser extension blocks returning raw HTML or query-string data.**
    Extract the values you need in-page and return only those.

### Measuring the model (everything below came out of the ten-season test bed)

17. **Low realized PAR per dollar means that tier is OVERpriced, not
    underpriced** — and the depth remedy runs opposite to the intuition:
    *shallower* depth raises replacement, which cuts marginal players' PAR and
    pushes dollars toward the top. `NEXT_STEPS.md` carried this mapping
    inverted in both directions until 2026-09-09. The corrected table lives in
    Task 1 there.
18. **Raw realized PAR is not a fair yardstick below ~$5.** A cheap player who
    loses his job scores roughly −replacement (hundreds of negative points) with
    no symmetric upside, but no owner eats that — you cut him and the spot
    reverts to replacement. `backtest.py --dollars` reports raw *and*
    zero-floored PAR precisely because they disagree in sign down there. Raw
    alone says cheap players are badly overpriced; floored alone says badly
    underpriced. Neither is evidence on its own.
19. **The top price tier is selected on projection optimism.** Model value is a
    function of the projection, so regression to the mean produces a mild droop
    at the top even under perfectly correct pricing. Don't read a small top
    droop as a finding.

20. **Validating on the league you fitted to proves nothing about generality.**
    `BASE_SP`/`BASE_RP` were fitted to league 1297's salaries and the dollar
    calibration (§4) says pricing is proportional — on league 1297. Those are
    the same league. The check that would mean something is a cross-league
    sample (`averageValues`) or a depth number derived from format settings.

21. **Two "rules" are actually league settings, and the rules doc asserted both
    ways.** Catcher slots (1 vs 2) and whether the seasonal position games cap
    applies. Both were written as universals; neither is. The 22-starter
    arithmetic (1+1+1+1+1+5+1+1+5+5) only closes with one catcher, which is what
    exposed it. Anything that reads like a universal but has a league-settings
    page behind it needs pulling per league — see the checklist at the top of
    the rules doc.

22. **A pitcher is only ever a pitcher.** Marcel's +200 PA playing-time floor
    pushed every NL pitcher's batting line past `MIN_PA`, and with no mappable
    fielding position they all fell through a `or ["1B"]` default — putting 1B
    replacement at 981 against C's 495 and mispricing every real first baseman.
    `value.py` carried the same default. Both now drop position-less hitters
    instead of inventing one, and `marcel.py` additionally excludes
    `primaryPosition == "P"` outright. MLB tags genuine two-way players `TWP`
    in every season checked (2018-2025), so the hard guard never eats a real
    two-way bat.
23. **Inventing a position is worse than dropping a player.** A phantom first
    baseman doesn't just misprice himself, he raises replacement level for
    everyone actually eligible there. When a player has no slot in the modelled
    lineup, say so — `value.py` prints who it's ignoring.

24. **A playing-time floor is a per-role constant, not a global one.** Marcel's
    published `+60 IP` is a *starter's* number. Applied to relievers it
    projected them at ~99 IP against a real ~65 — at 7.4 points an inning that
    inflated every reliever by ~250 points, put projected RP replacement at 541
    against a realized 392, and made the model look like it overpriced
    relievers by 2x. The floor is one third of a full workload for the role
    (200/600 PA = 60/180 SP innings = 22/65 RP innings), and the selftest pins
    that ratio.
25. **A position that underdelivers per dollar is not automatically a depth
    error.** Depth moves the projected *and* realized replacement level
    together, so it reallocates dollars and realized PAR at the same time.
    Halving RP depth made RP's realized-PAR-per-dollar *worse* (0.58 -> 0.38 of
    the hitter rate), not better. What that pattern actually says is that
    reliever *projections* are less reliable than everyone else's — and no depth
    constant can fix a projection-accuracy problem. The remedy for unreliability
    is shrinkage toward the mean, which is the same machinery as the option-value
    work.
26. **The bust-floored metric is depth-sensitive.** Raising replacement pushes
    more players below zero, and flooring discards them, so the mean shrinks for
    reasons that have nothing to do with pricing. Compare positions *at a fixed
    depth*; never compare one position across depth settings.

27. **A projected starter with RP-only eligibility is still a starter.** The
    "Ottoneu eligibility beats the guess" override runs the wrong way for
    pitchers: eligibility says where he may legally be slotted *today*, the
    projection says what he will actually *do*. Joe Musgrove, projected for 25.9
    starts and 149.6 innings but carrying RP-only eligibility on the way back
    from surgery, was demoted to RP and priced against the reliever replacement
    level (349 rather than 553) — making him the most valuable "reliever" in the
    league at $29 against a $5 market price. He requalifies as SP after five
    starts anyway (rules line 22). Trap 3 in a different hat: never let a
    starter's workload be paid at a reliever's replacement level. `main()` now
    prints who it kept at SP.

28. **Dollars-in-proportion-to-PAR assumes every position's projections are
    equally trustworthy.** They are not, and nothing in the pricing math notices.
    Relievers are the least predictable population in the format — roles turn
    over, innings are few, and saves and holds follow a job title rather than a
    skill — so their projected spread is far wider than reality delivers and
    pricing straight off it overpays all of them. The fix is shrinkage
    (`RELIABILITY`), applied to the **projection side only**: realized production
    is not a forecast and needs no haircut. Putting it inside `price()` would
    silently shrink the realized side too and destroy the very measurement that
    justified it.

29. **A per-dollar tier table re-buckets when pricing changes, and the
    intercept dominates its bottom rows.** Two separate traps that look like
    one. First: if `E[realized | projected] = a + b·PAR` has any intercept,
    proportional pricing cannot be flat per dollar — `a / small $` blows up in
    the cheap tiers whatever the pricing. The sign of `a` is the whole story:
    raw has a < 0, so cheap looks overpriced; floored has a > 0, so cheap looks
    underpriced. Second: pricing the intercept (the option cushion) moved ~50
    ex-$1 players a season into $2-5, and their busts widened that tier's
    raw-to-floored gap from 58.8 to 65.4 — while on the *same players* it
    narrowed to 35.0 in 10 seasons out of 10. When judging a pricing change,
    bucket both runs by the **old** price.
30. **An option value everyone has is worth nothing at the margin.** The
    refill cushion is real — every rostered player's missed time goes to the
    bench — and pricing it made the bed's cheap tiers look right. But the
    replacement-level alternative carries the same cushion, and with a fixed
    pool the money came off the stars: −16%, and a −$7 gap at $30+ against
    league 1297 *and* against the cross-league averageValues market, monotone
    in price. It is measured and printed by `--measure`, and not priced.
    Corollary: with the intercept out, the factor proportional pricing has to
    equalize is realized over projected PAR in aggregate — a **ratio of sums,
    not a regression slope**. The slope (SP 0.886) put SP 10% cheap on the
    bed, and its only support was agreeing better with the market.
31. **Age value, not points — and measure each horizon directly.** Keeper NPV
    first aged expected points and then subtracted a full replacement level.
    A pitcher's ~22% expected drop in points is mostly the chance he's hurt or
    gone, which costs his *value*, not a healthy season at 78%. Value is convex
    in points, so the leverage turned 22% into ~45%, and the model said to cut
    Skenes, Skubal and Ragans — 87 of 119 one-year keepers. The ratio is now of
    floored realized PAR (the `RELIABILITY` basis), applied to PAR.
    Separately, chaining a measured one-year multiplier overstated later
    seasons by up to a third, because year-to-year pairs are mostly survivors;
    every k is measured directly.
32. **A keeper backtest's error by age belongs to the base projection until
    k = 0 says otherwise.** Aging ratios are realized over realized, but they're
    applied to *projected* PAR, so realized/predicted at every k is close to
    Σ realized(Y) / Σ projected(Y). The out-of-sample NPV test missed by 1.6x
    for the young and 0.85x for the old at every horizon, which reads like an
    aging failure. k = 0 showed the same pattern: Marcel's age curve, not
    aging. Check the base season before blaming the horizon. **Confirmed
    2026-09-12** once historical Steamer existed to check it against
    (`marcel.py --age-check`): Marcel's k = 0 bias is steeply monotone by age
    (H 1.66→0.93, P 1.97→0.93 across the four bins); Steamer's is flat by
    comparison (H 1.15-1.18, P 1.10-1.42, not monotone). The bias really was
    Marcel's, not a property every projection carries — no age-bias factor
    belongs in the engine.

---

## 7. Open questions and roadmap

> The actionable queue lives in [`NEXT_STEPS.md`](NEXT_STEPS.md) — start there.

**Settled 2026-09-09:** `backtest.py --dollars` now scores the dollar values,
not Steamer. Over 867 players from the 2025-05-24 snapshot, realized PAR is
proportional to marginal model dollars across the $5+ range (intercept −34 raw /
+20 floored, against a $30+ tier that realizes ~200). The depth constants are
not measurably wrong. This was the project's first non-circular measurement;
everything before it was either an arithmetic identity or agreement with the
market. Details and the corrected curvature mapping: `NEXT_STEPS.md` Task 1.

**Settled 2026-09-12, a second and stronger non-circular measurement:** a
synthetic-league Monte Carlo (`marcel.py --league-sim`) runs value.py's own
$values in a real one-shot $400 auction against two deliberately worse
strategies (raw points, no scarcity or reliability adjustment; random), then
plays the real season out. Value beats points beats random on the Steamer bed
(15.33 vs 13.80 vs 12.28 mean wins of 28, 500-trial Monte Carlo) — the first
evidence that the model's adjustments predict actual winning, not just flatter
PAR per dollar. Conditional on projection quality, though: the same test on
the deliberately-worse Marcel bed inverts (value is the *worst* strategy,
13.35 vs 14.05/14.00) — scarcity-aware pricing amplifies whatever the
per-player projection says, for better or worse. `NEXT_STEPS.md` Task 11.

**Settled 2026-09-12: a per-position market review, one real fix, one real
non-fix.** Every position checked the same way (model $ vs cross-league
`average_values.csv`, by price tier, watching for a monotone-in-price gap
isolated to one position). Catcher and SP both showed a large top-tier gap;
only catcher got a second, independent signal (the ten-season bed's own
realized/projected PAR ratio, 0.852 relative to other hitters) — so only
catcher got fixed (`RELIABILITY["C"] = 0.852`). SP's gap (bigger, 16x the
sample) survived three separate attempts to corroborate it in realized
outcomes (bust rate, refill ratio, ratio-of-sums at the top all read like
hitters') and was left alone, explicitly logged rather than priced — the same
shape as the disproven RP claim (§4), and the same discipline applied.
Resimulating the Task 11 synthetic league after the catcher fix showed no
material change (15.31 vs 15.33 for `value`) — expected, since one roster
slot out of 40 is too small a lever for a whole-season win-rate metric to
see; the market table, not the league sim, is the right instrument for a
single-position correction. `NEXT_STEPS.md` Task 12.

Still open:

- Layer 2 has never run against a **real** open market, only a simulation. Needs
  a live check at the next auction.
- ~~Relievers underdeliver per dollar in 10 seasons out of 10~~ — **closed
  2026-09-10** by the measured `RELIABILITY` (RP 0.61; floored ratio to
  hitters 0.98). On the refill basis RP is still 0.63 — the two bases disagree.
- ~~The option cushion costs stars 16%~~ — **closed 2026-09-10**: unpriced
  after the cross-league check (§6.30).
- **Arbitration's per-player split is an assumption, not a rule.** The
  allocations method (confirmed for league 1297) caps what each *team* receives,
  never what a player receives. `arb_allocations` spreads it proportional to
  surplus; if allocations really concentrate on one target per team, cheap
  keepers are fine and the top bargains are worse than modelled. Check at the
  next arbitration.
- ~~Everything is still validated on one league~~ — **cross-league market check
  done 2026-09-10** (`backtest.py --market`): flat in price. Still a market
  comparison, never validation. Position residuals (SP and OF +4.6, SS −2.5)
  are candidate edges. The 10-start cap is universal, so SP's is not an
  artefact of an assumed setting.
- ~~Marginal starts are priced at full value~~ — **closed 2026-09-11**
  (predicted from depth alone) **and quantified 2026-09-12** by the weekly
  lineup simulation: the GS cap costs SP ~1.6-1.7% of relative realized value
  (season-total-equivalent 0.982 → capped 0.966 on Steamer). Small, as
  predicted, because depth (8 × 1.25 starts) already sits at the cap on
  average. `NEXT_STEPS.md` Task 9/10.
- **RP_SLOTS 5 vs 6 and refill vs floored on RP: direction settled, magnitude
  still open.** The roster-size question is still a coin flip on the
  season-total bed (0.57 vs 0.59). The lineup simulation (built weekly, then
  rebuilt at daily granularity once the league owner confirmed Ottoneu allows
  daily lineup changes — a week-locked bench understated it) confirms the
  *direction* both open questions pointed at: floored's season-total
  `RELIABILITY` (0.803 Steamer) overstates what a bench-constrained team
  actually captures, and the mandatory 5-of-6-active rule costs real value on
  top of it, at every activation-signal window tested. It does **not** settle
  the magnitude: RP5 swings 0.53 to 0.75+ (relative to hitters) purely on the
  trailing-days window used to decide who's active, with no asymptote found
  short of RP6's ceiling — see the sweep in `NEXT_STEPS.md` Task 10. A trailing
  points average is too weak a proxy for what a real GM knows (probable
  pitchers, save situations); the fix is a better signal, not a better window.
  **`RELIABILITY["RP"]` stays at the season-total 0.803** — an honest,
  reproducible measurement — until one exists. `NEXT_STEPS.md` Task 10.
- Seasonal games caps (162/hitter, 810 OF) aren't modelled; `value.py` warns
  rather than emitting uncapped hitter values for a league that uses one.
- ~~`1B` is the largest positional disagreement with market (−$7.3)~~ —
  **closed 2026-09-10: it was a flaw, not an edge.** DH-only hitters were
  defaulting to 1B and the lineup had no Util slot, so 1B replacement sat at 691
  against a real 570. With Util modelled the whole positional spread tightened to
  +2.5 (OF) .. −2.6 (SS), and 1B is now +2.1.
- ~~Prospects with no projection get no value~~ — **closed 2026-09-12**:
  `value.load_prospects()`, a flat judgment-call value by rank tier (owner's
  numbers), BYOD from a ranked list. `NEXT_STEPS.md` Task 13.
- ~~Intraseason bid/trade/cut use is unverified~~ — **closed 2026-09-12**:
  `base_value`/`surplus`/`cut_gain`/`keeper_npv` carry no full-season
  assumption, confirmed against a realistic-scale rest-of-season-collapse
  scenario (a real $38 preseason ace scaled to a 15%-of-pace year correctly
  crashed to the $1 floor with `cut_gain` +$18). Layer 2's mid-season silence
  is correct behavior (no roster spots open), not a gap. `NEXT_STEPS.md`
  Task 13.

---

## 8. Decisions log

| Decision | Rationale |
|---|---|
| BYOD for league data, permanently | Only the user can retrieve it; sidesteps redistribution entirely |
| stdlib only, `py -3.13` | Default 3.15 alpha has no pandas wheels; the job doesn't need a dataframe |
| Use FanGraphs' `FPTS`/`SPTS` in `value.py` | They already compute it; no formula to reimplement |
| Compute FGPts from components in `backtest.py` | Both sides must use one formula (§6.13) |
| Replacement = best *undrafted*, not Nth-best | It's the literal definition of what $1 buys |
| Base/league split rather than a prorate | A scalar can't express league-specific scarcity |
| Join on FanGraphs id; MLBAM id for statsapi | Both are carried in the exports; no crosswalk needed |
| Don't buy sportsdata.io ($100/mo) yet | Replaces the layer that's already free and open; can't supply Ottoneu data at all |
| Report raw *and* zero-floored realized PAR | They disagree in sign below $5; a roster spot is an option, not an obligation |
| Solve replacement inside each pool in `--dollars` | Keeps projection and realized sides on the same rest-of-season basis (§6.18) |
| League settings in `data/league.csv`, not constants | Teams/cap/roster/scoring/arbitration vary per league; the engine must price any of them from one edited file |
| Util is a leftovers slot, filled in a second pass | Making every hitter Util-eligible would funnel the league into the scarcest opening (§6.1); a DH is priced against the best *spare hitter of any position*, which is why he keeps his bat and loses positional scarcity |
| Derive SP depth from the weekly GS cap; `BASE_SP` deleted | The derivation is *not* measurably more accurate (0.165 vs 0.199, 6/10 seasons — inside the noise); it is adopted because it comes from the rules instead of one league's salaries. The cap is 10 in every Ottoneu H2H league (owner, 2026-09-10), so it is a rule (`GS_CAP`), not a setting |
| Shrink RP projected PAR by 0.6, don't cap RP at $15 | A cap hits the same ceiling while leaving the middle of the reliever curve wrong; shrinkage fixes the whole curve and the ceiling falls out as a consequence ($26 -> $16) |
| `RELIABILITY` is a property of the projection, not the league | Re-measure per projection source (`backtest.py --measure`); Steamer handles relievers better than Marcel — measured directly 2026-09-12 (SP 0.986, RP 0.803) once historical Steamer existed, up from the Marcel-proxy SP 0.957, RP 0.61 |
| `RELIABILITY` is a measured ratio per role — floored realized / projected PAR, relative to hitters | It is the quantity proportional pricing equalizes; a regression slope with an intercept is not (§6.29-30). The Marcel-proxy RP 0.61 recovered the hand-fitted 0.6; measured on Steamer itself it's 0.803 |
| The option cushion is measured, not priced | Everyone at the margin has it; pricing it cost stars 16% and opened a −$7 gap, monotone in price, against the cross-league market (§6.30) |
| Report a refill basis (`rPAR~`) beside raw and floored | Raw and floored are bounds; refill is mechanical (vacated time refilled at replacement) and has no knob |
| Run `backtest.py --market` after any pricing change | Market agreement validates nothing, but error monotone in price across *every* league of the format is a flaw signal one league can't give |
| Keeper NPV by backward induction, cut free each offseason | Offseason cuts cost nothing (rules), so declining years are cut rather than paid: V = max(0, surplus + d·V_next) |
| `keeper_discount` 0.5, a preference in `league.csv` | Owner's call: four seasons at full weight over-valued the distant future given roster turnover. Not measured and not a league setting — it's the manager's horizon. Weights are relative to this season, so next season already counts 0.5 and NPV is in this season's dollars |
| Aging on floored realized PAR, each horizon measured directly, 4-year bins | Points-then-replacement and chaining both gave confident wrong answers (§6.31); floored matches `RELIABILITY`; 2-year pitcher bins were non-monotone at n 100-300 |
| Birthdates via Steamer `xMLBAMID` → statsapi | Steamer's JSON carries the MLBAM id for every player and statsapi is open, so no name matching |
| Hitters pooled into one role, except catcher | Per-position hitter slopes swing −0.8 to 2.8 season to season; ten seasons can't separate them on their own. Catcher is the one exception (2026-09-12): a real-money cross-league market gap *and* the bed's own floored ratio agreed (0.852 relative to other hitters), which is the two-signal bar every other hitter position still hasn't cleared |
| A market disagreement needs a second, independent signal before it's priced | SP shows the same shape as catcher's gap (bigger, 16x the sample) but bust rate, refill ratio, and ratio-of-sums at the top all read like hitters' — no corroboration despite looking, so it stays unpriced and logged, not fixed. Repeating the disproven RP "underpriced" mistake (§4) in the opposite direction would be acting on market agreement alone, which validates nothing either way |
| Pitcher role comes from the projection, never the roster export | Eligibility says where he may be slotted today; only what he actually does scores points (§6.27) |
| `RP_SLOTS = 6` — roster practice, not the lineup's 5 | A reliever appears in ~40% of games, so 5 arms cannot keep 5 slots busy; 6 is standard practice across the format. Neither derived nor fitted: observed, and a property of the format rather than of one league. The bed cannot tell 5 from 6 apart on roster size (0.57 vs 0.59); the lineup sim confirms the mandatory 5-of-6-active rule costs real value on top of that but can't yet pin how much (`NEXT_STEPS.md` Task 10) |
| `catcher_slots` and `games_cap` are settings, not constants | Both were written as universals in the rules doc and are not (§6.21) |
| Warn on `format != h2h` rather than emit values | Season-long points leagues are governed by an innings cap, not a weekly GS cap; H2H-shaped pitcher values would be silently wrong |
| Vote-off arbitration returns `{}`, not a guess | It is a different mechanism, not a different number |
| Model arbitration take as a clamped share of team surplus | The rules bound it to $11-$33 per roster; bargain-heavy rosters draw the max |
| Spread arbitration proportional to surplus, not greedily | 11 managers choose independently, so the aggregate spreads; flagged as the one unruled assumption |
| No age-bias factor from the bed | The out-of-sample NPV test's miss by age is Marcel's age curve (visible at k = 0), a property of the projection, not aging — confirmed 2026-09-12 on historical Steamer, whose k = 0 bias is flat by comparison (§6.32) |
| Weekly lines cached per calendar week, from `stats=byDateRange` | One call per week for every player (~27 a season) rather than a game log per player (~1,500); calendar weeks because merging is a lossless sum, so Ottoneu's odd weeks are the reader's call. `--weekly` checks the sums against season totals |
| Marginal starts not priced, but quantified | GS-cap depth already makes the average week's starts fit the priced 8 slots, so a season-total correction would be a fitted guess; the lineup sim measured the real cost directly instead (~1.6-1.7% of SP's relative value) |
| Synthetic 12-team staffs for the lineup sim, snake-drafted by preseason rank | No historical Ottoneu roster export exists for these seasons; a snake draft off the same pool the season-total bed already prices matches the depth constants exactly, so the comparison isn't also silently changing the priced player universe |
| Lineup-sim bench decisions from trailing signal only, never that period's own result | A GM can't see today's line before setting it; SP benches the worst-*preseason*-ranked arm first when a week's starts exceed `GS_CAP` (cold: preseason projection), matching the project's no-hindsight standard elsewhere (`--npv`'s held-out tables) |
| RP lineup-sim mechanic rebuilt daily, not weekly | Ottoneu allows daily lineup changes (owner, 2026-09-12); a week-locked active-5 is stricter than real play and understated RP reliability. `marcel.py --weekly` now also pulls/validates a daily pitching cache (`data/mlb/YYYY_pitching_daily.json`) |
| RP5's number not folded into `RELIABILITY` despite the rebuild | Sweeping the daily trailing-days window 1-90 swings RP5 0.53-0.75+ with no asymptote short of the no-bench ceiling — a trailing-points average is too weak a stand-in for real role information (probable pitchers, save situations), so the window picked would be picking the answer, not measuring it |
