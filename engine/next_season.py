"""Next-season keeper values, before next year's Steamer is published.

Data prep plus a wrapper around value.py -- the engine itself is not changed.
The projection is ZiPS for the target season when data/Historic Zips Projections/
has it, otherwise a forward Marcel built from statsapi (the last three seasons).
Either way it is priced with that source's OWN constants, measured at runtime on
its historic bed: RELIABILITY per role, the aging table, and for Marcel only a
per-age factor (Marcel under-projects the young; ZiPS's bias is flat by age).
Steamer's constants describe Steamer (CLAUDE.md: re-measure if the source changes).

  py -3.13 next_season.py              # -> out/next/players.csv, out/next/teams.csv
  py -3.13 next_season.py --marcel     # force the Marcel fallback
  py -3.13 next_season.py --refresh    # re-pull the latest season from statsapi first
  py -3.13 next_season.py --selftest

Needs the bed for the source: out/backtest_YYYY_zips.csv (zips_bed.py) or
out/backtest_YYYY.csv (marcel.py). Writes only under out/next/; never touches data/.
"""
import csv
import datetime
import os
import shutil
import sys

import backtest as bt
import convert_fg_export as cfe
import marcel
import value

OUT = os.path.join("out", "next")
DATA = os.path.join(OUT, "data")
HIST_ZIPS = os.path.join(value.DATA, "Historic Zips Projections")
COPY = ("league.csv", "rosterexport.csv", "teams_cap.csv", "prospects.csv")
ZIPS = ("2027 zips hitter projection.csv", "2027 zips pitcher projection.csv")


def id_map():
    """-> {mlbam: (fg playerid, team)} from every projection file that carries both."""
    ids = {}
    for name in ZIPS:
        for r in cfe.read(os.path.join(HIST_ZIPS, name)):
            if r.get("MLBAMID") and r.get("PlayerId"):
                ids[r["MLBAMID"]] = (r["PlayerId"], r.get("Team", ""))
    for name in ("steamer_bat.csv", "steamer_pit.csv"):
        for r in cfe.read(os.path.join(value.DATA, name)):
            if r.get("xMLBAMID"):
                ids.setdefault(r["xMLBAMID"], (r["playerid"], r.get("Team", "")))
    return ids


def roster_facts(priors):
    """-> (games {mlbam: {pos: n}} over the two most recent seasons, people
    {mlbam: (name, birth, primary)}) from statsapi -- eligibility and role."""
    people = {}
    for y in reversed(priors):          # most recent season wins
        people.update(marcel.season_people(y))
    games = {}
    for y in priors[:2]:                # eligibility: the two most recent seasons
        for pid, g in marcel.season_positions(y).items():
            for pos, n in g.items():
                games.setdefault(pid, {})[pos] = games.get(pid, {}).get(pos, 0) + n
    return games, people


def project(target):
    """-> ({mlbam: stats} hitting, pitching, positions, people), Marcel for `target`
    with no target-season actuals needed (marcel.build is the backtest version)."""
    priors = marcel.prior_seasons(target)
    data = {y: {g: marcel.season_stats(y, g) for g in ("hitting", "pitching")}
            for y in priors}
    games, people = roster_facts(priors)
    out = {}
    for group, keys, pt_key, reg, pt_base in (
            ("hitting", [k for k in bt.BAT_W if k != "PA"], "PA", marcel.REG_PA,
             marcel.PT_BASE_PA),
            ("pitching", [k for k in bt.PIT_W if k != "IP"] + ["GS"], "IP", marcel.REG_IP,
             marcel.PT_BASE_IP_SP)):
        hist = [(data[y][group], w) for y, w in zip(priors, marcel.WEIGHTS)]
        lg = marcel.league_rates(hist, keys, pt_key)
        proj = out[group] = {}
        for pid in set().union(*(s for s, _ in hist)):
            if pid not in people:
                continue
            ph = [(data[y][group].get(pid, {}), w) for y, w in zip(priors, marcel.WEIGHTS)]
            base = pt_base
            if group == "pitching":     # same role floor as marcel.build
                gs = [(st.get("GS", 0.0), w) for st, w in ph if st.get("IP", 0.0) > 0]
                mean_gs = sum(g * w for g, w in gs) / sum(w for _, w in gs) if gs else 0.0
                base = marcel.PT_BASE_IP_SP if mean_gs >= 5 else marcel.PT_BASE_IP_RP
            proj[pid] = marcel.project(ph, lg, reg, keys, pt_key, base,
                                       marcel.age_on(people[pid][1], target))
    return out["hitting"], out["pitching"], games, people


def to_rows(bat, pit, games, people, ids, minpos):
    """Marcel -> engine-format rows. Players with no FanGraphs id are dropped and
    returned by name, never guessed at: the roster export is keyed on that id."""
    brows, prows, unmapped = [], [], []
    for pid, s in bat.items():
        pos = marcel.hitting_pos(people[pid][2], games.get(pid, {}))
        if pos is None:
            continue
        if pid not in ids:
            unmapped.append((people[pid][0], s["PA"]))
            continue
        fg, team = ids[pid]
        pts = round(bt.points(s, bt.BAT_W), 1)
        brows.append([fg, people[pid][0], team, minpos.get(fg) or pos, "", "",
                      round(s["PA"], 1), pts, pts, pid])
    for pid, s in pit.items():
        # Marcel's reliever floor (22 IP) turns every mop-up inning by a position
        # player into a projected RP line, and the engine then prices him as one.
        if people[pid][2] not in ("P", "TWP"):
            continue
        if pid not in ids:
            unmapped.append((people[pid][0], s["IP"]))
            continue
        fg, team = ids[pid]
        prows.append([fg, people[pid][0], team, "", round(s["GS"], 1), round(s["IP"], 1),
                      round(s["SV"], 1), round(s["HLD"], 1),
                      round(bt.points(s, bt.PIT_W), 1),
                      round(bt.points(s, bt.SABR_PIT_W), 1), pid])
    return brows, prows, unmapped


def zips_files(target):
    return [os.path.join(HIST_ZIPS, "%d zips %s projection.csv" % (target, k))
            for k in ("hitter", "pitcher")]


FRESH = 0.5   # real preseason updates score 0.74-0.79 (2025, 2026); a stale file ~0


def zips_freshness(target):
    """-> min over pitchers/hitters of Spearman(last season's surprise vs the
    season before's ZiPS, per IP/PA; the target file's revision from that ZiPS).

    FanGraphs also publishes multi-year ZiPS: a "2027" line made before 2026 was
    played. It looks like a projection and knows nothing about 2026 -- the
    2027 file saved 2026-09-19 scored -0.02 for pitchers. A file that has seen
    last season revises toward what happened."""
    last = target - 1
    out = []
    for k, g, pt, floor in (("pitcher", "pitching", "IP", 60), ("hitter", "hitting", "PA", 250)):
        w = bt.PIT_W if k == "pitcher" else bt.BAT_W
        rate = {}
        for y in (last, target):
            path = os.path.join(HIST_ZIPS, "%d zips %s projection.csv" % (y, k))
            rate[y] = {r["MLBAMID"]: bt.points({x: bt.num(r.get(x)) for x in w}, w)
                       / max(bt.num(r.get(pt)), 1.0) for r in cfe.read(path) if r.get("MLBAMID")}
        pairs = [(bt.points(s, w) / s[pt] - rate[last][m], rate[target][m] - rate[last][m])
                 for m, s in marcel.season_stats(last, g).items()
                 if m in rate[last] and m in rate[target] and s.get(pt, 0) >= floor]
        out.append(bt.spearman(pairs) if len(pairs) > 50 else 0.0)
    return min(out)


def zips_rows(bat, pit, games, people, minpos):
    """A FanGraphs ZiPS export -> engine-format rows (convert_fg_export), with two
    fixes from statsapi: a hitter Steamer has no minpos for (mostly rookies) gets
    his real games-based eligibility instead of Util, and a batting line for a
    known pitcher or a pitching line for a known position player is dropped."""
    brows, _ = cfe.convert_bat(bat, minpos)
    out_b = []
    for r in brows:
        who = people.get(r[-1])
        if who and who[2] == "P":
            continue
        if r[0] not in minpos and who:
            r[3] = marcel.hitting_pos(who[2], games.get(r[-1], {})) or "DH"
        out_b.append(r)
    out_p = [r for r in cfe.convert_pit(pit)
             if not people.get(r[-1]) or people[r[-1]][2] in ("P", "TWP")]
    return out_b, out_p


def group(p):
    return "P" if p["vpos"] in value.PITCHER_POS else "H"


def role(p):
    return p["vpos"] if p["vpos"] in value.PITCHER_POS or p["vpos"] == "C" else "H"


def age_bin(age):
    return next((i for i, (lo, hi) in enumerate(marcel.AGING_BINS) if lo <= age <= hi), None)


def bed(suffix=""):
    """-> ({season: projected pool with unshrunk par and realized_par}, {mlbam: birth})
    over the Marcel bed, priced the way backtest.py --measure prices it."""
    cfg = value.load_settings(os.path.join(value.DATA, "league.csv"))
    depth = value.base_depth(cfg["teams"] or 12, cfg)
    pools, birth = {}, {}
    for y in range(marcel.FIRST_TARGET, marcel.LAST_TARGET + 1):
        path = os.path.join(marcel.OUT, "backtest_%d%s.csv" % (y, suffix))
        if y in marcel.SKIP or not os.path.exists(path):
            continue
        rows, pp, ap = bt.load_bed(path, "", "")
        pools[y] = bt.pools(rows, depth, pp, ap)[0]
        birth.update({k: v[1] for k, v in marcel.season_people(y).items()})
    return pools, birth


def priced(pools, birth):
    """-> [(group, age bin or None, role, projected PAR, floored realized PAR)]."""
    out = []
    for y, pool in pools.items():
        for pid, p in pool.items():
            if p["par"] > 0:
                age = marcel.age_on(birth.get(pid, ""), y)
                out.append((group(p), None if age is None else age_bin(age), role(p),
                            p["par"], max(p["realized_par"], 0.0)))
    return out


def measure(obs, by_age=True):
    """-> (age factor {(group, bin): x}, reliability {role: x}).

    Marcel's error is steeply monotone in age (APPROACH trap 32; Steamer's is
    flat), so a role-level RELIABILITY can't carry it. Step 1: ratio of sums,
    floored realized over projected PAR, per group and age bin -- the same basis
    as `marcel.py --age-check`. Step 2: RELIABILITY per role, on the age-corrected
    PAR, relative to hitters -- the same definition as `backtest.py --measure`."""
    s, t = {}, {}
    for g, b, _, par, real in obs:
        for key in ((g, b), (g, None)):          # (g, None): age unknown
            s[key] = s.get(key, 0.0) + par
            t[key] = t.get(key, 0.0) + real
    age = {k: t[k] / s[k] for k in s}
    if not by_age:                               # a source whose bias is flat by age
        age = dict.fromkeys(age, 1.0)
    s, t = {}, {}
    for g, b, r, par, real in obs:
        s[r] = s.get(r, 0.0) + par * age[(g, b)]
        t[r] = t.get(r, 0.0) + real
    rel = {r: (t[r] / s[r]) / (t["H"] / s["H"]) for r in s if r != "H"}
    return age, rel


def factor(age, rel, g, b, r):
    return age.get((g, b), age[(g, None)]) * rel.get(r, 1.0)


def holdout(pools, birth):
    """Leave one season out: fit on the rest, then realized/corrected PAR by age on
    the held-out season, pooled over folds. Flat across ages = the correction
    generalizes; the raw column is the bias it removes."""
    raw, fix = {}, {}
    for y in pools:
        age, rel = measure(priced({k: v for k, v in pools.items() if k != y}, birth))
        for g, b, r, par, real in priced({y: pools[y]}, birth):
            for acc, p in ((raw, par), (fix, par * factor(age, rel, g, b, r))):
                a = acc.setdefault((g, b), [0.0, 0.0])
                a[0] += p
                a[1] += real
    def rel_to_group(acc, g, b):                 # 1.0 = no bias against the group
        tot = [sum(v[i] for k, v in acc.items() if k[0] == g) for i in (0, 1)]
        return (acc[(g, b)][1] / acc[(g, b)][0]) / (tot[1] / tot[0])
    return [(g, b, rel_to_group(raw, g, b), rel_to_group(fix, g, b))
            for g, b in sorted(k for k in raw if k[1] is not None)]


def next_npv(p, r, age, arb, rate, aging, discount=1.0):
    """value.keeper_npv for a NEXT-season projection. keeper_npv treats the loaded
    projection as this season and ages it from k=1; here the projection already
    IS next season, so next season is kept at ratio 1 and ageing starts the
    season after, on a salary that already carries next year's raise and arb."""
    salary = value.keeper_salary(r, arb)
    later = dict(r, salary=salary, has_mlb=True)
    v = 0.0
    for s in reversed(value.keeper_surpluses(p, later, age, 0, rate, aging)):
        v = max(0.0, s + discount * v)
    return discount * max(0.0, p["base_value"] - salary + discount * v)


def main(argv):
    # Next season. By January Steamer for it is usually out and belongs in data/;
    # --season covers the odd case.
    target = int(argv[argv.index("--season") + 1]) if "--season" in argv         else datetime.date.today().year + 1
    priors = marcel.prior_seasons(target)
    if "--refresh" in argv:             # the latest season may still be in progress
        for g in ("hitting", "pitching", "fielding", "people"):
            path = os.path.join(marcel.CACHE, "%d_%s.json" % (priors[0], g))
            if os.path.exists(path):
                os.remove(path)
    os.makedirs(DATA, exist_ok=True)
    minpos = {r["playerid"]: r["minpos"]
              for r in cfe.read(os.path.join(value.DATA, "steamer_bat.csv")) if r.get("minpos")}
    # ZiPS when it exists for the target season: it ranks outcomes better than Marcel
    # and its bias is flat by age (NEXT_STEPS Task 16). Marcel is the fallback.
    use_zips = "--marcel" not in argv and all(map(os.path.exists, zips_files(target)))
    if use_zips:
        fresh = zips_freshness(target)
        use_zips = fresh >= FRESH
        print("ZiPS %d freshness %.2f (needs %.2f)%s" % (
            target, fresh, FRESH, "" if use_zips else
            " -- made before %d was played; using Marcel until a post-season ZiPS "
            "is saved" % (target - 1)))
    source = ("zips" if use_zips else "marcel") + "-%d" % target
    if use_zips:
        print("ZiPS %d (%s)" % (target, HIST_ZIPS))
        games, people = roster_facts(priors)
        brows, prows = zips_rows(*(cfe.read(f) for f in zips_files(target)),
                                 games, people, minpos)
        print("projected %d hitters, %d pitchers" % (len(brows), len(prows)))
    else:
        print("Marcel %d <- %s" % (target, ", ".join(map(str, priors))))
        bat, pit, games, people = project(target)
        brows, prows, unmapped = to_rows(bat, pit, games, people, id_map(), minpos)
        big = sorted((u for u in unmapped if u[1] >= 100), key=lambda u: -u[1])
        print("projected %d hitters, %d pitchers; %d with no FanGraphs id dropped "
              "(%d with 100+ PA/IP%s)" % (len(brows), len(prows), len(unmapped), len(big),
                                          ": " + ", ".join(u[0] for u in big[:8]) if big else ""))
    for name, head, rows in (("steamer_bat.csv", cfe.BAT_HEAD, brows),
                             ("steamer_pit.csv", cfe.PIT_HEAD, prows)):
        with open(os.path.join(DATA, name), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(head)
            w.writerows(rows)

    for name in COPY:
        src = os.path.join(value.DATA, name)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(DATA, name))
    mlbam = {r[0]: r[-1] for r in brows + prows}
    known = {m: people[m][1] for m in mlbam.values() if m in people}
    known.update(marcel.fetch_birthdates([m for m in mlbam.values() if m not in known]))
    births = {pid: known.get(m, "") for pid, m in mlbam.items()}
    with open(os.path.join(DATA, "birthdates.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["playerid", "birthDate"])
        w.writerows(sorted(births.items()))

    # The source's own constants, measured on its own historic bed.
    suffix = "_zips" if use_zips else ""
    with open(os.path.join(DATA, "aging.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group", "k", "age_lo", "age_hi", "ratio", "n"])
        w.writerows(marcel.measure_aging(suffix))
    pools, bed_birth = bed(suffix)
    age, rel = measure(priced(pools, bed_birth), by_age=not use_zips)
    print("%s bed, %d seasons: RELIABILITY%s %s"
          % ("ZiPS" if use_zips else "Marcel", len(pools),
             "" if use_zips else " after age correction",
             {r: round(x, 3) for r, x in sorted(rel.items())}))
    if not use_zips:
        print("  age factor (x projected PAR)  " + "  ".join(
            "%s %d-%d %.2f" % (g, lo, hi, age[(g, b)]) for g in "HP"
            for b, (lo, hi) in enumerate(marcel.AGING_BINS) if (g, b) in age))
        print("  held-out bias by age, raw -> corrected (1.00 = none)  " + "  ".join(
            "%s %d-%d %.2f->%.2f" % (g, marcel.AGING_BINS[b][0], marcel.AGING_BINS[b][1], x, y)
            for g, b, x, y in holdout(pools, bed_birth)))

    def corrected(players, reliability=None):
        """Replaces value.apply_reliability for this run: the source's own
        reliability (and, for Marcel, age factor), on the projection side only."""
        for pid, p in players.items():
            a = value.age_on(births.get(pid, ""), target)
            p["par"] *= factor(age, rel, group(p), None if a is None else age_bin(a), role(p))
        return sum(p["par"] for p in players.values() if p["par"] > 0)

    # The engine, unchanged, pointed at this data and this projection's constants.
    value.DATA = DATA
    value.projection_season = lambda today=None: target
    value.apply_reliability = corrected
    value.keeper_npv = next_npv
    value.main(["--out", OUT])

    path = os.path.join(OUT, "players.csv")
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(rows[0] + ["proj_source"])
        w.writerows(r + [source] for r in rows[1:])
    rostered, _ = value.load_rosters(os.path.join(DATA, "rosterexport.csv"))
    have = {r[0] for r in rows[1:]}
    missing = [r["name"] for pid, r in rostered.items() if pid not in have]
    print("rostered players with no %d projection (unpriced): %d%s"
          % (target, len(missing), " e.g. " + ", ".join(missing[:8]) if missing else ""))


def selftest():
    aging0 = {("H", 1): [(0, 99, 0.0)], ("P", 1): [(0, 99, 0.0)]}
    aging1 = {("H", 1): [(0, 99, 1.0)], ("P", 1): [(0, 99, 1.0)]}
    p = {"base_value": 20, "base_par": 30.0, "pts": 500.0, "pts_p": 500.0}
    r = {"salary": 10, "has_mlb": True}
    ks = value.keeper_salary(r, 2)                       # 10 + raise + 2 arb
    # no future: next season only, at ratio 1, one discount step away
    assert next_npv(p, r, 25, 2, 1.0, aging0, 0.9) == 0.9 * (20 - ks)
    # one future season at ratio 1: 1 + 30*1*1 - (ks + raise), discounted twice
    fut = 1 + 30 - (ks + value.RETENTION_MLB)
    assert abs(next_npv(p, r, 25, 2, 1.0, aging1, 0.9)
               - 0.9 * (20 - ks + 0.9 * max(0, fut))) < 1e-9
    # never negative: an overpaid player is cut
    assert next_npv(dict(p, base_value=1), dict(r, salary=40), 25, 0, 1.0, aging0) == 0
    # young hitters realize 2x their projection, old 1x; SP on par with hitters
    age, rel = measure([("H", 0, "H", 10.0, 20.0), ("H", 3, "H", 10.0, 10.0),
                        ("P", 0, "SP", 10.0, 5.0)])
    assert age[("H", 0)] == 2.0 and age[("H", 3)] == 1.0 and age[("H", None)] == 1.5
    assert rel == {"SP": 1.0}                            # 5/(10*0.5) vs 30/(20+10)
    assert factor(age, rel, "H", None, "H") == 1.5       # unknown age: group ratio
    age, rel = measure([("H", 0, "H", 10.0, 20.0), ("H", 3, "H", 10.0, 10.0),
                        ("P", 0, "SP", 10.0, 5.0)], by_age=False)
    assert set(age.values()) == {1.0} and rel == {"SP": 0.5 / 1.5}  # plain RELIABILITY
    zb, zp = zips_rows(
        [{"PlayerId": "1", "MLBAMID": "9", "Name": "Rook", "PA": "400"},
         {"PlayerId": "2", "MLBAMID": "8", "Name": "Arm", "PA": "120"},
         {"PlayerId": "3", "MLBAMID": "7", "Name": "Vet", "PA": "500"}],
        [{"PlayerId": "4", "MLBAMID": "6", "Name": "SP", "GS": "30", "IP": "180"},
         {"PlayerId": "5", "MLBAMID": "9", "Name": "Rook", "IP": "25"}],
        {"9": {"SS": 40}}, {"9": ("Rook", "", "SS"), "8": ("Arm", "", "P")}, {"3": "1B"})
    assert [(r[0], r[3]) for r in zb] == [("1", "SS"), ("3", "1B")]  # rookie gets games-based pos
    assert [r[0] for r in zp] == ["4"]                   # position player's mop-up line dropped
    b, pr, un = to_rows({"1": {"PA": 500.0, "AB": 450.0, "H": 120.0},
                         "2": {"PA": 300.0}, "3": {"PA": 400.0}},
                        {"4": {"IP": 150.0, "GS": 25.0, "SV": 0.0, "HLD": 0.0}, "5": {"IP": 60.0},
                         "1": {"IP": 22.0, "GS": 0.0, "SV": 0.0, "HLD": 0.0}},
                        {"1": {"OF": 100}},
                        {"1": ("A", "", "LF"), "2": ("B", "", "C"), "3": ("P", "", "P"),
                         "4": ("S", "", "P"), "5": ("U", "", "P")},
                        {"1": ("fg1", "X"), "4": ("fg4", "Y")}, {})
    assert [x[0] for x in b] == ["fg1"] and b[0][3] == "OF" and b[0][-1] == "1"
    assert [x[0] for x in pr] == ["fg4"] and pr[0][4] == 25.0
    assert sorted(n for n, _ in un) == ["B", "U"]        # pitcher "P" batting line skipped
    print("selftest ok")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    selftest() if "--selftest" in sys.argv else main(sys.argv[1:])
