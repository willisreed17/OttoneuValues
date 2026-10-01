"""Aging table on the Steamer bed vs the shipped (Marcel-bed) table. Read-only: writes
nothing to data/. Run from engine/:  py -3.13 ../enhancements/aging_steamer_bed.py

A: cell-by-cell table, both beds, bootstrap CI for the Steamer bed.
B: out-of-sample calibration on the Steamer bed -- future floored PAR, realized /
   predicted, using (i) the shipped Marcel-bed table and (ii) a Steamer-bed table
   measured leave-seasons-out. The realized/predicted closer to 1.00 wins.
C: market corroboration (data/average_values.csv vs model base_value), young vs
   other pitchers. Market calibrates, never validates (APPROACH section 2).
D: writes the candidate table to the scratch path given as argv[1], if any.
"""
import csv, os, random, sys, collections
sys.path.insert(0, '.')
import marcel, value
random.seed(11)
BINS = marcel.AGING_BINS
birth_m, pools_m, _ = marcel.aging_bed("")
birth_s, pools_s, rates_s = marcel.aging_bed("_steamer")
tab_m = marcel.as_table(marcel.aging_ratios(birth_m, pools_m))
rows_s = marcel.aging_ratios(birth_s, pools_s)
tab_s = marcel.as_table(rows_s)
shipped = value.load_aging(os.path.join(value.DATA, "aging.csv"))

def obs(birth, pools, g):
    out = []
    for y in sorted(pools):
        for pid, p in pools[y].items():
            age = marcel.age_on(birth.get(pid, ""), y)
            if p["par"] <= 0 or age is None or (("P" if p["vpos"] in value.PITCHER_POS else "H") != g): continue
            for k in range(1, 5):
                if y + k in pools:
                    later = pools[y + k].get(pid)
                    out.append((pid, k, age, max(p["realized_par"], 0.0), max(later["realized_par"], 0.0) if later else 0.0))
    return out
def boot(rows, B=300):
    byp = collections.defaultdict(list)
    for r in rows: byp[r[0]].append(r)
    ids = list(byp); v = []
    for _ in range(B):
        s = [r for i in (random.choice(ids) for _ in ids) for r in byp[i]]
        d = sum(r[3] for r in s); v.append(sum(r[4] for r in s) / d if d else 0)
    v.sort(); return v[int(.025 * B)], v[int(.975 * B)]
def look(t, g, k, age):
    return next((x for lo, hi, x in t.get((g, k), ()) if lo <= age <= hi), 0.0)

print("A. aging ratio by cell: shipped(Marcel bed) | Steamer bed [95% CI] n")
for g in ("H", "P"):
    ob = obs(birth_s, pools_s, g)
    for b, (lo, hi) in enumerate(BINS):
        cells = []
        for k in range(1, 5):
            rows = [o for o in ob if o[1] == k and lo <= o[2] <= hi]
            a, c = look(shipped, g, k, lo), look(tab_s, g, k, lo)
            l, h = boot(rows) if len(rows) > 10 else (0, 0)
            cells.append("k%d %.2f|%.2f [%.2f,%.2f]%s n%d" % (k, a, c, l, h, "*" if not (l <= a <= h) else " ", len(rows)))
        print("  %s %2d-%-2d  %s" % (g, lo, hi, "  ".join(cells)))
print("  (* = shipped ratio outside the Steamer-bed 95% CI)")

print("\nB. Steamer bed, future floored PAR realized/predicted (want 1.00): shipped table | Steamer leave-seasons-out table")
acc = {}
for y in sorted(pools_s):
    h = 0
    while h < 4 and y + h + 1 in pools_s: h += 1
    if not h: continue
    win = range(y, y + h + 1)
    held = marcel.as_table(marcel.aging_ratios(birth_s, pools_s, lambda a, b: a in win or b in win))
    for pid, p in pools_s[y].items():
        age = marcel.age_on(birth_s.get(pid, ""), y)
        if p["par"] <= 0 or age is None: continue
        g = "P" if p["vpos"] in value.PITCHER_POS else "H"
        b = next(i for i, (lo, hi) in enumerate(BINS) if lo <= age <= hi)
        for k in range(1, h + 1):
            rp = max(pools_s[y + k][pid]["realized_par"], 0.0) if pid in pools_s[y + k] else 0.0
            a = acc.setdefault((g, b, k), [0.0, 0.0, 0.0, 0])
            a[0] += p["par"] * look(shipped, g, k, age); a[1] += p["par"] * look(held, g, k, age); a[2] += rp; a[3] += 1
for g in ("H", "P"):
    for b, (lo, hi) in enumerate(BINS):
        print("  %s %2d-%-2d  %s" % (g, lo, hi, "   ".join("k%d %.2f|%.2f n%d" % (k, a[2] / a[0], a[2] / a[1], a[3])
              for k in range(1, 5) for a in [acc.get((g, b, k))] if a and a[0] and a[1])))

print("\nC. market (avg salary, Roster% >= 50) minus model base_value, by group, model value >= $5")
mk = {}
with open(os.path.join(value.DATA, "average_values.csv"), newline="", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        try: mk[r["FG MajorLeagueID"]] = (float(r["Avg Salary"].replace("$", "")), float(r["Roster%"]))
        except (ValueError, KeyError): pass
gap = collections.defaultdict(list)
for r in csv.DictReader(open(os.path.join("out", "players.csv"), encoding="utf-8")):
    m = mk.get(r["playerid"]); bv = float(r["base_value"] or 0)
    if not m or m[1] < 50 or bv < 5 or not r["age"]: continue
    age = int(r["age"]); pit = r["vpos"] in ("SP", "RP")
    gap[("P" if pit else "H", "<=25" if age <= 25 else "26+")].append(m[0] - bv)
for key in sorted(gap):
    v = gap[key]; mean = sum(v) / len(v); sd = (sum((x - mean) ** 2 for x in v) / max(len(v) - 1, 1)) ** .5
    print("  %s age %-4s n=%3d  mean(market - model) %+.1f  se %.1f" % (key[0], key[1], len(v), mean, sd / len(v) ** .5))

if len(sys.argv) > 1:
    with open(sys.argv[1], "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["group", "k", "age_lo", "age_hi", "ratio", "n"]); w.writerows(rows_s)
    print("\nwrote candidate table", sys.argv[1])
