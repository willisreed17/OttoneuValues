"""FanGraphs full projection export (any system) -> steamer_{bat,pit}.csv in the engine's format.

Data prep only; never touches data/steamer_*.csv and never changes the engine.

  py -3.13 convert_fg_export.py "data/2027 zips hitter projection.csv" "data/2027 zips pitcher projection.csv"
  py -3.13 convert_fg_export.py --selftest

Writes out/proj/steamer_bat.csv, out/proj/steamer_pit.csv and out/proj/convert_report.txt.
The full export has Name/PlayerId/MLBAMID and no `minpos`; hitter positions are taken from the
current data/steamer_bat.csv by playerid (players it lacks, mostly rookies, become DH -> Util
and are listed in the report so they can be fixed by hand).
"""
import csv
import os
import sys

import backtest as bt
import value

OUT = os.path.join("out", "proj")
PIT_HEAD = ["playerid", "PlayerName", "Team", "G", "GS", "IP", "SV", "HLD", "FPTS", "SPTS", "xMLBAMID"]
BAT_HEAD = ["playerid", "PlayerName", "Team", "minpos", "Pos", "G", "PA", "FPTS", "SPTS", "xMLBAMID"]


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def clean(v):
    return "" if v is None else str(v).strip()


def convert_bat(rows, minpos):
    out, missing = [], []
    for r in rows:
        pid, mlbam = clean(r.get("PlayerId")), clean(r.get("MLBAMID"))
        if not pid or not mlbam or bt.num(r.get("PA")) <= 0:
            continue
        mp = minpos.get(pid, "")
        if not mp:
            missing.append((clean(r.get("Name")), bt.num(r.get("PA"))))
        out.append([pid, clean(r.get("Name")), clean(r.get("Team")), mp or "DH", "", clean(r.get("G")),
                    clean(r.get("PA")), clean(r.get("FPTS")), clean(r.get("SPTS")), mlbam])
    return out, missing


def convert_pit(rows):
    out = []
    for r in rows:
        pid, mlbam = clean(r.get("PlayerId")), clean(r.get("MLBAMID"))
        if not pid or not mlbam or bt.num(r.get("IP")) <= 0:
            continue
        out.append([pid, clean(r.get("Name")), clean(r.get("Team")), clean(r.get("G")), clean(r.get("GS")),
                    clean(r.get("IP")), clean(r.get("SV")) or "0", clean(r.get("HLD")) or "0",
                    clean(r.get("FPTS")), clean(r.get("SPTS")), mlbam])
    return out


def points_check(rows, weights, keys):
    """Recompute FPTS from raw components with bt.points; -> (rows checked, rows off by >1%)."""
    n = bad = 0
    for r in rows:
        if not all(clean(r.get(k)) != "" or k in ("SV", "HLD") for k in keys) or not clean(r.get("FPTS")):
            continue
        p = bt.points({k: bt.num(r[k]) for k in keys}, weights)
        f = bt.num(r["FPTS"])
        n += 1
        bad += abs(p - f) > 0.01 * abs(f) + 1
    return n, bad


def run(bat_path, pit_path):
    bat_rows, pit_rows = read(bat_path), read(pit_path)
    if not bat_rows or not pit_rows:
        print("could not read %s / %s" % (bat_path, pit_path))
        return 1
    minpos = {r["playerid"]: r["minpos"] for r in read(os.path.join(value.DATA, "steamer_bat.csv")) if r.get("minpos")}
    bat, missing = convert_bat(bat_rows, minpos)
    pit = convert_pit(pit_rows)
    os.makedirs(OUT, exist_ok=True)
    for name, head, rows in (("steamer_bat.csv", BAT_HEAD, bat), ("steamer_pit.csv", PIT_HEAD, pit)):
        with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(head)
            w.writerows(rows)
    bn, bb = points_check(bat_rows, bt.BAT_W, ["AB", "H", "2B", "3B", "HR", "BB", "HBP", "SB", "CS"])
    pn, pb = points_check(pit_rows, bt.PIT_W, ["IP", "SO", "H", "BB", "HBP", "HR", "SV", "HLD"])
    big = sorted((m for m in missing if m[1] >= bt.MIN_PA), key=lambda m: -m[1])
    lines = ["hitters written %d, pitchers written %d" % (len(bat), len(pit)),
             "FPTS recomputed from components with bt.points: hitters %d checked, %d off >1%%; pitchers %d checked, %d off >1%%" % (bn, bb, pn, pb),
             "hitters with no minpos in data/steamer_bat.csv (set to DH -> Util): %d, of which PA >= %d: %d" % (len(missing), bt.MIN_PA, len(big))]
    lines += ["  %s (PA %.0f)" % m for m in big[:60]]
    with open(os.path.join(OUT, "convert_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:3]))
    return 0


def selftest():
    b, miss = convert_bat([{"PlayerId": "1", "MLBAMID": "9", "Name": "A B", "Team": "X", "G": "10", "PA": "40", "FPTS": "12.5", "SPTS": "12.5"},
                           {"PlayerId": "2", "MLBAMID": "", "Name": "no id", "PA": "50"}], {"1": "OF"})
    assert len(b) == 1 and b[0][3] == "OF" and b[0][-1] == "9" and not miss
    b2, miss2 = convert_bat([{"PlayerId": "3", "MLBAMID": "8", "Name": "Rookie", "PA": "300"}], {})
    assert b2[0][3] == "DH" and miss2 == [("Rookie", 300.0)]
    p = convert_pit([{"PlayerId": "5", "MLBAMID": "7", "Name": "P", "G": "30", "GS": "30", "IP": "182.3", "SV": "", "HLD": "", "FPTS": "1", "SPTS": "1"},
                     {"PlayerId": "6", "MLBAMID": "7", "IP": "0"}])
    assert len(p) == 1 and p[0][6] == "0" and p[0][5] == "182.3"
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        sys.exit(run(args[0], args[1]) if len(args) == 2 else print(__doc__) or 1)
