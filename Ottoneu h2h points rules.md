# Ottoneu Head-to-Head Points League Rules

Reference doc for building the valuation app. Covers the mechanical rules that determine roster legality, cap math, contracts, and scoring, everything the app needs to model correctly. Sourced primarily from Ottoneu's official rules page (ottoneu.fangraphs.com/rules) and scoring options page.

## League format options

Ottoneu offers four scoring systems:

- Old School: 5x5 rotisserie (hitting: AVG, HR, RBI, SB, R; pitching: W, SV, ERA, WHIP, K)
- Ottoneu Classic: 4x4 sabermetric roto (hitting: OBP, SLG, HR, R; pitching: ERA, WHIP, HR/9, K)
- FanGraphs Points (FGPts): available in head-to-head
- SABR Points: available in head-to-head

This doc focuses on the **head-to-head points** format (FGPts or SABR points, H2H structure), which is what the app targets.

## Roster construction

- 40-man roster maximum, made up of an active roster and reserve spots.
- 22 spots must be MLB players capable of filling the starting lineup; 18 additional reserve spots can hold major or minor leaguers.
- Standard lineup (non-H2H): 1 C, 1 1B, 1 2B, 1 3B, 1 SS, 5 OF, 1 middle infield (2B/SS), 1 utility, 5 SP, 5 RP.
- H2H regular season lineup: same as above, but **no fixed SP slots** — pitcher usage is governed by a "Per Week GS Cap" league setting instead (commonly ~14 starts/week; confirm per-league).
- Playoff lineup: only 1 C slot, and either 2 SP slots or a customizable weekly GS cap.
- Positional eligibility: a hitter qualifies at a position with 10+ MLB games there (current or prior year), OR 5+ MLB starts there, OR 20+ minor league games there. Pitchers qualify as SP with 5+ starts, as RP with 5+ relief appearances.
- Two-way players occupy one roster spot and can be started as a hitter and a pitcher separately.
- Players lock into their lineup slot 5 minutes before their game starts (5 minutes before game 1 on doubleheader days, accruing stats for both games).

### H2H-specific roster mechanics

- Only **one catcher slot** in the lineup (vs. the two-catcher requirement in season-long formats) — this is deliberate, to stop teams from stacking catchers in favorable weekly matchups.
- **No weekly cap on offensive games played**, but the standard **seasonal** games cap still applies per position player (see caps below) — you can still run out of eligible games before the season/playoffs end if you're not careful.
- **No IP cap in H2H** (season-long formats have a 1,500 IP soft cap; H2H doesn't).
- **Two-starts-per-day limit** for starting pitchers, specifically to prevent stacking a single dominant SP into extra starts.
- SP lineup slots only accrue stats if the pitcher actually starts that day; RP slots only accrue stats when the pitcher appears out of the bullpen.

### Games/innings caps (season-long, non-H2H, for reference)

- Without playoffs: 162 games/position player (810 for OF, i.e., 5 OF slots x 162), 1,500 IP max for all pitchers (soft cap — stats still count the day the team crosses the limit), 1,250 IP minimum for Classic 4x4 (else 0 pitching points).
- With playoffs: 135 games/position player (675 for OF), 1,250 IP max, 1,040 IP minimum for Classic 4x4.
- Games caps are a **hard cap** (with a doubleheader exception); IP caps are a **soft cap**.
- H2H/playoffs: no positional or IP caps; only the optional weekly SP GS cap applies.

## Salary cap

- Each manager starts with **$400** in cap space to fill a roster, including money already committed to retained (kept) players.
- Must maintain at least **$1 of cap room per open roster spot**, up to the 40-man max (so you can't spend down to $0 while roster spots remain unfilled).
- Extra open spots created by a suspension, 60-day IL, COVID IL, or opt-out do **not** grant extra effective cap space.
- After the keeper deadline, total team salary can't exceed $360 plus current roster size, ensuring every team can still field a legal 40-man roster for $400.

## Contracts and salary growth (retention)

- Keeping a player from year to year increases their salary automatically:
  - **+$2** if the player appeared in 1+ MLB regular-season games in either of the past two seasons.
  - **+$1** for everyone else (i.e., pure prospects with no MLB time).
- These increases are applied after arbitration voting concludes.
- Teams may **not** trade salary cap dollars across season boundaries (loans are within-season only, see Trades below).

## Arbitration (choose one league-wide method)

**Allocations method**
- Each team gets a $25 arbitration budget for the offseason.
- Must allocate at least $1 and at most $3 to every other team.
- Allocations stack on top of the standard $1/$2 retention increases described above.
- If a team fails to hit the minimum-per-team allocation or doesn't spend the full $25, all of that team's allocations are voided.

**Vote-off method**
- Each team casts one vote per other team, naming a player to push into restricted free agency (RFA).
- The most-voted player on each team becomes an RFA.
- The player's original team gets an automatic **$5 discount** if they choose to re-bid on him in the auction.
- Ties are broken by the standings of the voting teams.
- RFA'd players cannot be traded, don't count against their old team's cap while in RFA limbo, and won't show up as normal free agents, they go through the RFA/auction process instead.

## Auction / annual draft

- All rosters are completed at an annual league auction, run at the commissioner's discretion (usually right after arbitration).
- Nomination order follows the **previous season's reverse standings** (worst team picks first).
- It's a **blind-bid (Vickrey) auction**: highest bid wins, but pays **$1 more than the second-highest bid**. Ties go to the team lower in the standings. An unbid/unclaimed player defaults to $1 (or the applicable cap-penalty price).
- No trades allowed during the draft itself, trading resumes once both teams have full legal rosters.
- Suspended/60-day IL/COVID-IL/opted-out players still count against the 40-man limit during the auction (they stop counting once the season starts).

## Free agency / in-season transactions

- To add an unrostered player, you start an **auction**; bidding runs for **48 hours** from the start.
- When a player is **dropped**, other managers get a **24-hour waiver window** to claim him for **100% of his prior salary**; priority goes to the team lowest in the standings. Pre-season ties are broken by coin flip.
- If nobody claims a dropped player, **50% of his prior salary (rounded up)** counts against his *former* team's cap as a **cap penalty**, until someone claims him, he's re-auctioned by the cutting team, or the season ends.
- The team that dropped a player can't nominate or bid on him again for **30 days**.
- Any free-agent bid on a previously-dropped player must be **at least 50% of his previous salary**.
- Off-season cuts carry **no cap penalty**; the 50% penalty is an in-season-only mechanic.
- Transactions can be requested from the day of the auction through the next-to-last day of the regular season; all auctions must resolve before midnight of the season's final day of games.

## Trades

- Trading window: from the end of the annual auction through **midnight ET on August 31**.
- Roster-size math on uneven trades: if Team A takes on 3 players while sending out 1, Team A must either already have room to stay at/under 40 or cut enough additional players to get there.
- **Salary cap dollars can be traded** between teams as in-season "loans," but these don't carry over once the regular season ends (no cross-season cap trading).
- After a trade is confirmed, the league gets a **24- or 48-hour review window** (league setting); if a **majority (50%+1)** of managers object, the trade is voided.

## Offseason sequence (cuts / keepers / re-signing)

1. **Before arbitration concludes**: no cuts allowed.
2. **Between arbitration end and the keeper deadline**: cuts and trades are both allowed. Retention salary increases (see above) apply here.
3. **After the keeper deadline through the auction**: no cuts or trades. Teams must already be legal (≤40 players, ≤$400) at the keeper deadline to participate in the auction; commissioners can forcibly cut players from teams that are over the limit.

## Playoffs

All playoff matchups are **head-to-head**, regardless of the league's regular-season scoring format, you choose FGPts or SABR points for playoff scoring.

Three playoff structures, commissioner's choice:

- **Wild Card** (6 teams): Week 1 is 3-seed vs 6-seed and 4-seed vs 5-seed; winners are re-seeded for week 2; the championship spans playoff weeks 3–4.
- **Extended Semifinal** (4 teams, top 2 seeds bye): semifinals span playoff weeks 1–2, finals span weeks 3–4.
- **Regular Semifinal** (4 teams, same seeding): semifinal is a single week (week 1), finals span weeks 2–3.
- Leagues with divisions: division winners are the top seeds; remaining playoff spots go to the best records regardless of division.

## Administration notes

- Base league fee starts at $20/team; prize leagues run higher with payouts scaled to entry cost.
- You must actively manage your team on the day payouts are made (typically just before arbitration) to be prize-eligible.
- Stats only accrue for MLB regular-season games, nothing from spring training or the postseason.

## Sources

- [Ottoneu Rules](https://ottoneu.fangraphs.com/rules)
- [Ottoneu Scoring Options](https://ottoneu.fangraphs.com/scoringoptions)
- [Ottoneu Support/FAQ](https://ottoneu.fangraphs.com/support)
- [Auction Rules and the Cap Penalty (community)](https://community.ottoneu.com/t/auction-rules-and-the-cap-penalty/7439)
