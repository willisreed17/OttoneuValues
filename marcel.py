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
  python marcel.py --aging              # -> data/aging.csv, data/birthdates.csv
  python marcel.py --npv                # out-of-sample keeper_npv backtest
  python marcel.py --selftest
"""

import csv
import datetime
import json
import os
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


def fetch_stats(season, group):
    def go():
        out, off = [], 0
        while True:
            url = ("%s/stats?stats=season&group=%s&season=%d&sportId=1"
                   "&playerPool=All&limit=1000&offset=%d" % (API, group, season, off))
            blob = json.load(urllib.request.urlopen(url, timeout=180))["stats"][0]
            sp = blob.get("splits", [])
            out += sp
            off += len(sp)
            if not sp or off >= blob.get("totalSplits", 0):
                return out
    return cached("%d_%s" % (season, group), go)


def season_stats(season, group):
    """-> {mlbam: stats} in our stat names. statsapi returns season totals
    already aggregated across trades, one row per player -- verified, so there
    is no duplicate-team row to merge."""
    api_map = bt.BAT_API if group == "hitting" else bt.PIT_API
    out = {}
    for sp in fetch_stats(season, group):
        st = sp["stat"]
        s = {v: bt.num(st.get(k, 0)) for k, v in api_map.items()}
        if group == "pitching":
            s["IP"] = bt.innings(st.get("inningsPitched"))
            s["GS"] = bt.num(st.get("gamesStarted", 0))
        else:
            s["PA"] = bt.num(st.get("plateAppearances", 0))
        out[str(sp["player"]["id"])] = s
    return out


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


def aging_bed():
    """-> (birth, {season: projected pool}, {season: $ per PAR}) over the bed.
    Each pool is reliability-shrunk and priced exactly as value.py prices a live
    season, so a player's `par` is what keeper_npv calls base_par."""
    cfg = value.load_settings(os.path.join(value.DATA, "league.csv"))
    n_teams = cfg["teams"] or 12
    depth = value.base_depth(n_teams, cfg)
    seasons = [y for y in range(FIRST_TARGET, LAST_TARGET + 1) if y not in SKIP]
    birth = {}
    for y in seasons:
        birth.update({k: v[1] for k, v in season_people(y).items()})
    pools, rates = {}, {}
    for y in seasons:
        rows, pp, ap = bt.load_bed(os.path.join(OUT, "backtest_%d.csv" % y), "", "")
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

    years = arg("--years", "")
    targets = ([int(y) for y in years.split(",")] if years else
               [y for y in range(FIRST_TARGET, LAST_TARGET + 1) if y not in SKIP])
    os.makedirs(OUT, exist_ok=True)
    cache = {}
    for t in targets:
        priors = prior_seasons(t)
        print("%d  <- %s" % (t, ", ".join(str(y) for y in priors)))
        rows = build(t, cache)
        path = os.path.join(OUT, "backtest_%d.csv" % t)
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
          "out/backtest_YYYY.csv")


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
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--aging" in sys.argv:
        aging_main()
    elif "--npv" in sys.argv:
        npv_backtest()
    else:
        main(sys.argv[1:])
