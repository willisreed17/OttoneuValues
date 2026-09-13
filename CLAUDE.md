# CLAUDE.md

Ottoneu H2H points valuation tool. Keep this file short — it is auto-loaded every
session, so anything that belongs in a doc belongs in the doc, not here.

## Read first

1. `NEXT_STEPS.md` — the current work queue and the open question for the user.
2. `APPROACH.md` — **required before changing valuation logic.** §6 lists 32
   traps that each already produced confident, wrong output. Several are
   non-obvious; every one cost a wrong answer once.

`README.md` is how to run it and how to refresh each input CSV.

** After each update made, review and if necessary revise the 'Next_Steps.md' and 'Approach.md'

## The valuation engine is locked

`value.py`, `backtest.py`, and `marcel.py`'s pricing logic — layer 1/2,
`RELIABILITY`, depth constants, keeper NPV — was verified as of 2026-09-12
(per-position market review, a synthetic-league Monte Carlo, an intraseason
check; `APPROACH.md` §7, `NEXT_STEPS.md` Tasks 11-13). **Do not change
pricing logic, a constant, or a `RELIABILITY` value — for the web app, a
"quick fix," or anything else — without a full analysis that clears the bar
already set in this project:**

- **One signal is never enough.** A market disagreement alone proves nothing
  (APPROACH §2) — that's the exact shape of the disproven "RP underpriced"
  claim (§4). SP shows a real, large, well-sampled market gap today and was
  deliberately left unpriced for exactly this reason (§7, `NEXT_STEPS.md`
  Task 12). Wanting a number to move is not evidence that it should.
- **The bar that clears it: two independent signals agreeing** — a measured
  realized-outcome ratio (`backtest.py --measure`) *and* a real-market or
  structural corroboration. That's what got catcher's `RELIABILITY` fixed and
  is why SP's wasn't, despite SP's gap being bigger. Match that standard, not
  a weaker one.
- **Before and after any change:** `value.py --selftest`, `backtest.py
  --selftest`, `marcel.py --selftest`, `backtest.py --market` (watch for
  error that's monotone in price, not just its sign), and — for anything
  touching `RELIABILITY`, depth, or positional scarcity — `marcel.py
  --league-sim` (does `value` still beat `points` beats `random`?). Record
  the before/after numbers in `NEXT_STEPS.md`; a change without them didn't
  happen as far as the next session is concerned.
- **If the two-signal bar isn't cleared, log the disagreement and stop** —
  don't act on it, the way SP's is logged. A UI bug report, a "this number
  looks off," or your own read of the market is a reason to *investigate*,
  never a reason to *change* something on its own.

The web app is a consumer of this engine's output. Building it is never a
reason to touch pricing logic.

## Environment

Run everything with `py -3.13`. The default interpreter is Python 3.15 alpha with
no pandas wheels — which is why both scripts are stdlib-only. Keep them that way.

Verify health before and after changes; all three should print `selftest ok`:

```
py -3.13 value.py --selftest
py -3.13 backtest.py --selftest
py -3.13 marcel.py --selftest
```

`marcel.py` builds the ten-season test bed from statsapi (cached in `data/mlb/`,
gitignored). To score a pricing change:
`py -3.13 backtest.py --dollars --backtest out/backtest_2024.csv` — the
**by-assigned-position** table is the only view that can see a depth or
reliability error; the price-tier table averages across positions and hides it.

`keeper_npv` needs `data/aging.csv` and `data/birthdates.csv`: rerun
`py -3.13 marcel.py --aging` after every projection refresh (the Steamer export
must carry `xMLBAMID` — see the README recipe).

## Hard constraints

- **FanGraphs and Ottoneu are behind Cloudflare and 403 every scripted client**,
  pybaseball included. Don't try to script them, don't reach for a scraping
  library, don't lift `cf_clearance`, don't sweep league IDs. Data is
  bring-your-own via the browser; refresh recipes are in `README.md`.
- `statsapi.mlb.com` and Baseball Savant *are* open to plain requests. Prefer
  them wherever they suffice.
- Market prices calibrate, they don't validate. A model tuned to fit salaries
  finds no edge by construction. See `APPROACH.md` §2.
- **The target is an engine for any Ottoneu points league, not a model of league
  1297.** Anything that varies between leagues goes in `data/league.csv`, never
  into a constant. **Nothing in the engine is fitted to anyone's salaries any
  more** — `BASE_RP` is gone (RP depth is roster practice, 6), and so is
  `BASE_SP`: the 10-start weekly cap is universal in Ottoneu H2H (`GS_CAP`, a
  rule). Don't reintroduce a fitted constant. `APPROACH.md` §2 has the rule/setting/fitted
  distinction; the rules doc opens with the checklist of settings to pull.
- **Two rules that read like universals are league settings**, and the rules doc
  contradicted itself on both until 2026-09-09: **catcher slots** (1 or 2 — C
  depth doubling moves catcher values more than any other lineup change) and
  **whether the seasonal position games cap applies**. Pull both per league.
  League 1297: 1 catcher, no position cap.
- **A pitcher's role comes from the projection, never the roster export.**
  Eligibility says where he may be slotted today; only what he actually does
  scores points. The export is wrong in both directions and both are expensive —
  see `resolve_positions()`, which is selftested with the three live cases.
  Do not "restore" the old `Ottoneu eligibility beats the guess` override.
- **`RELIABILITY` describes the projection, not the league.** It shrinks
  projected PAR per role (SP 0.975, RP 0.794, C 0.852), measured directly on
  historic Steamer by `backtest.py --measure "out/backtest_20*_steamer.csv"`
  (built via `marcel.py --steamer`) as a ratio of sums, not a regression
  slope. Apply it to the **projection side only** — putting it inside
  `price()` would shrink realized production too and destroy the measurement
  that justifies it. Re-measure if the projection source changes. Hitters are
  pooled into one role except catcher (2026-09-12, two independent signals —
  see "the valuation engine is locked" above); adding another hitter position
  needs the same bar, not just a market disagreement.
  **Don't price the option cushion** `--measure` also prints (APPROACH trap 30).
- After any pricing change, run `backtest.py --market` (cross-league
  averageValues). Look only for error that is monotone in price.
- **The old "relievers are underpriced, +$3.4 vs market" edge was disproven**
  and must not be restored. It rested entirely on market agreement. §4 carries
  the superseded table so the case isn't re-argued.
