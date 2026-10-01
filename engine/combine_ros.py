"""Season-to-date actuals + rest-of-season projection -> steamer_{pit,bat}.csv.

Data prep only: writes files in the existing steamer_*.csv format to out/ros/ so
value.py can price a mid-season line. It never touches data/ and never changes
the valuation engine. See ../enhancements/ENHANCEMENTS.md (Enhancement 1).

  py -3.13 combine_ros.py                 # data/ros/steamer_*.csv -> out/ros/
  py -3.13 combine_ros.py --selftest

Inputs (bring your own, from the browser): data/ros/steamer_pit.csv and
data/ros/steamer_bat.csv, FanGraphs Steamer rest-of-season exports carrying
xMLBAMID and the raw components (pitchers: G GS IP SO H BB HBP HR SV HLD;
hitters: G PA AB H 2B 3B HR BB HBP SB CS and minpos). Then diff out/ros/report.csv,
back up data/steamer_*.csv, and copy the out/ros files over them.
"""
import csv
import os
import sys

import backtest as bt
import marcel
import value

ROS_DIR = os.path.join(value.DATA, "ros")
OUT_DIR = os.path.join("out", "ros")
PIT_HEAD = ["playerid", "PlayerName", "Team", "G", "GS", "IP", "SV", "HLD", "FPTS", "SPTS", "xMLBAMID"]
BAT_HEAD = ["playerid", "PlayerName", "Team", "minpos", "Pos", "G", "PA", "FPTS", "SPTS", "xMLBAMID"]
PIT_KEYS = ["SO", "H", "BB", "HBP", "HR", "SV", "HLD", "IP"]
BAT_KEYS = ["AB", "H", "2B", "3B", "HR", "BB", "HBP", "SB", "CS", "PA"]


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def actuals(season, group):
    """-> {mlbam: {stats..., G}} fresh from statsapi. Deliberately not
    marcel.season_stats: cached() never refetches, so a season in progress
    would go stale silently."""
    out = {}
    for sp in marcel.pages("stats=season&group=%s&season=%d" % (group, season)):
        st = sp["stat"]
        s = marcel.our_stats(st, group)
        s["G"] = bt.num(st.get("gamesPlayed", st.get("gamesPitched", 0)))
        out[str(sp["player"]["id"])] = s
    return out


def ros_points(row, pitcher):
    """-> (fpts, spts, from_components). Recomputed from raw components with the
    same bt.points used everywhere else (one formula on both sides); falls back
    to the file's own FPTS/SPTS columns if the export lacks components."""
    keys = PIT_KEYS if pitcher else BAT_KEYS
    if all(k in row and str(row[k]).strip() != "" for k in keys):
        s = {k: bt.num(row[k]) for k in keys}  # ROS IP is a true decimal, not thirds
        if pitcher:
            return bt.points(s, bt.PIT_W), bt.points(s, bt.SABR_PIT_W), True
        f = bt.points(s, bt.BAT_W)
        return f, f, True
    return bt.num(row.get("FPTS")), bt.num(row.get("SPTS", row.get("FPTS"))), False


def actual_points(s, pitcher):
    if pitcher:
        return bt.points(s, bt.PIT_W), bt.points(s, bt.SABR_PIT_W)
    f = bt.points(s, bt.BAT_W)
    return f, f


def combine_pitcher(act, ros):
    """act: statsapi stats or None; ros: {G,GS,IP,SV,HLD} from the ROS file or None.
    -> combined counting line. Points are added by the caller."""
    a = act or {}
    r = ros or {}
    return {"G": a.get("G", 0) + r.get("G", 0), "GS": a.get("GS", 0) + r.get("GS", 0),
            "IP": a.get("IP", 0) + r.get("IP", 0), "SV": a.get("SV", 0) + r.get("SV", 0),
            "HLD": a.get("HLD", 0) + r.get("HLD", 0)}


def combine_hitter(act, ros):
    a = act or {}
    r = ros or {}
    return {"G": a.get("G", 0) + r.get("G", 0), "PA": a.get("PA", 0) + r.get("PA", 0)}


def run(season):
    os.makedirs(OUT_DIR, exist_ok=True)
    report = []
    for pitcher, name, head in ((True, "steamer_pit.csv", PIT_HEAD), (False, "steamer_bat.csv", BAT_HEAD)):
        group = "pitching" if pitcher else "hitting"
        ros_rows = read(os.path.join(ROS_DIR, name))
        pre_rows = read(os.path.join(value.DATA, name))
        if not ros_rows:
            print("missing %s -- export the FanGraphs Steamer rest-of-season file there" % os.path.join(ROS_DIR, name))
            return 1
        if "xMLBAMID" not in ros_rows[0]:
            print("%s has no xMLBAMID column; the join key is required" % name)
            return 1
        print("fetching %d %s from statsapi ..." % (season, group))
        act = actuals(season, group)
        ros, seen = {}, set()
        for r in ros_rows:
            m = str(r.get("xMLBAMID", "")).strip()
            if not m:
                report.append([group, "", r.get("PlayerName", ""), 0, 0, 0, "", "ros_row_no_mlbam"])
            elif m in ros:
                report.append([group, m, r.get("PlayerName", ""), 0, 0, 0, "", "duplicate_ros_row"])
            else:
                ros[m] = r
        pre = {str(r["xMLBAMID"]).strip(): r for r in pre_rows if r.get("xMLBAMID")}
        out = []
        for m in sorted(set(ros) | set(act)):
            r, a, p = ros.get(m), act.get(m), pre.get(m)
            pid = (r or p or {}).get("playerid")
            nm = (r or p or {}).get("PlayerName") or (r or p or {}).get("Name") or ""
            flags = []
            if not pid:
                report.append([group, m, nm, 0, 0, 0, "", "no_playerid_skipped"])
                continue
            a_f, a_s = actual_points(a, pitcher) if a else (0.0, 0.0)
            r_f, r_s, comp = ros_points(r, pitcher) if r else (0.0, 0.0, True)
            if r and not comp:
                flags.append("ros_used_fpts_column")
            if r and comp and bt.num(r.get("FPTS")) and abs(r_f - bt.num(r["FPTS"])) > 0.01 * abs(r_f) + 1:
                flags.append("ros_fpts_mismatch")
            if not r:
                flags.append("no_ros")
            if not a:
                flags.append("no_actuals")
            rint = {k: bt.num(r.get(k)) for k in ("G", "GS", "IP", "SV", "HLD", "PA")} if r else None
            if pitcher:
                c = combine_pitcher(a, rint)
                if c["IP"] <= 0:
                    continue
                if c["GS"] >= 5 and a and a.get("G", 0) > 2 * a.get("GS", 0):
                    flags.append("swingman")  # tagged SP on combined GS, but most actual appearances were relief
                row = [pid, nm, (r or p or {}).get("Team", ""), round(c["G"], 1), round(c["GS"], 1),
                       round(c["IP"], 3), round(c["SV"], 1), round(c["HLD"], 1),
                       round(a_f + r_f, 1), round(a_s + r_s, 1), m]
            else:
                c = combine_hitter(a, rint)
                if c["PA"] <= 0:
                    continue
                minpos = (r or {}).get("minpos") or (p or {}).get("minpos") or ""
                if not minpos:
                    flags.append("no_minpos")
                row = [pid, nm, (r or p or {}).get("Team", ""), minpos or "DH",
                       (r or p or {}).get("Pos", ""), round(c["G"], 1), round(c["PA"], 1),
                       round(a_f + r_f, 1), round(a_s + r_s, 1), m]
            out.append(row)
            tot = a_f + r_f
            report.append([group, m, nm, round(a_f, 1), round(r_f, 1), round(tot, 1),
                           "%.2f" % (a_f / tot) if tot else "", ";".join(flags)])
        with open(os.path.join(OUT_DIR, name), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(head)
            w.writerows(out)
        print("wrote %s (%d rows)" % (os.path.join(OUT_DIR, name), len(out)))
    with open(os.path.join(OUT_DIR, "report.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group", "mlbam", "name", "actual_pts", "ros_pts", "combined_pts", "actual_share", "flags"])
        w.writerows(report)
    flagged = sum(1 for r in report if r[-1])
    print("report.csv: %d rows, %d with flags. Review it, back up data/steamer_*.csv, then copy out/ros over them." % (len(report), flagged))
    return 0


def selftest():
    assert abs(bt.innings("45.2") - (45 + 2 / 3)) < 1e-9
    c = combine_pitcher({"G": 30, "GS": 30, "IP": 154.0, "SV": 0, "HLD": 0}, {"G": 2, "GS": 2, "IP": 10.0, "SV": 0, "HLD": 0})
    assert c == {"G": 32, "GS": 32, "IP": 164.0, "SV": 0, "HLD": 0}, c
    assert combine_pitcher(None, {"G": 5, "GS": 0, "IP": 6.0, "SV": 1, "HLD": 0})["SV"] == 1
    assert combine_hitter({"G": 100, "PA": 400}, {"G": 10, "PA": 40}) == {"G": 110, "PA": 440}
    row = {"SO": 10, "H": 5, "BB": 2, "HBP": 0, "HR": 1, "SV": 0, "HLD": 0, "IP": 6.0}
    f, s, comp = ros_points(row, True)
    assert comp and abs(f - (7.4 * 6 + 2 * 10 - 2.6 * 5 - 3 * 2 - 12.3 * 1)) < 1e-9
    f2, _, comp2 = ros_points({"FPTS": "12.5"}, True)
    assert not comp2 and f2 == 12.5
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        season = int(sys.argv[sys.argv.index("--season") + 1]) if "--season" in sys.argv else value.projection_season()
        sys.exit(run(season))
