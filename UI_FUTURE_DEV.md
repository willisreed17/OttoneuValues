# Ottoneu Values — UI / Future Development

> **Status:** Product and UI roadmap.
> The features described below are planned unless explicitly stated otherwise. The existing Python valuation engine remains the source of truth for current player valuation logic.

## Product Goal

Ottoneu Values should become a decision-support application for Ottoneu fantasy baseball managers.

The product should be organized around the actual decisions a manager needs to make:

1. **Rankings** — Who should I target?
2. **Keepers** — Who should I keep at their salary?
3. **Auction** — How high should I bid?
4. **Trades** — Does this trade improve my roster?
5. **Lineup** — Who should I start this week or today?

The UI should not simply expose CSV files or model outputs. Each area should turn the underlying data into a specific baseball decision.

---

# Core Navigation

```text
Ottoneu Values

Rankings    Keepers    Auction    Trades    Lineup

League: [ League ▼ ]
My Team: [ Team ▼ ]
```

League and team context should be persistent across the application.

The user should choose their Ottoneu league and team once. That context should then determine:

* roster ownership
* available players
* salaries
* cap space
* keeper decisions
* auction context
* trade context
* lineup options

---

# 1. Rankings

## Purpose

Answer:

> **Who are the best players for me to target?**

This is the primary pre-draft and player-pool page.

The default view should show **available players**, with the ability to switch to **all players** for research.

## Initial Table

```text
PRE-DRAFT RANKINGS

[ Search players... ]   [ Position ▼ ]   [ Available ▼ ]

Rank   Player              Pos       MLB   Age   Proj Pts   Base $   League $
1      Player A            SP        ATL    27     940.2      $42       $49
2      Player B            OF        LAD    25     811.7      $38       $43
3      Player C            SS/2B     BAL    24     779.1      $35       $39
```

## Important Fields

* Rank
* Player
* Position
* MLB team
* Age
* Projected Ottoneu points
* Base value
* League value
* Market salary/value when available
* Current owner
* Availability

## Filters

Eventually support:

* Available / All Players
* Position
* Hitter / Pitcher
* Age
* Minimum value
* Prospects
* Watchlist
* Owned / Free Agent

## Valuation Meaning

### Base Value

`base_value` represents the player's value within the scoring format before the current league's keeper-market conditions are applied.

### League Value

`league_value` represents what the player is worth in the current league's available-player and available-money environment.

League value should only be displayed when the model actually has an open market to price.

Do not manufacture or substitute a league value when the engine intentionally leaves it blank.

---

# 2. Keepers

## Purpose

Answer:

> **Which players should I keep at their future salary?**

The Keepers page should automatically load the user's roster.

This should be one of the application's primary features because the current valuation engine already contains substantial keeper logic.

## Roster Summary

```text
KEEPER DECISIONS

My Team

Projected Cap After Keepers     $___
Players Kept                    __ / 40
Projected Roster Value          $___
Keeper Surplus                  +$___
```

## Keeper Table

```text
Player          Pos    Salary   Next Salary   Value   1Y Surplus   Keeper NPV   Decision
Player A        SP       $8        $10         $31       +$21         +$34       KEEP
Player B        OF      $27        $29         $31        +$2          +$4       KEEP
Player C        RP      $14        $16         $11        -$5           $0       CUT
```

## Primary Metrics

* Current salary
* `keeper_salary`
* Base value
* League value when available
* `keeper_surplus`
* `keeper_npv`
* Arbitration impact
* Age
* Position

## User Decisions

Each player should support:

```text
KEEP
CUT
UNDECIDED
```

Changing keeper decisions should update the team summary immediately.

Examples:

* projected cap used
* cap remaining
* roster spots remaining
* total retained player value
* total keeper surplus

## Keeper NPV

`keeper_npv` should be treated as the primary long-term keeper metric.

It accounts for:

* projected player value
* aging
* future salary increases
* arbitration
* discounted future seasons
* the ability to cut a player during a future offseason

One-year `keeper_surplus` should remain visible because it provides useful context, but it should not be presented as equivalent to multi-year keeper value.

---

# 3. Auction

## Purpose

Answer:

> **How high should I bid on this player?**

Auction should behave like a live war-room tool rather than another rankings table.

## Auction Dashboard

```text
AUCTION WAR ROOM

Cap Remaining        Roster Spots       $ / Open Spot
$147                 12                 $12.25

Search / Nominate Player: [________________]
```

## Player Auction Card

```text
Juan Soto
OF · NYM · Age 27

Projected Points       1,038
Base Value                $60
League Value              $72
Market Value              $67

MODEL VALUE
$72
```

Eventually this may evolve into:

```text
Bid Range

Conservative     Target     Maximum
$65              $72        $78
```

but a bid range should **not** be created by arbitrarily adding and subtracting a percentage from the model value.

A future auction range must have a defensible methodology.

Possible inputs include:

* projection uncertainty
* league inflation
* roster needs
* remaining positional scarcity
* available money
* remaining roster spots
* market behavior
* nomination timing
* expected competition

Until that model exists, show the model's **value or maximum worth-it price**, not a fake confidence interval.

## Target List

Users should eventually be able to maintain an auction target list.

```text
Player          Pos    Base $   League $   Market $   Max Bid
Player A        SP       $30       $37        $31        $37
Player B        OF       $24       $29        $27        $29
```

---

# 4. Trades

## Purpose

Answer:

> **Does this trade make my team better?**

Trades should use a side-by-side package builder.

## Trade Builder

```text
YOUR SIDE                         THEIR SIDE

Player A        $12               Player C        $27
Player B         $4               Player D         $8
Cap Loan         $5

Current Value   $___              Current Value   $___
Keeper NPV      $___              Keeper NPV      $___
Future Salary   $___              Future Salary   $___
```

## Result

```text
NET TRADE VALUE

You gain: +$11

Key effects:

+ More long-term keeper value
+ Better salary efficiency
- Lose one usable roster player
+ Gain $5 cap flexibility

Recommendation:
LEAN ACCEPT
```

## Important Modeling Note

There is currently no dedicated `trade_value` output.

The best current starting point is likely `keeper_npv`, because a traded player arrives with their existing salary.

That makes trade value fundamentally different from auction value.

Example:

A player worth $40 who costs $8 is a much more valuable trade asset than a player worth $40 who costs $39.

Trade valuation should therefore consider:

* player value
* salary
* keeper NPV
* age
* future salary
* cap loans
* roster spots
* positional needs

A dedicated trade model should eventually be developed and tested rather than simply renaming keeper NPV as trade value.

---

# 5. Shared Player Detail

Rankings, Keepers, Auction, and Trades should share one reusable player-detail component.

Clicking a player should open a drawer or panel without forcing the user to leave their current workflow.

Example:

```text
SHOHEI OHTANI
LAD · Util/SP · Age 31

PROJECTION
Projected Points        1,710.6

VALUATION
Base Value                 $115
League Value                 —
Market Salary               $78

KEEPER
Current Salary              $71
Next Salary                 $81
1-Year Keeper Surplus       +$34
Keeper NPV                  +$1.7

LEAGUE
Owner                    Twin Pines
```

The same component can be reused throughout the application while emphasizing different metrics depending on the page.

---

# 6. Lineup

Lineup tools are planned future development.

They are a **different modeling problem from season-long valuation**.

Do not put daily or weekly matchup adjustments inside `value.py`.

A player's matchup against a weak opponent Tuesday should affect whether we start him Tuesday. It should not materially alter his keeper or auction value.

The application should therefore eventually maintain two conceptual engines:

```text
PLAYER DATA
    |
    +--------------------------+
    |                          |
VALUATION ENGINE          LINEUP ENGINE
Long horizon              Short horizon
    |                          |
Rankings                  Weekly Pitching
Keepers                   Daily Hitters
Auction
Trades
```

---

# 6A. Weekly Pitcher Rankings

## Purpose

Answer:

> **Which pitching starts should I use this week?**

Ottoneu H2H leagues have a weekly starting-pitcher limit.

The lineup tool should help identify the best starts available to the manager.

## Core Rule

Rank **individual starts**, not pitchers.

A pitcher scheduled twice during the week should appear twice.

Example:

```text
Monday vs OAK     Rank #2
Sunday @ LAD      Rank #14
```

The model may recommend using the first start and avoiding the second.

## Ranking Convention

**Rank 1 = best projected start of the week.**

Lower-ranked starts become progressively shakier.

## Required Model Outputs

Every projected start should return these five outputs:

* **Expected Ottoneu points**
* **Floor**
* **Ceiling**
* **Start confidence**
* **Recommendation: Recommended / Borderline / Sit**

These are core model outputs, not just presentation fields.

### Expected Ottoneu Points

The central estimate for how many Ottoneu points the pitcher is expected to score in that specific start.

### Floor

A lower-end realistic outcome for the start.

This should represent downside risk rather than an arbitrary percentage below the mean.

### Ceiling

A higher-end realistic outcome for the start.

This should represent upside potential rather than an arbitrary percentage above the mean.

### Start Confidence

How much confidence the model has in the recommendation and projection.

Confidence should consider uncertainty around:

* workload
* pitch count
* role
* probable-starter status
* injury/rest concerns
* opponent quality
* volatility in the underlying pitcher profile
* uncertainty in expected innings

### Recommendation

Each start should be classified as:

```text
RECOMMENDED
BORDERLINE
SIT
```

This should be based on the start's expected value, downside, upside, confidence, and how it compares with the user's other available starts for the week.

## Weekly Rankings

```text
WEEKLY PITCHER RANKINGS
Week of Sep 14–20

Rank   Pitcher       Day   Opp   Exp Pts   Floor   Ceiling   Confidence   Recommendation
1      Pitcher A     Mon   OAK    25.6     16.8      34.9       High       RECOMMENDED
2      Pitcher B     Tue   @DET   23.9     15.4      31.7       High       RECOMMENDED
3      Pitcher C     Wed   CHW    22.8     13.9      32.4       Medium     RECOMMENDED
4      Pitcher A     Sat   SEA    21.7     12.1      31.0       Medium     RECOMMENDED
5      Pitcher D     Thu   @KC    20.9     12.8      28.9       Medium     RECOMMENDED
6      Pitcher E     Fri   PIT    19.8     10.7      29.1       Medium     RECOMMENDED
7      Pitcher F     Tue   @MIA   18.7     11.3      26.8       Medium     RECOMMENDED
8      Pitcher G     Sun   COL    17.8      7.4      29.9       Low        BORDERLINE
9      Pitcher H     Fri   TEX    16.4      9.8      24.7       Medium     BORDERLINE
10     Pitcher I     Sun   @SF    15.9      9.1      23.4       Medium     BORDERLINE

---------------------------------------------------------------

11     Pitcher J     Tue   LAD    14.7      4.8      25.5       Low        SIT
12     Pitcher K     Sat   @NYY   13.8      3.9      24.8       Low        SIT
```

## Recommended Starts

The application should clearly identify:

```text
RECOMMENDED 10 STARTS

1. Pitcher A vs OAK
2. Pitcher B @ DET
3. Pitcher C vs CHW
4. Pitcher A vs SEA
5. Pitcher D @ KC
6. ...
7. ...
8. ...
9. ...
10. ...

FIRST OUT
11. Pitcher J vs LAD
```

The **First Out** is important.

If a scheduled starter is scratched, moved, or skipped, the user should immediately know the next-best start to use.

## Rank vs Confidence vs Recommendation

These concepts should remain separate.

### Rank

Answers:

> How good is this start relative to the other available starts?

### Confidence

Answers:

> How certain are we about the projection and recommendation?

### Recommendation

Answers:

> Given the user's weekly options and the 10-start constraint, should this start actually be used?

A start can rank relatively high while still carrying low confidence.

Example:

```text
Rank #8
Expected Points: 18.4
Floor: 7.1
Ceiling: 31.2
Confidence: Low
Recommendation: BORDERLINE
```

Another start may have less upside but a much safer profile:

```text
Rank #9
Expected Points: 17.8
Floor: 12.9
Ceiling: 23.8
Confidence: High
Recommendation: RECOMMENDED
```

This distinction should be visible to the user.

## Future Pitching Model

The primary output should eventually be:

**Expected Ottoneu points for this specific start, with a modeled floor, ceiling, confidence, and recommendation.**

Potential inputs:

* projected innings
* expected pitch count
* strikeout ability
* walk suppression
* home-run suppression
* quality of contact allowed
* opponent offensive quality
* opponent strikeout rate
* opponent handedness profile
* park
* home / away
* probable starter certainty
* rest
* injury/workload indicators
* recent role changes
* expected lineup strength
* bullpen context where relevant
* Ottoneu scoring weights

Potential future data sources include:

* Baseball Savant
* FanGraphs
* MLB schedule/probable starter data
* Statcast
* existing projection systems

The model should optimize the **portfolio of starts**, not simply rank season-long pitchers.

The ultimate decision problem is:

> Which combination of starts gives this team the best expected Ottoneu scoring outcome within the weekly start limit?

---

# 6B. Daily Hitter Start/Sit

## Purpose

Answer:

> **Which hitter should I start today?**

The first version should focus on direct hitter-vs-hitter decisions.

Example:

```text
START / SIT

                    PLAYER A          PLAYER B

Position               OF                OF
Team                    BOS               SEA

Projected Points        7.4               5.8
Start Probability       96%               89%
Expected PA             4.5               4.1
Platoon                  Advantage         Neutral
Park                     Positive          Negative
Opposing SP              RHP               LHP

RECOMMENDATION

START PLAYER A

Model Confidence: 68%
```

## Explanation

The model should explain why it prefers one player.

Example:

```text
WHY PLAYER A

+ Better projected plate appearances
+ Platoon advantage
+ Better run environment
+ More favorable opposing starter

- Slightly worse opposing bullpen
```

The explanation should be generated from actual model inputs rather than generic prose.

## Future Hitter Model

The primary target should eventually be:

**Expected Ottoneu points for today's game.**

Conceptually:

```text
Expected Points
=
Expected Plate Appearances
×
Expected Ottoneu Production per PA
```

Potential inputs:

* underlying hitter talent
* projected playing time
* lineup position
* platoon split
* opposing starter talent
* opposing starter handedness
* pitcher strikeout profile
* pitcher walk profile
* pitcher contact-quality profile
* park
* expected run environment
* bullpen quality
* weather where relevant
* expected lineup quality around the hitter

Baseball Savant and FanGraphs data can eventually be incorporated into this model.

Avoid heavily weighting direct batter-vs-pitcher history unless testing demonstrates predictive value. Those samples are generally much smaller than broader talent, handedness, and contact-quality samples.

---

# Data / Model Separation

The application should keep long-horizon valuation and short-horizon lineup recommendations separate.

## Valuation Engine

Used for:

* Rankings
* Keepers
* Auction
* Trades

Primary concepts:

* season projections
* replacement level
* positional scarcity
* league economics
* salary
* cap space
* keeper inflation
* arbitration
* aging
* keeper NPV

## Lineup Engine

Used for:

* Weekly Pitching
* Daily Hitter Start/Sit

Primary concepts:

* opponent
* schedule
* park
* handedness
* expected playing time
* expected workload
* matchup quality
* probable starters
* expected Ottoneu points for one game/start
* floor / ceiling
* confidence
* recommendation
* short-term uncertainty

The engines can share player IDs, eligibility, projections, and underlying data.

They should not share the same final score.

---

# UI Development Order

Recommended sequence:

## Phase 1 — Rankings

Build:

* application shell
* league/team selector
* player table
* filtering
* sorting
* ownership state
* shared player drawer

## Phase 2 — Keepers

Build:

* My Team roster
* keeper metrics
* Keep / Cut / Undecided interaction
* dynamic cap summary

## Phase 3 — Auction

Build:

* auction war room
* player nomination/search
* live roster/cap context
* target list
* league value display

Do not create an arbitrary bidding range before the methodology exists.

## Phase 4 — Trades

Build:

* trade package builder
* side-by-side player packages
* salaries
* cap loans
* keeper NPV comparison
* roster effects

Develop a dedicated trade-value model after the initial comparison workflow exists.

## Phase 5 — Lineup

After the short-horizon data pipeline and models are ready:

Build:

* weekly pitcher start rankings
* top 10 recommended starts
* First Out
* expected Ottoneu points
* floor
* ceiling
* start confidence
* Recommended / Borderline / Sit
* daily hitter-vs-hitter comparison
* start/sit explanations

---

# Future UI Data Contract

The frontend should be designed so future model outputs can be added without rebuilding the screens.

Potential future lineup fields:

```text
projected_points
floor
ceiling
rank
confidence
recommendation
opponent
game_date
home_away
park
expected_ip
expected_pa
platoon
start_probability
probable_starter_status
```

These fields may initially be missing.

Missing model outputs should be treated as **not yet implemented**.

Do not populate production screens with arbitrary fake calculations just to fill the UI.

---

# Product Principle

Every major page should answer one baseball question clearly:

```text
Rankings:
Who should I target?

Keepers:
Who should I keep?

Auction:
How high should I bid?

Trades:
Does this deal improve my team?

Weekly Pitching:
Which starts should I use?

Daily Hitters:

Who should I start today?
```

The models can become sophisticated underneath.

The UI should make the resulting decision simple.
