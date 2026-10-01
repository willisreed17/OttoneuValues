"use strict";
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

// ---- the one place numbers get formatted; null is always an em dash ----
const nil = '<span class="nil">—</span>';
const num = (v, d = 0) => (v == null ? null : v.toFixed(d));
const cls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");
const F = {
  usd: (v) => (v == null ? nil : (v < 0 ? "-$" : "$") + num(Math.abs(v))),
  pts: (v) => (v == null ? nil : num(v, 1)),
  int: (v) => (v == null ? nil : num(v)),
  sgn: (v, d = 0) => (v == null ? nil : `<span class="${cls(v)}">${v < 0 ? "-" : v > 0 ? "+" : ""}$${num(Math.abs(v), d)}</span>`),
  npv: (v) => F.sgn(v, 1),
  txt: (v) => (v == null || v === "" ? nil : esc(v)),
};

let players = [], teams = [], league = {}, playersNext = [], market = {};
// Season of the next-season file, from its proj_source ("marcel-2027").
const nextSeason = () => Number(String(playersNext[0]?.proj_source ?? "").split("-").pop()) || league.season + 1;
// Keeper decisions are about next season, so the keeper views default to it when
// engine/next_season.py has written it.
const keeperSrc = () => (playersNext.length ? "next" : "now");
const keeperPool = () => (keeperSrc() === "next" ? playersNext : players);
const keeperSeason = () => (keeperSrc() === "next" ? nextSeason() : league.season);
// Pre-draft (keepers through the auction) prices next season; post-draft (in season) prices this one.
// The user flips it by hand after their auction; nothing guesses it from dates or data.
let phase = store.get("phase", "pre");
const phasePool = () => (phase === "pre" ? keeperPool() : players);
const phaseSeason = () => (phase === "pre" ? keeperSeason() : league.season);
let myTeam = store.get("team", null);
const view = { q: "", vpos: "", type: "", own: "FA", min: "", sort: { k: "base_value", dir: -1 } };

// ---- shared table: cols = [{k, label, num?, f(row)}] ----
function tableHtml(cols, rows, sort) {
  const head = cols.map((c) => `<th class="${c.num ? "num" : ""}" data-k="${c.k}">${esc(c.label)}${sort.k === c.k ? (sort.dir < 0 ? " ▼" : " ▲") : ""}</th>`).join("");
  const body = rows.map((r) => "<tr>" + cols.map((c) => `<td class="${c.num ? "num" : ""}">${c.f(r)}</td>`).join("") + "</tr>").join("");
  return `<div class="wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}
const sortRows = (rows, s) => [...rows].sort((a, b) => {
  const x = a[s.k], y = b[s.k];
  if (x == null && y == null) return 0;
  if (x == null) return 1;
  if (y == null) return -1;
  return (x < y ? -1 : x > y ? 1 : 0) * s.dir;
});
const playerLink = (r) => `<a data-id="${esc(r.playerid)}">${esc(r.name)}</a>`;
function wireTable(root, sort, redraw) {
  root.querySelectorAll("th").forEach((th) => (th.onclick = () => {
    const k = th.dataset.k;
    sort.dir = sort.k === k ? -sort.dir : -1;
    sort.k = k;
    redraw();
  }));
  root.querySelectorAll("td a[data-id]").forEach((a) => (a.onclick = () => openDrawer(a.dataset.id)));
}

// ---- Rankings ----
const isPitcher = (p) => p.vpos === "SP" || p.vpos === "RP";
function rankings() {
  const players = phasePool();  // shadows the this-season list: pre-draft ranks next season
  const rank = new Map([...players].sort((a, b) => (b.base_value ?? -1e9) - (a.base_value ?? -1e9)).map((p, i) => [p.playerid, i + 1]));
  const vposes = [...new Set(players.map((p) => p.vpos))].sort();
  // The inputs value.py's league_values() checks: free cap and open spots, less $1 held back per open spot up to roster max.
  const sumT = (f) => teams.reduce((a, t) => a + f(t), 0);
  const basePool = teams.length * (league.cap - league.roster_max);
  const freeCap = sumT((t) => t.cap_space ?? 0), openSpots = sumT((t) => t.open_spots ?? 0);
  const reserve = sumT((t) => Math.max(0, league.roster_max - (t.players ?? 0))), spendable = freeCap - reserve;
  const open = players.some((p) => p.league_value != null);  // the engine's own verdict, not re-derived here
  // Worked example from the engine's own numbers: the best free agent, and the first pair League $ re-orders.
  const fa = players.filter((p) => p.owner === "FA" && p.league_value != null && p.base_value != null)
    .sort((a, b) => b.base_value - a.base_value).slice(0, 40);
  let flip = null;
  for (let i = 0; i < fa.length && !flip; i++) for (let j = i + 1; j < fa.length; j++)
    if (fa[i].base_value > fa[j].base_value && fa[i].league_value < fa[j].league_value) { flip = [fa[i], fa[j]]; break; }
  const bl = (p) => `${esc(p.name)} (${F.usd(p.base_value)} → ${F.usd(p.league_value)})`;
  const card = (k, v, note) => `<div class="card"><div class="k">${k}</div><div class="v">${v}</div><div class="note">${note}</div></div>`;
  $("#focus").innerHTML = `<div class="panel"><h2>Rankings</h2><p class="sub">${phase === "pre" ? "Who should I target at the auction?" : "Who should I pick up?"} Ranked by ${phaseSeason()} base value.</p>
    <div class="explain"><h3>Why League $ differs from Base $</h3>
    <div class="vs"><p><b>Base $</b> is a fresh draft: every player in baseball up for auction, ${teams.length} teams with empty rosters and full caps.</p>
      <p><b>League $</b> is your league today: only players nobody owns, bought with the cap room teams actually have left.</p></div>
    <div class="cards">
      ${card("Fresh-draft money", F.usd(basePool), `${teams.length} teams × (${F.usd(league.cap)} cap − $1 for each of ${league.roster_max} spots)`)}
      ${card("Cap room left", F.usd(freeCap), "Not yet spent on kept players or cut penalties")}
      ${card("− Held back", F.usd(reserve), `$1 per spot under ${league.roster_max} players · ${F.int(openSpots)} open spots league-wide`)}
      ${card("= Money to bid with", F.usd(spendable), open ? "Split among free agents by projected points: this sets League $" : "Not enough to open a market")}
    </div>
    <p class="sub">${open
      ? `Only ${F.usd(spendable)} is chasing free agents, not ${F.usd(basePool)}, so most cost less here${fa[0] ? `: ${bl(fa[0])}` : ""}.
        It is not a flat discount: each position is re-measured against the free agents left there${flip ? `, so ${bl(flip[0])} drops below ${bl(flip[1])}` : ""}. Owned players have no League $: they are not for sale.`
      : `<b>League $ is blank: no open market.</b> It needs open roster spots and more cap room than the $1 each spot holds back. It fills in once teams cut players and free up room, for example at the keeper deadline.`}</p>
    <details class="info"><summary>How is each number worked out?</summary><div class="pop">
      <p><b>Base $.</b> At each position, "replacement" is the best player still left once every team has filled its spots there, the kind you could pick up for free. A player earns dollars for the projected points he scores above that. The fresh-draft money is split in proportion to those points; every player also gets the $1 his roster spot costs.</p>
      <p><b>League $.</b> The same recipe, run on free agents only. Positions teams have already filled with kept players don't need filling again, and replacement becomes the best free agent left after the open spots are filled. Then only the money to bid with is split.</p>
      <p>That is why League $ can re-order players. If the good catchers are all kept, the free catchers are a weaker group, so the best of them sits further above the free-agent replacement and is worth relatively more than his Base $ suggests.</p>
      <p class="sub">Cap room is each team's cap minus salaries and cut penalties. Spots above ${league.roster_max} opened by the 60-day IL hold back no money. League $ is left blank when there are no open spots or the cap room is no more than the $1-per-spot hold-back.</p></div></details>
    </div>
    <div class="bar">
      <input type="search" id="q" placeholder="Search players…" value="${esc(view.q)}">
      <select id="vpos"><option value="">All positions</option>${vposes.map((v) => `<option ${v === view.vpos ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
      <select id="type"><option value="">Hitters + pitchers</option><option value="H">Hitters</option><option value="P">Pitchers</option></select>
      <select id="own"><option value="FA">Available</option><option value="">All players</option><option value="OWNED">Owned</option></select>
      <input type="number" id="min" placeholder="Min base $" min="0" class="w-min" value="${esc(view.min)}">
    </div><p class="count" id="count"></p><div id="tbl"></div></div>`;
  $("#type").value = view.type; $("#own").value = view.own;
  const cols = [
    { k: "rank", label: "Rank", num: true, f: (r) => rank.get(r.playerid) },
    { k: "name", label: "Player", f: playerLink },
    { k: "pos", label: "Pos", f: (r) => F.txt(r.pos) },
    { k: "mlb", label: "MLB", f: (r) => F.txt(r.mlb) },
    { k: "age", label: "Age", num: true, f: (r) => F.int(r.age) },
    { k: "pts", label: "Proj Pts", num: true, f: (r) => F.pts(r.pts) },
    { k: "base_value", label: "Base $", num: true, f: (r) => F.usd(r.base_value) },
    { k: "league_value", label: "League $", num: true, f: (r) => F.usd(r.league_value) },
    { k: "salary", label: "Salary", num: true, f: (r) => F.usd(r.salary) },
    { k: "owner", label: "Owner", f: (r) => F.txt(r.owner) },
  ];
  const draw = () => {
    const q = view.q.toLowerCase(), min = view.min === "" ? null : Number(view.min);
    const rows = players.filter((p) =>
      (!q || p.name.toLowerCase().includes(q)) && (!view.vpos || p.vpos === view.vpos) &&
      (!view.type || (view.type === "P") === isPitcher(p)) &&
      (!view.own || (view.own === "FA" ? p.owner === "FA" : p.owner !== "FA")) &&
      (min == null || (p.base_value ?? -1) >= min));
    const withRank = rows.map((p) => ({ ...p, rank: rank.get(p.playerid) }));
    const key = view.sort.k === "rank" ? { k: "rank", dir: -view.sort.dir } : view.sort;
    $("#count").textContent = `${rows.length} of ${players.length} players`;
    $("#tbl").innerHTML = tableHtml(cols, sortRows(withRank, key), view.sort);
    wireTable($("#tbl"), view.sort, draw);
  };
  $("#q").oninput = (e) => { view.q = e.target.value; draw(); };
  for (const id of ["vpos", "type", "own", "min"]) $("#" + id).onchange = (e) => { view[id] = e.target.value; draw(); };
  draw();
}

// ---- Keepers: get under the cap by cutting. Default cut = engine says cutting is optimal (keeper NPV $0) ----
const kview = { keep: { k: "keeper_surplus", dir: -1 }, cut: { k: "keeper_surplus", dir: -1 } };
const suggestCut = (p) => p.keeper_npv != null && p.keeper_npv <= 0;
const isCut = (p, dec) => (dec[p.playerid] ? dec[p.playerid] === "CUT" : suggestCut(p));
function keepers() {
  if (!myTeam) { $("#focus").innerHTML = '<div class="panel">Choose My Team above.</div>'; return; }
  const dkey = "dec:" + myTeam;
  let dec = store.get(dkey, {});
  // Source: this season's engine output, or next season's (engine/next_season.py) when it exists.
  const src = keeperSrc(), pool = keeperPool(), season = keeperSeason();
  const roster = pool.filter((p) => p.owner === myTeam);
  const sum = (a, k) => a.reduce((s, p) => s + (p[k] ?? 0), 0);
  $("#focus").innerHTML = `<div class="panel"><div class="khead"><div><h2>Keepers</h2>
    <p class="sub" id="ksub"></p></div></div>
    <details class="info"><summary>What is Keeper NPV, and how do I read it?</summary><div class="pop">
      <p><b>Keeper NPV</b> is the total dollars of surplus you gain by keeping a player over the next four seasons, in this season's dollars. Each year it takes his projected value (aged forward) minus his salary, which rises every year. Later seasons count for less: the weight halves each year by default.</p>
      <p>Because you can cut a player for free any offseason, a bad year never costs you, so NPV never goes below <b>$0</b>.</p>
      <ul><li><b>$0</b>: no season is worth more than it costs. Cutting is the best move.</li>
      <li><b>Above $0</b>: keeping beats cutting by about that many dollars. Higher means keep first.</li>
      <li><b>${season} value</b> is his projected ${season} dollar value. <b>Surplus</b> is that value minus his next salary, one season only. It can be negative, and it can be positive while NPV is $0 if he is expected to decline.</li></ul>
      <p class="sub">${src === "next"
        ? (String(roster[0]?.proj_source ?? "").startsWith("zips")
          ? `Next-season view: built from the ${season} ZiPS projection, priced with ZiPS's own measured reliability. It stands in until ${season} Steamer is published.`
          : `Next-season view: built from a ${season} Marcel projection (last three MLB seasons, from statsapi) with Marcel's own measured corrections, including one for its known under-projection of young players. It is a weaker projection than Steamer and stands in only until a post-season ZiPS or ${season} Steamer is published. Injury-shortened seasons pull a player's projected playing time down.`)
        : `It is built from the ${season} projection aged forward with measured ratios (for example 0.85 of this season's value one year on for pitchers 25 and under), not from a projection of next season. If a player's loaded projection is stale versus what he has actually done, his NPV is too.`} Expected values only; the four-season horizon undervalues the youngest stars.</p></div></details>
    <div id="meter"></div>
    <div class="two"><div class="col"><h3 class="lh keep-h">Keeping <span id="nk"></span></h3><div class="pane" id="keeping"></div></div>
    <div class="col"><h3 class="lh cut-h">Cutting <span id="nc"></span></h3><div class="pane" id="cutting"></div></div></div></div>`;
  const move = (r, to) => `<button class="mv" data-id="${esc(r.playerid)}" data-to="${to}">${to === "CUT" ? "Cut \u2192" : "\u2190 Keep"}</button>`;
  const cols = (to) => {
    const act = { k: "act", label: "", f: (r) => move(r, to) };
    const rest = [
      { k: "name", label: "Player", f: (r) => `${playerLink(r)} <span class="pp">${esc(r.pos)}</span>` },
      { k: "keeper_salary", label: "Next $", num: true, f: (r) => F.usd(r.keeper_salary) },
      { k: "keeper_npv", label: "NPV", num: true, f: (r) => F.npv(r.keeper_npv) },
      { k: "base_value", label: `${season} value`, num: true, f: (r) => F.usd(r.base_value) },
      { k: "keeper_surplus", label: "Surplus", num: true, f: (r) => F.sgn(r.keeper_surplus) },
    ];
    return to === "CUT" ? [...rest, act] : [act, ...rest];
  };
  const draw = () => {
    $("#ksub").textContent = `Players whose Keeper NPV is $0 start in Cutting (keeping adds nothing over cutting). Surplus shows how far over or under value each is. Move anyone; get payroll under the cap.`;
    const keep = roster.filter((p) => !isCut(p, dec)), cut = roster.filter((p) => isCut(p, dec));
    const cap = league.cap, payroll = sum(keep, "keeper_salary"), max = league.roster_max;
    const over = cap == null ? 0 : payroll - cap, pct = cap ? Math.min(100, (payroll / cap) * 100) : 0;
    const spots = max == null ? 0 : keep.length - max;
    $("#meter").innerHTML = `<div class="meter ${over > 0 ? "over" : ""}"><div class="mtop"><span>Keeper payroll <b>${F.usd(payroll)}</b> of ${F.usd(cap)} cap</span>
      <strong>${over > 0 ? F.usd(over) + " over \u2014 cut to get under" : F.usd(-over) + " of room"}</strong></div>
      <div class="track"><i style="width:${pct}%"></i></div>
      <div class="chips"><span>Kept <b>${keep.length} / ${max ?? "\u2014"}</b>${spots > 0 ? ` <em class="neg">${spots} over roster max</em>` : ""}</span>
      <span>Surplus <b>${F.sgn(sum(keep, "keeper_surplus"))}</b></span><span>Retained value <b>${F.usd(sum(keep, "base_value"))}</b></span></div></div>`;
    $("#nk").textContent = keep.length; $("#nc").textContent = cut.length;
    $("#keeping").innerHTML = keep.length ? tableHtml(cols("CUT"), sortRows(keep, kview.keep), kview.keep) : '<p class="empty">No one kept.</p>';
    $("#cutting").innerHTML = cut.length ? tableHtml(cols("KEEP"), sortRows(cut, kview.cut), kview.cut) : '<p class="empty">No one cut.</p>';
    for (const [id, sk] of [["#keeping", kview.keep], ["#cutting", kview.cut]]) {
      wireTable($(id), sk, draw);
      $(id).querySelectorAll("button.mv").forEach((b) => (b.onclick = () => {
        dec[b.dataset.id] = b.dataset.to === "CUT" ? "CUT" : "KEEP";
        store.set(dkey, dec); draw();
      }));
    }
  };
  draw();
}

// ---- Auction: the model's value as the most it's worth, no computed bid range (UI_FUTURE_DEV Phase 3) ----
const modelValue = (p) => p.league_value ?? p.base_value;
const aview = { q: "", vpos: "", sort: { k: "mv", dir: -1 } };
// Logged sales drop out on their own once a re-exported roster shows the player owned.
function liveSales() {
  const pool = new Map(keeperPool().map((p) => [p.playerid, p]));
  const sales = store.get("sales", []).filter((s) => pool.get(s.id)?.owner === "FA");
  store.set("sales", sales);
  return sales;
}
function auction() {
  const pool = keeperPool(), season = keeperSeason(), byId = new Map(pool.map((p) => [p.playerid, p]));
  const sales = liveSales(), sold = new Map(sales.map((s) => [s.id, s]));
  const targets = store.get("targets", {});
  const withVals = (p) => ({ ...p, mv: modelValue(p), mkt: market[p.playerid] ?? null });
  const avail = pool.filter((p) => p.owner === "FA" && !sold.has(p.playerid)).map(withVals);
  const label = (p) => `${p.name} · ${p.pos} · ${p.mlb}`;
  const byLabel = new Map(avail.map((p) => [label(p), p.playerid]));
  // Each team's room: the engine's cap_space/open_spots less the sales logged since.
  const room = (t) => {
    const mine = sales.filter((s) => s.team === t.team);
    const cap = (t.cap_space ?? 0) - mine.reduce((a, s) => a + s.price, 0), spots = Math.max(0, t.open_spots ?? 0) - mine.length;
    return { cap, spots, max: spots > 0 ? cap - (spots - 1) : null };  // $1 must stay free for each other open spot
  };
  const me = teams.find((t) => t.team === myTeam), r = me ? room(me) : { cap: null, spots: 0, max: null };
  const freeCap = teams.reduce((a, t) => a + room(t).cap, 0), freeSpots = teams.reduce((a, t) => a + room(t).spots, 0);
  const hasLeague = pool.some((p) => p.league_value != null);
  const vposes = [...new Set(avail.map((p) => p.vpos))].sort();
  const why = "the engine found no open market (rosters full, or no free money beyond the $1 per open spot). After the keeper deadline, press Update from Ottoneu.";
  $("#focus").innerHTML = `<div class="panel"><div class="khead"><div><h2>Auction</h2>
      <p class="sub">How high should I bid? Model $ (League $ when the market is open, else Base $) is the most a player is worth. There is no bid range until one has a real method behind it.</p></div>
      <button id="reprice">Re-price</button></div>
    <p class="count" id="rpmsg">${hasLeague ? "" : "League $ is blank: " + why}</p>
    <div class="cards">
      <div class="card"><div class="k">My cap left</div><div class="v">${F.usd(r.cap)}</div></div>
      <div class="card"><div class="k">My open spots</div><div class="v">${F.int(r.spots)}</div></div>
      <div class="card"><div class="k">$ / open spot</div><div class="v">${r.spots > 0 ? F.usd(r.cap / r.spots) : nil}</div></div>
      <div class="card"><div class="k">Most I can bid</div><div class="v">${F.usd(r.max)}</div></div>
      <div class="card"><div class="k">League free $ / spots</div><div class="v">${F.usd(freeCap)} / ${F.int(freeSpots)}</div></div>
    </div>
    <form class="bar" id="sale"><input id="sp" list="avail" placeholder="Log a sale: player…" class="w-name" required>
      <datalist id="avail">${avail.map((p) => `<option value="${esc(label(p))}">`).join("")}</datalist>
      <select id="st">${teams.map((t) => `<option ${t.team === myTeam ? "selected" : ""}>${esc(t.team)}</option>`).join("")}</select>
      <input id="sx" type="number" min="1" step="1" placeholder="$" class="w-min" required><button>Log sale</button>
      <span class="count" id="smsg"></span></form>
    ${sales.length ? `<details class="info log"><summary>${sales.length} sale${sales.length > 1 ? "s" : ""} logged since the last re-price</summary><ul>${[...sales].reverse().map((s) =>
      `<li>${esc(byId.get(s.id)?.name ?? s.id)} → ${esc(s.team)} ${F.usd(s.price)} <button class="mv" data-undo="${esc(s.id)}">Undo</button></li>`).join("")}</ul></details>` : ""}
    <h3 class="lh">Targets <span>${Object.keys(targets).length}</span></h3><div id="tgt"></div>
    <h3 class="lh">Available (${season})</h3>
    <div class="bar"><input type="search" id="aq" placeholder="Search players…" value="${esc(aview.q)}">
      <select id="avp"><option value="">All positions</option>${vposes.map((v) => `<option ${v === aview.vpos ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
    <p class="count" id="acount"></p><div id="atbl"></div></div>`;

  const star = (x) => `<button class="mv" data-star="${esc(x.playerid)}" aria-label="Toggle target">${Object.hasOwn(targets, x.playerid) ? "★" : "☆"}</button>`;
  const valueCols = [
    { k: "base_value", label: "Base $", num: true, f: (x) => F.usd(x.base_value) },
    { k: "league_value", label: "League $", num: true, f: (x) => F.usd(x.league_value) },
    { k: "mkt", label: "Market $", num: true, f: (x) => F.usd(x.mkt) },
  ];
  const status = (x) => (sold.has(x.playerid) ? `Sold · ${esc(sold.get(x.playerid).team)} ${F.usd(sold.get(x.playerid).price)}`
    : x.owner === "FA" ? "Available" : `Owned · ${esc(x.owner)}`);
  const tgtCols = [
    { k: "star", label: "", f: star },
    { k: "name", label: "Player", f: (x) => `${playerLink(x)} <span class="pp">${esc(x.pos)}</span>` },
    { k: "mv", label: "Model $", num: true, f: (x) => `<b>${F.usd(x.mv)}</b>` },
    ...valueCols,
    { k: "max", label: "Max bid", num: true, f: (x) => `<input type="number" min="1" step="1" class="w-bid" data-max="${esc(x.playerid)}" value="${esc(targets[x.playerid] ?? num(x.mv) ?? "")}">` },
    { k: "status", label: "Status", f: status },
  ];
  const tsort = { k: "mv", dir: -1 };
  const drawTargets = () => {
    const rows = Object.keys(targets).map((id) => byId.get(id)).filter(Boolean).map(withVals);
    $("#tgt").innerHTML = rows.length ? tableHtml(tgtCols, sortRows(rows, tsort), tsort) : '<p class="empty">Star a player below to add him.</p>';
    wireTable($("#tgt"), tsort, drawTargets);
  };
  const draw = () => {
    const q = aview.q.toLowerCase();
    const rows = avail.filter((p) => (!q || p.name.toLowerCase().includes(q)) && (!aview.vpos || p.vpos === aview.vpos));
    const cols = [{ k: "star", label: "", f: star },
      { k: "name", label: "Player", f: playerLink }, { k: "pos", label: "Pos", f: (x) => F.txt(x.pos) },
      { k: "age", label: "Age", num: true, f: (x) => F.int(x.age) }, { k: "pts", label: "Proj Pts", num: true, f: (x) => F.pts(x.pts) },
      { k: "mv", label: "Model $", num: true, f: (x) => `<b>${F.usd(x.mv)}</b>` }, ...valueCols];
    $("#acount").textContent = `${rows.length} of ${avail.length} available`;
    $("#atbl").innerHTML = tableHtml(cols, sortRows(rows, aview.sort), aview.sort);
    wireTable($("#atbl"), aview.sort, draw);
  };
  $("#focus").onclick = (e) => {
    const b = e.target.closest("button[data-star]");
    if (b) {
      const id = b.dataset.star;
      if (Object.hasOwn(targets, id)) delete targets[id]; else targets[id] = null;
      store.set("targets", targets); auction(); return;
    }
    const u = e.target.closest("button[data-undo]");
    if (u) { store.set("sales", sales.filter((s) => s.id !== u.dataset.undo)); auction(); }
  };
  $("#focus").onchange = (e) => {
    const id = e.target.dataset?.max;
    if (id) { targets[id] = e.target.value === "" ? null : Number(e.target.value); store.set("targets", targets); }
  };
  $("#sale").onsubmit = (e) => {
    e.preventDefault();
    const id = byLabel.get($("#sp").value), price = Number($("#sx").value);
    if (!id) { $("#smsg").textContent = "Pick a player from the list."; return; }
    if (!Number.isInteger(price) || price < 1) { $("#smsg").textContent = "Price must be a whole dollar amount, $1 or more."; return; }
    store.set("sales", [...sales, { id, team: $("#st").value, price }]);
    auction();
  };
  $("#reprice").onclick = async () => {
    $("#reprice").disabled = true; $("#rpmsg").textContent = "Re-pricing…";
    try {
      const res = await fetch("/api/reprice", { method: "POST", headers: { "X-Ottoneu": "1" } }).then((x) => x.json());
      if (!res.ok) { $("#rpmsg").innerHTML = `<span class="neg">Engine run failed.</span><pre>${esc(res.log)}</pre>`; $("#reprice").disabled = false; return; }
      await load(); auction();
    } catch (err) { $("#rpmsg").innerHTML = `<span class="neg">Re-price failed: ${esc(err.message)}</span>`; $("#reprice").disabled = false; }
  };
  $("#aq").oninput = (e) => { aview.q = e.target.value; draw(); };
  $("#avp").onchange = (e) => { aview.vpos = e.target.value; draw(); };
  drawTargets(); draw();
}

// ---- Trades: side-by-side packages, compared on the engine's keeper figures. No verdict: there is no
// trade-value model yet (UI_FUTURE_DEV Phase 4), so the page shows the numbers and leaves the call to you. ----
const tview = { partner: null, give: [], get: [], loanOut: 0, loanIn: 0 };
function trades() {
  if (!myTeam) { $("#focus").innerHTML = '<div class="panel">Choose My Team above.</div>'; return; }
  const pool = phasePool(), season = phaseSeason(), byId = new Map(pool.map((p) => [p.playerid, p]));
  const others = teams.filter((t) => t.team !== myTeam);
  if (!others.some((t) => t.team === tview.partner)) { tview.partner = others[0]?.team ?? null; tview.get = []; }
  // Drop picks that no longer sit on the right roster (a refresh moved them, or My Team changed).
  tview.give = tview.give.filter((id) => byId.get(id)?.owner === myTeam);
  tview.get = tview.get.filter((id) => byId.get(id)?.owner === tview.partner);
  const give = tview.give.map((id) => byId.get(id)), get = tview.get.map((id) => byId.get(id));
  const sum = (a, k) => a.reduce((s, p) => s + (p[k] ?? 0), 0);
  const me = teams.find((t) => t.team === myTeam), them = teams.find((t) => t.team === tview.partner);

  const side = (who, list, ids, owner) => {
    const left = pool.filter((p) => p.owner === owner && !ids.includes(p.playerid)).sort((a, b) => (b.keeper_npv ?? -1) - (a.keeper_npv ?? -1));
    const rows = list.map((p) => `<tr><td>${playerLink(p)} <span class="pp">${esc(p.pos)}</span></td><td class="num">${F.usd(p.salary)}</td>
      <td class="num">${F.usd(p.base_value)}</td><td class="num">${F.npv(p.keeper_npv)}</td>
      <td><button class="mv" data-rm="${who}" data-id="${esc(p.playerid)}" aria-label="Remove">✕</button></td></tr>`).join("");
    return `<div class="col"><h3 class="lh">${who === "give" ? "You give" : "You get"} <span>${esc(owner ?? "—")}</span></h3>
      <select data-add="${who}"><option value="">Add a player…</option>${left.map((p) =>
        `<option value="${esc(p.playerid)}">${esc(p.name)} · ${esc(p.pos)} · ${F.usd(p.salary).replace(/<[^>]+>/g, "")}</option>`).join("")}</select>
      ${list.length ? `<div class="wrap"><table><thead><tr><th>Player</th><th class="num">Salary</th><th class="num">${season} value</th><th class="num">NPV</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table></div>` : '<p class="empty">No players yet.</p>'}
      <label class="loan">Cap loan ${who === "give" ? "you send" : "you receive"} $<input type="number" min="0" step="1" class="w-bid" data-loan="${who === "give" ? "loanOut" : "loanIn"}" value="${who === "give" ? tview.loanOut : tview.loanIn}"></label></div>`;
  };

  // Net = what you get minus what you give. For salary, lower is better, so its colour flips.
  const net = (k, flip) => { const v = sum(get, k) - sum(give, k); if (k === "keeper_npv") return F.npv(v); return flip ? F.sgn(v).replace(/class="(pos|neg)"/, (m, c) => `class="${c === "pos" ? "neg" : "pos"}"`) : F.sgn(v); };
  const line = (label, k, fmt, flip) => `<tr><td>${label}</td><td class="num">${fmt(sum(give, k))}</td><td class="num">${fmt(sum(get, k))}</td><td class="num">${net(k, flip)}</td></tr>`;
  // This season's cap room, as Ottoneu enforces it today: teams.csv cap_space, moved by the salaries and loans in the deal.
  const salOut = sum(give, "salary"), salIn = sum(get, "salary");
  const after = (t, out, inn, loanSent, loanGot) => (t?.cap_space == null ? null : t.cap_space + out - inn - loanSent + loanGot);
  const myCap = after(me, salOut, salIn, tview.loanOut, tview.loanIn), theirCap = after(them, salIn, salOut, tview.loanIn, tview.loanOut);
  const myRoster = me ? me.players - give.length + get.length : null, theirRoster = them ? them.players - get.length + give.length : null;
  const capCell = (v) => (v == null ? nil : v < 0 ? `<span class="neg">${F.usd(v)} (over cap)</span>` : F.usd(v));
  const rosterCell = (n, t) => (n == null ? nil : n > t.roster_max ? `<span class="neg">${n} / ${t.roster_max} (over max)</span>` : `${n} / ${t.roster_max}`);

  $("#focus").innerHTML = `<div class="panel"><h2>Trades</h2>
    <p class="sub">Does this trade make my team better? Build both sides, then compare. A traded player keeps his salary, so what he is worth <i>above</i> that salary is what changes hands: <b>Keeper NPV</b> (surplus over the next four seasons) is the best single number here. There is no trade-value model yet, so the page shows the numbers but makes no accept/decline call.</p>
    <div class="bar"><label>Trade with <select id="partner">${others.map((t) => `<option ${t.team === tview.partner ? "selected" : ""}>${esc(t.team)}</option>`).join("")}</select></label>
      <button id="treset">Clear trade</button></div>
    <div class="two">${side("give", give, tview.give, myTeam)}${side("get", get, tview.get, tview.partner)}</div>
    <h3 class="lh">Comparison (${season})</h3>
    <div class="wrap"><table><thead><tr><th></th><th class="num">You give</th><th class="num">You get</th><th class="num">Net for you</th></tr></thead><tbody>
      <tr><td>Players</td><td class="num">${give.length}</td><td class="num">${get.length}</td><td class="num">${get.length - give.length > 0 ? "+" : ""}${get.length - give.length}</td></tr>
      ${line("Keeper NPV", "keeper_npv", F.npv)}
      ${line(`${season} value`, "base_value", F.usd)}
      ${line("Surplus (value − next salary)", "keeper_surplus", F.sgn)}
      ${line("Salary now", "salary", F.usd, true)}
      ${line("Next salary", "keeper_salary", F.usd, true)}
    </tbody></table></div>
    <h3 class="lh">After the trade (this season, as Ottoneu counts it now)</h3>
    <div class="wrap"><table><thead><tr><th></th><th class="num">${esc(myTeam)}</th><th class="num">${esc(tview.partner ?? "—")}</th></tr></thead><tbody>
      <tr><td>Cap room</td><td class="num">${capCell(myCap)}</td><td class="num">${capCell(theirCap)}</td></tr>
      <tr><td>Roster</td><td class="num">${rosterCell(myRoster, me)}</td><td class="num">${rosterCell(theirRoster, them)}</td></tr>
      <tr><td>Positions out → in</td><td colspan="2">${give.map((p) => esc(p.pos)).join(", ") || "—"} → ${get.map((p) => esc(p.pos)).join(", ") || "—"}</td></tr>
    </tbody></table></div>
    <p class="sub">Cap loans move this season's cap room only and are not counted in the value rows.</p></div>`;

  $("#partner").onchange = (e) => { tview.partner = e.target.value; tview.get = []; trades(); };
  $("#treset").onclick = () => { Object.assign(tview, { give: [], get: [], loanOut: 0, loanIn: 0 }); trades(); };
  $("#focus").onchange = (e) => {
    const add = e.target.dataset?.add, loan = e.target.dataset?.loan;
    if (add && e.target.value) { tview[add].push(e.target.value); trades(); }
    if (loan) { tview[loan] = Math.max(0, Number(e.target.value) || 0); trades(); }
  };
  $("#focus").onclick = (e) => {
    const rm = e.target.closest("button[data-rm]");
    if (rm) { tview[rm.dataset.rm] = tview[rm.dataset.rm].filter((id) => id !== rm.dataset.id); trades(); }
  };
  $("#focus").querySelectorAll("a[data-id]").forEach((a) => (a.onclick = () => openDrawer(a.dataset.id)));
}

// ---- Player drawer (shared) ----
function openDrawer(id) {
  const p = players.find((x) => x.playerid === id);
  if (!p) return;
  // Keeper figures follow the Keepers page: next season's output when it exists.
  const k = keeperPool().find((x) => x.playerid === id) ?? p, ks = k === p ? league.season : keeperSeason();
  const row = (a, b) => `<div class="row"><span>${a}</span><b>${b}</b></div>`;
  $("#drawer").innerHTML = `<button class="x" id="close">Close</button><h2>${esc(p.name)}</h2>
    <p class="sub">${esc(p.mlb)} · ${esc(p.pos)}${p.vpos && p.vpos !== p.pos ? " (priced as " + esc(p.vpos) + ")" : ""} · Age ${F.int(p.age)}</p>
    <h3>${league.season} projection</h3>${row("Projected points", F.pts(p.pts))}${row("Points above replacement", F.pts(p.par))}
    <h3>${league.season} valuation</h3>${row("Base value", F.usd(p.base_value))}${row("League value", F.usd(p.league_value))}${row("Surplus (base − salary)", F.sgn(p.surplus))}${row("Market (cross-league avg)", F.usd(market[p.playerid]))}
    <h3>Keeper (${ks})</h3>${row("Current salary", F.usd(p.salary))}${row("Next salary", F.usd(k.keeper_salary))}${row("Arbitration", F.usd(k.arb))}
      ${row(`${ks} value`, F.usd(k.base_value))}${row("Surplus (value − next salary)", F.sgn(k.keeper_surplus))}${row("Keeper NPV", F.npv(k.keeper_npv))}
    <h3>League</h3>${row("Owner", F.txt(p.owner))}`;
  $("#drawer").classList.add("open");
  $("#close").onclick = () => $("#drawer").classList.remove("open");
}

// ---- Placeholders: model outputs that don't exist yet are never faked ----
const pending = (title, q, need) => () => {
  $("#focus").innerHTML = `<div class="panel"><h2>${title}</h2><p class="sub">${q}</p>
    <p><b>Not yet implemented.</b> Needs: ${need}</p></div>`;
};
// key -> question, accent class, focus view, and what a not-yet-built card is waiting on
const NEED = {
  Lineup: "the short-horizon lineup engine: per-start points, floor, ceiling, confidence, recommendation.",
};
// `in` = the phases a page belongs to; the board and router show only the current phase's pages.
const PAGES = {
  Keepers: { q: "Who should I keep?", c: "keep", run: keepers, in: ["pre"] },
  Auction: { q: "How high should I bid?", c: "auct", run: auction, in: ["pre"] },
  Rankings: { q: "Who should I target?", c: "rank", run: rankings, in: ["pre", "post"] },
  Trades: { q: "Does this trade improve my team?", c: "trade", run: trades, in: ["pre", "post"] },
  Lineup: { q: "Who should I start?", c: "line", run: pending("Lineup", "Which starts and hitters should I use?", NEED.Lineup), in: ["post"] },
};
const inPhase = (name) => Object.hasOwn(PAGES, name) && PAGES[name].in.includes(phase);

// ---- Board: one glance per decision; a card opens its full view ----
const bar = (v, max) => `<span class="bar-v"><i style="width:${Math.max(0, Math.min(100, ((v ?? 0) / (max || 1)) * 100))}%"></i></span>`;
function glance(rows, valKey, fmt) {
  const max = Math.max(...rows.map((r) => r[valKey] ?? 0), 1);
  return `<ol class="glance">${rows.map((r) => `<li><a data-id="${esc(r.playerid)}">${esc(r.name)}</a><span class="pp">${esc(r.pos)}</span>${bar(r[valKey], max)}<b>${fmt(r[valKey])}</b></li>`).join("")}</ol>`;
}
// ---- League breakdown: my team against every team, on the phase's season ----
const POS_ORDER = ["C", "1B", "2B", "SS", "3B", "OF", "SP", "RP"];
const ord = (n) => n + ([11, 12, 13].includes(n % 100) ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] ?? "th");
function leagueTable() {
  // Pre-draft: next season, every current player assumed kept (other teams' cuts are unknown). Post-draft: this season.
  const pre = phase === "pre", pool = phasePool();
  return teams.map((t) => {
    const r = pool.filter((p) => p.owner === t.team), s = (k) => r.reduce((a, p) => a + (p[k] ?? 0), 0);
    const pos = Object.fromEntries(POS_ORDER.map((v) => [v, r.filter((p) => p.vpos === v).reduce((a, p) => a + (p.base_value ?? 0), 0)]));
    return { team: t.team, value: s("base_value"), salary: s(pre ? "keeper_salary" : "salary"),
      surplus: s(pre ? "keeper_surplus" : "surplus"), npv: s("keeper_npv"), pos };
  });
}
function breakdown() {
  const rows = leagueTable(), mine = rows.find((r) => r.team === myTeam);
  if (!mine) return "";
  const pre = phase === "pre", n = rows.length;
  const rankOf = (k, get = (r) => r[k]) => 1 + rows.filter((r) => get(r) > get(mine)).length;
  // One card per metric: my level, rank, gap to the league average (all 12 teams), and what it's made of.
  const stand = (label, k, fmt, note) => {
    const avg = rows.reduce((a, r) => a + (r[k] ?? 0), 0) / n, d = fmt === F.npv ? F.npv : F.sgn;
    return `<div class="card"><div class="k">${label}</div><div class="v">${fmt(mine[k])} <span class="lr">${ord(rankOf(k))} of ${n}</span></div>
      <div class="note">${d(mine[k] - avg)} vs league avg ${fmt(avg)}</div><div class="note">${note}</div></div>`;
  };
  // Position grid: value on each position, teams sorted by total value. Shade = rank within the column.
  const sorted = [...rows].sort((a, b) => b.value - a.value);
  const colRank = (r, v) => 1 + rows.filter((o) => o.pos[v] > r.pos[v]).length;
  const cell = (r, v) => { const k = colRank(r, v), a = Math.round(6 + 52 * (n - k) / Math.max(n - 1, 1));
    return `<td class="num" style="background:color-mix(in srgb, var(--accent) ${a}%, transparent)" title="${esc(r.team)} · ${v}: $${Math.round(r.pos[v])} (${ord(k)} of ${n})">${F.usd(r.pos[v])}</td>`; };
  const posRanks = POS_ORDER.map((v) => [v, colRank(mine, v)]).sort((a, b) => a[1] - b[1]);
  const best = posRanks.slice(0, 2).map(([v, k]) => `${v} (${ord(k)})`).join(", "), worst = posRanks.slice(-2).reverse().map(([v, k]) => `${v} (${ord(k)})`).join(", ");
  return `<section class="panel league-bd"><h2>${esc(myTeam)} vs the league <span class="pp">${phaseSeason()}${pre ? " · every current player assumed kept" : ""}</span></h2>
    <p class="sub">Rank 1st = highest of ${n} teams. Hover a grid cell for the team.</p>
    <div class="cards">
      ${stand("Roster value", "value", F.usd, `made of ${F.usd(mine.salary)} ${pre ? "next " : ""}salary and ${F.sgn(mine.surplus)} surplus`)}
      ${stand("Surplus", "surplus", F.sgn, pre ? "value − next salary, all rostered players before cuts (the top row counts only your keepers)" : "value − salary")}
      ${pre ? stand("Keeper NPV", "npv", F.npv, "four-season surplus; bad contracts count as cut ($0)") : ""}
    </div>
    <h3 class="lh">Value by position <span>strongest ${best} · weakest ${worst}</span></h3>
    <div class="wrap"><table class="heat"><thead><tr><th>Team</th><th class="num">Total</th>${POS_ORDER.map((v) => `<th class="num">${v}</th>`).join("")}</tr></thead>
      <tbody>${sorted.map((r) => `<tr class="${r.team === myTeam ? "me" : ""}"><td>${esc(r.team)}</td><td class="num">${F.usd(r.value)}</td>${POS_ORDER.map((v) => cell(r, v)).join("")}</tr>`).join("")}</tbody></table></div>
  </section>`;
}

function board() {
  const dec = store.get("dec:" + myTeam, {});
  const roster = keeperPool().filter((p) => p.owner === myTeam);
  const k = roster.filter((p) => !isCut(p, dec));
  const sum = (a, key) => a.reduce((s, p) => s + (p[key] ?? 0), 0);
  const me = teams.find((t) => t.team === myTeam), mine = players.filter((p) => p.owner === myTeam);
  const vit = phase === "pre" ? [
    ["Cap room after keepers", league.cap == null ? nil : F.usd(league.cap - sum(k, "keeper_salary"))],
    ["Kept", `${k.length} / ${league.roster_max ?? "—"}`],
    [`${keeperSeason()} surplus, your keepers`, F.sgn(sum(k, "keeper_surplus"))],
    ["Cutting", String(roster.filter((p) => isCut(p, dec)).length)],
  ] : [  // in season: what Ottoneu enforces today (teams.csv), and this season's surplus
    ["Cap room", F.usd(me?.cap_space)],
    ["Roster", me ? `${me.players} / ${me.roster_max}` : nil],
    [`${league.season} surplus`, F.sgn(sum(mine, "surplus"))],
    ["Open spots", F.int(me?.open_spots)],
  ];
  const top = (arr, key) => sortRows(arr.filter((p) => p[key] != null), { k: key, dir: -1 }).slice(0, 3);
  const card = (name, body, foot) => !inPhase(name) ? "" : `<section class="tile c-${PAGES[name].c}" data-go="${name}" tabindex="0" role="link" aria-label="Open ${name}">
    <header><span class="dot"></span><h2>${name}</h2></header><p class="q">${PAGES[name].q}</p>${body}<footer>${foot}</footer></section>`;
  const soon = (name) => !inPhase(name) ? "" : `<section class="tile soon c-${PAGES[name].c}"><header><span class="dot"></span><h2>${name}</h2><em>coming</em></header>
    <p class="q">${PAGES[name].q}</p><p class="need">Needs ${NEED[name]}</p></section>`;
  $("#main").innerHTML = `<div class="vitals"><div class="team"><span class="k">My team</span><b>${esc(myTeam ?? "—")}</b></div>
      ${vit.map(([a, b]) => `<div class="vital"><span class="k">${a}</span><b>${b}</b></div>`).join("")}</div>
    <div class="grid mini">
      ${card("Keepers", `<p class="cap">Top keeper NPV on your roster (${keeperSeason()})</p>` + glance(top(roster, "keeper_npv"), "keeper_npv", F.npv), "Open Keepers →")}
      ${card("Rankings", `<p class="cap">Best available players by base $ (${phaseSeason()})</p>` + glance(top(phasePool().filter((p) => p.owner === "FA"), "base_value"), "base_value", F.usd), "Open Rankings →")}
      ${card("Trades", `<p class="cap">Compare two packages on keeper NPV, value, salary and cap room</p>`, "Open Trades →")}${soon("Lineup")}
    </div>
    ${breakdown()}`;
  document.querySelectorAll(".tile[data-go]").forEach((t) => {
    const go = () => { location.hash = t.dataset.go; };
    t.onclick = (e) => { if (!e.target.closest("a[data-id]")) go(); };
    t.onkeydown = (e) => { if (e.key === "Enter") go(); };
  });
  document.querySelectorAll(".glance a[data-id]").forEach((a) => (a.onclick = () => openDrawer(a.dataset.id)));
}

function route() {
  const name = location.hash.slice(1);
  $("#drawer").classList.remove("open");
  document.body.classList.toggle("fit", name === "Keepers");
  document.querySelectorAll("#phase button").forEach((b) => b.classList.toggle("on", b.dataset.phase === phase));
  if (!inPhase(name)) { $("#main").innerHTML = ""; board(); return; }
  $("#main").innerHTML = `<div class="focus c-${PAGES[name].c}"><a class="back" href="#">← Board</a><div id="focus"></div></div>`;
  PAGES[name].run();
}
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if ($("#drawer").classList.contains("open")) $("#drawer").classList.remove("open"); else if (location.hash) location.hash = "";
});

async function load() {
  [players, teams, league] = await Promise.all(["players", "teams", "league"].map((n) => fetch("/api/" + n).then((r) => r.json())));
  market = await fetch("/api/market").then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  // Optional: absent (no next_season.py run, or an older app.py) means this-season views only.
  playersNext = await fetch("/api/players_next").then((r) => (r.ok ? r.json() : [])).catch(() => []);
}
// ---- Update from Ottoneu: app.py pulls rosters, team caps and market values, checks them and reruns the engine ----
async function runUpdate() {
  const btn = $("#updbtn"), box = $("#upd");
  btn.disabled = true; box.hidden = false; document.body.classList.add("busy");
  box.innerHTML = `<button class="x" id="updx" hidden>Close</button><h2>Update from Ottoneu</h2>
    <p id="updmsg">Pulling rosters, team caps and market values, then rerunning the engine. This takes about half a minute…</p>
    <progress id="updbar" max="100" value="0"></progress>`;
  $("#updx").onclick = () => { box.hidden = true; };
  // ponytail: /api/update is one blocking request, so the bar is time-based (eases toward 95% over ~30s), not real progress.
  const bar = $("#updbar"), tick = setInterval(() => { bar.value += (95 - bar.value) * 0.03; }, 250);
  try {
    const res = await fetch("/api/update", { method: "POST", headers: { "X-Ottoneu": "1" } }).then((r) => r.json());
    $("#updmsg").innerHTML = `<span class="${res.ok ? "pos" : "neg"}">${esc(res.msg)}</span>`;
    if (res.ok) { await load(); route(); }
  } catch (e) {
    $("#updmsg").innerHTML = `<span class="neg">Update failed: ${esc(e.message)}. Is app.py running (and restarted since this button was added)?</span>`;
  }
  clearInterval(tick); bar.value = 100; $("#updx").hidden = false;
  document.body.classList.remove("busy"); btn.disabled = false;
}

async function init() {
  $("#updbtn").onclick = runUpdate;
  await load();
  if (!teams.some((t) => t.team === myTeam)) myTeam = teams[0]?.team ?? null;
  $("#team").innerHTML = teams.map((t) => `<option ${t.team === myTeam ? "selected" : ""}>${esc(t.team)}</option>`).join("");
  $("#team").onchange = (e) => { myTeam = e.target.value; store.set("team", myTeam); route(); };
  document.querySelectorAll("#phase button").forEach((b) => (b.onclick = () => {
    phase = b.dataset.phase; store.set("phase", phase);
    if (!inPhase(location.hash.slice(1))) history.replaceState(null, "", "#");  // a page outside the new phase falls back to the board
    route();
  }));
  window.onhashchange = route;
  route();
}
init().catch((e) => { $("#main").innerHTML = `<div class="panel neg">Could not load data: ${esc(e.message)}. Is app.py running?</div>`; });
