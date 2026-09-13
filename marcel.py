"""Marcel projections from MLB statsapi -- a multi-season test bed for the
valuation engine.

Why this exists: `backtest.py --dollars` can only score one FanGraphs projection
snapshot, because that is all we have and all we can get (FanGraphs 403s every
scripted client, and historical rest-of-season snapshots are not retrievable at
all). Tuning anything against n=1 is how `BASE_SP`/`BASE_RP` got fitted to one
league in the first place. statsapi is open, so a Marcel built from it turns one
sample into ten.

Marcel is deliberately a *worse* projection than Steamer. It is not competing
with it. It exists so the question "does realized PAR per dollar stay flat" can
be asked ten times instead of once -- systematic curvature across ten seasons is
a finding, curvature in one is noise. Compare Marcel-2016 to Marcel-2017; never
compare a Marcel number to the Steamer run.

It also projects *full* seasons, which is how the engine is actually used
(preseason auction pricing), rather than the mid-May rest-of-season snapshot.

Usage:
  python marcel.py                      # all target seasons -> out/backtest_YYYY.csv
  python marcel.py --years 2022,2023
  python marcel.py --steamer             # same bed, projected side from data/Historic
                                          #   Steamer Preseason Projections/ instead of
                                          #   Marcel -> out/backtest_YYYY_steamer.csv
  python marcel.py --aging              # -> data/aging.csv, data/birthdates.csv
  python marcel.py --npv                # out-of-sample keeper_npv backtest
  python marcel.py --age-check [--steamer]  # k=0 realized/projected PAR by age
  python marcel.py --weekly             # cache weekly lines for every bed season
  python marcel.py --lineup-sim [--steamer]  # weekly SP/RP bench sim, RP5 vs RP6
  python marcel.py --league-sim [--steamer] [--trials 200]  # synthetic auction
                                          #   + season Monte Carlo: value vs
                                          #   raw-points vs random drafting
  python marcel.py --selftest
"""

import csv
import datetime
import json
import os
import random
import sys
import urllib.request

import backtest as bt
import value

API = "https://statsapi.mlb.com/api/v1"
CACHE = os.path.join("data", "mlb")
OUT = "out"

# 2020 was 60 games. Weighted as a normal season it poisons every projection
# that uses it as an input, so it is dropped as a target *and* as an input --
# the season sequence simply skips it. The cost lands on 2021, whose most recent
# input is then 2019; that row is flagged in the output rather than quietly
# treated as equal to the others.
SKIP = {2020}
FIRST_TARGET, LAST_TARGET = 2015, 2025

# Marcel, per Tango's published spec.
WEIGHTS = (5, 4, 3)          # most recent season first
REG_PA, REG_IP = 1200, 134   # league-average playing time added as regression
PT_RECENT, PT_PRIOR = 0.5, 0.1
# Marcel's playing-time floor is one third of a full workload for the role:
# 200 of 600 PA, 60 of ~180 SP innings. Tango's published +60 is a *starter's*
# number, and applying it to relievers projected them for ~99 IP against a real
# ~65 -- at 7.4 points an inning that inflated every reliever by ~250 points and
# put projected RP replacement at 541 against a realized 392. It made relievers
# look overpriced by the model when the error was entirely in this constant.
PT_BASE_PA, PT_BASE_IP_SP, PT_BASE_IP_RP = 200, 60, 22
FULL_PA, FULL_IP_SP, FULL_IP_RP = 600, 180, 65
AGE_PIVOT, AGE_YOUNG, AGE_OLD = 29, 0.006, 0.003

# Ottoneu positional eligibility is 10+ games at a position in the current or
# prior year (rules line 22). The 5-starts and 20-minor-league-games clauses are
# not modelled: statsapi fielding gives games by position directly, but minor
# league games sit under a different sportId. Prospects are therefore slightly
# under-eligible, which is acceptable for a test bed.
ELIG_GAMES = 10
FIELD_POS = {"C": "C", "1B": "1B", "2B": "2B", "3B": "3B", "SS": "SS",
             "LF": "OF", "CF": "OF", "RF": "OF", "OF": "OF"}


def hitting_pos(primary, games):
    """-> the slash-joined hitting positions this batting line may be used at,
    or None if it must not enter the hitter pool at all.

    `games` is {position: games played} already mapped through FIELD_POS, so it
    never contains a pitching position. Two guards, because the incidental one is
    too easy to break: FIELD_POS maps no pitching position, AND primaryPosition
    "P" is excluded outright. Marcel's playing-time floor pushes every NL
    pitcher's batting line past MIN_PA, and before this they fell through a
    `or ["1B"]` default -- which put 1B replacement at 981 against C's 495 and
    mispriced every real first baseman.

    A hitter with no qualifying fielding position is a DH: real, often excellent
    (2024 alone: Ohtani, Schwarber, Ozuna, McCutchen, J.D. Martinez) and eligible
    only at Util, where he is priced against the best spare hitter of any
    position -- so he keeps his bat and loses the positional scarcity that is
    most of what a hitter is paid for.
    """
    if primary == "P":
        return None
    elig = [p for p, n in games.items() if n >= ELIG_GAMES]
    return "/".join(sorted(elig)) or value.UTIL


def cached(name, fetch):
    """Fetch once, then never again. statsapi is open and we intend to keep it
    that way; re-pulling 13 seasons on every run of a tool you are actively
    iterating on is exactly the behaviour that gets an IP blocked."""
    path = os.path.join(CACHE, name + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    data = fetch()
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print("  cached %s (%d rows)" % (name, len(data)))
    return data


def pages(query):
    """Every split of one MLB /stats query, paged."""
    out, off = [], 0
    while True:
        url = ("%s/stats?%s&sportId=1&playerPool=All&limit=1000&offset=%d"
               % (API, query, off))
        blob = json.load(urllib.request.urlopen(url, timeout=180))["stats"][0]
        sp = blob.get("splits", [])
        out += sp
        off += len(sp)
        if not sp or off >= blob.get("totalSplits", 0):
            return out


def fetch_stats(season, group):
    return cached("%d_%s" % (season, group),
                  lambda: pages("stats=season&group=%s&season=%d" % (group, season)))


def our_stats(st, group):
    """One statsapi stat block -> our stat names."""
    api_map = bt.BAT_API if group == "hitting" else bt.PIT_API
    s = {v: bt.num(st.get(k, 0)) for k, v in api_map.items()}
    if group == "pitching":
        s["IP"] = bt.innings(st.get("inningsPitched"))
        s["GS"] = bt.num(st.get("gamesStarted", 0))
    else:
        s["PA"] = bt.num(st.get("plateAppearances", 0))
    return s


def season_stats(season, group):
    """-> {mlbam: stats} in our stat names. statsapi returns season totals
    already aggregated across trades, one row per player -- verified, so there
    is no duplicate-team row to merge."""
    return {str(sp["player"]["id"]): our_stats(sp["stat"], group)
            for sp in fetch_stats(season, group)}


def season_positions(season):
    """-> {mlbam: {pos: games}} from fielding splits."""
    out = {}
    for sp in fetch_stats(season, "fielding"):
        pos = FIELD_POS.get((sp.get("position") or {}).get("abbreviation"))
        if pos:
            g = out.setdefault(str(sp["player"]["id"]), {})
            g[pos] = g.get(pos, 0) + bt.num(sp["stat"].get("games", 0))
    return out


def season_people(season):
    """-> {mlbam: (name, birthDate, primary_position)}."""
    def go():
        url = "%s/sports/1/players?season=%d" % (API, season)
        return json.load(urllib.request.urlopen(url, timeout=180))["people"]
    return {str(p["id"]): (p["fullName"], p.get("birthDate", ""),
                           (p.get("primaryPosition") or {}).get("abbreviation", ""))
            for p in cached("%d_people" % season, go)}


# Weekly lines, for anything H2H does inside a week that season totals can't
# show: benching a healthy bad player, the 10-start cap, how many relievers a
# week actually uses. Stored per *calendar* week (Monday-Sunday; the first week
# starts on opening day), because merging weeks is a lossless sum -- the reader
# decides how Ottoneu groups the odd ones (opening week, All-Star week, an
# overseas opener). One call per week for every player, not a game log per
# player: ~27 calls a season instead of ~1,500.
def calendar_weeks(start, end):
    """-> [(first day, last day)] ISO dates, Monday-Sunday, clipped to the season."""
    d, end = datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)
    out = []
    while d <= end:
        sun = min(d + datetime.timedelta(days=6 - d.weekday()), end)
        out.append((d.isoformat(), sun.isoformat()))
        d = sun + datetime.timedelta(days=1)
    return out


def season_bounds(season):
    """-> (regularSeasonStartDate, regularSeasonEndDate), ISO strings."""
    def go():
        url = "%s/seasons?sportId=1&season=%d" % (API, season)
        return json.load(urllib.request.urlopen(url, timeout=180))["seasons"][0]
    s = cached("%d_season" % season, go)
    return s["regularSeasonStartDate"], s["regularSeasonEndDate"]


def season_weeks(season):
    return calendar_weeks(*season_bounds(season))


def season_days(season):
    """-> every calendar date (ISO) of the regular season, inclusive."""
    d, end = (datetime.date.fromisoformat(x) for x in season_bounds(season))
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += datetime.timedelta(days=1)
    return out


def weekly_stats(season, group):
    """-> {week's first day: {mlbam: stats}}, zero stats omitted."""
    def go():
        out = {}
        for a, b in season_weeks(season):
            q = ("stats=byDateRange&group=%s&season=%d&startDate=%s&endDate=%s"
                 % (group, season, a, b))
            out[a] = {str(sp["player"]["id"]): {k: v for k, v in
                                               our_stats(sp["stat"], group).items() if v}
                      for sp in pages(q)}
        return out
    return cached("%d_%s_weekly" % (season, group), go)


# Daily lines, pitching only. Ottoneu allows daily lineup changes (confirmed by
# the league owner 2026-09-12), so a reliever's active-or-benched decision is a
# per-day call, not a per-week one -- the weekly lineup sim's first cut locked
# the active 5 for the whole calendar week, which is a stricter constraint than
# a real GM plays under and understated RP reliability. SP is untouched: GS_CAP
# is a genuinely weekly rule, and a start either happens on its day or it
# doesn't -- the weekly bench-the-worst-ranked-arm mechanic already operates at
# effectively per-start granularity, since a starter works one turn a week.
def daily_stats(season, group="pitching"):
    """-> {date: {mlbam: stats}}, zero stats omitted, days with no stats
    omitted entirely. One stats=byDateRange call per calendar day for the
    whole league (~180 a season) rather than a game log per player (~1,500) --
    same trick as weekly_stats, one day wide instead of seven."""
    def go():
        out = {}
        for d in season_days(season):
            q = ("stats=byDateRange&group=%s&season=%d&startDate=%s&endDate=%s"
                 % (group, season, d, d))
            rows = {str(sp["player"]["id"]): {k: v for k, v in
                                              our_stats(sp["stat"], group).items() if v}
                    for sp in pages(q)}
            if rows:
                out[d] = rows
        return out
    return cached("%d_%s_daily" % (season, group), go)


def weekly_main(seasons):
    """Pull, then check the weeks (or days, for pitching) add back up to
    statsapi's own season totals -- a window that drops a traded player's
    games, or a gap between windows, shows up here rather than as a quiet
    shortfall in whatever reads it."""
    for y in seasons:
        for group in ("hitting", "pitching"):
            wk = weekly_stats(y, group)
            w = bt.BAT_W if group == "hitting" else bt.PIT_W
            tot = {}
            for week in wk.values():
                for pid, s in week.items():
                    tot[pid] = tot.get(pid, 0.0) + bt.points(s, w)
            season = season_stats(y, group)
            off = [pid for pid in set(tot) | set(season)
                   if abs(tot.get(pid, 0.0) - bt.points(season.get(pid, {}), w)) > 0.5]
            print("%d %-8s %2d weeks  %4d players  weekly sums off season total: %d"
                  % (y, group, len(wk), len(tot), len(off)))
        dy = daily_stats(y, "pitching")
        tot = {}
        for day in dy.values():
            for pid, s in day.items():
                tot[pid] = tot.get(pid, 0.0) + bt.points(s, bt.PIT_W)
        season = season_stats(y, "pitching")
        off = [pid for pid in set(tot) | set(season)
               if abs(tot.get(pid, 0.0) - bt.points(season.get(pid, {}), bt.PIT_W)) > 0.5]
        print("%d %-8s %2d days   %4d players  daily sums off season total: %d"
              % (y, "pitching", len(dy), len(tot), len(off)))


# --- weekly pitching lineup simulation (Task 10) -----------------------------
# The season-total bed prices every rostered starter's and reliever's projected
# PAR in full, as if a team could always deploy its whole staff. Real Ottoneu
# H2H can't: SP is capped at GS_CAP starts a week (a team with 8 rotation arms
# often turns in more than 10 combined starts some weeks and has to sit some of
# them), and a reliever only pitches ~40% of his team's games, so an owner is
# choosing which 5 of his bullpen are "active" -- daily, since Ottoneu allows
# daily lineup changes (confirmed 2026-09-12; a first cut of this sim locked
# the choice for the whole week and understated RP reliability). Neither is
# visible to a season-total bed. This builds synthetic 12-team staffs from the
# same projected pool the bed already prices, and replays each actual line
# through a no-hindsight bench policy, to see whose realized value the bench
# decisions actually cost.
ACTIVE_RP = 5          # rules: the standard lineup's RP slots (roster carries RP_SLOTS)
# Ottoneu allows daily lineup changes (confirmed by the league owner
# 2026-09-12), so RP activation is decided fresh each day, not locked for the
# week -- a week-locked active-5 is stricter than a real GM plays under and
# understates RP reliability. TRAILING_DAYS is the day-granularity analogue of
# the original TRAILING_WEEKS=3 (roughly the same elapsed time, ~21 days);
# both are activation-signal windows, not rules, and both are stress-tested by
# `--lineup-sim`'s own sensitivity sweep.
TRAILING_DAYS = 14


def snake_teams(ranked_pids, n_teams, roster_size):
    """-> {team: [pid, ...]}. `ranked_pids` sorted best-to-worst (preseason
    projection); a snake draft spreads talent the way an auction/draft roughly
    does, so no synthetic team is stacked or starved by construction."""
    teams = {t: [] for t in range(n_teams)}
    order = list(range(n_teams))
    it = iter(ranked_pids)
    for rnd in range(roster_size):
        for t in (order if rnd % 2 == 0 else order[::-1]):
            pid = next(it, None)
            if pid is None:
                return teams
            teams[t].append(pid)
    return teams


def sim_sp_team(roster, weeks, wk_pit, proj_pts):
    """-> ({pid: policy points}, {pid: uncapped points}, [team policy points
    per week]) for one team's rotation. A week whose combined starts exceed
    GS_CAP benches whole starts from the worst-projected arm first -- fixed by
    preseason rank, never that week's result, so this is a policy a GM could
    actually have followed. The weekly breakdown is what a real matchup needs;
    the two season totals are what the RELIABILITY-ratio measurement needs."""
    worst_first = sorted(roster, key=lambda pid: proj_pts.get(pid, 0.0))
    policy, uncapped, weekly = {pid: 0.0 for pid in roster}, {pid: 0.0 for pid in roster}, []
    for wk in weeks:
        lines = {pid: wk_pit.get(wk, {}).get(pid, {}) for pid in roster}
        starts = {pid: lines[pid].get("GS", 0.0) for pid in roster}
        pts = {pid: bt.points(lines[pid], bt.PIT_W) for pid in roster}
        for pid in roster:
            uncapped[pid] += pts[pid]
        remaining = sum(starts.values())
        active = set(roster)
        for pid in worst_first:
            if remaining <= value.GS_CAP:
                break
            if starts[pid] <= 0:
                continue
            active.discard(pid)
            remaining -= starts[pid]
        for pid in active:
            policy[pid] += pts[pid]
        weekly.append(sum(pts[pid] for pid in active))
    return policy, uncapped, weekly


def sim_rp_team(roster, periods, stats_by_period, proj_pts,
                active_slots=ACTIVE_RP, trailing=TRAILING_DAYS):
    """-> {pid: policy points}. Each period (a day, in practice -- Ottoneu
    allows daily changes) activates the `active_slots` arms with the best
    trailing signal (mean actual points, last `trailing` periods, zeros
    included; preseason projection before any history exists) -- what a GM
    could know setting that day's lineup, never that period's own result."""
    policy = {pid: 0.0 for pid in roster}
    history = {pid: [] for pid in roster}
    for period in periods:
        lines = {pid: stats_by_period.get(period, {}).get(pid, {}) for pid in roster}
        pts = {pid: bt.points(lines[pid], bt.PIT_W) for pid in roster}

        def signal(pid):
            h = history[pid][-trailing:]
            return sum(h) / len(h) if h else proj_pts.get(pid, 0.0)

        for pid in sorted(roster, key=signal, reverse=True)[:active_slots]:
            policy[pid] += pts[pid]
        for pid in roster:
            history[pid].append(pts[pid])
    return policy


def simulate_season(y, suffix, n_teams, depth, active_rp=ACTIVE_RP):
    """-> {"SP": {pid: policy pts}, "SP_uncapped": {...}, "RP": {pid: policy pts}}
    for one bed season's projected pool, drafted into synthetic staffs and
    replayed week by week.

    Roster size always matches `depth` (the same SP/RP counts the season-total
    bed already prices) -- only `active_rp` (how many of the 6 rostered arms
    play a given day) varies, so a 5-vs-6 comparison changes one mechanic at a
    time instead of also silently changing the priced player pool.

    SP is replayed by calendar week (GS_CAP is a genuinely weekly rule); RP by
    calendar day (Ottoneu allows daily lineup changes, so the active-5 decision
    is a daily one -- see the TRAILING_DAYS comment)."""
    rows, pp, ap = bt.load_bed(os.path.join(OUT, "backtest_%d%s.csv" % (y, suffix)), "", "")
    proj = bt.mkpool(rows, "proj", pp)
    _, _, assigned = value.price(proj, depth)
    proj_pts = {pid: p["pts"] for pid, p in proj.items()}
    wk_pit = weekly_stats(y, "pitching")
    weeks = [a for a, _ in season_weeks(y)]
    day_pit = daily_stats(y, "pitching")
    days = season_days(y)

    out = {"SP": {}, "SP_uncapped": {}, "RP": {}}
    sp_ranked = sorted((pid for pid, role in assigned.items() if role == "SP"),
                       key=lambda pid: -proj_pts[pid])
    for roster in snake_teams(sp_ranked, n_teams, depth["SP"] // n_teams).values():
        policy, uncapped, _ = sim_sp_team(roster, weeks, wk_pit, proj_pts)
        out["SP"].update(policy)
        out["SP_uncapped"].update(uncapped)

    rp_ranked = sorted((pid for pid, role in assigned.items() if role == "RP"),
                       key=lambda pid: -proj_pts[pid])
    for roster in snake_teams(rp_ranked, n_teams, depth["RP"] // n_teams).values():
        out["RP"].update(sim_rp_team(roster, days, day_pit, proj_pts, active_rp))
    return out


def lineup_sim_main(suffix):
    """Aggregate the lineup policy across the whole bed and print it beside the
    season-total floored `RELIABILITY` ratio (the basis proportional pricing
    actually uses -- APPROACH trap 29/30), relative to hitters.

    RP runs twice: active_rp=6 (every rostered arm always active every day --
    no bench mechanic at all, so this should reproduce the season-total floored
    ratio almost exactly, as a sanity check) and active_rp=5 (the real rule --
    the gap between them is what the mandatory daily bench actually costs)."""
    cfg = value.load_settings(os.path.join(value.DATA, "league.csv"))
    n_teams = cfg["teams"] or 12
    depth = value.base_depth(n_teams, cfg)
    seasons = [y for y in range(FIRST_TARGET, LAST_TARGET + 1) if y not in SKIP
               if os.path.exists(os.path.join(OUT, "backtest_%d%s.csv" % (y, suffix)))]

    acc = {g: [0.0, 0.0] for g in ("H", "SP", "SP_uncapped", "RP5", "RP6")}
    for y in seasons:
        sim5 = simulate_season(y, suffix, n_teams, depth, active_rp=5)
        sim6 = simulate_season(y, suffix, n_teams, depth, active_rp=6)
        rows, pp, ap = bt.load_bed(os.path.join(OUT, "backtest_%d%s.csv" % (y, suffix)), "", "")
        proj, _, alevels = bt.pools(rows, depth, pp, ap)
        for pid, p in proj.items():
            if p["par"] <= 0:
                continue
            g = "H" if p["vpos"] in value.HITTER_POS else p["vpos"]
            if g == "H":
                acc["H"][1] += p["par"]
                acc["H"][0] += max(p["realized_par"], 0.0)
            elif g == "SP" and pid in sim5["SP"]:
                acc["SP"][1] += p["par"]
                acc["SP"][0] += max(sim5["SP"][pid] - alevels["SP"], 0.0)
                acc["SP_uncapped"][1] += p["par"]
                acc["SP_uncapped"][0] += max(sim5["SP_uncapped"][pid] - alevels["SP"], 0.0)
            elif g == "RP" and pid in sim5["RP"]:
                acc["RP5"][1] += p["par"]
                acc["RP5"][0] += max(sim5["RP"][pid] - alevels["RP"], 0.0)
                acc["RP6"][1] += p["par"]
                acc["RP6"][0] += max(sim6["RP"][pid] - alevels["RP"], 0.0)
    ratio = {g: (t / p if p else 0.0) for g, (t, p) in acc.items()}
    print("%d seasons, lineup-policy realized/projected PAR relative to hitters:" % len(seasons))
    for g in ("SP", "SP_uncapped", "RP5", "RP6"):
        print("  %-12s %.3f" % (g, ratio[g] / ratio["H"]))
    print("  SP_uncapped ignores the GS cap (what the season-total bed already prices);\n"
          "  SP is the same staffs with weekly benching applied -- the gap is the cap's cost.\n"
          "  RP6 (all 6 rostered arms always active every day) is the no-bench sanity check\n"
          "  against the season-total floored RELIABILITY ratio; RP5 is the real daily 5-of-6 rule.")


# --- synthetic league Monte Carlo: does $value actually predict winning? -----
# The lineup sim measured realized PAR per dollar; this measures the thing
# that's a proxy FOR -- does a $value-drafted roster win more real weekly
# matchups than a roster built by a deliberately worse strategy, given the
# SAME real subsequent production? "Value agrees with itself" would be
# circular (APPROACH trap 2: market agreement validates nothing), so this
# always runs strategies against each other in one league, never value alone.
#
# No historical Ottoneu roster export is needed: everything here is a
# one-shot startup auction (no keepers) built from the same projected pool the
# season-total bed already prices, followed by the real season's actual
# weekly production. Only the schedule and the random strategy's own bids are
# randomized -- Monte Carlo washes out matchup luck, not model uncertainty.
STRATEGIES = ("value", "points", "random")
TEAMS_PER_STRATEGY = 4    # 12 = 4+4+4, fixed every trial. Which team NUMBER
                          # carries which strategy is uninformative here (a
                          # strategy's bids don't depend on a label), so only
                          # the schedule and the random strategy's own draws
                          # need repeating across Monte Carlo trials.
ROSTER_SIZE = 40          # one-shot startup draft: no keepers, full 40-man auction


def naive_dollar_values(pool, n_teams, cfg):
    """value.py's own $-conversion mechanics, but one undifferentiated position
    (no scarcity split) and no RELIABILITY shrink -- the "points" strategy,
    and the exact ablation this test measures value.py's adjustments against.
    The replacement pool is sized to the SAME total as value.py's own per-
    position depths (~318 "starter" slots, not the full 480-player, 40-man-
    roster count) -- matching pool size is what keeps this an ablation of
    scarcity-and-reliability alone, not a second, accidental difference in how
    deep the market is. Works on a copy: `pool`'s own scarcity-aware
    par/vpos/value (the "value" strategy) is untouched."""
    flat = {pid: dict(p, pos=["ANY"]) for pid, p in pool.items()}
    total_slots = sum(value.base_depth(n_teams, cfg).values())
    value.price(flat, {"ANY": total_slots})
    total_par = sum(max(p["par"], 0.0) for p in flat.values())  # no reliability shrink
    value.to_dollars(flat, total_par, n_teams * (cfg["cap"] - cfg["roster_max"]))
    return flat


class DraftTeam:
    def __init__(self, strategy, valuations, cap):
        self.strategy, self.valuations, self.budget = strategy, valuations, cap
        self.roster = []

    def bid(self, pid, rng):
        if len(self.roster) >= ROSTER_SIZE:
            return 0
        room = self.budget - (ROSTER_SIZE - len(self.roster) - 1)  # $1 held per other open slot
        if room < 1:
            return 0
        if self.strategy == "random":
            return rng.randint(1, room)
        return max(0, min(room, round(self.valuations.get(pid, 0))))


def clear_price(bids):
    """-> the winning price for a list of bids, English-auction convention:
    $1 over the runner-up, capped at the winning bid itself (so a tie clears
    at the tied amount, and a sole bidder pays the $1 floor)."""
    ranked = sorted(bids, reverse=True)
    return min(ranked[0], ranked[1] + 1) if len(ranked) > 1 else 1


def run_auction(pool, n_teams, cfg, rng):
    """-> [DraftTeam, ...], TEAMS_PER_STRATEGY per strategy. Nominates in
    descending true (scarcity-aware) $value -- best player up first, the real
    auction convention -- and clears each at `clear_price`."""
    naive = naive_dollar_values(pool, n_teams, cfg)
    by_strategy = {"value": {pid: p["value"] for pid, p in pool.items()},
                   "points": {pid: p["value"] for pid, p in naive.items()},
                   "random": {}}
    teams = [DraftTeam(s, by_strategy[s], cfg["cap"])
             for s in STRATEGIES for _ in range(TEAMS_PER_STRATEGY)]
    for pid in sorted(pool, key=lambda k: -pool[k]["value"]):
        bids = {t: t.bid(pid, rng) for t in teams if pid not in t.roster}
        bids = {t: b for t, b in bids.items() if b > 0}
        if not bids:
            continue
        winner = max(bids, key=bids.get)
        winner.roster.append(pid)
        winner.budget -= clear_price(list(bids.values()))
    return teams


def team_hitter_pos(pos):
    """A team's own weekly lineup has a literal middle-infield flex slot (2B
    or SS), not the season-total depth solver's 50/50 split across all teams
    -- that split only means something once smoothed over n_teams, not for one
    team's own seven-slot infield-plus-outfield lineup."""
    return pos + (["MI"] if {"2B", "SS"} & set(pos) else [])


def score_week_hitting(roster, week, wk_bat, cfg, pool):
    """-> this team's best possible hitting lineup score for one week, from
    its own roster's real weekly production -- reuses value.draft()'s
    scarcest-slot-first, Util-second-pass logic exactly as the season-total
    engine does, just scoped to one team's roster instead of the whole league."""
    depth = {"C": cfg["catcher_slots"], "1B": 1, "2B": 1, "3B": 1, "SS": 1,
             "MI": value.MIDDLE_INFIELD, "OF": 5, "Util": 1}
    week_pool = {pid: {"pos": team_hitter_pos(pool[pid]["pos"]),
                       "pts": bt.points(wk_bat.get(week, {}).get(pid, {}), bt.BAT_W)}
                for pid in roster if value.is_hitter(pool[pid])}
    _, assigned = value.draft(week_pool, depth)
    return sum(week_pool[pid]["pts"] for pid in assigned)


def score_season(team, pool, weeks, wk_bat, wk_pit, cfg):
    """-> [this team's total FGPts, one per week], its own drafted roster
    against real production. SP still benches the worst-projected arm first
    past GS_CAP (validated, low-sensitivity, `NEXT_STEPS.md` Task 10); RP is
    credited in full every week -- the daily RP bench signal's own magnitude is
    unresolved (Task 10), and importing that noise into a different experiment
    would confound this one, so RP is deliberately the uncapped (RP6) case."""
    sp = [pid for pid in team.roster if pool[pid]["pos"][:1] == ["SP"]]
    rp = [pid for pid in team.roster if pool[pid]["pos"][:1] == ["RP"]]
    proj_pts = {pid: pool[pid]["pts"] for pid in team.roster}
    _, _, sp_weekly = sim_sp_team(sp, weeks, wk_pit, proj_pts)
    return [score_week_hitting(team.roster, wk, wk_bat, cfg, pool) + sp_weekly[i]
            + sum(bt.points(wk_pit.get(wk, {}).get(pid, {}), bt.PIT_W) for pid in rp)
            for i, wk in enumerate(weeks)]


def league_trial(pool, weeks, wk_bat, wk_pit, cfg, n_teams, rng):
    """-> {strategy: mean wins} for one Monte Carlo trial: one auction, one
    random weekly pairing schedule, real actual production decides every
    matchup."""
    teams = run_auction(pool, n_teams, cfg, rng)
    scores = [score_season(t, pool, weeks, wk_bat, wk_pit, cfg) for t in teams]
    wins = [0.0] * n_teams
    order = list(range(n_teams))
    for wi in range(len(weeks)):
        rng.shuffle(order)
        for a, b in zip(order[0::2], order[1::2]):
            if scores[a][wi] > scores[b][wi]:
                wins[a] += 1
            elif scores[b][wi] > scores[a][wi]:
                wins[b] += 1
            else:
                wins[a] += 0.5
                wins[b] += 0.5
    by_strategy = {s: [] for s in STRATEGIES}
    for t, w in zip(teams, wins):
        by_strategy[t.strategy].append(w)
    return {s: sum(v) / len(v) for s, v in by_strategy.items()}


def league_sim_main(suffix, trials=200):
    cfg = value.load_settings(os.path.join(value.DATA, "league.csv"))
    n_teams = cfg["teams"] or 12
    seasons = [y for y in range(FIRST_TARGET, LAST_TARGET + 1) if y not in SKIP
               if os.path.exists(os.path.join(OUT, "backtest_%d%s.csv" % (y, suffix)))]
    rng = random.Random(0)
    print("%d seasons x %d trials, mean wins/season by strategy "
          "(%d teams, .5 = expected under a coin flip):" % (len(seasons), trials, TEAMS_PER_STRATEGY))
    grand = {s: [] for s in STRATEGIES}
    for y in seasons:
        rows, pp, ap = bt.load_bed(os.path.join(OUT, "backtest_%d%s.csv" % (y, suffix)), "", "")
        pool = bt.mkpool(rows, "proj", pp)
        value.base_values(pool, n_teams, cfg)   # sets par/vpos/value -- the "value" strategy
        wk_bat = weekly_stats(y, "hitting")
        wk_pit = weekly_stats(y, "pitching")
        weeks = [a for a, _ in season_weeks(y)]
        per = {s: [] for s in STRATEGIES}
        for _ in range(trials):
            r = league_trial(pool, weeks, wk_bat, wk_pit, cfg, n_teams, rng)
            for s in STRATEGIES:
                per[s].append(r[s])
        print("  %d  " % y + "  ".join("%s %5.2f" % (s, sum(v) / len(v)) for s, v in per.items()))
        for s in STRATEGIES:
            grand[s] += per[s]
    print("all seasons  " + "  ".join("%s %5.3f" % (s, sum(v) / len(v)) for s, v in grand.items())
          + "  (%d weeks/season)" % len(weeks))


age_on = value.age_on


def age_factor(age):
    """Marcel's aging curve: young players improve, old ones decline, and the
    decline is gentler than the improvement."""
    if age is None:
        return 1.0
    delta = AGE_PIVOT - age
    return 1 + (AGE_YOUNG if delta > 0 else AGE_OLD) * delta


def league_rates(seasons, keys, pt_key):
    """Weighted league-average rate per unit of playing time, over the same
    seasons that feed the projection -- regression has to pull toward the run
    environment the player played in, not toward a modern or historical one."""
    tot = {k: 0.0 for k in keys}
    pt = 0.0
    for stats, w in seasons:
        for s in stats.values():
            for k in keys:
                tot[k] += w * s.get(k, 0.0)
            pt += w * s.get(pt_key, 0.0)
    return {k: (v / pt if pt else 0.0) for k, v in tot.items()}


def project(hist, lg, reg, keys, pt_key, pt_base, age):
    """One Marcel. `hist` is [(stats, weight)] most recent first.

    Components are projected as *rates*, regressed toward league average by
    adding `reg` units of league-average playing time, then aged and multiplied
    by a separately-projected playing time. Playing time is never age-adjusted:
    the aging curve is about performance, and applying it to PA as well would
    charge every player for his age twice.
    """
    tot = {k: 0.0 for k in keys}
    den = 0.0
    for stats, w in hist:
        for k in keys:
            tot[k] += w * stats.get(k, 0.0)
        den += w * stats.get(pt_key, 0.0)
    for k in keys:                       # regression toward the league
        tot[k] += reg * lg[k]
    den += reg
    f = age_factor(age)
    rate = {k: f * v / den for k, v in tot.items()}

    recent = [stats.get(pt_key, 0.0) for stats, _ in hist] + [0.0, 0.0]
    pt = PT_RECENT * recent[0] + PT_PRIOR * recent[1] + pt_base
    out = {k: v * pt for k, v in rate.items()}
    out[pt_key] = pt
    return out


def prior_seasons(target):
    """The three most recent seasons before `target`, skipping 2020 entirely."""
    out, y = [], target - 1
    while len(out) < len(WEIGHTS) and y >= FIRST_TARGET - 5:
        if y not in SKIP:
            out.append(y)
        y -= 1
    return out


def build(target, cache):
    """-> rows in the shape backtest.py --dollars reads."""
    priors = prior_seasons(target)
    for y in priors + [target]:
        cache.setdefault(y, {
            "hitting": season_stats(y, "hitting"),
            "pitching": season_stats(y, "pitching"),
            "pos": season_positions(y),
            "people": season_people(y),
        })

    rows = {}
    for group, weights_key, keys, pt_key, reg, pt_base in (
            ("hitting", "H", [k for k in bt.BAT_W if k != "PA"], "PA", REG_PA, PT_BASE_PA),
            ("pitching", "P", [k for k in bt.PIT_W if k != "IP"] + ["GS"], "IP",
             REG_IP, PT_BASE_IP_SP)):
        hist = [(cache[y][group], w) for y, w in zip(priors, WEIGHTS)]
        lg = league_rates(hist, keys, pt_key)
        actual = cache[target][group]
        w = bt.BAT_W if group == "hitting" else bt.PIT_W
        floor = bt.MIN_PA if group == "hitting" else bt.MIN_IP

        played = set()
        for stats, _ in hist:
            played |= set(stats)
        for pid in played:
            person = next((cache[y]["people"].get(pid) for y in priors
                           if pid in cache[y]["people"]), None)
            if not person:
                continue
            name, birth, primary = person
            ph = [(cache[y][group].get(pid, {}), wt) for y, wt in zip(priors, WEIGHTS)]
            base = pt_base
            if group == "pitching":
                # Role decides the floor, and it is read off prior starts rather
                # than projected ones -- projected GS depends on projected IP,
                # which depends on this, and that loop has no fixed point.
                gs = [(st.get("GS", 0.0), wt) for st, wt in ph if st.get("IP", 0.0) > 0]
                mean_gs = (sum(g * wt for g, wt in gs) / sum(wt for _, wt in gs)
                           if gs else 0.0)
                base = PT_BASE_IP_SP if mean_gs >= 5 else PT_BASE_IP_RP
            proj = project(ph, lg, reg, keys, pt_key, base, age_on(birth, target))
            if proj[pt_key] < floor:
                continue
            a = actual.get(pid)
            if not a:
                continue

            # Eligibility is what you'd have known at the auction: games played
            # at a position in the two seasons before the target.
            if group == "hitting":
                g = {}
                for y in priors[:2]:
                    for pos, n in cache[y]["pos"].get(pid, {}).items():
                        g[pos] = g.get(pos, 0) + n
                ppos = hitting_pos(primary, g)
                if ppos is None:
                    continue
                apos = ppos
            else:
                ppos = "SP" if proj["GS"] >= 5 else "RP"
                apos = "SP" if a.get("GS", 0) >= 5 else "RP"

            r = rows.get(pid)
            if r:  # a two-way player scores in both -- his points add up
                r["proj"] += bt.points(proj, w)
                r["actual"] += bt.points(a, w)
                r["group"] = "2W"
                r["proj_pos"] = r["proj_pos"] + "/" + ppos
                r["act_pos"] = r["act_pos"] + "/" + apos
                continue
            rows[pid] = {"mlbam": pid, "fg_id": "", "name": name,
                         "group": weights_key, "pos": apos,
                         "proj_pos": ppos, "act_pos": apos,
                         "proj": bt.points(proj, w), "actual": bt.points(a, w),
                         "proj_pt": proj[pt_key], "actual_pt": a.get(pt_key, 0.0)}
    return list(rows.values())


HIST_STEAMER = os.path.join(value.DATA, "Historic Steamer Preseason Projections")


def steamer_hist(year, pitcher):
    """-> {mlbam: stats} from a FanGraphs "Historical Projections" Steamer
    export, in our stat names -- the same raw components bt.points() scores
    everywhere else, not the file's own FPTS/SPTS column (one formula for both
    sides, per backtest.py's docstring)."""
    name = "%d %s.csv" % (year, "Pitchers" if pitcher else "Hitter")
    keys = ["GS", "IP", "SO", "H", "BB", "HBP", "HR", "SV", "HLD"] if pitcher \
        else ["PA", "AB", "H", "2B", "3B", "HR", "BB", "HBP", "SB", "CS"]
    with open(os.path.join(HIST_STEAMER, name), newline="", encoding="utf-8-sig") as f:
        # IP here is a real decimal (a projection, not a box score), unlike
        # statsapi's .1/.2-for-thirds -- bt.innings() would misread it.
        return {r["MLBAMID"]: {k: bt.num(r[k]) for k in keys}
                for r in csv.DictReader(f) if r.get("MLBAMID")}


def build_steamer(target, cache):
    """-> rows in the shape backtest.py reads, like build(), but the projected
    line comes from a historic Steamer export instead of Marcel. Positions and
    actuals still come from the statsapi cache, so only the projection source
    differs and the two beds are comparable (`--measure`, aging_ratios)."""
    priors = prior_seasons(target)
    for y in priors + [target]:
        cache.setdefault(y, {
            "hitting": season_stats(y, "hitting"),
            "pitching": season_stats(y, "pitching"),
            "pos": season_positions(y),
            "people": season_people(y),
        })
    rows = {}
    for group, weights_key, pitcher in (("hitting", "H", False), ("pitching", "P", True)):
        w = bt.PIT_W if pitcher else bt.BAT_W
        floor = bt.MIN_IP if pitcher else bt.MIN_PA
        pt_key = "IP" if pitcher else "PA"
        actual = cache[target][group]
        for pid, proj in steamer_hist(target, pitcher).items():
            if proj[pt_key] < floor:
                continue
            a = actual.get(pid)
            person = next((cache[y]["people"].get(pid) for y in priors
                           if pid in cache[y]["people"]), None)
            if not a or not person:
                continue
            name, birth, primary = person
            if pitcher:
                ppos = "SP" if proj["GS"] >= 5 else "RP"
                apos = "SP" if a.get("GS", 0) >= 5 else "RP"
            else:
                g = {}
                for y in priors[:2]:
                    for pos, n in cache[y]["pos"].get(pid, {}).items():
                        g[pos] = g.get(pos, 0) + n
                ppos = hitting_pos(primary, g)
                if ppos is None:
                    continue
                apos = ppos

            r = rows.get(pid)
            if r:  # a two-way player scores in both -- his points add up
                r["proj"] += bt.points(proj, w)
                r["actual"] += bt.points(a, w)
                r["group"] = "2W"
                r["proj_pos"] = r["proj_pos"] + "/" + ppos
                r["act_pos"] = r["act_pos"] + "/" + apos
                continue
            rows[pid] = {"mlbam": pid, "fg_id": "", "name": name,
                         "group": weights_key, "pos": apos,
                         "proj_pos": ppos, "act_pos": apos,
                         "proj": bt.points(proj, w), "actual": bt.points(a, w),
                         "proj_pt": proj[pt_key], "actual_pt": a.get(pt_key, 0.0)}
    return list(rows.values())


# Keeper aging: realized PAR k seasons later over realized PAR now, both floored
# at zero (the basis RELIABILITY is measured on), for the players Marcel PRICED,
# by age. Two things learned the hard way:
#
# * Measure VALUE, not points. Ageing points and then subtracting a full
#   replacement level treats a pitcher's ~22% chance of being hurt as a healthy
#   season at 78% -- and value is convex, so that turned a 22% points drop into
#   a ~45% value drop and told you to cut Skenes and Skubal.
# * Measure every k directly; don't chain a one-year multiplier. Chaining
#   overstated a 30-year-old hitter's fourth year by a third (0.53 vs 0.40 on
#   points), because the one-year pairs are dominated by survivors.
#
# Four seasons is as far as the bed reaches; the bins are four years wide
# because floored PAR is heavy-tailed and two-year pitcher bins came out
# non-monotone at n 100-300.
AGING_BINS = [(0, 25), (26, 29), (30, 33), (34, 99)]
AGING_HORIZON = 4


def aging_bed(suffix=""):
    """-> (birth, {season: projected pool}, {season: $ per PAR}) over the bed.
    Each pool is reliability-shrunk and priced exactly as value.py prices a live
    season, so a player's `par` is what keeper_npv calls base_par.

    `suffix` picks the bed: "" is Marcel (`out/backtest_YYYY.csv`), "_steamer"
    the historic-Steamer bed from `marcel.py --steamer`."""
    cfg = value.load_settings(os.path.join(value.DATA, "league.csv"))
    n_teams = cfg["teams"] or 12
    depth = value.base_depth(n_teams, cfg)
    seasons = [y for y in range(FIRST_TARGET, LAST_TARGET + 1) if y not in SKIP]
    birth = {}
    for y in seasons:
        birth.update({k: v[1] for k, v in season_people(y).items()})
    pools, rates = {}, {}
    for y in seasons:
        path = os.path.join(OUT, "backtest_%d%s.csv" % (y, suffix))
        if not os.path.exists(path):
            continue
        rows, pp, ap = bt.load_bed(path, "", "")
        pool = bt.pools(rows, depth, pp, ap)[0]
        rates[y] = value.to_dollars(pool, value.apply_reliability(pool),
                                    n_teams * (cfg["cap"] - cfg["roster_max"]))
        pools[y] = pool
    return birth, pools, rates


def measure_aging():
    birth, pools, _ = aging_bed()
    return aging_ratios(birth, pools)


def aging_ratios(birth, pools, drop=lambda y, later: False):
    """-> [(group, k, age_lo, age_hi, ratio, n)]. A player gone from the majors
    counts as zero -- he is worth nothing to a keeper and cutting him is free --
    but a season that isn't there (2020, the future) is unknown, not zero.
    `drop(y, y + k)` leaves a pair out; --npv uses it to hold out what it scores."""
    acc = {}
    for y in sorted(pools):
        for pid, p in pools[y].items():
            age = age_on(birth.get(pid, ""), y)
            if p["par"] <= 0 or age is None:
                continue
            g = "P" if p["vpos"] in value.PITCHER_POS else "H"
            b = next(i for i, (lo, hi) in enumerate(AGING_BINS) if lo <= age <= hi)
            for k in range(1, AGING_HORIZON + 1):
                if y + k in pools and not drop(y, y + k):
                    later = pools[y + k].get(pid)   # absent = didn't play = zero
                    a = acc.setdefault((g, k, b), [0.0, 0.0, 0])
                    a[0] += max(p["realized_par"], 0.0)
                    a[1] += max(later["realized_par"], 0.0) if later else 0.0
                    a[2] += 1
    return [(g, k, AGING_BINS[b][0], AGING_BINS[b][1], round(t / s, 3), n)
            for (g, k, b), (s, t, n) in sorted(acc.items())]


def same_season_bias(birth, pools):
    """-> [(group, age_lo, age_hi, ratio, n)]: realized/projected PAR by age
    bin, k=0 (no aging horizon). Isolates whether an aging-table miss by age
    belongs to the base projection itself, before any horizon is applied
    (APPROACH trap 32)."""
    acc = {}
    for y, pool in pools.items():
        for pid, p in pool.items():
            age = age_on(birth.get(pid, ""), y)
            if p["par"] <= 0 or age is None:
                continue
            g = "P" if p["vpos"] in value.PITCHER_POS else "H"
            b = next(i for i, (lo, hi) in enumerate(AGING_BINS) if lo <= age <= hi)
            a = acc.setdefault((g, b), [0.0, 0.0, 0])
            a[0] += p["par"]
            a[1] += max(p["realized_par"], 0.0)
            a[2] += 1
    return [(g, AGING_BINS[b][0], AGING_BINS[b][1], round(t / s, 3), n)
            for (g, b), (s, t, n) in sorted(acc.items())]


def realize(pred, real, d):
    """-> (realized NPV following the model's keep/cut policy, realized NPV with
    hindsight), both in this season's dollars like keeper_npv. The policy keeps
    season k while the expected path says what remains is worth it; hindsight
    cuts perfectly and brackets it from above."""
    v, vs = 0.0, []
    for s in reversed(pred):
        v = max(0.0, s + d * v)
        vs.insert(0, v)
    pol, w = 0.0, d
    for vk, s in zip(vs, real):
        if vk <= 0:
            break
        pol += w * s
        w *= d
    h = 0.0
    for s in reversed(real):
        h = max(0.0, s + d * h)
    return pol, d * h


def npv_backtest():
    """Out-of-sample keeper_npv on the bed: price each season Y, predict its
    future seasons with an aging table measured WITHOUT any pair touching
    Y..Y+h, and compare to what those seasons realized. No historical salaries
    exist, so two synthetic ones: $1 (every season kept -- scores the value path)
    and half the model price (where cut decisions bite). The horizon h is the
    run of consecutive known seasons after Y, on both sides alike; 2020 ends it.

    # ponytail: held-out tables are measured on seasons before AND after the
    # window -- leave-seasons-out, not a forecast in time.
    """
    d = value.load_settings(os.path.join(value.DATA, "league.csv"))["keeper_discount"]
    birth, pools, rates = aging_bed()
    full = as_table(aging_ratios(birth, pools))
    fut, npv = {}, {}
    for y in sorted(pools):
        h = 0
        while h < AGING_HORIZON and y + h + 1 in pools:
            h += 1
        if not h:
            continue
        window = range(y, y + h + 1)
        held = as_table(aging_ratios(birth, pools, lambda a, b: a in window or b in window))
        tabs = {tag: {key: v for key, v in t.items() if key[1] <= h}
                for tag, t in (("in", full), ("out", held))}
        for pid, p in pools[y].items():
            age = age_on(birth.get(pid, ""), y)
            if p["par"] <= 0 or age is None:
                continue
            g = "P" if p["vpos"] in value.PITCHER_POS else "H"
            b = next(i for i, (lo, hi) in enumerate(AGING_BINS) if lo <= age <= hi)
            p["base_par"], p["pts_p"] = p["par"], (p["pts"] if g == "P" else 0.0)
            real = [max(pools[y + k][pid]["realized_par"], 0.0) if pid in pools[y + k]
                    else 0.0 for k in range(1, h + 1)]
            for k, rp in enumerate(real, 1):
                a = fut.setdefault((g, b, k), [0.0, 0.0, 0.0, 0])
                for i, tag in enumerate(("in", "out")):
                    a[i] += p["par"] * next((x for lo, hi, x in tabs[tag].get((g, k), ())
                                             if lo <= age <= hi), 0.0)
                a[2] += rp
                a[3] += 1
            for sc, s0 in (("$1", 1), ("half", max(1, round(p["value"] / 2)))):
                r = {"salary": s0, "has_mlb": True}
                real_s = [1 + rp * rates[y] - (s0 + value.RETENTION_MLB * k)
                          for k, rp in enumerate(real, 1)]
                pol, hind = realize(value.keeper_surpluses(p, r, age, 0, rates[y], tabs["out"]),
                                    real_s, d)
                a = npv.setdefault((sc, g, b), [0, 0.0, 0.0, 0.0, 0.0])
                a[0] += 1
                a[1] += value.keeper_npv(p, r, age, 0, rates[y], tabs["in"], d)
                a[2] += value.keeper_npv(p, r, age, 0, rates[y], tabs["out"], d)
                a[3] += pol
                a[4] += hind

    ratio = lambda n, m: "%.2f" % (n / m) if m else "  - "
    print("future floored PAR, realized / predicted -- out-of-sample (in-sample):")
    for g in ("H", "P"):
        for b, (lo, hi) in enumerate(AGING_BINS):
            cells = ["k%d %s (%s) n%d" % (k, ratio(a[2], a[1]), ratio(a[2], a[0]), a[3])
                     for k in range(1, AGING_HORIZON + 1)
                     for a in [fut.get((g, b, k))] if a]
            print("  %s %2d-%-2d  %s" % (g, lo, hi, "   ".join(cells)))
    print("\nkeeper NPV per player, discount %.2f -- predicted in / out-of-sample, "
          "realized under the model's policy, realized with hindsight:" % d)
    for sc in ("$1", "half"):
        print("  salary %s" % sc)
        for g in ("H", "P"):
            for b, (lo, hi) in enumerate(AGING_BINS):
                a = npv.get((sc, g, b))
                if a:
                    n = a[0]
                    print("    %s %2d-%-2d n%5d   %6.2f %6.2f   %6.2f   %6.2f   "
                          "realized/predicted %s"
                          % (g, lo, hi, n, a[1] / n, a[2] / n, a[3] / n, a[4] / n,
                             ratio(a[3], a[2])))


def as_table(rows):
    """aging_ratios rows -> the {(group, k): [(lo, hi, ratio)]} load_aging gives."""
    out = {}
    for g, k, lo, hi, x, _ in rows:
        out.setdefault((g, k), []).append((lo, hi, x))
    return out


def fetch_birthdates(ids):
    """{mlbam: birthDate} from statsapi, cached, asking only for ids not already
    known. An id statsapi doesn't recognise is stored blank so it isn't asked
    for again on every run."""
    path = os.path.join(CACHE, "birthdates.json")
    have = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            have = json.load(f)
    need = sorted(set(ids) - set(have))
    for i in range(0, len(need), 100):
        url = "%s/people?personIds=%s" % (API, ",".join(need[i:i + 100]))
        for p in json.load(urllib.request.urlopen(url, timeout=180)).get("people", []):
            have[str(p["id"])] = p.get("birthDate", "")
    for pid in need:
        have.setdefault(pid, "")
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(have, f)
    return have


def aging_main():
    rows = measure_aging()
    with open(os.path.join(value.DATA, "aging.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group", "k", "age_lo", "age_hi", "ratio", "n"])
        w.writerows(rows)
    for g in ("H", "P"):
        print("%s  " % g + "  ".join(
            "%d-%d: %s" % (lo, hi, "/".join("%.2f" % x for gg, k, l2, h2, x, n in rows
                                             if gg == g and l2 == lo))
            for lo, hi in AGING_BINS))
    print("  (ratio of floored PAR 1/2/3/4 seasons later to now; wrote data/aging.csv)")
    ids = {}
    for name in ("steamer_bat.csv", "steamer_pit.csv"):
        with open(os.path.join(value.DATA, name), newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r.get("xMLBAMID"):
                    ids[r["playerid"]] = r["xMLBAMID"]
    if not ids:
        print("no xMLBAMID column in data/steamer_*.csv -- re-export per README")
        return
    bd = fetch_birthdates(ids.values())
    with open(os.path.join(value.DATA, "birthdates.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["playerid", "birthDate"])
        w.writerows(sorted((pid, bd.get(m, "")) for pid, m in ids.items()))
    print("wrote data/birthdates.csv: %d of %d projected players dated"
          % (sum(1 for m in ids.values() if bd.get(m)), len(ids)))


def main(argv):
    def arg(flag, default):
        return argv[argv.index(flag) + 1] if flag in argv else default

    steamer = "--steamer" in argv
    builder, suffix = (build_steamer, "_steamer") if steamer else (build, "")
    years = arg("--years", "")
    targets = ([int(y) for y in years.split(",")] if years else
               [y for y in range(FIRST_TARGET, LAST_TARGET + 1) if y not in SKIP])
    os.makedirs(OUT, exist_ok=True)
    cache = {}
    for t in targets:
        priors = prior_seasons(t)
        print("%d  <- %s" % (t, ", ".join(str(y) for y in priors)))
        rows = builder(t, cache)
        path = os.path.join(OUT, "backtest_%d%s.csv" % (t, suffix))
        with open(path, "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            wr.writeheader()
            for r in sorted(rows, key=lambda r: -r["actual"]):
                wr.writerow({k: (round(v, 1) if isinstance(v, float) else v)
                             for k, v in r.items()})
        note = "  (most recent input is %d -- 2020 skipped)" % priors[0] \
            if priors[0] != t - 1 else ""
        print("  wrote %s (%d players)%s" % (path, len(rows), note))
    print("\nScore each with:  py -3.13 backtest.py --dollars --backtest "
          "out/backtest_YYYY%s.csv" % suffix)


def selftest():
    assert 2020 not in prior_seasons(2021) and prior_seasons(2021) == [2019, 2018, 2017]
    assert prior_seasons(2019) == [2018, 2017, 2016]
    assert prior_seasons(2022) == [2021, 2019, 2018], prior_seasons(2022)

    # Aging: young players get a bump, old ones a smaller cut, 29 is neutral.
    assert age_factor(29) == 1.0
    assert age_factor(24) > 1.0 and age_factor(34) < 1.0
    assert abs(age_factor(24) - 1.03) < 1e-9      # 5 years x 0.006
    assert abs(age_factor(34) - 0.985) < 1e-9     # 5 years x 0.003
    assert age_factor(None) == 1.0, "unknown birthdate must not shift anyone"
    assert age_on("1990-06-29", 2020) == 30 and age_on("1990-07-01", 2020) == 29

    # A player exactly at league average, aged 29, projects to the league rate:
    # regression can't move him and aging can't either.
    lg = {"HR": 0.05}
    hist = [({"HR": 25.0, "PA": 500.0}, 5), ({"HR": 25.0, "PA": 500.0}, 4)]
    base = project(hist, lg, REG_PA, ["HR"], "PA", PT_BASE_PA, 29)
    assert abs(base["HR"] / base["PA"] - 0.05) < 1e-9, base
    assert abs(base["PA"] - (0.5 * 500 + 0.1 * 500 + 200)) < 1e-9, base

    # An above-average player is pulled *down* toward the league, never past it.
    hot = [({"HR": 50.0, "PA": 500.0}, 5)]
    p = project(hot, lg, REG_PA, ["HR"], "PA", PT_BASE_PA, 29)
    assert 0.05 < p["HR"] / p["PA"] < 0.10, p["HR"] / p["PA"]
    # ...and regression is stronger with less playing time behind it.
    thin = [({"HR": 10.0, "PA": 100.0}, 5)]
    q = project(thin, lg, REG_PA, ["HR"], "PA", PT_BASE_PA, 29)
    assert abs(q["HR"] / q["PA"] - 0.05) < abs(p["HR"] / p["PA"] - 0.05)

    # Playing time must not be aged twice: a 24-year-old's rate rises, his
    # projected PA does not.
    young = project(hist, lg, REG_PA, ["HR"], "PA", PT_BASE_PA, 24)
    assert young["PA"] == base["PA"], "playing time is not age-adjusted"
    assert abs(young["HR"] / base["HR"] - age_factor(24)) < 1e-9

    # A pitcher is only ever a pitcher: no pitching position may ever map to a
    # hitting slot, or NL pitchers' batting lines flood the 1B pool.
    # The playing-time floor is one third of a full workload, per role. A single
    # floor across all pitchers is what broke relievers.
    for base, full in ((PT_BASE_PA, FULL_PA), (PT_BASE_IP_SP, FULL_IP_SP),
                       (PT_BASE_IP_RP, FULL_IP_RP)):
        assert abs(base / full - 1 / 3.0) < 0.02, (base, full)
    # A reliever's projection must not carry a starter's floor: 65 prior innings
    # projects near 65, not near 100.
    lg2 = {"SO": 0.25}
    rp = project([({"SO": 70.0, "IP": 65.0}, 5)], lg2, REG_IP, ["SO"], "IP",
                 PT_BASE_IP_RP, 29)
    assert 50 < rp["IP"] < 75, rp["IP"]
    sp = project([({"SO": 180.0, "IP": 180.0}, 5)], lg2, REG_IP, ["SO"], "IP",
                 PT_BASE_IP_SP, 29)
    assert 140 < sp["IP"] < 180, sp["IP"]

    assert FIELD_POS["CF"] == "OF" and "DH" not in FIELD_POS
    for bad in ("P", "SP", "RP", "DH", "PH", "PR", ""):
        assert bad not in FIELD_POS, bad
    assert set(FIELD_POS.values()) <= set(value.POSITIONS)
    # A pitcher's batting line must never reach the hitter pool, by either
    # guard. MLB tags genuine two-way players TWP, never P (checked 2018-2025),
    # so the hard guard cannot eat a real two-way bat, and a DH with no fielding
    # position is a Util player rather than a dropped one.
    assert hitting_pos("P", {"1B": 40}) is None, "a pitcher is never a hitter"
    assert hitting_pos("P", {}) is None
    assert hitting_pos("TWP", {"OF": 80}) == "OF", "two-way bats survive"
    assert hitting_pos("DH", {}) == value.UTIL, "a DH is a Util player"
    assert hitting_pos("1B", {"1B": 9}) == value.UTIL, "9 games is not eligibility"
    assert hitting_pos("LF", {"OF": 60}) == "OF"   # keys arrive already mapped
    assert hitting_pos("2B", {"2B": 40, "SS": 30}) == "2B/SS"

    # --npv: the policy stops at the first season the expected path says to cut,
    # even if it then realized big; hindsight doesn't.
    assert realize([5, -1], [3, 100], 1.0) == (3, 103)
    assert realize([5, -1], [3, 100], 0.5) == (1.5, 26.5)
    # Held-out pairs really are held out.
    pools = {2015: {"a": {"par": 10.0, "realized_par": 10.0, "vpos": "OF"}},
             2016: {"a": {"par": 10.0, "realized_par": 5.0, "vpos": "OF"}}}
    birth = {"a": "1990-01-01"}                   # 25 in 2015
    assert aging_ratios(birth, pools) == [("H", 1, 0, 25, 0.5, 1)]
    assert aging_ratios(birth, pools, lambda y, later: later == 2016) == []
    assert same_season_bias(birth, {2015: pools[2015]}) == [("H", 0, 25, 1.0, 1)]

    # Weekly lineup sim: snake draft spreads talent, doesn't stack one team.
    teams = snake_teams(["a", "b", "c", "d"], 2, 2)
    assert teams == {0: ["a", "d"], 1: ["b", "c"]}, teams

    # SP bench: a week's combined starts over GS_CAP bench the worst-projected
    # arm's whole week, not just the overage -- 'x' outranks 'y' on preseason
    # points, so 'y' sits and scores nothing that week, capped or not.
    wk_pit = {"w1": {"x": {"GS": 6, "IP": 40, "SO": 40}, "y": {"GS": 6, "IP": 40, "SO": 40}}}
    policy, uncapped, weekly = sim_sp_team(["x", "y"], ["w1"], wk_pit, {"x": 100, "y": 50})
    assert weekly == [376.0], weekly
    assert policy == {"x": 376.0, "y": 0.0}, policy
    assert uncapped == {"x": 376.0, "y": 376.0}, "uncapped ignores the bench entirely"

    # RP activation: week 1 has no history, so the preseason-ranked top 2 of 3
    # play; week 2 re-ranks on trailing actual points, no hindsight -- 'c' was
    # benched in week 1 despite the big week he actually had, and only starts
    # counting once week 2's ranking (built from week 1's *result*) picks him.
    wk_rp = {"w1": {"a": {"IP": 2, "SO": 2}, "b": {"IP": 1, "SO": 1}, "c": {"IP": 5, "SO": 5}},
             "w2": {"a": {"IP": 3, "SO": 3}, "b": {"IP": 10, "SO": 10}, "c": {"IP": 1, "SO": 1}}}
    rp_policy = sim_rp_team(["a", "b", "c"], ["w1", "w2"], wk_rp,
                            {"a": 10, "b": 5, "c": 1}, active_slots=2)
    assert round(rp_policy["b"], 1) == 9.4, "b's week 2 (94 pts) never counts -- benched"
    assert round(rp_policy["c"], 1) == 9.4, "c's week 1 (47 pts) never counts -- benched"

    # Synthetic league: auction clearing price, budget reserve, MI flex slot.
    assert clear_price([50, 30, 10]) == 31         # $1 over the runner-up
    assert clear_price([50, 50]) == 50             # a tie clears at the tied bid
    assert clear_price([50]) == 1                  # sole bidder pays the $1 floor

    t = DraftTeam("value", {"a": 50}, cap=100)
    assert t.bid("a", random.Random(0)) == 50      # plenty of room
    t.roster, t.budget = ["x"] * 38, 10            # 2 slots left, one is this bid
    assert t.bid("a", random.Random(0)) == 9       # $1 held back for the other slot
    t.roster, t.budget = ["x"] * 39, 5             # last slot: no reserve needed
    assert t.bid("a", random.Random(0)) == 5
    t.roster = ["x"] * 40                          # roster full
    assert t.bid("a", random.Random(0)) == 0

    assert team_hitter_pos(["2B"]) == ["2B", "MI"]
    assert team_hitter_pos(["OF"]) == ["OF"]
    week_pool = {"c1": {"pos": team_hitter_pos(["C"]), "pts": 10.0},
                "ss1": {"pos": team_hitter_pos(["SS"]), "pts": 8.0},
                "ss2": {"pos": team_hitter_pos(["SS"]), "pts": 7.0},
                "2b1": {"pos": team_hitter_pos(["2B"]), "pts": 6.0}}
    _, assigned = value.draft(week_pool, {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1,
                                          "MI": value.MIDDLE_INFIELD, "OF": 5, "Util": 1})
    # ss2 has no natural SS slot left (ss1 outscored him for it) but still
    # starts, at the extra middle-infield flex slot the season-total depth
    # solver's 50/50 split can't represent for one team's own lineup.
    assert set(assigned) == {"c1", "ss1", "ss2", "2b1"}, assigned
    assert assigned["ss2"] == "MI", assigned

    # Weeks tile the season exactly: no gap, no overlap, Monday starts after
    # the first. 2019 opened on a Wednesday in Tokyo.
    wk = calendar_weeks("2019-03-20", "2019-09-29")
    assert wk[0] == ("2019-03-20", "2019-03-24") and wk[-1][1] == "2019-09-29"
    for (_, b), (a, _) in zip(wk, wk[1:]):
        nxt = datetime.date.fromisoformat(a)
        assert nxt - datetime.date.fromisoformat(b) == datetime.timedelta(days=1)
        assert nxt.weekday() == 0
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--aging" in sys.argv:
        aging_main()
    elif "--npv" in sys.argv:
        npv_backtest()
    elif "--weekly" in sys.argv:
        weekly_main([y for y in range(FIRST_TARGET, LAST_TARGET + 1) if y not in SKIP])
    elif "--age-check" in sys.argv:
        suffix = "_steamer" if "--steamer" in sys.argv else ""
        birth, pools, _ = aging_bed(suffix)
        print("same-season (k=0) realized/projected PAR by age, %s bed:"
              % ("Steamer" if suffix else "Marcel"))
        for g, lo, hi, ratio, n in same_season_bias(birth, pools):
            print("  %s %2d-%-3d ratio %.2f  n=%d" % (g, lo, hi, ratio, n))
    elif "--lineup-sim" in sys.argv:
        lineup_sim_main("_steamer" if "--steamer" in sys.argv else "")
    elif "--league-sim" in sys.argv:
        trials = int(sys.argv[sys.argv.index("--trials") + 1]) if "--trials" in sys.argv else 200
        league_sim_main("_steamer" if "--steamer" in sys.argv else "", trials)
    else:
        main(sys.argv[1:])
