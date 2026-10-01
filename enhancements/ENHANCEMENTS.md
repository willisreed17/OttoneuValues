# Enhancements — in-season data, and next-year keeper values

Written 2026-09-19. All paths below (`data/`, `out/`, `value.py`) are inside `engine/`, and engine commands run from there. Two planned enhancements, prompted by Chase Burns showing
Keeper NPV $0. **Update 2026-09-23:** #1 is built (`combine_ros.py`, never yet run on a
real ROS export). #2's "real gap" (September until next year's projections exist) is
covered by `engine/next_season.py`: see `engine/NEXT_STEPS.md` Task 16. Line references below came from read-only
planning passes and were not re-verified; check them before relying on them.

**Order matters: do #1 first, then re-check Burns, then decide whether #2 is
needed at all.**

## Why

`data/steamer_pit.csv` has Burns at 114 IP / 530.8 pts (a preseason-style
projection). His 2026 actuals are 154 IP / 809 pts. The engine prices whatever
`pts` is in the file, so it never sees what he has done: value above replacement
-22.1, base value $1 (the floor), next salary $12, so every future season is
negative and `keeper_npv` sits at $0.

Two separate problems are mixed in that one number:

- **(a) A stale input.** Fixed by #1 (data only).
- **(b) The young-pitcher aging ratio** (`data/aging.csv`, P age<=25, k=1 is
  0.65, no growth credit). That is a pricing constant, locked (#2).

## Constraints that apply to both

- The engine is locked: `value.py`, `backtest.py`, `marcel.py` pricing logic,
  `RELIABILITY`, depth constants, keeper NPV. See `CLAUDE.md`.
- FanGraphs and Ottoneu are Cloudflare-blocked. Rest-of-season projections are
  a manual browser export. `statsapi.mlb.com` is open.
- Scripts stay stdlib-only, run with `py -3.13`.
- Before and after any change: the three `--selftest`s (`selftest ok`),
  `backtest.py --market`. Record numbers in `NEXT_STEPS.md`.

---

## Enhancement 1 — combine actuals with rest-of-season projections

**Goal:** a data-prep script that writes a season-to-date + rest-of-season file in
the existing `steamer_*.csv` format, so in-season pricing reflects reality. No
engine change.

**Script:** `combine_ros.py` (new, stdlib-only, separate from the engine).

**Inputs**
- `data/ros/steamer_pit.csv`, `data/ros/steamer_bat.csv`: manual FanGraphs ROS
  exports, including `xMLBAMID`. Hitters also need the `minpos` column.
- 2026 season totals from statsapi (hitting and pitching).
- Current `data/steamer_*.csv` as a fallback for position fields only.

**Outputs** (never written to `data/` by the script)
- `out/ros/steamer_pit.csv`, `out/ros/steamer_bat.csv`: headers identical to
  the current files.
- `out/ros/report.csv`: per player, actual pts, ROS pts, combined pts, status
  flags, realized share.
- You diff the report, back up `data/steamer_*.csv`, then copy the files over.

**Design**
- **Join key:** `xMLBAMID` only. Carry FanGraphs `playerid` from the ROS file.
  Never join on name; log IDs missing on either side.
- **Actual points:** fetch fresh via `marcel.pages(...)`. Do not use the cached
  `fetch_stats`/`season_stats` path: `cached()` never refetches, so a 2026 file
  goes stale silently. Convert with `marcel.our_stats` (handles IP thirds), score
  with `bt.points(stats, bt.PIT_W / bt.BAT_W)`; SABR with `bt.SABR_PIT_W`.
  One scoring formula on both sides (APPROACH trap 13).
- **ROS points:** recompute from the ROS file's raw components with the same
  `bt.points`, not its FPTS column. Report a warning if recomputed vs FPTS
  differs by more than about 1%. ROS IP is a true decimal; do not apply the
  thirds conversion to it.
- **Combine:** points additive; `IP`, `G`, `GS`, `SV`, `HLD`, `PA` summed.
  Hitters: `minpos` from ROS, else preseason, else `marcel.hitting_pos`.
  Team from the ROS row (handles trades).
- **Role:** combined `GS` decides SP vs RP (`value.py` `resolve_positions`).
  Flag rows where role by actual GS differs from role by ROS GS (a reliever
  moved into the rotation mid-year); default to combined, you override.

**Edge cases:** actuals but no ROS row (IL, released, callup) keep actuals and
flag `no_ros`; ROS but no actuals keep ROS and flag; prospects still need
`MIN_IP=20` / `MIN_PA=100` on combined totals, else they fall to
`data/prospects.csv`; Ohtani appears in both files and `load_projections`
sums them, so verify no double count; duplicate MLBAM rows keep the first and
warn; zero-IP/zero-PA rows dropped.

**The RELIABILITY trap (important).** `apply_reliability` shrinks PAR by
`RELIABILITY` on the *projection* side only, because realized production needs
no shrinking. Feeding combined points through the engine shrinks the realized
share too. Small for SP (0.975), larger for RP (0.794) and C (0.852): late in
the season an RP's PAR is mostly realized yet still cut about 20%. This cannot
be cancelled by inflating points, since replacement level is subtracted inside
the engine. **Decision:** leave the engine locked, print each position's
realized share in `report.csv` so the bias is visible, and log a deferred
follow-up (an opt-in realized-points field) in `NEXT_STEPS.md`. Also note
`keeper_npv` ages `pts` as if it were a projection; a mostly-realized season is
a noisier base, so late-season Keeper NPV is provisional.

**Tasks**
1. Fresh statsapi fetch and actual points, both groups (S)
2. ROS loader, MLBAM join, pitcher combine, role-flip flagging (M)
3. Hitters, `minpos` fallback, Ohtani case (M)
4. `report.csv` and the FPTS sanity check (S)
5. Script self-check assertions (IP thirds 45.2 -> 45.667, additivity, two-way
   sum) and a README "Mid-season" recipe (S)
6. Validation run (S)

**Validation**
- Selftests print `selftest ok`; `git status` shows only new files.
- `backtest.py --market` output identical before and after.
- Burns: combined at least 809 pts; value and Keeper NPV no longer $0.
- SP top-20 before vs after: expect hot arms up, injured aces down; no reliever
  wrongly promoted to SP.

**You supply:** a fresh ROS export (hitters and pitchers, with `xMLBAMID`)
whenever you want a refresh; decisions on role-flip and unmatched-ID rows; the
final copy over `data/steamer_*.csv` (keep a backup).

**Open question:** `value.py` reads `data/`; no data-directory flag was found.
To compare before and after you run `value.py` on either side of the copy.
Confirm before promising a flag.

---

## Enhancement 2 — keeper values on next-draft-year projections

**Status (2026-09-23): the gap is covered by `engine/next_season.py`** (next-season projection, ZiPS if post-season else age-corrected Marcel, own measured constants, NPV timing fixed; Keepers page defaults to it). Burns: $38 / NPV $13.2. `NEXT_STEPS.md` Task 16.
**Earlier status (2026-09-19): investigated; bar not cleared; logged as `engine/NEXT_STEPS.md` Task 14.** Phase 1 (re-run Burns after #1: NPV $3.3, PAR +374), phase 2 (UI label) and phase 3 (cohort study, `aging_cohort_study.py`) done; signal one failed (Burns-analogue cohort indistinguishable from all young pitchers in both beds), so phases 4-5 were not run. Phase 6 still applies once 2027 Steamer exists. Open follow-up: re-measure `aging.csv` on the Steamer bed.

**Goal:** understand and, if justified, fix how young pitchers like Burns are
valued going forward. This is an investigation, not an implementation.

**What the code already does.** `keeper_surplus` = `base_value - keeper_salary`,
where `base_value` is priced on the season the loaded file describes.
`projection_season()` is date-inferred: this year until November, next year
after. So once a 2027 projection file is loaded, from November the engine
already prices 2027 with no code change. `keeper_npv` already starts at k=1
(next season) but is anchored on the loaded season's PAR, aged forward with
`aging.csv` ratios.

**The real gap** is roughly September to the time 2027 projections exist:
the anchor is this season's projection, and the aging path stands in.

**Interim options**

| Option | What | Allowed? |
|---|---|---|
| A | Keep the aging path as the stand-in | yes (default) |
| B | Feed the #1 combined file into `base_par` | yes (data only) |
| C | Change the `("P", k)` ratios, e.g. young-pitcher exception | locked, needs the bar |
| D | Blanket "no growth credit is wrong", or hand-tune Burns | no |

Hand-editing `aging.csv` counts as a pricing change; it is regenerated by
`marcel.py --aging`.

**Phases and stop conditions**
1. **(S) Land #1, re-run Burns.** If his Keeper NPV is now sensible, stop:
   the complaint was the stale input.
2. **(S) UI labels** (allowed, independent): show the projection season and
   source, e.g. "Projections for 2026, aged forward" until November; label
   Keeper NPV as aged from the loaded projection; flag rows whose loaded
   projection is stale versus actuals; show the aging ratio applied.
3. **(M) Baselines, then a cohort study** in a scratch script (not the repo),
   reusing `aging_bed()` / `aging_ratios()`. Baselines: the three selftests,
   `marcel.py --aging` (diff `data/aging.csv`, expect no change),
   `marcel.py --npv` (also on the Steamer bed), `backtest.py --market`,
   `backtest.py --measure` on both bed types. Cohort: P, age<=25, k=1..4,
   split by a full-workload definition set from projection-time or in-season
   information only (conditioning on year-y realized workload biases the ratio
   down through survivorship). Test the calibration of the applied path
   (realized-later over projected-now), not just realized-over-realized.
   **Signal one counts only if:** the bootstrap-by-player 95% interval excludes
   0.65; it holds in both the Marcel and Steamer beds; it holds at k=1 and in
   the same direction at k=2 and k=3; and n is at least about 100. The current
   cell has n=100, so n will likely be the binding constraint.
4. **(S) Signal two**, independent of realized ratios: market prices in
   `data/average_values.csv` for age<=25 pitchers against model value (a gap
   that is not monotone in price corroborates; per APPROACH section 2 it never
   proves), and historic Steamer year-over-year growth for the cohort. Both
   must agree in direction and rough size, or the bar is not cleared.
5. **(M, only if both clear)** Propose the ratio change with full before/after:
   the three selftests, `backtest.py --market` (revert if error becomes
   monotone in price), and `marcel.py --league-sim` (does `value` still beat
   `points` beats `random`). Record numbers in `NEXT_STEPS.md`.
6. **(S) When 2027 Steamer exists** (about winter): drop it in. The November
   rollover does the work; no ratio involved.

**If the bar is not cleared:** log it in `NEXT_STEPS.md` as a new dated Task
(Burns numbers, cohort table, which signal agreed, before/after checks, the
verdict "left unpriced, aging ratio unchanged"), add a one-line pointer in
`APPROACH.md` section 7 next to SP, and stop. Do not act on it.

**Traps that apply:** APPROACH section 2 (market calibrates, not validates);
section 4 (the disproven RP claim: one signal is not enough); section 7 (SP left
unpriced despite a large gap); trap 30 (do not price the option cushion);
trap 31 (measure value not points, each k directly); one-year-pair survivorship;
heavy tails from floored PAR (one Skenes-type player moves a cohort mean, so
bootstrap by player). Burns is an example, not evidence.

---

## Enhancement 3 (outstanding, not started) — programmatic rest-of-season pull

**Need:** Enhancement 1 depends on a rest-of-season projection file that today
must be exported by hand from FanGraphs each time (`engine/data/ros/`).
Owner will address this after everything else is in place. Logged 2026-09-19.

**Why it can't just be scripted:** FanGraphs and Ottoneu are behind Cloudflare and
403 every scripted client (pybaseball included). `CLAUDE.md` forbids scraping
libraries, lifting `cf_clearance`, or sweeping IDs. Steamer is only published
there; no public API is known. Only the actuals half of Enhancement 1 is
automatic (statsapi is open).

**Options to evaluate (none chosen):**
1. **In-house ROS projection from open data.** `marcel.py` already builds Marcel
   projections from statsapi; scale one to the remaining games. Fully automatic,
   but weaker than Steamer. `RELIABILITY` was measured on Steamer, so it would
   need re-measuring (`backtest.py --measure`), and any pricing implication
   falls under the two-signal bar in `CLAUDE.md`.
2. **Browser-assisted export.** Drive the owner's own logged-in Chrome (Claude
   in Chrome extension) to click Export. Effectively a manual export, but near
   the "don't script FanGraphs" line, so it needs an explicit owner decision;
   downloads also need approval each time.
3. **Another open source** of rest-of-season projections comparable to Steamer.
   None known to be both open to scripts and comparable; verify before use.

**Interim:** manual export weekly is probably enough (Steamer ROS moves little
day to day). A one-command wrapper (run `combine_ros.py`, back up
`data/steamer_*.csv`, prompt before overwriting) would cut the effort without
solving the pull; also unbuilt.

## Combined sequence

1. Build #1 (`combine_ros.py`), refresh the ROS export, validate.
2. Re-run Burns and the SP top-20. Decide from the result.
3. Ship the #2 UI labels regardless.
4. Run the #2 cohort study only if Burns-type players still look wrong after #1.
5. Log or act per the bar. Re-check when 2027 projections are available.
