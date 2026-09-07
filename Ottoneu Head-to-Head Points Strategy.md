# Ottoneu Head-to-Head Points Strategy

Strategic context for the valuation app, how the FGPts/SABR points scoring systems distort player value relative to real-world performance and traditional roto, and how good Ottoneu managers construct rosters, run auctions, and manage keepers as a result. Pair with `ottoneu-h2h-points-rules.md` for the mechanical rules these strategies operate within.

## The scoring formulas (for reference)

**FanGraphs Points (FGPts)**

| Hitting | Pts | | Pitching | Pts |
|---|---|---|---|---|
| AB | -1.0 | | IP | 7.4 |
| H | 5.6 | | K | 2.0 |
| 2B | 2.9 | | H (allowed) | -2.6 |
| 3B | 5.7 | | BB (allowed) | -3.0 |
| HR | 9.4 | | HBP (allowed) | -3.0 |
| BB | 3.0 | | HR (allowed) | -12.3 |
| HBP | 3.0 | | SV | 5.0 |
| SB | 1.9 | | HOLD | 4.0 |
| CS | -2.8 | | | |

**SABR Points** is identical on hitting; pitching differs slightly: IP is worth 5.0 (not 7.4), HR allowed is -13.0 (not -12.3), and there's no separate H-allowed penalty line.

## Why this scoring system changes everything

The hitting formula is, in FanGraphs' own framing, essentially linear weights scaled by ~10, so points totals track closely with 10x a player's wRC. That has concrete implications:

- **OBP and power are rewarded directly; batting-average-only value is not.** A single is only worth 5.6 - 1.0 = 4.6 net points once you subtract the AB cost, so a high-average, low-walk, no-power hitter (the classic "empty average" guy) is worth much less here than in a roto AVG category. Walks (+3.0) count the same regardless of whether they "help" a roto average.
- **Extra-base power compounds fast**: HR (+9.4) and triples (+5.7) are worth far more than the marginal AB they cost.
- **Stolen bases matter, but modestly** (+1.9, with a real -2.8 cost for getting caught) — speed is a real but secondary lever, not a category to dominate the way it can in 5x5 roto.

On the pitching side:

- **Home runs allowed are brutally punished** (-12.3 / -13.0). A pitcher's real fantasy value in this format leans heavily on HR/9 suppression, not just ERA or wins (wins aren't scored at all). This means pitchers on bad teams (who don't rack up wins) but with strong K/BB and low HR/9 are undervalued by "traditional" reputation and overvalued... no, *correctly* valued here versus roto, where they'd be underrated because of poor win totals.
- **Innings are worth a lot** (+7.4/IP in FGPts), so pitchers who go deep into starts accumulate value quickly, provided they aren't bleeding points back out via home runs and walks.
- **Saves and holds are nearly equal** (5.0 vs 4.0). This is the single biggest points-league-specific market inefficiency: a non-closing setup man who racks up holds is worth almost as much as a closer, and the market (auction prices) chronically undervalues him because "closer" is the label people pay for in roto/traditional formats.

## Reliever strategy: the market's biggest inefficiency

Because holds and saves score almost identically, and because there's no IP cap in H2H, the highest-leverage strategy in the format is building a deep bullpen of multiple high-leverage (not necessarily closing) relievers rather than paying up for one or two "proven closers":

- Target relievers who get regular high-leverage innings (i.e., real bullpen roles, not just recent-closer name value), especially on good teams that generate more save/hold chances.
- Prioritize **total points**, which rewards innings pitched at a strong rate, over raw points-per-inning efficiency alone; a durable reliever who racks up innings and holds outproduces a slightly-more-efficient arm who barely pitches.
- This is a real, documented pricing gap: analysis has pegged top relief arms as being "worth" roughly $21-25 in auction value while regularly selling for closer to $9. That gap is exactly the kind of surplus-value signal the app should be built to surface.
- Practical roster target: **5-7 quality relievers**, many biddable for $1, used both as a scoring engine and as trade/waiver chips as roles shift in-season.

## Starting pitcher strategy

- Since H2H uses a **weekly games-started cap** (not a fixed 5-SP-lineup slot) and there's no season IP cap, the goal is to **maximize starts thrown against the weekly cap** — you need enough startable arms that a rainout, a skipped start, or a two-start pitcher's day doesn't leave points on the table.
- Rule of thumb from experienced managers: roster **9-10 SP** to comfortably fill a weekly cap around 14 starts, prioritizing volume/floor over pure upside once you're past your top few arms.
- But don't ignore quality entirely: because HR-allowed is such a heavy penalty, a "compiler" who serves up home runs is a real drag on points, not just a roto-ERA nuisance. The best value targets combine three traits: low HR/9, above-average innings-per-start, and a reasonable K rate. Pitchers who grade well on all three (rather than just one) are where the real point-per-dollar gains are.
- Because pitchers on bad teams aren't penalized for lacking wins, undervalued-by-mainstream-reputation starters (good peripherals, bad win-loss record, weak team) are exactly the kind of buy-low target this format rewards, and traditional rankings/ADP will often miss this.

## Catcher strategy (H2H-specific)

Since the lineup only carries **one catcher slot** in H2H (vs. two in season-long formats), and catchers are notoriously injury/rest-prone, most competitive managers carry **at least two rosterable catchers** so a day off or injury doesn't create a scoring hole.

## Weekly / seasonal roster management

- There's no weekly cap on offensive games played in H2H, only the standard **seasonal** games cap per position (162 games/hitter, 810 for the OF pool, in a non-playoff season; less in playoff formats). That means:
  - In a tough matchup, you can legally start everyone every game to try to win the week (there's no downside from "using up" a weekly limit).
  - In an easy matchup, it can be correct to **bench hitters and conserve their remaining season-long games** for tougher weeks or to make sure you don't run dry before the playoffs.
- Watch your remaining games budget as the season progresses; running out of eligible games for key players before the playoffs start is a real, self-inflicted failure mode in this format.
- The two-starts-per-day rule for SPs exists specifically to stop teams from stacking one ace into extra starts, plan pitching usage around that constraint, not around it being exploitable.

## Auction and roster-construction philosophy

- A commonly cited positional allocation target (from experienced Ottoneu managers) for a ~20-player hitting core plus ~15-player pitching staff:
  - 1-2 catchers (either one clear starter, or two complementary/platoon arms)
  - Full lockdown of 1B and the utility slot
  - Middle infield treated as a strength: aim for roughly 3 2B + 3 SS on the roster
  - 1 clear 3B starter plus a multi-position backup
  - Heavy OF depth (8-9 OF-eligible players) since the OF games cap (810) is the hardest positional cap to fully use
  - 8-9 SP (moderate investment, lean toward mid-tier/high-workload arms over one or two stars)
  - 5-7 RP (see reliever strategy above; several can be $1 bids)
- Auction discipline matters more than a rigid budget split: the best-performing approach isn't "spend exactly X% on hitting," it's **buying players for less than your own valuation of them**, commonly cited as targeting wins of roughly $0-4 under your sheet value, while staying flexible enough to pivot as the room's price dynamics (inflation on stars, deflation on scrubs) play out live.
- Pre-ranking players **by position** inside the auction tool before the draft starts is a repeatedly recommended, low-effort prep step that pays off in speed and discipline during the live auction.
- Maintain enough **cap flexibility during the season** to both absorb the 40-man/positional-cap math (games played, innings) and to pounce on early-season waiver-wire pickups.

## Keeper / contract / arbitration strategy

- The core offseason workflow experienced managers use, and the one the app should replicate and automate:
  1. Pull fresh projections (Steamer or similar) and run them through an auction-value calculator matched to your league's settings.
  2. Merge those projected dollar values against your **actual current roster and salaries**.
  3. Anywhere actual salary meaningfully exceeds projected value, that player is a cut or trade-away candidate; anywhere projected value exceeds salary, that's a keep (and a tradeable trade chip if you're rebuilding).
  4. Use a roster-impact tool to see how cutting/trading a given player actually affects your cap situation, not every "overpay" should be cut outright, some are better shopped to a team that values that specific player/skillset more.
- This "salary vs. projected value" delta *is* surplus value, and it's exactly the metric the app is meant to formalize league-wide (not just for your own roster) by joining Ottoneu roster/salary data with FanGraphs projections.
- Arbitration allocation (if your league uses the allocations method) is a soft, social lever, small, cheap ways to nudge up an opponent's cost on a player you don't want them keeping. It rarely changes outcomes on its own but is a low-cost consideration during the offseason planning window.

## Prospect / reserve-spot strategy (contrarian view worth encoding)

A well-argued minority position in the Ottoneu strategy community: **stashing prospects is often a poor use of reserve spots**, and the app's valuation logic shouldn't assume prospects are automatically valuable just because they're cheap. The reasoning:

- Historical hit rates on prospects reaching real fantasy relevance are low, roughly 15% of Top-100 prospects turn into 2-WAR-or-better players in their rookie year, and the picture is worse for pitching prospects specifically (roughly half never reach 2 WAR at all).
- Ottoneu's replacement level is high enough that a prospect has to become a **clear top-half starter at his position**, not just "an average MLB regular", to be worth the roster spot and salary growth he accumulates while stashed.
- Salary/contract growth on a stashed prospect compounds slowly and often outpaces the marginal value he provides even if he does pan out as a solid (not star) contributor.
- The suggested alternative use of bench/reserve spots: **cheap MLB-ready platoon bats** (e.g., strong-side platoon hitters who post well above replacement production against one throwing hand) tend to offer better, faster, more reliable returns on a $1-3 salary than a lottery-ticket prospect.
- Practical implication for reserve-spot allocation: treat prospects as **trade assets and in-season injury/streaming reinforcements** first, and long-term "the next star" bets only selectively, don't default to filling every open reserve spot with a prospect just because the price is low.

## General mentality

- Ottoneu is explicitly a long-game format: multi-year contracts, rolling keeper decisions, and a real trade market mean single-auction "mistakes" are correctable and roster construction is an ongoing process, not a one-day event.
- Because trades, arbitration voting, and RFA all involve your actual leaguemates, understanding opponents' team needs and tendencies (who's rebuilding, who's cap-strapped, who overvalues saves) is treated by veteran managers as being nearly as important as raw player valuation, worth keeping in mind if/when the app expands beyond single-team analysis into trade-finder or league-wide surplus dashboards.

## Sources

- [How pitching is scored in ottoneu FanGraphs Points leagues](https://fantasy.fangraphs.com/how-pitching-is-scored-in-ottoneu-fangraphs-points-leagues/)
- [How hitting is scored in ottoneu FanGraphs Points leagues](https://fantasy.fangraphs.com/how-hitting-is-scored-in-ottoneu-fangraphs-points-leagues/)
- [Ottoneu: These Pitchers Are More Valuable In Points Leagues](https://fantasy.fangraphs.com/ottoneu-these-pitchers-are-more-valuable-in-points-leagues/)
- [Building a Bullpen in Ottoneu Points Leagues](https://pitcherlist.com/building-a-bullpen-in-ottoneu-points-leagues/)
- [Ottoneu Head To Head Strategies](https://fantasy.fangraphs.com/ottoneu-head-to-head-strategies/)
- [The Ottoneu Standings Dashboard](https://fantasy.fangraphs.com/the-ottoneu-standings-dashboard/)
- [Ottoneu Offseason Checklist](https://fantasy.fangraphs.com/ottoneu-offseason-checklist/)
- [How To Win Your Ottoneu Auction](https://fantasy.fangraphs.com/how-to-win-your-ottoneu-auction/)
- [How I Construct My Ottoneu Rosters](https://fantasy.fangraphs.com/how-i-construct-my-ottoneu-rosters/)
- [Ottoneu Strategy: Forget Prospects](https://fantasy.fangraphs.com/ottoneu-strategy-forget-prospects/)
