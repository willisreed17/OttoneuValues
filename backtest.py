"""Yardstick for the valuation model.

Scores a projection snapshot against what actually happened, so changes to the
valuation logic can be measured instead of argued about.

Both sides are computed from raw components with the documented FGPts weights.
FanGraphs' own FPTS column is deliberately ignored: it doesn't reproduce exactly
from the components they export (off by ~1%), and using one formula for the
projection and another for the actuals would bake that gap into every score.

Projection side: a FanGraphs leaderboard export (rest-of-season snapshot).
Actual side:     MLB statsapi, same date window, free and unblocked.

Usage:
  python backtest.py --start 2025-05-24 --end 2025-09-30 \
      --bat "~/Downloads/fangraphs-leaderboard-projections-Hitters.csv" \
      --pit "~/Downloads/fangraphs-leaderboard-projections-Pitchers.csv"
  python backtest.py --dollars      # score value.py's dollar values, not Steamer
  python backtest.py --measure "out/backtest_20*.csv"   # -> value.RELIABILITY
  python backtest.py --market data/average_values.csv   # cross-league sanity check
  python backtest.py --selftest
"""

import csv
import glob
import json
import os
import statistics
import sys
import urllib.request

import value

API = "https://statsapi.mlb.com/api/v1/stats"

# FGPts, per the Ottoneu scoring table. Verified against FanGraphs' own FPTS
# column by least squares over 473 projected hitters: the recovered weights come
# back as AB -1.008, H 5.664, 2B 3.012, 3B 5.716, HR 9.696, BB 3.031, HBP 3.098,
# SB 1.899, CS -2.466, and every other counting stat lands within +-0.5 of zero,
# i.e. there is no missing term.
BAT_W = {"AB": -1.0, "H": 5.6, "2B": 2.9, "3B": 5.7, "HR": 9.4,
         "BB": 3.0, "HBP": 3.0, "SB": 1.9, "CS": -2.8}
PIT_W = {"IP": 7.4, "SO": 2.0, "H": -2.6, "BB": -3.0, "HBP": -3.0,
         "HR": -12.3, "SV": 5.0, "HLD": 4.0}
SABR_PIT_W = dict(PIT_W, IP=5.0, HR=-13.0)
SABR_PIT_W.pop("H")

# statsapi field -> our stat name
BAT_API = {"atBats": "AB", "hits": "H", "doubles": "2B", "triples": "3B",
           "homeRuns": "HR", "baseOnBalls": "BB", "hitByPitch": "HBP",
           "stolenBases": "SB", "caughtStealing": "CS"}
PIT_API = {"strikeOuts": "SO", "hits": "H", "baseOnBalls": "BB",
           "hitByPitch": "HBP", "homeRuns": "HR", "saves": "SV", "holds": "HLD"}

MIN_PA, MIN_IP = 100, 20  # ex-ante filter, applied to the projection side


def num(s, default=0.0):
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def innings(s):
    """MLB writes thirds as .1/.2, so '45.2' is 45 2/3 innings, not 45.2."""
    whole, _, frac = str(s or 0).partition(".")
    return num(whole) + {"1": 1 / 3, "2": 2 / 3}.get(frac, 0.0)


def points(stats, weights):
    return sum(w * stats.get(k, 0.0) for k, w in weights.items())


def fetch_actuals(group, start, end):
    """-> {mlbam_id: {name, stats}} for one stat group over a date window."""
    out, offset = {}, 0
    api_map = BAT_API if group == "hitting" else PIT_API
    while True:
        url = ("%s?stats=byDateRange&group=%s&startDate=%s&endDate=%s"
               "&sportId=1&playerPool=All&limit=1000&offset=%d"
               % (API, group, start, end, offset))
        blob = json.load(urllib.request.urlopen(url, timeout=120))["stats"][0]
        splits = blob.get("splits", [])
        for sp in splits:
            st = sp["stat"]
            stats = {v: num(st.get(k, 0)) for k, v in api_map.items()}
            if group == "pitching":
                stats["IP"] = innings(st.get("inningsPitched"))
                stats["GS"] = num(st.get("gamesStarted", 0))
            else:
                stats["PA"] = num(st.get("plateAppearances", 0))
            out[str(sp["player"]["id"])] = {"name": sp["player"]["fullName"],
                                            "stats": stats}
        offset += len(splits)
        if not splits or offset >= blob.get("totalSplits", 0):
            return out


def load_projection(path, pitcher):
    """FanGraphs leaderboard export -> {mlbam_id: {name, fg_id, stats}}."""
    out = {}
    with open(os.path.expanduser(path), newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            stats = {k: num(r.get(k)) for k in (PIT_W if pitcher else BAT_W)}
            if pitcher:
                stats["IP"], stats["GS"] = num(r.get("IP")), num(r.get("GS"))
                stats["HLD"] = num(r.get("HLD"))
                if stats["IP"] < MIN_IP:
                    continue
            else:
                stats["PA"] = num(r.get("PA"))
                if stats["PA"] < MIN_PA:
                    continue
            mlbam = r.get("MLBAMID") or ""
            if mlbam:
                out[mlbam] = {"name": r.get("NameASCII") or r.get("Name"),
                              "fg_id": r.get("PlayerId"), "stats": stats}
    return out


def spearman(pairs):
    """Rank correlation. Ties get average ranks."""
    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        rk = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                rk[order[k]] = avg
            i = j + 1
        return rk

    if len(pairs) < 3:
        return float("nan")
    a, b = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a) ** 0.5
    vb = sum((y - mb) ** 2 for y in b) ** 0.5
    return cov / (va * vb) if va and vb else float("nan")


def score(rows, label):
    r = spearman([(x["proj"], x["actual"]) for x in rows])
    tot_p = sum(x["proj"] for x in rows)
    tot_a = sum(x["actual"] for x in rows)
    bias = (tot_p - tot_a) / tot_a * 100 if tot_a else 0.0
    mae = sum(abs(x["proj"] - x["actual"]) for x in rows) / len(rows)
    print("  %-10s n=%-4d spearman %.3f   MAE %6.1f pts   bias %+6.1f%%"
          % (label, len(rows), r, mae, bias))
    return r


def main(argv):
    def arg(flag, default):
        return argv[argv.index(flag) + 1] if flag in argv else default

    start, end = arg("--start", "2025-05-24"), arg("--end", "2025-09-30")
    dl = "~/Downloads/fangraphs-leaderboard-projections-%s.csv"
    bat_path = arg("--bat", dl % "Hitters")
    pit_path = arg("--pit", dl % "Pitchers")
    out_dir = arg("--out", "out")

    rows = []
    for group, path, pitcher in (("hitting", bat_path, False),
                                 ("pitching", pit_path, True)):
        weights = BAT_W if not pitcher else PIT_W
        proj = load_projection(path, pitcher)
        print("fetching %s actuals %s..%s" % (group, start, end))
        actual = fetch_actuals(group, start, end)
        hit = 0
        for mlbam, p in proj.items():
            a = actual.get(mlbam)
            if not a:
                continue
            hit += 1
            rows.append({
                "mlbam": mlbam, "fg_id": p["fg_id"], "name": p["name"],
                "group": "P" if pitcher else "H",
                "pos": ("SP" if a["stats"]["GS"] >= 5 else "RP") if pitcher else "",
                "proj": points(p["stats"], weights),
                "actual": points(a["stats"], weights),
                "proj_pt": p["stats"]["IP" if pitcher else "PA"],
                "actual_pt": a["stats"]["IP" if pitcher else "PA"],
            })
        print("  matched %d/%d projected %s on MLBAM id" % (hit, len(proj), group))

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "backtest.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in sorted(rows, key=lambda r: -r["actual"]):
            w.writerow({k: (round(v, 1) if isinstance(v, float) else v)
                        for k, v in r.items()})

    print("\nprojection quality (%s to %s), FGPts from components both sides:" % (start, end))
    score(rows, "all")
    score([r for r in rows if r["group"] == "H"], "hitters")
    score([r for r in rows if r["pos"] == "SP"], "SP")
    score([r for r in rows if r["pos"] == "RP"], "RP")
    print("\nwrote %s (%d players)" % (path, len(rows)))
    print("This scores Steamer, not the valuation model -- it is the floor to beat.\n"
          "Once value.py emits dollar values, score those against 'actual' here.")



# --- dollar-value calibration ------------------------------------------------
# The first non-circular measurement in this project. Everything else either is
# an arithmetic identity (top-480 values sum to the cap) or agrees with the
# market (pearson 0.813) -- and a tool whose whole purpose is to disagree with
# the market profitably cannot be validated by agreeing with it.
#
# The test: price a projection snapshot with value.py's layer 1, then check
# whether *realized* points above replacement per dollar of model value is flat
# across the price spectrum. If pricing is right, a $30 player returns roughly
# 3x a $10 player. Curvature is the finding (APPROACH.md trap 17):
#   droop at the top    -> stars overpriced, curve too steep
#   droop at the bottom -> marginal players overpriced, curve too flat

TIERS = [(30, 9e9, "$30+"), (15, 30, "$15-30"), (5, 15, "$5-15"),
         (2, 5, "$2-5"), (0, 2, "$1")]


def hitter_positions(path):
    """{fg_id: [pos]} from a Steamer-style export -- the leaderboard export has
    no minpos column, so positions have to come from somewhere else."""
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            pos = [p for p in r["minpos"].split("/") if p in value.POSITIONS]
            if pos:
                out[r["playerid"]] = pos
    return out


def mkpool(rows, key, pos_of):
    """value.py wants {id: {pos, pts, ...}}; build that from backtest rows."""
    pool = {}
    for r in rows:
        pos = pos_of(r)
        if not pos:
            continue
        pool[r["mlbam"]] = {"name": r["name"], "pos": pos, "pts": num(r[key]),
                            "mlb": "", "pt": 0, "two_way": False,
                            "ppt": num(r.get("proj_pt")), "apt": num(r.get("actual_pt"))}
    return pool


def refill(par, rep, proj_pt, actual_pt):
    """Realized PAR with vacated playing time refilled at replacement level.

    Raw PAR charges a player who loses his job for the whole replacement season
    he didn't play; floored PAR pretends every bust is cut instantly and free.
    What a 40-man roster actually does is mechanical and in between: the starts
    he doesn't make go to the bench at about replacement level, so the share of
    his projected time he didn't fill is credited back at `rep`. A healthy
    player who was simply bad is still charged in full -- benching him is the
    part of the option this does not credit.
    """
    short = max(0.0, 1 - actual_pt / proj_pt) if proj_pt else 0.0
    return par + rep * short


def load_bed(path, pit_path, steamer):
    """-> (rows, proj_pos, act_pos) for one backtest file."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    own_pos = any(r.get("proj_pos") for r in rows)
    hpos = {} if own_pos else hitter_positions(steamer)
    # Projected SP/RP split comes from projected GS; realized split from realized
    # GS (already in backtest.csv). Each side is classified on its own basis.
    proj_gs = {} if own_pos else {
        k: v["stats"]["GS"]
        for k, v in load_projection(pit_path, pitcher=True).items()}

    # marcel.py emits its own proj_pos/act_pos (statsapi has no FanGraphs id to
    # join positions on). A file without those columns falls back to the
    # FanGraphs path, so out/backtest.csv still scores exactly as before.
    def col(r, key):
        return [p for p in (r.get(key) or "").split("/") if p in value.POSITIONS]

    def proj_pos(r):
        if col(r, "proj_pos"):
            return col(r, "proj_pos")
        if r["group"] == "P":
            return ["SP"] if proj_gs.get(r["mlbam"], 0) >= 5 else ["RP"]
        return hpos.get(r["fg_id"])

    def act_pos(r):
        if col(r, "act_pos"):
            return col(r, "act_pos")
        return [r["pos"]] if r["group"] == "P" else hpos.get(r["fg_id"])

    return rows, proj_pos, act_pos


def pools(rows, depth, proj_pos, act_pos):
    """-> (projected pool, projected levels, realized levels). Each projected
    player carries unshrunk `par`, `realized_par`, and `refill_par`.

    Replacement is solved inside each pool, so both sides stay on the same
    basis. Mixing a full-season replacement level with ~60%-of-a-season totals
    would make every PAR meaningless.
    """
    proj = mkpool(rows, "proj", proj_pos)
    act = mkpool(rows, "actual", act_pos)
    both = set(proj) & set(act)
    proj = {k: v for k, v in proj.items() if k in both}
    act = {k: v for k, v in act.items() if k in both}
    plevels, _, _ = value.price(proj, depth)
    alevels, _, _ = value.price(act, depth)
    for pid, p in proj.items():
        a = act[pid]
        p["realized_par"] = a["par"]
        p["refill_par"] = refill(a["par"], alevels.get(a["vpos"], 0.0), p["ppt"], a["apt"])
    return proj, plevels, alevels


def fit_reliability(obs):
    """obs: [(role, projected PAR, refill PAR, projected replacement)] over
    priced players -> {role: (slope, cushion)}: slope relative to hitters (what
    value.RELIABILITY holds), cushion the intercept as a fraction of the
    replacement level (measured, not priced -- APPROACH trap 30)."""
    fits = {}
    for g in sorted({o[0] for o in obs}):
        q = [o for o in obs if o[0] == g]
        mx, my = sum(o[1] for o in q) / len(q), sum(o[2] for o in q) / len(q)
        b = (sum((o[1] - mx) * (o[2] - my) for o in q)
             / sum((o[1] - mx) ** 2 for o in q))
        fits[g] = (b, (my - b * mx) / (sum(o[3] for o in q) / len(q)))
    bh = fits["H"][0]
    return {g: (round(b / bh, 3), round(c / bh, 3)) for g, (b, c) in fits.items()}


def measure(argv):
    """Measure value.RELIABILITY from any set of backtest files.

    This is what makes reliability a property of the projection source rather
    than a constant: build a bed from whatever source is loaded, run this, and
    paste the result. Fitted over priced players (projected PAR > 0) only --
    selecting on the projection does not bias a regression on it.
    """
    files = sorted(f for a in argv if a.endswith(".csv") for f in glob.glob(a))
    cfg = value.load_settings(os.path.join(value.DATA, "league.csv"))
    depth = value.base_depth(cfg["teams"] or 12, cfg)
    obs = []
    for path in files:
        rows, pp, ap = load_bed(
            path, "~/Downloads/fangraphs-leaderboard-projections-Pitchers.csv",
            os.path.join("data", "steamer_bat.csv"))
        proj, plevels, _ = pools(rows, depth, pp, ap)
        obs += [(p["vpos"] if p["vpos"] in value.PITCHER_POS else "H", p["par"],
                 p["refill_par"], plevels[p["vpos"]], p["realized_par"])
                for p in proj.values() if p["par"] > 0]
    n = {g: sum(1 for o in obs if o[0] == g) for g in ("H", "SP", "RP")}
    # The factor is a RATIO of sums, not a regression slope. Dollars are
    # proportional to PAR, so what has to come out equal across roles is
    # realized-per-projected in aggregate -- exactly what the by-position table
    # measures. A slope with an intercept answers a marginal question the
    # pricing never asks, and put SP 10% cheap on that table (APPROACH trap 29).
    ratio = {g: sum(max(o[4], 0.0) for o in obs if o[0] == g)
             / sum(o[1] for o in obs if o[0] == g) for g in n}
    print("%d files, priced players: %s" % (len(files), n))
    print("RELIABILITY = %s" % {g: round(ratio[g] / ratio["H"], 3) for g in n if g != "H"})
    print("  floored realized / projected PAR, relative to hitters")
    print("regression (slope, cushion), for reference -- neither is priced: %s"
          % fit_reliability(obs))


def market(argv):
    """Cross-league sanity check: layer-1 values against Ottoneu's averageValues
    export -- every player's salary averaged across all leagues of one format.

    A sanity check, never a target (APPROACH §2). What it can do that league
    1297 can't is show whether a disagreement is a quirk of one league. Error
    that is MONOTONE IN PRICE is a structural flaw; error confined to one
    position is a candidate edge. Last 10 (the last ten transactions) is read
    beside the average: the average carries years-old auction prices plus +$2 a
    year of retention, Last 10 is nearer what the player costs today.
    """
    path = argv[argv.index("--market") + 1] if len(argv) > argv.index("--market") + 1 \
        else os.path.join(value.DATA, "average_values.csv")
    cfg = value.load_settings(os.path.join(value.DATA, "league.csv"))
    value.SCORING = cfg["scoring"]
    av = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            av[r["FG MajorLeagueID"] or r["FG MinorLeagueID"]] = {
                "name": r["Name"], "roster": num(r["Roster%"]),
                "avg": num(r["Avg Salary"].lstrip("$")), "last10": num(r["Last 10"].lstrip("$")),
                "pos": value.normalize([p for p in r["Position(s)"].split("/")
                                        if p in value.POSITIONS])}
    players = value.load_projections(os.path.join(value.DATA, "steamer_bat.csv"), pitcher=False)
    value.load_projections(os.path.join(value.DATA, "steamer_pit.csv"), pitcher=True, out=players)
    value.resolve_positions(players, av)      # Ottoneu eligibility, league-wide
    value.base_values(players, cfg["teams"] or 12, cfg)

    # Mid-season the market spends less than the cap -- cut penalties and loose
    # cash buy nobody -- so compare shape by rank as well as player by player.
    core = {k: a for k, a in av.items() if a["roster"] >= 50}
    both = [(players[k], a) for k, a in core.items() if k in players]
    print("market: %d players, per-league spend $%d of $%d cap; %d rostered in half "
          "the leagues, %d of them projected"
          % (len(av), sum(a["avg"] * a["roster"] / 100 for a in av.values()),
             12 * cfg["cap"], len(core), len(both)))
    ks = (1, 5, 12, 36, 100, 200, 300, 400)
    ranked = lambda vals: " ".join("%d:$%.0f" % (k, v) for k, v in
                                   zip(ks, [sorted(vals, reverse=True)[k - 1] for k in ks]))
    print("k-th dearest  model:  " + ranked([p["value"] for p in players.values()]))
    for key in ("avg", "last10"):
        print("k-th dearest  %-6s " % key + ranked([a[key] for a in core.values()]))
    for key in ("avg", "last10"):
        xs, ys = [p["value"] for p, _ in both], [a[key] for _, a in both]
        tiers = []
        for lo, hi, nm in TIERS:
            q = [p["value"] - a[key] for p, a in both if lo <= a[key] < hi]
            if q:
                tiers.append("%s %+.1f" % (nm, sum(q) / len(q)))
        print("vs %-6s pearson %.3f | model - market, by market tier: %s"
              % (key, statistics.correlation(xs, ys), "  ".join(tiers)))
    pos = {}
    for p, a in both:
        if a["avg"] >= 5:
            pos.setdefault(p["vpos"], []).append(p["value"] - a["avg"])
    print("by position, market avg >= $5, model - avg: " + "  ".join(
        "%s %+.1f (n%d)" % (k, sum(v) / len(v), len(v)) for k, v in sorted(pos.items())))


def dollars(argv):
    """Score value.py's dollar values against realized production."""
    def arg(flag, default):
        return argv[argv.index(flag) + 1] if flag in argv else default

    bt_path = arg("--backtest", os.path.join("out", "backtest.csv"))
    pit_path = arg("--pit", "~/Downloads/fangraphs-leaderboard-projections-Pitchers.csv")
    steamer = arg("--pos", os.path.join("data", "steamer_bat.csv"))
    # League settings come from the same file value.py reads, so the calibration
    # is scored against the league it is actually pricing for.
    cfg = value.load_settings(os.path.join(value.DATA, "league.csv"))
    n_teams = int(arg("--teams", cfg["teams"] or 12))
    depth = value.base_depth(n_teams, cfg)

    rows, pp, ap = load_bed(bt_path, pit_path, steamer)
    proj, plevels, alevels = pools(rows, depth, pp, ap)
    # Projection side only: realized production is not a forecast and needs no
    # reliability haircut.
    total_par = value.apply_reliability(proj)
    value.to_dollars(proj, total_par,
                     n_teams * (cfg["cap"] - cfg["roster_max"]))

    print("dollar-value calibration: %d players, %d teams, $%d cap, depth %s"
          % (len(proj), n_teams, cfg["cap"],
             " ".join("%s%d" % (k, depth[k]) for k in value.POSITIONS)))
    print("replacement (proj / realized): "
          + "  ".join("%s %d/%d" % (k, plevels[k], alevels[k]) for k in value.POSITIONS))

    def report(label, buckets):
        # Three bases, because a roster spot is an option, not an obligation.
        # rPAR (raw) charges a cheap player who loses his job ~400 negative
        # points no owner eats; rPAR+ (floored at 0) pretends every bust is cut
        # instantly and free. Both are bounds, never evidence alone. rPAR~
        # (refill) is the mechanism in between: his vacated time is refilled
        # at replacement, a healthy bad player is still charged in full.
        print("\n%s" % label)
        print("  %-10s %5s %9s %10s %10s %10s %10s   %s"
              % ("tier", "n", "mean $", "mean rPAR", "med rPAR", "mean rPAR+",
                 "mean rPAR~", "per marginal $: raw / + / ~"))
        for name, ps in buckets:
            if not ps:
                continue
            n = len(ps)
            mv = sum(p["value"] for p in ps) / n
            mp = sum(p["realized_par"] for p in ps) / n
            med = sorted(p["realized_par"] for p in ps)[n // 2]
            pos = sum(max(p["realized_par"], 0.0) for p in ps) / n
            fill = sum(p["refill_par"] for p in ps) / n
            marg = sum(p["value"] - 1 for p in ps) / n
            print("  %-10s %5d %9.1f %10.1f %10.1f %10.1f %10.1f   %s"
                  % (name, n, mv, mp, med, pos, fill,
                     "%6.1f %6.1f %6.1f" % (mp / marg, pos / marg, fill / marg)
                     if marg > 0.5 else "     -"))

    # By position, which is the only view that can see a depth error. Depth sets
    # replacement, replacement sets PAR, and PAR sets dollars -- so if SP depth
    # is too shallow, every SP is underpriced and returns MORE realized PAR per
    # dollar than a hitter. The price-tier table cannot see that: it averages
    # across positions, and a position priced 30% light still lands in the
    # tier its dollars put it in. Flat down this column is what says the depth
    # constants are right.
    ps = list(proj.values())
    report("by assigned position:",
           [(pos, [p for p in ps if p["vpos"] == pos and p["value"] > 1])
            for pos in value.POSITIONS])

    report("by price tier:", [(nm, [p for p in ps if lo <= p["value"] < hi])
                              for lo, hi, nm in TIERS])
    # Deciles over the players who carry real value; the $1 tail is one big bin
    # and would swamp the low deciles otherwise.
    paid = sorted((p for p in ps if p["value"] > 1), key=lambda p: -p["value"])
    k = len(paid)
    report("by decile of model value (%d players above $1):" % k,
           [("d%d" % (i + 1), paid[i * k // 10:(i + 1) * k // 10]) for i in range(10)])

    flat = [p for p in paid if p["value"] >= 5]
    if flat:
        r = spearman([(p["value"], max(p["realized_par"], 0.0) / max(p["value"] - 1, 1))
                      for p in flat])
        print("\nspearman(model $, realized PAR per marginal $) over %d players >= $5: "
              "%+.3f" % (len(flat), r))
        print("  ~0 means pricing is proportional; positive means the top is "
              "underpriced, negative means it is overpriced.")


def selftest():
    assert abs(innings("45.2") - (45 + 2 / 3)) < 1e-9
    assert innings("45.1") == 45 + 1 / 3 and innings("45") == 45
    # Judge's 2025 RoS projection, documented weights
    j = {"AB": 383.43, "H": 118.831, "2B": 19.1963, "3B": 0.77659, "HR": 40.4478,
         "BB": 76.4512, "HBP": 4.24374, "SB": 5.26571, "CS": 1.62591}
    assert abs(points(j, BAT_W) - 969.9) < 0.5, points(j, BAT_W)
    # a HR is worth its own weight plus the hit, minus the at-bat
    assert abs(points({"AB": 1, "H": 1, "HR": 1}, BAT_W) - (9.4 + 5.6 - 1.0)) < 1e-9
    assert abs(spearman([(1, 1), (2, 2), (3, 3)]) - 1.0) < 1e-9
    assert abs(spearman([(1, 3), (2, 2), (3, 1)]) + 1.0) < 1e-9
    assert abs(spearman([(1, 1), (2, 2), (3, 3), (4, 3)]) - 0.9486) < 1e-3  # ties

    # --dollars plumbing: rows without a position are dropped, not defaulted to
    # 1B -- a fake first baseman moves the 1B replacement level and mispricies
    # everyone eligible there.
    rows = [{"mlbam": "1", "fg_id": "a", "name": "n", "group": "H",
             "pos": "", "proj": "500", "actual": "400"},
            {"mlbam": "2", "fg_id": "z", "name": "m", "group": "H",
             "pos": "", "proj": "300", "actual": "600"}]
    pool = mkpool(rows, "proj", lambda r: {"a": ["OF"]}.get(r["fg_id"]))
    assert list(pool) == ["1"] and pool["1"]["pts"] == 500.0, pool

    # The calibration identity: if projections came true exactly, realized PAR
    # per marginal dollar MUST be the same for every player. Anything else means
    # the reporting is lying about the pricing rather than measuring it.
    pool = {str(i): {"name": "x", "pos": ["OF"], "pts": 900.0 - 30 * i,
                     "mlb": "", "pt": 0, "two_way": False} for i in range(20)}
    _, total_par, _ = value.price(pool, {"OF": 10})
    value.to_dollars(pool, total_par, 2000)
    per = [p["par"] / (p["value"] - 1) for p in pool.values() if p["value"] > 5]
    assert max(per) - min(per) < 0.05 * max(per), per

    # Refill: a no-show is a hole the bench fills, so he nets zero, not -rep;
    # a full-timer is charged in full; extra time is never credited twice.
    assert refill(-500, 500, 600, 0) == 0
    assert refill(-100, 500, 600, 600) == -100
    assert refill(50, 500, 600, 900) == 50
    assert refill(-200, 500, 600, 300) == 50

    # The measurement recovers a known line: slope relative to hitters, and
    # the intercept as a fraction of replacement.
    obs = [("H", x, x + 0.05 * 500, 500) for x in (100, 200, 300)]
    obs += [("RP", x, 0.5 * x + 0.1 * 300, 300) for x in (50, 100, 150)]
    fit = fit_reliability(obs)
    assert fit == {"H": (1.0, 0.05), "RP": (0.5, 0.1)}, fit
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--dollars" in sys.argv:
        dollars(sys.argv[1:])
    elif "--measure" in sys.argv:
        measure(sys.argv[1:])
    elif "--market" in sys.argv:
        market(sys.argv[1:])
    else:
        main(sys.argv[1:])
