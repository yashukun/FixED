/* ===========================================================
   FixED Dashboard — data + rendering
   Three features: Search/Ask · Question-paper generation · Viva
   =========================================================== */

const $ = (s, r = document) => r.querySelector(s);
const fmt = n => n.toLocaleString("en-US");

const CH = {
  indigo: "var(--c-indigo)", cyan: "var(--c-cyan)", green: "var(--c-green)",
  amber: "var(--c-amber)", rose: "var(--c-rose)",
};

/* ---------- Sample data (30 days) ---------- */
const DAYS = 30;
function seedSeries(base, vol, trend, floor = 0) {
  const out = []; let v = base;
  for (let i = 0; i < DAYS; i++) {
    v += (Math.sin(i / 3.1) * vol * 0.4) + (Math.random() - 0.45) * vol + trend;
    out.push(Math.max(floor, Math.round(v)));
  }
  return out;
}
const today = new Date(2026, 4, 30);
const dates = Array.from({ length: DAYS }, (_, i) => {
  const d = new Date(today); d.setDate(today.getDate() - (DAYS - 1 - i)); return d;
});

/* The three real features → the three trend series */
const SERIES = {
  searches: seedSeries(38, 12, 0.7, 4),
  papers:   seedSeries(3.2, 2.2, 0.06, 0),
  vivas:    seedSeries(1.3, 1.3, 0.02, 0),
};
const SERIES_META = {
  searches: { label: "Searches & questions", color: CH.indigo, fmt: fmt },
  papers:   { label: "Question papers",      color: CH.green,  fmt: fmt },
  vivas:    { label: "Viva sessions",         color: CH.cyan,   fmt: fmt },
};

/* ---------- KPIs ---------- */
const KPIS = [
  { lab: "Books in library", val: "21", unit: "", delta: +3, deltaUnit: "new", ctx: "3 processing", icon: "book",
    color: CH.cyan, spark: seedSeries(12, 2, 0.32, 1) },
  { lab: "Searches asked", val: "1,240", unit: "", delta: +18, deltaUnit: "%", ctx: "this month", icon: "search",
    color: CH.indigo, spark: SERIES.searches },
  { lab: "Question papers", val: "47", unit: "", delta: +12, deltaUnit: "%", ctx: "generated", icon: "doc",
    color: CH.green, spark: seedSeries(20, 5, 0.2, 1) },
  { lab: "Vivas completed", val: "12", unit: "", delta: +3, deltaUnit: "new", ctx: "video tests", icon: "mic",
    color: CH.amber, spark: SERIES.vivas },
];

/* ---------- Breakdowns ---------- */
/* Activity by book — which uploaded books get queried most */
const BOOKS_USE = [
  { nm: "Physics — HC Verma", val: 34, color: CH.indigo },
  { nm: "Calculus, Vol II",   val: 24, color: CH.cyan },
  { nm: "Organic Chemistry",  val: 18, color: CH.green },
  { nm: "Genetics & Evolution", val: 14, color: CH.amber },
  { nm: "Modern History",     val: 10, color: CH.rose },
];
/* Feature usage split */
const FEATURES = [
  { nm: "Search & Ask", val: 58, color: CH.indigo },
  { nm: "Question-paper generation", val: 27, color: CH.green },
  { nm: "Viva (video test)", val: 15, color: CH.cyan },
];

/* ---------- Library (book processing states) ---------- */
const LIBRARY = [
  { nm: "Physics — HC Verma", meta: "Vol I & II · 1,042 pp", state: "Ready", cls: "b-good", color: CH.indigo, pages: 1042 },
  { nm: "Calculus, Vol II", meta: "412 pp · 9 chapters", state: "Ready", cls: "b-good", color: CH.cyan, pages: 412 },
  { nm: "Organic Chemistry", meta: "366 pp · indexing 72%", state: "Processing", cls: "b-warn", color: CH.green, pages: 366 },
  { nm: "Inorganic Chemistry", meta: "298 pp · in queue", state: "Queued", cls: "b-info", color: CH.amber, pages: 298 },
];

/* ---------- Recent activity feed ---------- */
const FEED = [
  { ico: "search", c: CH.indigo, title: "“Explain Carnot efficiency with an example”", meta: "Search · Physics — HC Verma", when: "12 min ago", chip: ["Answered", "b-good"] },
  { ico: "doc", c: CH.green, title: "Mock paper — Organic Chemistry", meta: "Generate · 60 marks · all selected books", when: "1h ago", chip: ["Ready", "b-good"] },
  { ico: "mic", c: CH.amber, title: "Viva — Thermodynamics", meta: "Video test · 8 questions · 18 min", when: "Today 9:20 AM", chip: ["Scored 88", "b-info"] },
  { ico: "book", c: CH.cyan, title: "“Organic Chemistry” uploaded", meta: "366 pages · indexing 72%", when: "2h ago", chip: ["Processing", "b-warn"] },
];

/* ---------- Recent question papers ---------- */
const PAPERS = [
  { title: "Organic Chemistry — Mock", scope: "1 book", marks: 60, q: 25, date: "May 28", status: ["Ready", "b-good"] },
  { title: "Mechanics — Unit Test", scope: "Physics — HC Verma", marks: 40, q: 18, date: "May 26", status: ["Ready", "b-good"] },
  { title: "Full Syllabus — Term", scope: "All books", marks: 100, q: 40, date: "May 24", status: ["Ready", "b-good"] },
  { title: "Calculus — Practice Set", scope: "Calculus, Vol II", marks: 35, q: 15, date: "May 22", status: ["Draft", "b-warn"] },
];

/* ---------- Recent vivas ---------- */
const VIVAS = [
  { subj: "Thermodynamics", date: "May 28", q: "8/8", score: 88, dur: "18m", status: ["Passed", "b-good"] },
  { subj: "Organic Chemistry", date: "May 26", q: "10/10", score: 74, dur: "22m", status: ["Passed", "b-good"] },
  { subj: "Linear Algebra", date: "May 24", q: "6/8", score: 59, dur: "16m", status: ["Review", "b-warn"] },
];

/* ===========================================================
   Icons
   =========================================================== */
const ICONS = {
  grid: '<path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/>',
  book: '<path d="M4 5a2 2 0 0 1 2-2h11a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1H6a2 2 0 0 1-2-2zM8 3v18"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5zM3 13l9 5 9-5"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  doc: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h6"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  up: '<path d="M7 14l5-5 5 5"/>',
  down: '<path d="M7 10l5 5 5-5"/>',
  bolt: '<path d="M13 2 4 14h6l-1 8 9-12h-6z"/>',
  cam: '<path d="M3 7a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM15 10l6-3v10l-6-3"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5M5 20h14"/>',
  play: '<path d="M8 5v14l11-7z"/>',
};
function icon(name, stroke = true) {
  return `<svg viewBox="0 0 24 24" fill="${stroke ? "none" : "currentColor"}" stroke="${stroke ? "currentColor" : "none"}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ""}</svg>`;
}

/* ===========================================================
   Sparkline
   =========================================================== */
function sparkline(data, color) {
  const w = 220, h = 38, n = data.length;
  const mn = Math.min(...data), mx = Math.max(...data);
  const rng = mx - mn || 1;
  const pts = data.map((v, i) => [ (i / (n - 1)) * w, h - 4 - ((v - mn) / rng) * (h - 8) ]);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const area = line + ` L${w} ${h} L0 ${h} Z`;
  const id = "sg" + Math.random().toString(36).slice(2, 7);
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${color}" stop-opacity="0.28"/>
      <stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
    <path d="${area}" fill="url(#${id})"/>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}

/* ===========================================================
   Main trend chart (interactive)
   =========================================================== */
let curSeries = "searches";
let curRange = 14;

function renderTrend() {
  const meta = SERIES_META[curSeries];
  const full = SERIES[curSeries];
  const data = full.slice(full.length - curRange);
  const ds = dates.slice(dates.length - curRange);
  const W = 860, H = 300, padL = 52, padR = 16, padT = 16, padB = 34;
  const iw = W - padL - padR, ih = H - padT - padB;
  const mx = Math.max(...data) * 1.12 || 1, mn = 0;
  const x = i => padL + (i / (data.length - 1)) * iw;
  const y = v => padT + ih - ((v - mn) / (mx - mn || 1)) * ih;

  const ticks = 4; let grid = "", ylab = "";
  for (let t = 0; t <= ticks; t++) {
    const gy = padT + (ih / ticks) * t;
    const gv = mx - (mx / ticks) * t;
    grid += `<line x1="${padL}" y1="${gy.toFixed(1)}" x2="${W - padR}" y2="${gy.toFixed(1)}" stroke="var(--border)"/>`;
    ylab += `<text x="${padL - 10}" y="${(gy + 4).toFixed(1)}" text-anchor="end" class="ax">${shortNum(gv)}</text>`;
  }
  let xlab = ""; const step = Math.max(1, Math.round(data.length / 6));
  for (let i = 0; i < data.length; i += step) {
    xlab += `<text x="${x(i).toFixed(1)}" y="${H - 10}" text-anchor="middle" class="ax">${ds[i].toLocaleDateString("en-US",{month:"short",day:"numeric"})}</text>`;
  }

  const pts = data.map((v, i) => [x(i), y(v)]);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const area = line + ` L${x(data.length - 1).toFixed(1)} ${padT + ih} L${padL} ${padT + ih} Z`;

  const dots = pts.map((p, i) =>
    `<circle class="hp" data-i="${i}" cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="4" fill="${meta.color}" stroke="var(--bg)" stroke-width="2" opacity="0"/>`).join("");
  const hot = pts.map((p, i) =>
    `<rect class="hot" data-i="${i}" x="${(x(i) - iw / data.length / 2).toFixed(1)}" y="${padT}" width="${(iw / data.length).toFixed(1)}" height="${ih}" fill="transparent"/>`).join("");

  $("#trend").innerHTML = `<svg viewBox="0 0 ${W} ${H}" id="trendSvg">
    <defs><linearGradient id="ta" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${meta.color}" stop-opacity="0.30"/>
      <stop offset="1" stop-color="${meta.color}" stop-opacity="0"/></linearGradient></defs>
    <style>.ax{fill:var(--faint);font-size:11px;font-family:var(--mono)}</style>
    ${grid}${ylab}${xlab}
    <path d="${area}" fill="url(#ta)"/>
    <path d="${line}" fill="none" stroke="${meta.color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
    <line id="vline" x1="0" y1="${padT}" x2="0" y2="${padT + ih}" stroke="${meta.color}" stroke-opacity="0.4" stroke-dasharray="3 4" opacity="0"/>
    ${dots}${hot}
  </svg>`;

  const tip = $("#trendTip"), svg = $("#trendSvg"), vline = $("#vline");
  const dotsEl = [...svg.querySelectorAll(".hp")];
  svg.querySelectorAll(".hot").forEach(r => {
    r.addEventListener("mouseenter", () => {
      const i = +r.dataset.i; const p = pts[i];
      dotsEl.forEach(d => d.setAttribute("opacity", d.dataset.i == i ? "1" : "0"));
      vline.setAttribute("x1", p[0]); vline.setAttribute("x2", p[0]); vline.setAttribute("opacity", "1");
      tip.style.left = (p[0] / W * 100) + "%";
      tip.style.top = (p[1] / H * 100) + "%";
      tip.innerHTML = `<div class="tip-d">${ds[i].toLocaleDateString("en-US",{weekday:"short",month:"short",day:"numeric"})}</div>
        <div class="tip-r"><i style="background:${meta.color}"></i>${meta.label}: <b>${meta.fmt(data[i])}</b></div>`;
      tip.style.opacity = "1";
    });
  });
  svg.addEventListener("mouseleave", () => {
    tip.style.opacity = "0"; vline.setAttribute("opacity", "0");
    dotsEl.forEach(d => d.setAttribute("opacity", "0"));
  });

  const tot = data.reduce((a, b) => a + b, 0);
  const prev = full.slice(full.length - curRange * 2, full.length - curRange).reduce((a, b) => a + b, 0) || tot;
  const pct = ((tot - prev) / prev * 100);
  $("#trendTotal").textContent = fmt(tot);
  const dd = $("#trendDelta");
  dd.className = "delta " + (pct >= 0 ? "up" : "down");
  dd.innerHTML = icon(pct >= 0 ? "up" : "down") + Math.abs(pct).toFixed(1) + "%";
}
function shortNum(v) {
  if (v >= 1000) return (v / 1000).toFixed(v >= 10000 ? 0 : 1) + "k";
  return Math.round(v);
}

/* ===========================================================
   Donut — activity by book
   =========================================================== */
function renderDonut() {
  const total = BOOKS_USE.reduce((a, b) => a + b.val, 0);
  const r = 58, cx = 70, cy = 70, c = 2 * Math.PI * r;
  let off = 0, arcs = "";
  BOOKS_USE.forEach(s => {
    const len = (s.val / total) * c;
    arcs += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${s.color}" stroke-width="16"
      stroke-dasharray="${len.toFixed(2)} ${(c - len).toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}"
      transform="rotate(-90 ${cx} ${cy})"/>`;
    off += len;
  });
  $("#donut").innerHTML = `
    <div class="ring-c" style="width:140px;height:140px;position:relative">
      <svg viewBox="0 0 140 140" style="width:140px;height:140px">
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="oklch(1 0 0 / 0.05)" stroke-width="16"/>
        ${arcs}
      </svg>
      <div class="donut-center"><div><div class="big">${fmt(1240)}</div><div class="sm">searches</div></div></div>
    </div>
    <div class="donut-legend">
      ${BOOKS_USE.map(s => `<div class="dl-row"><i style="background:${s.color}"></i><span class="nm">${s.nm}</span><span class="vl">${Math.round(s.val/total*100)}%</span></div>`).join("")}
    </div>`;
}

/* ===========================================================
   Feature usage bars
   =========================================================== */
function renderBars() {
  const mx = Math.max(...FEATURES.map(s => s.val));
  $("#bars").innerHTML = FEATURES.map(s => `
    <div class="bar-row">
      <div class="bl"><span class="nm">${s.nm}</span><span class="vl">${s.val}%</span></div>
      <div class="track"><div class="fill" style="width:${s.val / mx * 100}%;background:${s.color}"></div></div>
    </div>`).join("");
}

/* ===========================================================
   Library (book processing states)
   =========================================================== */
function renderLibrary() {
  $("#library").innerHTML = LIBRARY.map(b => `
    <div class="lib-book">
      <div class="lib-spine" style="background:${b.color}"></div>
      <div class="lib-ico" style="color:${b.color}">${icon("book")}</div>
      <div class="lib-body">
        <div class="lib-nm">${b.nm}</div>
        <div class="lib-meta">${b.meta}</div>
      </div>
      <span class="badge ${b.cls}">${b.state}</span>
    </div>`).join("");
}

/* ===========================================================
   Feed + tables
   =========================================================== */
function renderFeed() {
  $("#feed").innerHTML = FEED.map(f => `
    <div class="feed-item">
      <div class="feed-dot" style="background:color-mix(in oklch, ${f.c} 16%, transparent);color:${f.c}">${icon(f.ico)}</div>
      <div class="feed-body">
        <div class="feed-title">${f.title}</div>
        <div class="feed-meta">${f.meta}</div>
      </div>
      <div style="text-align:right;display:flex;flex-direction:column;gap:6px;align-items:flex-end">
        <span class="chip ${f.chip[1]}">${f.chip[0]}</span>
        <span class="feed-when">${f.when}</span>
      </div>
    </div>`).join("");
}
function renderPapers() {
  $("#paperBody").innerHTML = PAPERS.map(p => `
    <tr>
      <td class="subj">${p.title}</td>
      <td style="color:var(--muted)">${p.scope}</td>
      <td style="font-family:var(--mono);color:var(--muted)">${p.marks}</td>
      <td style="font-family:var(--mono);color:var(--muted)">${p.q}</td>
      <td style="color:var(--muted);font-family:var(--mono);font-size:12.5px">${p.date}</td>
      <td><span class="badge ${p.status[1]}">${p.status[0]}</span></td>
    </tr>`).join("");
}
function renderVivaList() {
  $("#vivaList").innerHTML = VIVAS.map(v => `
    <div class="vrow">
      <div>
        <div class="vrow-nm">${v.subj}</div>
        <div class="vrow-meta">${v.date} · ${v.q} · ${v.dur}</div>
      </div>
      <div class="vrow-right">
        <span class="score" style="color:${v.score>=75?'var(--good)':v.score>=60?'var(--warn)':'var(--bad)'}">${v.score}<span style="color:var(--faint);font-weight:400">/100</span></span>
        <span class="badge ${v.status[1]}">${v.status[0]}</span>
      </div>
    </div>`).join("");
}

/* ===========================================================
   KPIs
   =========================================================== */
function renderKpis() {
  $("#kpis").innerHTML = KPIS.map(k => {
    const dcls = k.delta > 0 ? "up" : k.delta < 0 ? "down" : "flat";
    const dico = k.delta > 0 ? "up" : k.delta < 0 ? "down" : "";
    const dsuffix = k.deltaUnit === "%" ? "%" : " " + k.deltaUnit;
    return `<div class="card kpi">
      <div class="kpi-top">
        <div class="icobox" style="background:color-mix(in oklch, ${k.color} 16%, transparent);color:${k.color}">${icon(k.icon)}</div>
        <span class="lab">${k.lab}</span>
      </div>
      <div>
        <div class="kpi-val">${k.val}<small>${k.unit}</small></div>
        <div class="kpi-foot" style="margin-top:8px">
          <span class="delta ${dcls}">${dico?icon(dico):""}${Math.abs(k.delta)}${dsuffix}</span>
          <span class="ctx">${k.ctx}</span>
        </div>
      </div>
      ${sparkline(k.spark, k.color)}
    </div>`;
  }).join("");
}

/* ===========================================================
   Init + interactions
   =========================================================== */
function initNav() {
  document.querySelectorAll(".nav-item").forEach(n => {
    n.addEventListener("click", e => {
      e.preventDefault();
      document.querySelectorAll(".nav-item").forEach(x => x.classList.remove("active"));
      n.classList.add("active");
    });
  });
}
function initToolbar() {
  $("#seriesSeg").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    $("#seriesSeg").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    curSeries = b.dataset.s; renderTrend();
  });
  $("#rangeSeg").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    $("#rangeSeg").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    curRange = +b.dataset.r; renderTrend();
    $("#rangeNote").textContent = "Last " + curRange + " days · updated just now";
  });
}

function boot() {
  renderKpis();
  renderTrend();
  renderDonut();
  renderBars();
  renderLibrary();
  renderFeed();
  renderPapers();
  renderVivaList();
  initNav();
  initToolbar();
}
document.addEventListener("DOMContentLoaded", boot);
