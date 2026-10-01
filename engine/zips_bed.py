"""Historic-ZiPS test bed: out/backtest_YYYY_zips.csv, same shape as the Steamer bed.

Data prep only. Reuses marcel.build_steamer with its file reader pointed at
data/Historic Zips Projections/ ("YYYY zips {hitter,pitcher} projection.csv", the same
FanGraphs columns as the historic Steamer exports), so positions, actuals and pricing
are identical and only the projection source differs.

  py -3.13 zips_bed.py            # build the bed, then print RELIABILITY and k=0 age bias
  py -3.13 zips_bed.py --report   # skip the build, just measure
"""
import csv
import os
import sys

import backtest as bt
import marcel
import value

HIST_ZIPS = os.path.join(value.DATA, "Historic Zips Projections")
SUFFIX = "_zips"


def zips_hist(year, pitcher):
    """marcel.steamer_hist, for a ZiPS export."""
    name = "%d zips %s projection.csv" % (year, "pitcher" if pitcher else "hitter")
    keys = ["GS", "IP", "SO", "H", "BB", "HBP", "HR", "SV", "HLD"] if pitcher \
        else ["PA", "AB", "H", "2B", "3B", "HR", "BB", "HBP", "SB", "CS"]
    with open(os.path.join(HIST_ZIPS, name), newline="", encoding="utf-8-sig") as f:
        return {r["MLBAMID"]: {k: bt.num(r.get(k)) for k in keys}
                for r in csv.DictReader(f) if r.get("MLBAMID")}


def build():
    marcel.steamer_hist = zips_hist
    cache = {}
    for t in range(marcel.FIRST_TARGET, marcel.LAST_TARGET + 1):
        if t in marcel.SKIP:
            continue
        rows = marcel.build_steamer(t, cache)
        path = os.path.join(marcel.OUT, "backtest_%d%s.csv" % (t, SUFFIX))
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            for r in sorted(rows, key=lambda r: -r["actual"]):
                w.writerow({k: (round(v, 1) if isinstance(v, float) else v) for k, v in r.items()})
        print("  wrote %s (%d players)" % (path, len(rows)))


def report():
    bt.measure(["out/backtest_20*%s.csv" % SUFFIX])
    for suffix, label in (("_steamer", "Steamer"), (SUFFIX, "ZiPS"), ("", "Marcel")):
        birth, pools, _ = marcel.aging_bed(suffix)
        print("k=0 realized/projected PAR by age, %s bed (%d seasons):" % (label, len(pools)))
        print("  " + "  ".join("%s %d-%d %.2f (n %d)" % r for r in marcel.same_season_bias(birth, pools)))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--report" not in sys.argv:
        build()
    report()
