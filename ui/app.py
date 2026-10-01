"""Local web UI for league 1297. Reads out/players.csv, out/teams.csv and (if present) out/next/players.csv; never touches pricing.
Also reads data/average_values.csv (market context), and POST /api/reprice reruns the engine unchanged.
POST /api/update pulls rosterexport, the team pages behind teams_cap.csv, and the averageValues CSV straight
from Ottoneu (open to plain requests, verified 2026-09-24), checks them, backs up the old files, writes them
into engine/data/ and reruns the engine.

Run: py -3.13 ui/app.py   then open http://localhost:8000
Refresh numbers by rerunning value.py (README), then reload the page.
"""
import csv, datetime, html, io, json, os, re, shutil, subprocess, sys, threading, urllib.request, webbrowser
import xml.etree.ElementTree as ET
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "engine")
sys.path.insert(0, ENGINE)
import value  # read-only: only projection_season()
TEXT = {"playerid", "name", "mlb", "pos", "vpos", "owner", "team", "proj_source"}


def rows(name, sub=""):
    path = os.path.join(ENGINE, "out", sub, name)
    if sub and not os.path.exists(path):  # next-season view is optional (engine/next_season.py)
        return []
    with open(path, encoding="utf-8", newline="") as f:
        out = []
        for r in csv.DictReader(f):
            # strip text: rosterexport can carry "Iron " while teams_cap has "Iron", and owner must join to team
            out.append({k: (v.strip() if k in TEXT else (float(v) if v.strip() else None)) for k, v in r.items()})
        return out


def league():
    out = {}
    with open(os.path.join(ENGINE, "data", "league.csv"), encoding="utf-8") as f:
        for line in f:
            k, _, v = line.strip().partition(",")
            if k and not k.startswith("#") and k != "key":
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
    out["season"] = value.projection_season()  # the season the loaded projections describe
    return out


def market():
    """{playerid: cross-league avg salary}, joined the way backtest.py --market does. Optional file."""
    path = os.path.join(ENGINE, "data", "average_values.csv")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        return {r["FG MajorLeagueID"] or r["FG MinorLeagueID"]: float(r["Avg Salary"].strip("$").replace(",", ""))
                for r in csv.DictReader(f) if (r["FG MajorLeagueID"] or r["FG MinorLeagueID"]) and r["Avg Salary"].strip("$")}


LOCK = threading.RLock()  # one data write / engine run at a time
OTTONEU = "https://ottoneu.fangraphs.com"
LEAGUE_ID = 1297  # same league as the header label in web/index.html
MARKET_GAME_TYPE = 5  # averageValues gameType: 5 = H2H FanGraphs Points (the league API's scoring id)
ROSTER_COLS = ["TeamID", "Team Name", "ottoneu ID", "FG MajorLeagueID", "FG MinorLeagueID", "Name", "MLB Team", "Position(s)", "Salary"]
CAP_COLS = ["team_id", "team_name", "roster", "roster_max", "base_cap", "loans_in", "loans_out", "salary", "penalties"]
MARKET_COLS = {"Name", "FG MajorLeagueID", "FG MinorLeagueID", "Avg Salary"}


def parse(text):
    r = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    return (r[0], [x for x in r[1:] if any(x)]) if r else ([], [])


def check_import(files):
    """-> list of problems; empty means every supplied file is safe to write. Nothing is written on any problem."""
    bad = []
    head, roster = parse(files.get("rosterexport") or "")
    if head != ROSTER_COLS or len(roster) < 100:
        bad.append(f"rosterexport: unexpected header or only {len(roster)} rows (got {head[:3]})")
    head, cap = parse(files.get("teams_cap") or "")
    if head != CAP_COLS or not cap:
        bad.append(f"teams_cap: unexpected header or no rows (got {head[:3]})")
    else:
        try:
            nums = [[int(v) for v in row[2:]] for row in cap]
        except ValueError:
            bad.append("teams_cap: a cap figure is blank or not a number (team page text may have changed)")
        else:
            if sum(n[3] for n in nums) != sum(n[4] for n in nums):
                bad.append("teams_cap: loans in don't equal loans out")
        if not bad and {r[0] for r in roster} != {r[0] for r in cap}:
            bad.append("teams_cap: team ids don't match the roster export's")
    if files.get("average_values"):
        head, mk = parse(files["average_values"])
        if not MARKET_COLS <= set(head) or len(mk) < 100:
            bad.append(f"average_values: unexpected header or only {len(mk)} rows")
    return bad


def get(path):
    with urllib.request.urlopen(OTTONEU + path, timeout=30) as r:
        return r.read().decode("utf-8-sig")


def team_cap_row(team_id, name):
    """One teams_cap.csv row from a team page, with the README recipe's patterns. Blank on a miss (check_import refuses it)."""
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", get(f"/{LEAGUE_ID}/team/{team_id}"))))
    g = lambda pat, i=1, d="": (m.group(i).replace(",", "") if (m := re.search(pat, t, re.I)) else d)
    return [team_id, name,
            g(r"Roster\s*(\d+)\s*of\s*(\d+)"), g(r"Roster\s*(\d+)\s*of\s*(\d+)", 2),
            g(r"Salary\s*Cap\s*\$([\d,]+)\s*\(base\)"),
            g(r"\+\s*\$([\d,]+)\s*\(loans in\)", d="0"), g(r"-\s*\$([\d,]+)\s*\(loans out\)", d="0"),
            g(r"Cap\s*Used\s*\$([\d,]+)\s*\(salary\)"), g(r"\+\s*\$([\d,]+)\s*\(cap penalties\)", d="0")]


def pull_ottoneu():
    """-> {rosterexport, teams_cap, average_values} as CSV text. About 15 requests, what a person clicking through makes."""
    teams = [(t.findtext("id"), t.findtext("name").strip())
             for t in ET.fromstring(get(f"/api/league?leagueID={LEAGUE_ID}&output=xml")).iter("team")]
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows([CAP_COLS] + [team_cap_row(i, n) for i, n in teams])
    return {"rosterexport": get(f"/{LEAGUE_ID}/rosterexport?csv=1"), "teams_cap": out.getvalue(),
            "average_values": get(f"/averageValues?export=csv&gameType={MARKET_GAME_TYPE}")}


def update():
    """Pull from Ottoneu, check, back up, write, rerun. -> (ok, message). Nothing is written unless every file checks out."""
    try:
        files = pull_ottoneu()
    except Exception as e:  # network, HTTP error, or the league API changed shape
        return False, f"Nothing written. Couldn't pull from Ottoneu: {e}"
    bad = check_import(files)
    if bad:
        return False, "Nothing written. " + "; ".join(bad)
    with LOCK:
        return write_and_run(files)


def write_and_run(files):
    data = os.path.join(ENGINE, "data")
    backup = os.path.join(data, "backup", datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(backup, exist_ok=True)
    wrote = []
    for key in ("rosterexport", "teams_cap", "average_values"):
        if not files.get(key):
            continue
        path = os.path.join(data, key + ".csv")
        if os.path.exists(path):
            shutil.copy2(path, backup)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(files[key].lstrip("\ufeff"))
        wrote.append(key + ".csv")
    ok, log = reprice()
    msg = f"Wrote {', '.join(wrote)} (old copies in data/backup/{os.path.basename(backup)})."
    return ok, msg + (" Engine rerun." if ok else " Engine run failed:\n" + log)


def reprice():
    """Rerun the engine on whatever data/ now holds: value.py, then next_season.py if its output exists."""
    runs = [["value.py"]] + ([["next_season.py"]] if os.path.isdir(os.path.join(ENGINE, "out", "next")) else [])
    log = []
    with LOCK:
        for args in runs:
            r = subprocess.run([sys.executable, *args], cwd=ENGINE, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            log.append(f"$ {' '.join(args)}\n" + (r.stdout + r.stderr)[-1500:])
            if r.returncode:
                return False, "\n".join(log)
    return True, "\n".join(log)


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/api/players", "/api/teams", "/api/league", "/api/players_next", "/api/market"):
            name = self.path.split("/")[-1]
            self.send_json(league() if name == "league" else market() if name == "market" else
                           rows("players.csv", "next") if name == "players_next" else rows(name + ".csv"))
        else:
            super().do_GET()

    def do_POST(self):
        # The custom header forces a CORS preflight, so another site open in the browser can't trigger a pull or rerun.
        if self.path not in ("/api/reprice", "/api/update") or self.headers.get("X-Ottoneu") != "1":
            return self.send_error(404)
        if self.path == "/api/update":
            ok, msg = update()
            return self.send_json({"ok": ok, "msg": msg}, 200 if ok else 502)
        ok, log = reprice()
        self.send_json({"ok": ok, "log": log}, 200 if ok else 500)


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", 8000), partial(Handler, directory=os.path.join(HERE, "web")))
    print("http://localhost:8000  (Ctrl+C to stop)")
    webbrowser.open("http://localhost:8000")
    srv.serve_forever()
