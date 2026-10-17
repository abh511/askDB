// AskDB web UI: plain JavaScript, talks only to the FastAPI backend (POST /ask, GET /health).

const EXAMPLES = {
  "Revenue": [
    "Which 5 product categories earned the most revenue in 2017?",
    "What was the revenue in each month of 2018?",
    "Which 5 customer states generated the most revenue?",
  ],
  "Customers": [
    "How many repeat customers are there?",
    "Which 10 cities have the most unique customers?",
  ],
  "Delivery": [
    "What share of delivered orders arrived late, per year?",
    "Which 5 states have the longest average delivery time?",
  ],
  "Reviews & payments": [
    "What is the average review score for each order status?",
    "How many orders were paid with each payment type?",
  ],
  "Safety demo": [
    "Delete all orders from 2016",
  ],
};

const HISTORY_KEY = "askdb.history";
const THEME_KEY = "askdb.theme";
const $ = (id) => document.getElementById(id);

let current = null;      // the result being shown
let chartType = "table"; // what the chart switch has selected

// ---------- small helpers ----------
function storageGet(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function storageSet(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode: fine */ }
}
function isNumber(v) { return typeof v === "number" && Number.isFinite(v); }
function formatValue(v) {
  if (v === null || v === undefined) return "—";
  if (isNumber(v)) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return String(v);
}
function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

// ---------- theme ----------
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  storageSet(THEME_KEY, theme);
  if (current) renderChart();
}
$("theme-toggle").addEventListener("click", () =>
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
applyTheme(storageGet(THEME_KEY,
  window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));

// ---------- health ----------
async function checkHealth() {
  const el = $("health");
  try {
    const data = await (await fetch("/health")).json();
    const ok = data.status === "ok";
    el.textContent = ok ? "● connected" : "● database unavailable";
    el.className = "health " + (ok ? "ok" : "bad");
  } catch {
    el.textContent = "● API unreachable";
    el.className = "health bad";
  }
}

// ---------- examples + history ----------
function renderExamples() {
  const box = $("examples");
  for (const [group, questions] of Object.entries(EXAMPLES)) {
    const wrap = document.createElement("div");
    wrap.className = "example-group";
    wrap.innerHTML = `<h4>${group}</h4>`;
    for (const q of questions) {
      const b = document.createElement("button");
      b.className = "chip";
      b.textContent = q;
      b.addEventListener("click", () => { $("question").value = q; ask(q); });
      wrap.appendChild(b);
    }
    box.appendChild(wrap);
  }
}

function renderHistory() {
  const list = $("history");
  list.innerHTML = "";
  const items = storageGet(HISTORY_KEY, []);
  if (!items.length) {
    list.innerHTML = `<li class="muted" style="cursor:default">Your questions will appear here.</li>`;
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="dot ${item.status}"></span><span></span>`;
    li.lastChild.textContent = item.question;
    li.title = "Show this result again";
    li.addEventListener("click", () => { $("question").value = item.question; showResult(item); });
    list.appendChild(li);
  }
}

function addToHistory(result) {
  const items = storageGet(HISTORY_KEY, []).filter((i) => i.question !== result.question);
  items.unshift(result);
  storageSet(HISTORY_KEY, items.slice(0, 20));
  renderHistory();
}
$("clear-history").addEventListener("click", () => { storageSet(HISTORY_KEY, []); renderHistory(); });

// ---------- asking ----------
async function ask(question) {
  question = question.trim();
  if (question.length < 3) return;
  $("ask-btn").disabled = true;
  $("welcome").hidden = true;
  $("result").hidden = true;
  $("loading").hidden = false;
  const started = Date.now();
  const timer = setInterval(() => { $("elapsed").textContent = Math.round((Date.now() - started) / 1000); }, 250);
  try {
    const resp = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (!resp.ok) throw new Error(`API returned ${resp.status}`);
    const result = await resp.json();
    addToHistory(result);
    showResult(result);
  } catch (err) {
    showResult({ question, status: "failed", reason: `Could not reach the AskDB API: ${err.message}`,
      sql: null, columns: [], rows: [], chart: { type: "table" }, answer: null, attempts: 0, latency_ms: 0 });
  } finally {
    clearInterval(timer);
    $("elapsed").textContent = "0";
    $("loading").hidden = true;
    $("ask-btn").disabled = false;
  }
}

$("ask-form").addEventListener("submit", (e) => { e.preventDefault(); ask($("question").value); });
$("question").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask($("question").value); }
});

// ---------- showing a result ----------
const STATUS_TEXT = { ok: "answered", blocked: "blocked", failed: "failed" };

function showResult(result) {
  current = result;
  $("welcome").hidden = true;
  $("result").hidden = false;

  const badge = $("status-badge");
  badge.className = "badge " + result.status;
  badge.textContent = STATUS_TEXT[result.status] ?? result.status;
  const attempts = result.attempts === 1 ? "1 attempt" : `${result.attempts} attempts`;
  $("meta").textContent = `${attempts} · ${(result.latency_ms / 1000).toFixed(1)} s`;

  const fallback = {
    ok: "Done.",
    blocked: "This query was blocked by the safety guard. AskDB only runs read-only SELECT queries.",
    failed: "AskDB could not answer this question.",
  };
  $("answer").textContent = result.answer || fallback[result.status] || "";
  $("reason").hidden = !result.reason;
  $("reason").textContent = result.reason || "";

  $("sql").textContent = result.sql || "(no SQL)";
  $("data-cards").hidden = result.status !== "ok";
  if (result.status === "ok") {
    chartType = result.chart?.type || "table";
    renderTable(result.columns, result.rows);
    updateChartSwitch();
    renderChart();
  }
}

// ---------- table ----------
let sortState = { col: null, asc: true };

function renderTable(columns, rows) {
  const table = $("table");
  $("row-count").textContent = `(${rows.length} row${rows.length === 1 ? "" : "s"}${rows.length === 500 ? ", capped" : ""})`;
  const numeric = columns.map((_, i) => rows.length > 0 && rows.every((r) => r[i] === null || isNumber(r[i])));
  const head = "<thead><tr>" + columns.map((c, i) =>
    `<th data-i="${i}">${escapeHtml(c)}${sortState.col === i ? (sortState.asc ? " ▲" : " ▼") : ""}</th>`).join("") + "</tr></thead>";
  const body = "<tbody>" + rows.map((r) => "<tr>" + r.map((v, i) =>
    `<td class="${numeric[i] ? "num" : ""}">${escapeHtml(formatValue(v))}</td>`).join("") + "</tr>").join("") + "</tbody>";
  table.innerHTML = head + body;
  table.querySelectorAll("th").forEach((th) => th.addEventListener("click", () => sortBy(Number(th.dataset.i))));
}

function sortBy(i) {
  sortState = { col: i, asc: sortState.col === i ? !sortState.asc : true };
  const dir = sortState.asc ? 1 : -1;
  const rows = [...current.rows].sort((a, b) => {
    if (a[i] === b[i]) return 0;
    if (a[i] === null) return 1;
    if (b[i] === null) return -1;
    return (a[i] > b[i] ? 1 : -1) * dir;
  });
  renderTable(current.columns, rows);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

$("download-csv").addEventListener("click", () => {
  if (!current) return;
  const cell = (v) => (v === null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const csv = [current.columns, ...current.rows].map((r) => r.map(cell).join(",")).join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = "askdb_result.csv";
  a.click();
  URL.revokeObjectURL(a.href);
});

$("copy-sql").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("sql").textContent);
    $("copy-sql").textContent = "copied";
    setTimeout(() => ($("copy-sql").textContent = "copy"), 1200);
  } catch { /* clipboard blocked: ignore */ }
});

// ---------- chart ----------
// The API picks the chart by rules (date -> line, text + number -> bar). The user can switch,
// but only to chart types that make sense for the columns.
function chartAxes() {
  const { columns, rows, chart } = current;
  if (chart?.x && chart?.y) return { x: chart.x, y: chart.y };
  if (columns.length < 2 || rows.length < 2) return null;
  const yIndex = columns.findIndex((_, i) => rows.every((r) => r[i] === null || isNumber(r[i])));
  if (yIndex < 0) return null;
  const xIndex = columns.findIndex((_, i) => i !== yIndex);
  return { x: columns[xIndex], y: columns[yIndex] };
}

function updateChartSwitch() {
  const possible = chartAxes() !== null;
  document.querySelectorAll("#chart-switch button").forEach((b) => {
    b.disabled = b.dataset.type !== "table" && !possible;
    b.classList.toggle("active", b.dataset.type === chartType);
  });
}
document.querySelectorAll("#chart-switch button").forEach((b) =>
  b.addEventListener("click", () => { chartType = b.dataset.type; updateChartSwitch(); renderChart(); }));

function renderChart() {
  const el = $("chart");
  const axes = chartAxes();
  if (window.Plotly) Plotly.purge(el);
  const show = chartType !== "table" && axes && window.Plotly;
  el.hidden = !show;
  $("no-chart").hidden = !!show;
  if (!show) return;

  const xi = current.columns.indexOf(axes.x);
  const yi = current.columns.indexOf(axes.y);
  let rows = current.rows;
  if (chartType === "line") rows = [...rows].sort((a, b) => (a[xi] > b[xi] ? 1 : -1));
  const x = rows.map((r) => r[xi]);
  const y = rows.map((r) => r[yi]);
  // long category names read better as horizontal bars
  const horizontal = chartType === "bar" && (rows.length > 8 || x.some((v) => String(v).length > 14));

  const trace = chartType === "line"
    ? { type: "scatter", mode: "lines+markers", x, y, line: { color: cssVar("--accent"), width: 2 } }
    : horizontal
      ? { type: "bar", orientation: "h", x: y, y: x.map(String), marker: { color: cssVar("--accent") } }
      : { type: "bar", x: x.map(String), y, marker: { color: cssVar("--accent") } };

  Plotly.newPlot(el, [trace], {
    margin: { l: horizontal ? 150 : 60, r: 16, t: 8, b: 48 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: cssVar("--text"), family: cssVar("--font"), size: 12 },
    // the category axis needs no title: its labels already say what it is
    xaxis: { title: { text: horizontal ? axes.y : axes.x }, gridcolor: cssVar("--border"), automargin: true },
    yaxis: { title: { text: horizontal ? "" : axes.y }, gridcolor: cssVar("--border"), automargin: true,
             autorange: horizontal ? "reversed" : true },
  }, { displayModeBar: false, responsive: true });
}

// ---------- start ----------
renderExamples();
renderHistory();
checkHealth();
