"""Per-season consistency of the young-pitcher miss on the Steamer bed. Read-only.
Run from engine/:  py -3.13 ../enhancements/aging_by_year.py
For each season Y: P age<=25 with projected PAR>0. k=0 realized/projected PAR (base projection
bias, trap 32); k=1 realized/predicted with the shipped table and with a Steamer table measured
leave-seasons-out. Also the same for P age 26-29 as the control."""
import os, sys
sys.path.insert(0, '.')
import marcel, value
birth, pools, _ = marcel.aging_bed("_steamer")
shipped = value.load_aging(os.path.join(value.DATA, "aging.csv"))
look = lambda t, g, k, age: next((x for lo, hi, x in t.get((g, k), ()) if lo <= age <= hi), 0.0)
def cell(sel):
    print("  %-5s %-4s %-6s %-6s %-6s" % ("Y", "n", "k0", "k1 ship", "k1 stmr"))
    yrs = 0; wins = 0
    for y in sorted(pools):
        if y + 1 not in pools: continue
        win = range(y, y + 2)
        held = marcel.as_table(marcel.aging_ratios(birth, pools, lambda a, b: a in win or b in win))
        a0 = a1 = b1 = r0 = r1 = 0.0; n = 0
        for pid, p in pools[y].items():
            age = marcel.age_on(birth.get(pid, ""), y)
            if p["par"] <= 0 or age is None or p["vpos"] not in value.PITCHER_POS or not sel(age): continue
            rp = max(pools[y + 1][pid]["realized_par"], 0.0) if pid in pools[y + 1] else 0.0
            a0 += p["par"]; r0 += max(p["realized_par"], 0.0)
            a1 += p["par"] * look(shipped, "P", 1, age); b1 += p["par"] * look(held, "P", 1, age); r1 += rp; n += 1
        if n < 5: continue
        yrs += 1; wins += (abs(r1 / b1 - 1) < abs(r1 / a1 - 1))
        print("  %-5d %-4d %-6.2f %-6.2f %-6.2f" % (y, n, r0 / a0, r1 / a1, r1 / b1))
    print("  Steamer table closer to 1.00 in %d of %d seasons" % (wins, yrs))
print("P age <= 25"); cell(lambda a: a <= 25)
print("P age 26-29 (control)"); cell(lambda a: 26 <= a <= 29)
