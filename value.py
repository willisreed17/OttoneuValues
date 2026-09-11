"""Ottoneu H2H points valuation: join FanGraphs projections to league rosters,
price every player, report surplus value (value - salary) per player and per team.

Inputs (all local CSVs, see README for how to refresh them):
  data/rosterexport.csv   Ottoneu {league}/rosterexport?csv=1
  data/steamer_bat.csv    FanGraphs projections, batters  (playerid, PlayerName, minpos, PA, FPTS, SPTS)
  data/steamer_pit.csv    FanGraphs projections, pitchers (playerid, PlayerName, GS, IP, FPTS, SPTS)

Usage: python value.py [--sabr] [--slots] [--out out]
       python value.py --selftest
"""

import collections
import csv
import datetime
import os
import sys

DATA = "data"
SCORING = "FPTS"  # --sabr switches to SPTS

# --- layer 1 knobs: base valuation, league-agnostic --------------------------
# The H2H starting lineup, straight from the rules.
LINEUP = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "OF": 5, "Util": 1}  # C is a setting
MIDDLE_INFIELD = 1

# Pitcher depth, derived from the rules rather than fitted to one league.
#
# RP is free: the H2H lineup is the standard lineup minus the fixed SP slots
# (rules line 21), and the standard lineup carries 5 RP (line 20). Season-long
# carries 5 SP as well. Neither number was ever a mystery.
#
# SP in H2H is the one genuinely derived quantity: there are no SP slots, and a
# weekly games-started cap governs instead -- 10 starts, the same in every
# Ottoneu H2H points league (confirmed by the league owner 2026-09-10). A
# starter takes every fifth turn through a rotation in a week holding ~6.2 team
# games, so he supplies ~1.25 starts; depth is the ratio, ~8 per team. BASE_SP
# (7.7), the last number fitted to one league's salaries, was approximately
# recovering this, and is gone.
GS_CAP = 10
# RP depth is roster practice, not the lineup count. The lineup has 5 RP slots,
# but a reliever appears in only ~40% of his team's games, so 5 arms cannot keep
# 5 slots busy -- standard practice across Ottoneu H2H is to carry 6. This is
# the one depth number that is neither derived from the rules nor fitted to
# salaries; it is observed behaviour, and it is a property of the FORMAT rather
# than of any one league, which is why it is a constant and not a setting.
# The ten-season bed cannot tell 5 from 6 apart (RP/hitters 0.57 vs 0.59), so 6
# is chosen because it is true, not because it scored better.
RP_SLOTS = 6
SEASON_SP_SLOTS = 5   # rules line 20, season-long only
GAMES_PER_WEEK = 162.0 / 26.0   # MLB team-games in a week
ROTATION = 5                    # a starter takes every fifth turn

# Projection reliability, by role: how far projected PAR can be trusted.
#
# Dollars are handed out in proportion to projected PAR, which silently assumes
# every role's projected spread is equally real. Relievers' is not -- roles turn
# over, the innings are few, and saves and holds follow a job title rather than
# a skill -- so pricing straight off it overpays every reliever.
#
# Measured, not guessed: realized over projected PAR per role, summed over the
# priced players of the ten-season bed and taken relative to hitters (a common
# scale is a no-op on dollars):
#   py -3.13 backtest.py --measure "out/backtest_20*.csv"
# A ratio of sums, not a regression slope, because dollars are proportional to
# PAR and the ratio is exactly what has to come out equal across roles. The
# slope (SP 0.886) put SP 10% cheap on the bed's own position table; its only
# support was market agreement, which validates nothing (APPROACH trap 29).
# RP 0.61 lands on the 0.6 hand-fitted before this was a measurement, and on
# the slope too. Leave-one-season-out: SP 0.92-1.00, RP 0.58-0.64.
#
# The regression's INTERCEPT is the option value of a roster spot, and
# --measure reports it, but it is deliberately NOT priced. It was for a day: it
# cost stars 16% of their dollars and opened a -$7 gap at the top, monotone in
# price, against both league 1297 and the cross-league averageValues market
# (APPROACH trap 30). The replacement-level alternative carries the same
# cushion, so it cancels at the margin.
#
# It describes the PROJECTION, not the league -- these are Marcel's numbers.
# Re-measure when the source changes; Steamer handles relievers better, so its
# RP slope is probably nearer 1. A hard "no reliever above $15" cap would hit
# the same ceiling while leaving the middle of the reliever curve wrong.
RELIABILITY = {"SP": 0.957, "RP": 0.61}

# --- league settings ---------------------------------------------------------
# Anything that differs between Ottoneu leagues belongs HERE, as an input, not
# baked into a function. The defaults are the Ottoneu standard, not this
# league's preferences; data/league.csv overrides any of them with key,value
# rows. If you find yourself hardcoding a number because "our league does X",
# it goes in this table instead -- the engine is meant to price any points
# league, and a constant fitted to one of them is a bug in every other one.
#
#   roster_max -- the cap-relevant limit. A team page may report 41-47 because
#     60-day IL / suspended / opt-out players stop counting once the season
#     starts, but those extra spots grant NO extra cap space (rules line 46),
#     so the $1-per-open-spot reserve is still measured against this number.
#   catcher_slots -- doubling C depth moves catcher values more than any other
#     lineup change, and the rules doc contradicted itself on whether H2H is one
#     or two. Pull it from the league, never assume. League 1297: 1.
#   games_cap  -- seasonal games per position player (162 standard, 810 across
#     the 5 OF slots). 0 = no cap, which is league 1297. Where it binds,
#     production above it is worth nothing, so it compresses elite hitters and
#     lifts high-rate part-timers -- NOT modelled yet, so main() warns.
#   format     -- h2h is modelled. Season-long points leagues are governed by a
#     team innings cap and per-position games caps instead of a weekly GS cap,
#     which changes pitcher valuation entirely; main() warns rather than
#     silently emitting H2H-shaped values for one.
#   keeper_discount -- weight on each further keeper season in keeper_npv. A
#     preference, not a measurement: rosters turn over, owners trade, and a
#     title now beats a maybe later. Weights are relative to THIS season: 0.5
#     counts next season at 0.5, then 0.25, 0.125, 0.0625; 1.0 counts every
#     season the aging table reaches in full.
DEFAULTS = {
    "teams": 0,                  # 0 = infer from the roster export
    "format": "h2h",             # h2h | season
    "scoring": "FPTS",           # FPTS | SPTS
    "cap": 400,
    "roster_max": 40,
    "catcher_slots": 1,          # H2H is commonly 1; some formats require 2
    "games_cap": 0,              # 0 = none. Seasonal games per position player
    "arb_method": "allocations",  # allocations | voteoff | none
    "arb_budget": 25,
    "arb_min": 1,
    "arb_max": 3,
    "keeper_discount": 0.5,
}
TEAM_CAP, ROSTER_MAX = DEFAULTS["cap"], DEFAULTS["roster_max"]

# Retention: keeping a player raises his salary automatically, +$2 if he has MLB
# service in either of the past two seasons, +$1 for a pure prospect. Presence of
# an FG major-league id is the proxy for MLB service -- imperfect, but it is what
# the export gives us. Arbitration stacks on top; see ARB_BUDGET below.
RETENTION_MLB, RETENTION_PROSPECT = 2, 1

# Arbitration is a per-league choice of method and budget -- see arb_method /
# arb_budget in DEFAULTS. Under allocations, every team distributes its budget
# across the OTHER teams, arb_min to arb_max each, so a roster's take is bounded
# and budget x teams of new salary enters the league every offseason. It stacks
# on top of the retention raise, which is why keeper_surplus is optimistic
# without it.
MIN_PA = 100          # below this a batter is a bench body, not a valuation input
MIN_IP = 20
# -----------------------------------------------------------------------------

POSITIONS = ("C", "1B", "2B", "3B", "SS", "OF", "Util", "SP", "RP")
UTIL = "Util"
HITTER_POS = frozenset(("C", "1B", "2B", "3B", "SS", "OF", UTIL))
PITCHER_POS = frozenset(("SP", "RP"))


def is_hitter(p):
    return bool(HITTER_POS & set(p["pos"]))


def normalize(pos):
    """A swingman is a starter. Ottoneu lists plenty of arms as SP/RP, but their
    innings -- and so their points -- come from starting. Left dual-eligible they
    arbitrage into whichever pool is momentarily cheaper and get paid twice for
    the same innings.
    """
    return [p for p in pos if p != "RP"] if "SP" in pos else list(pos)


def num(s, default=0.0):
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def load_projections(path, pitcher, out=None):
    """-> {playerid: {name, mlb, pos:[...], pts, pts_p, pt}} for players with real
    playing time; pts_p is the pitching share of pts.

    Pass an existing dict as `out` to merge: a two-way player appears in both the
    batter and pitcher files and scores in both, so his points add up.
    """
    out = {} if out is None else out
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            pt = num(r["IP"]) if pitcher else num(r["PA"])
            if pt < (MIN_IP if pitcher else MIN_PA):
                continue
            if pitcher:
                pos = ["SP"] if num(r["GS"]) >= 5 else ["RP"]
            else:
                # A DH-only hitter (minpos "DH") is a Util player, not a
                # first baseman. Defaulting him to 1B raises 1B replacement for
                # every real first baseman; dropping him throws away a genuinely
                # valuable bat. Util is what Ottoneu actually calls him, and
                # what the lineup actually offers him.
                pos = [p for p in r["minpos"].split("/") if p in POSITIONS] or [UTIL]
            pts = num(r[SCORING])
            p = out.get(r["playerid"])
            if p:
                p["pos"] += [x for x in pos if x not in p["pos"]]
                p["pts"] += pts
                p["pts_p"] += pts if pitcher else 0.0
                p["two_way"] = True
                continue
            out[r["playerid"]] = {
                "name": r["PlayerName"],
                "mlb": r["Team"],
                "pos": pos,
                "pts": pts,
                # Pitching points kept apart so a two-way player's bat and arm
                # can age on their own curves (keeper_npv).
                "pts_p": pts if pitcher else 0.0,
                "pt": pt,
                "two_way": False,
            }
    return out


def load_settings(path):
    """-> a settings dict, DEFAULTS overridden by key,value rows in `path`.

    An unknown key is reported rather than ignored: a typo silently falling back
    to the default is how a tool quietly starts pricing your league as if it
    were somebody else's.
    """
    cfg = dict(DEFAULTS)
    if not (path and os.path.exists(path)):
        return cfg
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) < 2 or not row[0].strip() or row[0].lstrip().startswith("#"):
                continue
            k, v = row[0].strip(), row[1].strip()
            if k in cfg:
                kind = type(DEFAULTS[k])
                cfg[k] = kind(num(v)) if kind in (int, float) else v
            elif k != "key":  # tolerate a header row, flag anything else
                print("WARNING: unknown league setting %r in %s -- ignored" % (k, path))
    return cfg


def load_rosters(path):
    """-> ({playerid: {team, team_id, salary, pos}}, {team_id: name})."""
    rostered, teams = {}, {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            teams[r["TeamID"]] = r["Team Name"]
            pid = r["FG MajorLeagueID"] or r["FG MinorLeagueID"]
            rostered[pid] = {
                "team_id": r["TeamID"],
                "team": r["Team Name"],
                "salary": num(r["Salary"].lstrip("$")),
                "has_mlb": bool(r["FG MajorLeagueID"].strip()),
                "pos": normalize([p for p in r["Position(s)"].split("/")
                                  if p in POSITIONS]),
                "name": r["Name"],
            }
    return rostered, teams


def keeper_salary(r, arb=0):
    """What this player costs you *next* year if you keep him.

    Salaries escalate on retention, so surplus measured against today's salary
    flatters every cheap keeper -- a $3 player is a $5 player the moment you keep
    him, which is a 67%% raise. Arbitration stacks on top of that (see
    arb_allocations); both are flat dollar adds, so the order they apply in
    doesn't matter.
    """
    return (r["salary"] + (RETENTION_MLB if r["has_mlb"] else RETENTION_PROSPECT)
            + arb)


def age_on(birth, season):
    """Baseball age: how old he is on June 30 of the season."""
    try:
        y, m, d = (int(x) for x in birth.split("-")[:3])
    except (ValueError, AttributeError):
        return None
    ref = datetime.date(season, 6, 30)
    return ref.year - y - ((ref.month, ref.day) < (m, d))


def projection_season(today=None):
    """The season the loaded projections describe.

    # ponytail: inferred from the date -- this year until November, next year
    # after. Wrong if you price last year's projections in December; carry the
    # season in the projection file if that ever matters.
    """
    today = today or datetime.date.today()
    return today.year + (today.month >= 11)


def load_aging(path):
    """-> {(group, k): [(age_lo, age_hi, ratio)]} from marcel.py --aging, or {}."""
    out = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out.setdefault((r["group"], int(r["k"])), []).append(
                    (int(r["age_lo"]), int(r["age_hi"]), float(r["ratio"])))
    return out


def keeper_npv(p, r, age, arb, rate, aging, discount=1.0):
    """Dollars of surplus from keeping him, over every season the aging table
    reaches -- the number keeper_surplus approximates with one year.

    Each future season: this season's reliability-shrunk PAR scaled by the
    measured ratio for his age k seasons on (marcel.py --aging), at this
    season's $/PAR, against a salary that rises by the retention raise every
    year. The ratio is of VALUE, not points -- see marcel.AGING_BINS for why
    ageing points cut every ace in the league. Offseason cuts are free, so you keep him
    only while what remains is worth it: V = max(0, surplus + discount *
    V_next), solved from the last season back -- the discount (keeper_discount)
    changes when he is cut, not just the total. The result is in this season's
    dollars, so next season counts `discount`, the one after `discount**2`. That is why an aging star's bad final years
    cost nothing -- you cut him first -- and why a young cheap player compounds.

    # ponytail: arbitration is charged once, at next year's rate, and stays;
    # future arbitration is not modelled. Seasons past the table's horizon
    # (four) are worth nothing here, which undervalues the youngest stars. And
    # keep-or-cut is solved on expected values, while a real owner decides each
    # offseason knowing how last season went -- so for volatile players,
    # pitchers most, this is a floor. Model the state (healthy / not) if that
    # ever decides a real keeper.
    """
    v = 0.0
    for s in reversed(keeper_surpluses(p, r, age, arb, rate, aging)):
        v = max(0.0, s + discount * v)
    # In this season's dollars: next season is already one step away, so it too
    # is discounted. A common scale, so no keep/cut decision moves.
    return discount * v


def keeper_surpluses(p, r, age, arb, rate, aging):
    """Expected surplus of each future season kept, next season first -- the
    path keeper_npv solves over (marcel.py --npv replays it against realized
    seasons)."""
    def x(group, k):
        return next((x for lo, hi, x in aging.get((group, k), ()) if lo <= age <= hi), 0.0)

    # Bat and arm age on their own curves -- it matters for exactly one player,
    # and he is the most valuable one in the league.
    arm = p.get("pts_p", 0.0) / p["pts"] if p["pts"] > 0 else 0.0
    par = max(p["base_par"], 0.0)
    salary = keeper_salary(r, arb)
    surplus = []
    k = 1
    while ("H", k) in aging:
        ratio = (1 - arm) * x("H", k) + arm * x("P", k)
        surplus.append(1 + par * ratio * rate - salary)
        salary += RETENTION_MLB
        k += 1
    return surplus


def arb_allocations(players, rostered, n_teams, cfg=DEFAULTS):
    """-> {playerid: extra dollars} from arbitration under the allocations method.

    Two questions, and the rules only answer the first.

    *How much each roster receives* is bounded: 11 opponents at $1-$3 each, so
    $11 to $33. A roster full of bargains draws the maximum from everyone and a
    roster of bad contracts draws the minimum, so the take is modelled as each
    team's share of league-wide surplus, clamped into that band.

    *Where it lands inside a roster* is pure judgement -- the rules constrain the
    per-team total, not the per-player one. Eleven managers choose independently,
    so the aggregate spreads across a team's bargains rather than landing wholly
    on the single best one; modelled proportional to surplus. A team with no
    underpaid players still eats the $11 floor, spread by value.

    # ponytail: proportional split, and the league-wide total isn't pinned to
    # $25 x teams once the clamp bites. Go greedy-to-top-surplus and rebalance
    # the remainder if the league turns out to concentrate allocations.
    """
    if cfg["arb_method"] != "allocations":
        # Vote-off pushes one player per team to RFA with a $5 re-bid discount --
        # a different mechanism entirely, not a different number. Better to
        # report it unmodelled than to charge allocations dollars nobody pays.
        return {}
    lo = cfg["arb_min"] * (n_teams - 1)
    hi = cfg["arb_max"] * (n_teams - 1)
    rosters = collections.defaultdict(list)
    for pid, r in rostered.items():
        p = players.get(pid)
        if p:
            rosters[r["team_id"]].append((pid, p["base_value"] - r["salary"]))
    league = sum(max(s, 0.0) for rows in rosters.values() for _, s in rows)
    arb = {}
    for tid, rows in rosters.items():
        share = sum(max(s, 0.0) for _, s in rows)
        take = (min(hi, max(lo, cfg["arb_budget"] * n_teams * share / league))
                if league else lo)
        weights = [(pid, max(s, 0.0)) for pid, s in rows]
        total = sum(w for _, w in weights)
        if not total:  # nobody underpaid: the $11 floor still lands somewhere
            weights = [(pid, max(players[pid]["base_value"], 1)) for pid, _ in rows]
            total = sum(w for _, w in weights)
        for pid, w in weights:
            # Whole dollars; rounding drifts a dollar or two off `take` per team,
            # which is well inside the precision of the split itself.
            d = round(take * w / total)
            if d:
                arb[pid] = d
    return arb


def cut_penalty(salary):
    """In-season, dropping a player leaves 50%% of his salary (rounded up) on your
    cap until someone claims him, you re-auction him, or the season ends. So a cut
    frees only about half what the salary suggests. Off-season cuts are free."""
    return -(-int(salary) // 2)


def cut_gain(value, salary, in_season=True):
    """Cap dollars actually freed by cutting, minus the production given up.

    Positive means the cut helps. This is the number that matters, not raw
    negative surplus: a $50 player worth $32 looks like the worst contract on the
    roster, but cutting him mid-season frees only $25 while costing $32 of
    production, so you keep him and shop him instead.
    """
    freed = salary - (cut_penalty(salary) if in_season else 0)
    return freed - value


def sp_slots(cfg):
    """Starting-pitcher roster spots per team that carry value."""
    if cfg["format"] != "h2h":
        return SEASON_SP_SLOTS
    return GS_CAP * ROTATION / GAMES_PER_WEEK


def base_slots(cfg=DEFAULTS):
    """Roster spots per team that carry real value, by position.

    Layer 1 is deliberately league-agnostic: this is what a player is worth in a
    generic 12-team Ottoneu FGPts league, with no reference to who is rostered
    where. League context enters in layer 2 (see league_values).

    The hitter shape is the lineup rule -- 1 C, 1 1B, 1 2B, 1 3B, 1 SS, 5 OF plus
    a middle-infield slot split between 2B and SS. The utility slot is left out
    on purpose: it's nearly always filled by a player already counted at his own
    position, so adding it would double-count him.
    """
    s = dict(LINEUP, C=cfg["catcher_slots"])
    s["2B"] += MIDDLE_INFIELD / 2.0
    s["SS"] += MIDDLE_INFIELD / 2.0
    s["SP"], s["RP"] = sp_slots(cfg), RP_SLOTS
    return s


def base_depth(n_teams, cfg=DEFAULTS):
    return {k: max(1, int(round(n_teams * v))) for k, v in base_slots(cfg).items()}


def load_cap(path):
    """Per-team cap reality, scraped from each Ottoneu team page (see README).

    The roster export cannot produce this. Three things live only on the team
    page and all three break a naive $400/40 assumption:
      * loans   -- teams trade cap dollars in-season, so a real cap can be $633
      * penalties -- 50%% of a dropped player's salary, money that buys nobody
      * roster_max -- 43 here, not 40, because in-season IL slots don't count
    """
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            n = lambda k: num(r.get(k))
            out[r["team_id"]] = {
                "name": r["team_name"],
                "roster": int(n("roster")), "roster_max": int(n("roster_max")),
                "cap": n("base_cap") + n("loans_in") - n("loans_out"),
                "used": n("salary") + n("penalties"),
                "penalties": n("penalties"),
            }
    return out


def draft(players, depth):
    """Fill the league's roster spots best-player-first, then read replacement
    level off whoever is left over.

    Replacement at a position is the best player there you could still get for
    nothing -- so it's the best *undrafted* player eligible at that spot, which
    is what the $1 tier actually offers you.

    This replaced a fixed-point iteration that recomputed replacement from the
    pool of players currently assigned to each position. That oscillates instead
    of converging: every 2B/SS-eligible player piles onto whichever spot is
    momentarily cheaper, which empties the other one and flips the incentive next
    pass. Drafting in one descending sweep has no such feedback loop.
    """
    openings = dict(depth)
    assigned = {}
    for pid, p in sorted(players.items(), key=lambda kv: -kv[1]["pts"]):
        elig = [pos for pos in p["pos"] if openings.get(pos, 0) > 0]
        if elig:
            # Scarcest open spot first, so a multi-eligible player is spent
            # where he is hardest to replace.
            pos = min(elig, key=lambda x: openings[x])
            openings[pos] -= 1
            assigned[pid] = pos
    # Util is a leftovers slot. Whatever it doesn't take from players with no
    # other home, it fills with the best hitters still going spare -- which is
    # done as a second pass rather than by making every hitter Util-eligible,
    # because Util is the scarcest opening in the lineup and the scarcest-first
    # rule would funnel the entire league into it (trap 1 all over again).
    if openings.get(UTIL, 0) > 0:
        for pid, p in sorted(players.items(), key=lambda kv: -kv[1]["pts"]):
            if openings[UTIL] <= 0:
                break
            if pid not in assigned and is_hitter(p):
                openings[UTIL] -= 1
                assigned[pid] = UTIL
    levels = {}
    for pos in depth:
        left = [p["pts"] for pid, p in players.items()
                if pos in p["pos"] and pid not in assigned]
        levels[pos] = max(left) if left else 0.0
    if UTIL in depth:
        # ...and the same logic sets its replacement level. What a Util-only bat
        # has to beat is not the next-best DH -- it is the best undrafted hitter
        # of ANY position, because that is who would otherwise be standing in
        # that slot. This is exactly why a DH is worth less than his raw points:
        # he can only occupy the one slot with the deepest pool of alternatives.
        spare = [p["pts"] for pid, p in players.items()
                 if pid not in assigned and is_hitter(p)]
        levels[UTIL] = max(spare) if spare else levels.get(UTIL, 0.0)
    return levels, assigned


def price(players, depth):
    """Assign each player his best position and points above replacement."""
    levels, assigned = draft(players, depth)
    for p in players.values():
        p["par"], p["vpos"] = max(
            ((p["pts"] - levels.get(pos, 0.0), pos) for pos in p["pos"]),
            default=(0.0, "?"),
        )
    return levels, sum(p["par"] for p in players.values() if p["par"] > 0), assigned


def apply_reliability(players, reliability=RELIABILITY):
    """Shrink projected PAR by how far the projection can be trusted in each
    role, and return the new total. Call it on the PROJECTION side only --
    realized production needs no shrinking, it already happened. Hitters are
    one role: ten seasons cannot tell one hitting position's error from
    another's."""
    for p in players.values():
        k = reliability.get(p.get("vpos"))
        if k is not None:
            p["par"] *= k
    return sum(p["par"] for p in players.values() if p["par"] > 0)


def base_values(players, n_teams, cfg):
    """Layer 1 end to end: depth, replacement, reliability, dollars.
    -> (depth, levels, assigned, $ per PAR); each player gains par, vpos, value."""
    depth = base_depth(n_teams, cfg)
    levels, _, assigned = price(players, depth)
    rate = to_dollars(players, apply_reliability(players),
                      n_teams * (cfg["cap"] - cfg["roster_max"]))
    return depth, levels, assigned, rate


def to_dollars(players, total_par, money):
    """Split `money` (the pool left after every roster spot's $1 minimum) across
    players in proportion to points above replacement."""
    rate = money / total_par if total_par else 0.0
    for p in players.values():
        p["value"] = round(1 + max(p["par"], 0.0) * rate)
    return rate


def league_values(players, rostered, cap, assigned, depth, roster_max=ROSTER_MAX):
    """Layer 2: re-price against what your league can actually get.

    Base value assumes the entire player universe is available. In a keeper
    league most of it isn't, so the best *free* catcher is a different and worse
    player than the best catcher -- and that, not the base number, is what a
    replacement-level catcher is worth to you.

    This re-solves replacement against the available pool rather than applying a
    flat inflation multiplier. A scalar prorate preserves the base ranking
    exactly, so it could never surface that catchers are scarce in your league,
    which is the entire reason this layer exists.

    Returns (values_by_id, note); values is empty when no market is open.
    """
    free_money = sum(t["cap"] - t["used"] for t in cap.values())
    open_spots = sum(t["roster_max"] - t["roster"] for t in cap.values())
    # $1 of cap room must stay free per open spot, but only up to the 40-man max:
    # spots opened by the 60-day IL don't come with money attached.
    reserve = sum(max(0, roster_max - t["roster"]) for t in cap.values())
    if open_spots <= 0 or free_money <= reserve:
        return {}, ("no open market -- %d open spots, $%d free league-wide"
                    % (open_spots, free_money))
    available = {pid: p for pid, p in players.items() if pid not in rostered}
    if not available:
        return {}, "no unrostered players with projections"
    # Slots already spent on rostered players don't need filling again.
    filled = collections.Counter(pos for pid, pos in assigned.items() if pid in rostered)
    remaining = {pos: max(1, n - filled[pos]) for pos, n in depth.items()}
    price(available, remaining)
    total_par = apply_reliability(available)
    to_dollars(available, total_par, free_money - reserve)
    return ({pid: p["value"] for pid, p in available.items()},
            "$%d free across %d open spots" % (free_money, open_spots))


def resolve_positions(players, rostered):
    """Settle each player's positions from the projection and the roster export.
    -> the names whose Ottoneu pitcher eligibility was overruled.

    What a pitcher IS comes from the projection, never from the roster export.
    Ottoneu eligibility says where a player may legally be slotted today; the
    projection says what he will actually do, and only the second one scores
    points. The export gets this wrong in both directions and both are expensive:

      * Joe Musgrove and Justin Steele are projected for 25+ starts but carry
        RP-only eligibility coming back from injury. Demoted to RP, a starter's
        innings get paid against the reliever replacement level (351 rather than
        553) -- Musgrove came out the most valuable "reliever" in the league at
        $29 against a $5 market price.
      * 28 projected relievers (Griffin Jax, Clarke Schmidt) carry SP
        eligibility. Promoted to SP, a reliever's innings get measured against
        the starter replacement level, which zeroes out every one of them.
      * Jake Bauers is a hitter with RP eligibility. Given it, he is priced
        against the reliever replacement level with a hitter's points -- he
        escapes only by being bad enough that it does not bite, which is luck
        rather than correctness.

    So: if the projection says he pitches, it decides the role outright, and the
    export may only ever supply HITTING positions.
    """
    overruled = []
    for pid, r in rostered.items():
        p = players.get(pid)
        if not (p and r["pos"]) or p["two_way"]:
            continue
        mine = PITCHER_POS & set(p["pos"])
        if mine:
            if PITCHER_POS & set(r["pos"]) != mine:
                overruled.append(p["name"])
            continue
        hit = [q for q in r["pos"] if q in HITTER_POS]
        if hit:
            p["pos"] = hit
    return overruled


def main(argv):
    global SCORING
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out_dir = argv[argv.index("--out") + 1] if "--out" in argv else "out"
    cfg = load_settings(os.path.join(DATA, "league.csv"))
    SCORING = "SPTS" if "--sabr" in argv else cfg["scoring"]
    if cfg["format"] != "h2h":
        print("WARNING: format=%s. Season-long points leagues are governed by a "
              "team innings cap and per-position games caps rather than a weekly "
              "GS cap; pitcher values below are H2H-shaped and will be wrong."
              % cfg["format"])
    if cfg["games_cap"]:
        print("WARNING: games_cap=%d. Production above a seasonal games cap is "
              "worth nothing, which compresses elite hitters and lifts high-rate "
              "part-timers; that is not modelled, so hitter values below are "
              "uncapped totals." % cfg["games_cap"])

    players = load_projections(os.path.join(DATA, "steamer_bat.csv"), pitcher=False)
    pit_path = os.path.join(DATA, "steamer_pit.csv")
    if os.path.exists(pit_path):
        load_projections(pit_path, pitcher=True, out=players)
    else:
        print("WARNING: %s missing -- hitters only, values will be wrong." % pit_path)

    homeless = [p["name"] for p in players.values() if not p["pos"]]
    if homeless:
        print("NOTE: %d projected hitter(s) have no rosterable position (DH only) "
              "and are priced at $1: %s" % (len(homeless), ", ".join(homeless[:6])))

    rostered, teams = load_rosters(os.path.join(DATA, "rosterexport.csv"))
    n_teams = cfg["teams"] or len(teams)
    overruled = resolve_positions(players, rostered)
    if overruled:
        print("NOTE: projection overrode Ottoneu pitcher eligibility for %d arm(s), "
              "e.g. %s" % (len(overruled), ", ".join(overruled[:5])))

    # ---- layer 1: base value, no league context at all ----------------------
    depth, levels, assigned, rate = base_values(players, n_teams, cfg)
    for p in players.values():
        p["base_value"], p["base_vpos"], p["base_par"] = p["value"], p["vpos"], p["par"]

    # ---- layer 2: what it's worth in *this* league --------------------------
    cap_path = os.path.join(DATA, "teams_cap.csv")
    cap = load_cap(cap_path) if os.path.exists(cap_path) else {}
    if cap:
        lv, note = league_values(players, rostered, cap, assigned, depth,
                                 cfg["roster_max"])
    else:
        lv, note = {}, "no data/teams_cap.csv -- cap space unknown, layer 2 skipped"
    # ---- decision layer: what next year actually costs -----------------------
    # Arbitration needs base_value, so it runs after layer 1, not before.
    arb = arb_allocations(players, rostered, n_teams, cfg)
    aging = load_aging(os.path.join(DATA, "aging.csv"))
    births = {}
    bd_path = os.path.join(DATA, "birthdates.csv")
    if os.path.exists(bd_path):
        with open(bd_path, newline="", encoding="utf-8") as f:
            births = {r["playerid"]: r["birthDate"] for r in csv.DictReader(f)}
    if not (aging and births):
        print("NOTE: no data/aging.csv or data/birthdates.csv -- keeper_npv left "
              "blank. Run: py -3.13 marcel.py --aging")
    season = projection_season()
    for pid, p in players.items():
        p["age"] = age_on(births.get(pid, ""), season)
        p["league_value"] = lv.get(pid)
        r = rostered.get(pid)
        p["arb"] = arb.get(pid, 0) if r else None
        p["salary"] = r["salary"] if r else None
        p["owner"] = r["team"] if r else "FA"
        p["keeper_salary"] = keeper_salary(r, p["arb"]) if r else None
        p["surplus"] = p["base_value"] - r["salary"] if r else None
        p["keeper_surplus"] = p["base_value"] - p["keeper_salary"] if r else None
        p["cut_gain"] = cut_gain(p["base_value"], r["salary"]) if r else None
        p["keeper_npv"] = (round(keeper_npv(p, r, p["age"], p["arb"], rate, aging,
                                            cfg["keeper_discount"]), 1)
                           if r and aging and p["age"] is not None else None)

    os.makedirs(out_dir, exist_ok=True)
    rows = sorted(players.items(), key=lambda kv: -kv[1]["base_value"])
    with open(os.path.join(out_dir, "players.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["playerid", "name", "mlb", "pos", "vpos", "age", "pts", "par",
                    "base_value", "league_value", "salary", "surplus", "arb",
                    "keeper_salary", "keeper_surplus", "keeper_npv", "cut_gain", "owner"])
        for pid, p in rows:
            w.writerow([pid, p["name"], p["mlb"], "/".join(p["pos"]), p["base_vpos"],
                        p["age"], round(p["pts"], 1), round(p["par"], 1), p["base_value"],
                        p["league_value"], p["salary"], p["surplus"], p["arb"],
                        p["keeper_salary"], p["keeper_surplus"], p["keeper_npv"],
                        p["cut_gain"], p["owner"]])

    # ---- team ledger, on real cap data when we have it ----------------------
    # Joined on team id, not name: the roster export carries trailing whitespace
    # on some team names ("Iron ") that the team page doesn't.
    ledger = {}
    for pid, r in rostered.items():
        t = ledger.setdefault(r["team_id"],
                              {"name": r["team"].strip(), "n": 0, "value": 0, "surplus": 0})
        t["n"] += 1
        p = players.get(pid)
        if p:
            t["value"] += p["base_value"]
            t["surplus"] += p["surplus"]
    with open(os.path.join(out_dir, "teams.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["team", "players", "roster_max", "cap", "used", "penalties",
                    "cap_space", "open_spots", "projected_value", "surplus"])
        for tid, t in sorted(ledger.items(), key=lambda kv: -kv[1]["surplus"]):
            c = cap.get(tid)
            if c:
                w.writerow([t["name"], c["roster"], c["roster_max"], int(c["cap"]),
                            int(c["used"]), int(c["penalties"]),
                            int(c["cap"] - c["used"]), c["roster_max"] - c["roster"],
                            t["value"], int(t["surplus"])])
            else:  # no cap data: leave it blank rather than invent $400/40
                w.writerow([t["name"], t["n"], "", "", "", "", "", "", t["value"],
                            int(t["surplus"])])

    print("%s | %d teams | $%d cap | %d-man | layer 1 base value"
          % (SCORING, n_teams, cfg["cap"], cfg["roster_max"]))
    print("depth:       " + "  ".join("%s %d" % (k, depth[k]) for k in POSITIONS))
    print("replacement: " + "  ".join("%s %d" % (k, levels[k]) for k in POSITIONS))
    print("layer 2:     " + note)
    print("\narbitration: $%d allocated across %d players (%d teams x $%d budget)"
          % (sum(arb.values()), len(arb), n_teams, cfg["arb_budget"])
          if arb else "arbitration: method=%s -- not modelled" % cfg["arb_method"])
    print("\nBest keeper surplus (value - NEXT year's salary, after retention + arbitration):")
    keep = sorted((p for _, p in rows if p["keeper_surplus"] is not None),
                  key=lambda p: -p["keeper_surplus"])
    for p in keep[:12]:
        print("  %-24s %-4s $%3d value  $%2d -> $%-3d keep (arb +$%d)  +$%-3d  %s"
              % (p["name"], p["base_vpos"], p["base_value"], p["salary"],
                 p["keeper_salary"], p["arb"], p["keeper_surplus"], p["owner"]))
    npv = sorted((p for _, p in rows if p["keeper_npv"] is not None),
                 key=lambda p: -p["keeper_npv"])
    if npv:
        print("\nBest keeper NPV (this season's dollars, each season ahead x%.2f; "
              "cut when it stops paying):" % cfg["keeper_discount"])
        for p in npv[:12]:
            print("  %-24s %-4s age %2d  $%3d value  $%2d salary  NPV %+6.1f  %s"
                  % (p["name"], p["base_vpos"], p["age"], p["base_value"], p["salary"],
                     p["keeper_npv"], p["owner"]))
    print("\nWorst contracts, and whether cutting actually helps:")
    print("  (cut frees salary minus a 50%% in-season penalty, and costs you the value)")
    for p in keep[-8:][::-1]:
        verdict = "CUT  +$%d" % p["cut_gain"] if p["cut_gain"] > 0 else "hold %+d" % p["cut_gain"]
        print("  %-24s %-4s $%3d value  $%3d salary  frees $%-3d  %s"
              % (p["name"], p["base_vpos"], p["base_value"], p["salary"],
                 p["salary"] - cut_penalty(p["salary"]), verdict))
    best_cuts = sorted((p for _, p in rows if p["cut_gain"] is not None),
                       key=lambda p: -p["cut_gain"])[:8]
    print("\nActual cut candidates (net cap freed exceeds production lost):")
    for p in best_cuts:
        print("  %-24s %-4s $%3d value  $%3d salary  net +$%-3d  %s"
              % (p["name"], p["base_vpos"], p["base_value"], p["salary"],
                 p["cut_gain"], p["owner"]))
    fa = [kv for kv in rows if kv[1]["owner"] == "FA"]
    print("\nTop free agents (base / league value):")
    for _, p in fa[:12]:
        lvv = "$%d" % p["league_value"] if p["league_value"] is not None else "n/a"
        print("  %-24s %-4s base $%-4d league %s  %s"
              % (p["name"], p["base_vpos"], p["base_value"], lvv, p["mlb"]))
    print("\nwrote %s/players.csv (%d players) and %s/teams.csv"
          % (out_dir, len(rows), out_dir))


def selftest():
    def mkp(pos, pts):
        return {"name": "x", "mlb": "X", "pos": list(pos), "pts": float(pts),
                "pt": 600, "two_way": False}

    # 6 first basemen, 4 spots -> the 5th-best is the best you can still get free.
    players = {str(i): mkp(["1B"], 100 - 10 * i) for i in range(6)}
    levels, total_par, assigned = price(players, {"1B": 4})
    assert levels["1B"] == 60, levels
    assert len(assigned) == 4 and players["5"]["par"] < 0
    to_dollars(players, total_par, 2 * (TEAM_CAP - ROSTER_MAX))
    assert players["5"]["value"] == 1, "below replacement is a $1 player"
    assert players["0"]["value"] > players["1"]["value"] > players["2"]["value"]
    spent = sum(p["value"] for p in players.values() if p["par"] > 0)
    pool = 2 * (TEAM_CAP - ROSTER_MAX) + sum(1 for p in players.values() if p["par"] > 0)
    assert abs(spent - pool) <= 3, (spent, pool)

    # Multi-eligibility: priced at whichever spot is scarcer, counted at one only.
    two = {"a": mkp(["2B", "SS"], 500)}
    for i in range(4):
        two["b%d" % i] = mkp(["2B"], 400 - i)
        two["c%d" % i] = mkp(["SS"], 300 - i)
    lv, _, _ = price(two, {"2B": 2, "SS": 2})
    assert two["a"]["vpos"] == "SS", two["a"]      # weaker pool -> more PAR there
    assert lv["SS"] < lv["2B"]

    # Rules: retention raises, in-season cut penalty, 40-man reserve.
    assert keeper_salary({"salary": 3, "has_mlb": True}) == 5      # +$2
    assert keeper_salary({"salary": 3, "has_mlb": False}) == 4     # +$1 prospect
    assert keeper_salary({"salary": 3, "has_mlb": True}, arb=4) == 9  # arb stacks

    # Arbitration: every roster's take lands in [$1, $3] x (teams - 1), the money
    # follows the bargains, and a roster with no bargains still eats the floor.
    pl = {"a": dict(mkp(["OF"], 900), base_value=40),
          "b": dict(mkp(["OF"], 800), base_value=30),
          "c": dict(mkp(["OF"], 100), base_value=1)}
    ros = {"a": {"team_id": "1", "salary": 5.0}, "b": {"team_id": "1", "salary": 28.0},
           "c": {"team_id": "2", "salary": 30.0}}
    a = arb_allocations(pl, ros, 12)
    assert 11 <= a["a"] + a["b"] <= 33, a
    assert a["a"] > a["b"], "the $35 bargain draws more than the $2 one"
    assert a["c"] == 11, "a roster of bad contracts still takes the $11 minimum"
    # The team with all the surplus is taxed harder than the one with none.
    assert a["a"] + a["b"] > a["c"], a
    # Keeper NPV: the task's own example -- same projection, same $5 salary,
    # 23 vs 33. The young one compounds; the old one is cut before his decline
    # costs anything, so his bad years are worth zero, not negative.
    ag = {("H", 1): [(0, 29, 1.0), (30, 99, 0.4)], ("H", 2): [(0, 29, 1.0), (30, 99, 0.2)]}
    kp = dict(mkp(["OF"], 700), base_par=200.0)        # $21 of value at $0.1/PAR
    kr = {"salary": 5.0, "has_mlb": True}
    young = keeper_npv(kp, kr, 23, 0, 0.1, ag)
    old = keeper_npv(kp, kr, 33, 0, 0.1, ag)
    assert abs(young - ((21 - 7) + (21 - 9))) < 1e-9, young   # $7 then $9 salary
    assert abs(old - (9 - 7)) < 1e-9, old      # keep one year at +$2, cut before -$4
    assert keeper_npv(kp, kr, 23, 0, 0.1, {}) == 0, "no table, no NPV"
    # Discounting starts with next season -- it is worth less than this one --
    # and can flip the cut: a -$2 year carried by a +$3 one is kept
    # undiscounted and cut at 0.5.
    assert abs(keeper_npv(kp, kr, 23, 0, 0.1, ag, 0.5) - (0.5 * 14 + 0.25 * 12)) < 1e-9
    ag4 = {("H", 1): [(0, 99, 0.2)], ("H", 2): [(0, 99, 0.55)]}    # -$2, then +$3
    assert abs(keeper_npv(kp, kr, 23, 0, 0.1, ag4) - 1) < 1e-9
    assert keeper_npv(kp, kr, 23, 0, 0.1, ag4, 0.5) == 0
    assert isinstance(DEFAULTS["keeper_discount"], float), "float-typed setting parses"
    # A losing year is carried when the years after it pay for it.
    ag2 = {("H", 1): [(0, 99, 0.2)], ("H", 2): [(0, 99, 1.5)]}
    assert abs(keeper_npv(kp, kr, 23, 0, 0.1, ag2) - ((5 - 7) + (31 - 9))) < 1e-9
    # A two-way player's arm ages on the pitcher curve and his bat on the
    # hitter one, weighted by where his points come from.
    ag3 = {("H", 1): [(0, 99, 1.0)], ("P", 1): [(0, 99, 0.0)]}
    tw = dict(kp, pts_p=350.0)                           # half his points pitching
    assert abs(keeper_npv(tw, kr, 23, 0, 0.1, ag3) - (11 - 7)) < 1e-9
    assert abs(keeper_npv(dict(tw, pts_p=0.0), kr, 23, 0, 0.1, ag3) - 14) < 1e-9
    assert projection_season(datetime.date(2026, 9, 10)) == 2026
    assert projection_season(datetime.date(2026, 11, 5)) == 2027
    assert cut_penalty(50) == 25 and cut_penalty(9) == 5           # 50%, rounded up
    assert cut_penalty(1) == 1
    # A $50 player worth $32 frees only $25 -- cutting loses ground.
    assert cut_gain(32, 50) == 25 - 32 < 0
    # A $18 player worth $1 frees $9 for $1 of production -- cut him.
    assert cut_gain(1, 18) == 9 - 1 > 0
    assert cut_gain(32, 50, in_season=False) == 50 - 32, "no off-season penalty"

    # League settings are inputs, not constants: an 8-team $260 league must not
    # be priced with the 12-team $400 defaults, and a non-allocations league must
    # not be charged allocations dollars.
    cfg = dict(DEFAULTS, teams=8, cap=260, roster_max=30, arb_method="voteoff")
    assert arb_allocations(pl, ros, 8, cfg) == {}, "vote-off isn't allocations"
    cfg2 = dict(DEFAULTS, arb_budget=50, arb_max=6)
    a2 = arb_allocations(pl, ros, 12, cfg2)
    assert a2["c"] == 11 and a2["a"] + a2["b"] > a["a"] + a["b"], (a, a2)
    assert load_settings("nonexistent.csv") == DEFAULTS
    assert isinstance(DEFAULTS["cap"], int), "int-typed defaults drive the parser"

    # A DH-only hitter is a Util player, never a phantom first baseman -- an
    # invented 1B raises 1B replacement for every real one.
    dh = {"dh": mkp([UTIL], 900), "a": mkp(["1B"], 800), "b": mkp(["1B"], 700)}
    lv2, _, _ = price(dh, {"1B": 1, UTIL: 1})
    assert lv2["1B"] == 700, lv2                # the DH never touches 1B depth
    # Util's replacement is the best *spare hitter of any position*, not the
    # next DH: with the 800 1B drafted, the 700 1B is what a Util slot could
    # otherwise hold, so a 900-point DH is worth 200 PAR, not 900.
    assert lv2[UTIL] == 700, lv2
    assert dh["dh"]["par"] == 200 and dh["dh"]["vpos"] == UTIL, dh["dh"]
    # A Util bat is worth the same as an equally productive player at the
    # DEEPEST position -- both are measured against the best spare hitter -- and
    # strictly less than one at a scarce position. That is the whole point: the
    # DH gives up positional scarcity, which is most of what a hitter is paid
    # for, and keeps only his bat.
    pool = {"c": mkp(["C"], 900), "dh": mkp([UTIL], 900), "c2": mkp(["C"], 400)}
    for i, pts in enumerate((850, 800, 750, 700, 650)):
        pool["of%d" % i] = mkp(["OF"], pts)
    lv4, _, _ = price(pool, {"C": 1, "OF": 3, UTIL: 1})
    assert lv4["C"] == 400 and lv4["OF"] == 700 and lv4[UTIL] == 700, lv4
    assert pool["c"]["par"] == 500 and pool["dh"]["par"] == 200, (pool["c"], pool["dh"])
    assert lv4[UTIL] >= max(lv4[p] for p in ("C", "OF")),         "Util always has the deepest pool of alternatives"

    # Util is a leftovers slot: spare hitters fill it, and being parked there
    # does not change what a player is worth at his own position.
    spare = {"x": mkp(["OF"], 900), "y": mkp(["OF"], 800)}
    lv3, asg3 = draft(spare, {"OF": 1, UTIL: 1})
    assert asg3 == {"x": "OF", "y": UTIL}, asg3
    assert lv3[UTIL] == 0.0, "no spare hitters left once Util is filled"

    # Reliability shrinks projected PAR in the roles the projection handles
    # worst, and touches nothing else.
    rel = {"a": mkp(["RP"], 900), "b": mkp(["RP"], 500), "c": mkp(["SP"], 900),
           "d": mkp(["SP"], 500)}
    price(rel, {"RP": 1, "SP": 1})
    tp = apply_reliability(rel, {"RP": 0.6})
    assert abs(rel["a"]["par"] - 0.6 * 400) < 1e-9, rel["a"]
    assert rel["c"]["par"] == 400, "SP untouched"
    assert abs(tp - (0.6 * 400 + 400)) < 1e-9, tp
    # An empty map is a no-op, so a league with a trusted projection pays full
    # freight everywhere.
    price(rel, {"RP": 1, "SP": 1})
    assert apply_reliability(rel, {}) == 800.0
    assert set(RELIABILITY) <= PITCHER_POS, "hitters are the unit; no cushion"

    assert normalize(["SP", "RP"]) == ["SP"], "a swingman is a starter"
    # ...and so is a projected starter who currently carries RP-only Ottoneu
    # eligibility. The roster export must never decide a pitcher's role: all
    # three of these were live, and the first cost $24 on one player.
    pool2 = {"musgrove": mkp(["SP"], 633), "jax": mkp(["RP"], 550),
             "bauers": mkp(["1B", "OF"], 257), "ohtani": mkp([UTIL], 900)}
    for k in pool2:
        pool2[k]["name"] = k
    pool2["ohtani"]["two_way"] = True
    ros2 = {
        "musgrove": {"pos": ["RP"], "name": "Musgrove"},        # back from injury
        "jax": {"pos": ["SP"], "name": "Jax"},                  # converted to the pen
        "bauers": {"pos": ["1B", "OF", "RP"], "name": "Bauers"},  # position player who pitched
        "ohtani": {"pos": ["Util", "SP"], "name": "Ohtani"},
    }
    over = resolve_positions(pool2, ros2)
    assert pool2["musgrove"]["pos"] == ["SP"], "a projected starter stays a starter"
    assert pool2["jax"]["pos"] == ["RP"], "a projected reliever stays a reliever"
    assert pool2["bauers"]["pos"] == ["1B", "OF"], "a hitter never gets pitcher eligibility"
    assert sorted(over) == ["jax", "musgrove"], over
    assert pool2["ohtani"]["pos"] == [UTIL], "two-way players are left alone"
    assert normalize(["RP"]) == ["RP"] and normalize(["2B", "SS"]) == ["2B", "SS"]

    # Layer 1 is league-agnostic: same shape regardless of who is rostered.
    slots = base_slots()
    assert slots["SS"] == slots["2B"] > slots["3B"], slots   # the MI slot lifts 2B/SS
    assert slots["OF"] == 5 and slots["C"] == 1 and slots[UTIL] == 1, slots
    assert base_depth(12)["OF"] == 60 and base_depth(12)["C"] == 12
    assert base_depth(12)[UTIL] == 12
    # Catcher slots are a league setting, not a constant: a two-catcher league
    # has twice the C depth and a materially lower replacement catcher.
    two_c = dict(DEFAULTS, catcher_slots=2)
    assert base_slots(two_c)["C"] == 2 and base_depth(12, two_c)["C"] == 24
    assert base_depth(12, two_c)["OF"] == 60, "changing C must not move anything else"

    # RP depth comes straight off the lineup rules, in both formats.
    assert base_slots()["RP"] == RP_SLOTS == 6
    assert base_slots(dict(DEFAULTS, format="season"))["RP"] == 6
    # Season-long has 5 fixed SP slots; H2H has none and derives from the cap.
    assert sp_slots(dict(DEFAULTS, format="season")) == 5
    # 10 starts a week, ~1.25 starts per pitcher per week -> ~8 starters.
    assert abs(sp_slots(DEFAULTS) - 8.0) < 0.1

    # Layer 2: a rostered player is unavailable, so the best free player at his
    # position sets replacement -- that is the whole point of the second pass.
    pool = {"star": mkp(["C"], 900), "ok": mkp(["C"], 500), "meh": mkp(["C"], 100)}
    rostered = {"star": {"salary": 5, "pos": ["C"], "team": "t", "has_mlb": True,
                         "team_id": "1", "name": "n"}}
    cap = {"1": {"name": "t", "roster": 30, "roster_max": 40, "cap": 400.0,
                 "used": 100.0, "penalties": 0.0}}
    _, _, assigned2 = price(pool, {"C": 2})
    vals, note = league_values(pool, rostered, cap, assigned2, {"C": 2})
    assert "star" not in vals, "rostered players are not on the market"
    assert vals["ok"] > vals["meh"], vals
    assert "300 free" in note, note                  # $300 cap space, 10 spots

    # IL-created spots grant no cap money: a 42-of-43 roster reserves nothing,
    # because the $1-per-open-spot rule is measured against the 40-man max.
    il = {"1": {"name": "t", "roster": 42, "roster_max": 43, "cap": 400.0,
                "used": 398.0, "penalties": 0.0}}
    vals, note = league_values(pool, rostered, il, assigned2, {"C": 2})
    assert vals, "one open spot and $2 free, with no reserve owed on it"

    # A full league with no money is reported as closed, not priced as if open.
    shut = {"1": {"name": "t", "roster": 40, "roster_max": 40, "cap": 400.0,
                  "used": 399.0, "penalties": 0.0}}
    vals, note = league_values(pool, rostered, shut, assigned2, {"C": 2})
    assert vals == {} and "no open market" in note, note
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main(sys.argv[1:])
