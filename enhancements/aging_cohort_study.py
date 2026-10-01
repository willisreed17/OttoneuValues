"""Young-pitcher aging cohort study (Enhancement 2, 2026-09-19). Read-only: measures, changes nothing.

Run from engine/:  py -3.13 ../enhancements/aging_cohort_study.py
Bootstrap by player, 400 draws, both beds (Marcel and historic Steamer). See NEXT_STEPS Task 14.
"""
import sys, random, collections
sys.path.insert(0, '.')  # run from engine/
import marcel, value
random.seed(7)
def collect(suffix):
    birth, pools, _ = marcel.aging_bed(suffix)
    obs = []  # (pid, k, age, ppt, proj_par, real_now, real_later)
    for y in sorted(pools):
        for pid, p in pools[y].items():
            age = marcel.age_on(birth.get(pid, ""), y)
            if p["par"] <= 0 or age is None or p["vpos"] not in value.PITCHER_POS: continue
            for k in range(0, 5):
                if k == 0: later = p
                elif y + k in pools: later = pools[y + k].get(pid)
                else: continue
                rl = max(later["realized_par"], 0.0) if later else 0.0
                obs.append((pid, k, age, p.get("ppt", 0.0), p["par"], max(p["realized_par"], 0.0), rl))
    return obs
def ratio(rows, num, den):
    d = sum(den(r) for r in rows)
    return sum(num(r) for r in rows) / d if d else float('nan')
def boot(rows, num, den, B=400):
    byp = collections.defaultdict(list)
    for r in rows: byp[r[0]].append(r)
    ids = list(byp); out = []
    for _ in range(B):
        s = [r for i in (random.choice(ids) for _ in ids) for r in byp[i]]
        out.append(ratio(s, num, den))
    out.sort(); return out[int(.025*B)], out[int(.975*B)]
cur = {1: .65, 2: .591, 3: .517, 4: .609}   # data/aging.csv, P age<=25
beds = {s: collect(s) for s in ("", "_steamer")}
for s, obs in beds.items():
    print("\nbed", s or "marcel")
    for lab, sel in (("P<=25 all", lambda o: o[2]<=25), ("P<=25 ppt>=140", lambda o: o[2]<=25 and o[3]>=140),
                     ("P26-29", lambda o: 26<=o[2]<=29), ("P30-33", lambda o: 30<=o[2]<=33)):
        for k in range(1,5):
            rows=[o for o in obs if o[1]==k and sel(o)]
            r=ratio(rows, lambda o:o[6], lambda o:o[5]); lo,hi=boot(rows, lambda o:o[6], lambda o:o[5])
            print("  %-15s k=%d n=%3d ratio %.3f CI [%.3f,%.3f]%s"%(lab,k,len(rows),r,lo,hi, "  excludes current %.3f"%cur[k] if lab=="P<=25 all" and not (lo<=cur[k]<=hi) else ""))
# projected-ppt distribution / share of young P priced, per bed
for s,obs in beds.items():
    k1=[o for o in obs if o[1]==1 and o[2]<=25]
    print(s or "marcel","young-P k=1 obs:",len(k1),"mean projected par %.1f"%(sum(o[4] for o in k1)/len(k1)),"mean realized-now %.1f"%(sum(o[5] for o in k1)/len(k1)))
