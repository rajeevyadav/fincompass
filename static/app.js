"use strict";

const CONSENT_KEY = "fincompass_consent_v2";
const WATCH_KEY = "fincompass_watchlist_v2";
const SETTINGS_KEY = "fincompass_settings_v3";
const TRAINING_SETTINGS_KEY = "fincompass_training_settings_v4";
const REALTIME_SETTINGS_KEY = "fincompass_realtime_settings_v4";
const EXPERIENCE_MODE_KEY = "fincompass_experience_mode_v1";
const volatileStorage = new Map();

// --- Plain-language tooltips for jargon metric labels ---------------------
const METRIC_TOOLTIPS = {
  "Locked-test Brier skill": "How much better the model's probabilities are than a naive baseline, measured on unseen 'locked' test data. 0% = no better than the baseline; higher is better.",
  "Locked-test ROC AUC": "How well the model ranks outperformers above underperformers. 0.5 = a coin flip; 1.0 = perfect ranking.",
  "Calibration error": "How closely the stated probabilities match what actually happens. Lower is better; 5% means predictions are off by about 5 percentage points on average.",
  "Model uncertainty range": "The plausible range for this probability, combining statistical uncertainty and disagreement between the component models.",
  "90% score interval": "The range expected to contain the true evidence score about 90% of the time.",
  "P(score ≥ 8)": "The estimated chance the 0-10 evidence score is 8 or higher.",
  "Evidence coverage": "How much of the needed underlying data was actually available for this assessment.",
  "Metric completeness": "The share of individual metrics that had usable data.",
  "Frozen anchor": "The validated forecast probability from the locked model. It does not change between retrainings.",
  "Adaptive candidate": "A provisional probability that reacts to fresh information. It is only APPLIED if the adaptive gate has passed.",
  "Gate": "The safety check that decides whether the adaptive adjustment is trustworthy enough to apply. 'warming' means there is not enough evidence yet.",
  "Validated anchors": "Number of forecast models that have passed validation and can be used for live forecasts.",
  "Adaptive artifacts": "Number of stored adaptive-learning states.",
  "Realtime engine": "Version identifier of the live / adaptive engine.",
  "Forecast engine": "Version identifier of the forecasting engine.",
  "Active tier": "Validation level of the currently active model (fixture_only, validated_research, or validated_market).",
  "Usable models": "Forecast models currently eligible to produce live forecasts.",
  "Market-validated": "Models validated against real market data with survivorship / delisting controls.",
  "Pending labels": "Live observations waiting for their forecast horizon to finish before the model can learn from them.",
  "Pending observation": "Whether the current view has queued an observation for later learning.",
};
function applyMetricTooltips() {
  try {
    document.querySelectorAll(".k-label").forEach((el) => {
      if (el.dataset.tipDone) return;
      const tip = METRIC_TOOLTIPS[el.textContent.trim()];
      if (tip) { el.title = tip; el.classList.add("has-tip"); }
      el.dataset.tipDone = "1";
    });
  } catch (_) {}
}
if (typeof document !== "undefined" && document.addEventListener) {
  document.addEventListener("DOMContentLoaded", () => {
    applyMetricTooltips();
    try {
      const obs = new MutationObserver(() => { window.requestAnimationFrame(applyMetricTooltips); });
      obs.observe(document.body, { childList: true, subtree: true });
    } catch (_) {}
  });
}

const state = {
  universe: [],
  screenerRows: [],
  sortKey: "composite",
  sortDir: "desc",
  charts: new Map(),
  selectedSuggestion: -1,
  refreshTimer: null,
  methodLoaded: false,
  forecastStatusLoaded: false,
  settingsLoaded: false,
  liveStatusLoaded: false,
  liveTimer: null,
  forecastRegistry: null,
  modelLabRecipes: [],
  modelLabRecommended: null,
  modelLabRecommendedReason: "",
  modelBuildRunning: false,
};

const $ = (id) => document.getElementById(id);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const num = (v, fallback = 0) => Number.isFinite(Number(v)) ? Number(v) : fallback;
const pct = (v, digits = 0) => `${(num(v) * 100).toFixed(digits)}%`;
const pctRange = (range, fallback) => Array.isArray(range) && range.length >= 2 ? `${pct(range[0])}–${pct(range[1])}` : pct(fallback);
const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[ch]));
const scoreClass = (score) => num(score) >= 8 ? "label-strong" : num(score) >= 6 ? "label-acceptable" : "label-weak";
const confidenceClass = (c) => `confidence-${String(c || "low").toLowerCase()}`;
const formatCap = (v) => {
  const n = num(v, NaN);
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return `$${n.toLocaleString()}`;
};

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {"Accept": "application/json", ...(options.headers || {})}, ...options});
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === "object" && payload ? (payload.detail || payload.message || payload.error) : payload;
    const err = new Error(message || `Request failed (${response.status})`);
    err.status = response.status;
    err.payload = payload;
    throw err;
  }
  return payload;
}

function storageGet(key, fallback = null) {
  try {
    const value = window.localStorage.getItem(key);
    return value ?? volatileStorage.get(key) ?? fallback;
  } catch (_) {
    return volatileStorage.get(key) ?? fallback;
  }
}

function pushPrefToServer(key, value) {
  try { fetch("/api/prefs", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({[key]: value})}).catch(() => {}); } catch (_) {}
}
function seedPrefsFromServer() {
  try {
    fetch("/api/prefs").then((r) => r.json()).then((d) => {
      if (d && typeof d === "object" && !Array.isArray(d)) {
        for (const k in d) {
          try { window.localStorage.setItem(k, d[k]); } catch (_) {}
          volatileStorage.set(k, d[k]);
        }
        try { updateWatchCount(); } catch (_) {}
      }
    }).catch(() => {});
  } catch (_) {}
}
function storageSet(key, value) {
  volatileStorage.set(key, value);
  pushPrefToServer(key, value);
  try { window.localStorage.setItem(key, value); return true; } catch (_) { return false; }
}

function getExperienceMode() {
  const value = String(storageGet(EXPERIENCE_MODE_KEY, "guided") || "guided").toLowerCase();
  return value === "research" ? "research" : "guided";
}

function applyExperienceMode(mode) {
  const resolved = mode === "research" ? "research" : "guided";
  document.body.classList.toggle("mode-guided", resolved === "guided");
  document.body.classList.toggle("mode-research", resolved === "research");
  const select = $("experience-mode");
  if (select) select.value = resolved;
  storageSet(EXPERIENCE_MODE_KEY, resolved);
}

function changeExperienceMode() {
  applyExperienceMode($("experience-mode")?.value || "guided");
}

function getWatchlist() {
  try {
    const data = JSON.parse(storageGet(WATCH_KEY, "[]") || "[]");
    if (!Array.isArray(data)) return [];
    return [...new Set(data.map((x) => String(x).toUpperCase()).filter(Boolean))].slice(0, 50);
  } catch (_) {
    return [];
  }
}

function saveWatchlist(items) {
  storageSet(WATCH_KEY, JSON.stringify(items.slice(0, 50)));
  updateWatchCount();
  renderWatchlist();
}

function toggleWatch(ticker) {
  const symbol = String(ticker || "").trim().toUpperCase();
  if (!symbol) return;
  const items = getWatchlist();
  const i = items.indexOf(symbol);
  if (i >= 0) items.splice(i, 1);
  else items.unshift(symbol);
  saveWatchlist(items);
  syncStarButtons();
}

function updateWatchCount() {
  $("watch-count").textContent = String(getWatchlist().length);
}

function syncStarButtons() {
  const watched = new Set(getWatchlist());
  document.querySelectorAll("[data-watch-toggle]").forEach((button) => {
    const ticker = button.dataset.watchToggle;
    const active = watched.has(ticker);
    button.classList.toggle("active", active);
    button.classList.toggle("starred", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.textContent = active ? "★ Saved" : "☆ Watch";
  });
}

function showPage(page) {
  document.querySelectorAll('[role="tabpanel"]').forEach((panel) => { panel.hidden = panel.id !== `page-${page}`; });
  document.querySelectorAll('[role="tab"]').forEach((tab) => {
    const active = tab.dataset.page === page;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
    tab.tabIndex = active ? 0 : -1;
  });
  if (page === "watchlist") renderWatchlist();
  if (page === "forecast") { if (!state.forecastStatusLoaded) loadForecastStatus(); loadModelLab(); resumeBuildStatus(); }
  if (page === "live") { if (!state.liveStatusLoaded) loadLiveStatus(); scheduleLiveTimer(); } else if (state.liveTimer) { clearInterval(state.liveTimer); state.liveTimer=null; }
  if (page === "settings" && !state.settingsLoaded) loadSettings();
  if (page === "method" && !state.methodLoaded) loadMethodology();
  window.requestAnimationFrame(redrawCharts);
}

function initTabs() {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => showPage(tab.dataset.page));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let next = index;
      if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = tabs.length - 1;
      tabs[next].focus();
      showPage(tabs[next].dataset.page);
    });
  });
}

function initConsent() {
  const gate = $("consent-gate");
  seedPrefsFromServer();
  if (storageGet(CONSENT_KEY) === "accepted") {
    gate.hidden = true;
    return;
  }
  const checkbox = $("consent-checkbox");
  const accept = $("consent-accept");
  checkbox.addEventListener("change", () => {
    accept.disabled = !checkbox.checked;
    accept.setAttribute("aria-disabled", accept.disabled ? "true" : "false");
  });
  accept.addEventListener("click", () => {
    if (!checkbox.checked) return;
    storageSet(CONSENT_KEY, "accepted");
    gate.hidden = true;
    $("ticker").focus();
  });
  window.requestAnimationFrame(() => checkbox.focus());
}

async function loadUniverse() {
  try {
    const data = await api("/api/v1/universe");
    state.universe = Array.isArray(data.entries) ? data.entries : [];
  } catch (_) {
    state.universe = [];
  }
}

function renderSuggestions(query) {
  const box = $("ticker-suggestions");
  const q = String(query || "").trim().toLowerCase();
  if (!q || !state.universe.length) {
    box.hidden = true;
    $("ticker").setAttribute("aria-expanded", "false");
    return;
  }
  const matches = state.universe.filter((e) => String(e.ticker).toLowerCase().startsWith(q) || String(e.name).toLowerCase().includes(q)).slice(0, 8);
  if (!matches.length) {
    box.hidden = true;
    $("ticker").setAttribute("aria-expanded", "false");
    return;
  }
  state.selectedSuggestion = -1;
  box.innerHTML = matches.map((e, i) => `<button type="button" class="suggestion-item" role="option" aria-selected="false" data-suggestion-index="${i}" data-suggestion-ticker="${esc(e.ticker)}"><span class="s-ticker">${esc(e.ticker)}</span><span class="s-name">${esc(e.name)}</span></button>`).join("");
  box.hidden = false;
  $("ticker").setAttribute("aria-expanded", "true");
}

function selectSuggestion(button) {
  if (!button) return;
  $("ticker").value = button.dataset.suggestionTicker || "";
  $("ticker-suggestions").hidden = true;
  $("ticker").setAttribute("aria-expanded", "false");
  state.selectedSuggestion = -1;
}

function initAutocomplete() {
  const input = $("ticker");
  const box = $("ticker-suggestions");
  input.addEventListener("input", () => renderSuggestions(input.value));
  input.addEventListener("keydown", (event) => {
    const items = [...box.querySelectorAll(".suggestion-item")];
    if (box.hidden || !items.length) {
      if (event.key === "Enter") analyze();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      state.selectedSuggestion = event.key === "ArrowDown" ? (state.selectedSuggestion + 1) % items.length : (state.selectedSuggestion - 1 + items.length) % items.length;
      items.forEach((el, i) => {
        const active = i === state.selectedSuggestion;
        el.classList.toggle("active", active);
        el.setAttribute("aria-selected", active ? "true" : "false");
      });
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (state.selectedSuggestion >= 0) selectSuggestion(items[state.selectedSuggestion]);
      analyze();
    }
    if (event.key === "Escape") {
      box.hidden = true;
      input.setAttribute("aria-expanded", "false");
    }
  });
  box.addEventListener("click", (event) => selectSuggestion(event.target.closest("[data-suggestion-ticker]")));
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".search-row-wrap")) {
      box.hidden = true;
      input.setAttribute("aria-expanded", "false");
    }
  });
}

function metricKpis(d) {
  const u = d.uncertainty || {};
  const dq = d.data_quality || {};
  const interval = Array.isArray(u.credible_interval) ? u.credible_interval : [d.composite, d.composite];
  return `
    <div class="kpi-grid">
      <div class="kpi"><div class="k-label">Confidence range</div><div class="k-value">${num(interval[0]).toFixed(2)}–${num(interval[1]).toFixed(2)}</div><div class="k-note">how much the score could vary</div></div>
      <div class="kpi"><div class="k-label">Evidence coverage</div><div class="k-value">${pct(u.evidence_coverage)}</div><div class="k-note">weighted evidence observed</div></div>
      <div class="kpi"><div class="k-label">P(score ≥ 8)</div><div class="k-value">${pctRange(u.probability_strong_score_range, u.probability_strong_score)}</div><div class="k-note">dependence-sensitive range; not returns</div></div>
      <div class="kpi"><div class="k-label">Metric completeness</div><div class="k-value">${pct(dq.metric_completeness)}</div><div class="k-note">${num(dq.metrics_available)}/${num(dq.metrics_expected)} core fields</div></div>
    </div>`;
}

function plainRead(d) {
  const c = num(d.composite);
  const conf = String((d.uncertainty || {}).confidence || "Low");
  const names = {quality: "quality", moat: "durability", safety: "safety", valuation: "valuation", cycle: "cycle"};
  const scored = Object.entries(names)
    .map(([k, label]) => ({ label, v: num(d.pillars?.[k]?.score) }))
    .filter((p) => Number.isFinite(p.v));
  const weakest = scored.length ? scored.reduce((a, b) => (b.v < a.v ? b : a)) : null;
  const strongest = scored.length ? scored.reduce((a, b) => (b.v > a.v ? b : a)) : null;

  const band = c >= 8
    ? "The fundamentals look <strong>strong</strong> overall."
    : c >= 6
      ? "The fundamentals look <strong>mixed</strong> — solid in places, weak in others."
      : "The fundamentals look <strong>weak</strong> overall.";
  const confidence = conf === "High"
    ? "There is plenty of data behind this read."
    : conf === "Medium"
      ? "There is a fair amount of data behind this, but some gaps remain."
      : "There is limited data behind this, so treat it as an early read.";
  const detail = (strongest && weakest && strongest.label !== weakest.label)
    ? ` Strongest area: <strong>${strongest.label}</strong>; weakest: <strong>${weakest.label}</strong>.`
    : "";
  return `
    <div class="plain-read">
      <div class="plain-read-head">In plain terms</div>
      <p>${band} ${confidence}${detail}</p>
      <p class="plain-read-do">This is research, not a buy or sell call. For plain-language pointers on what to look at next, see <strong>Investor Posture</strong> below.</p>
    </div>`;
}

function fmtPrice(v) { const n = num(v); return Number.isFinite(n) && n !== 0 ? `$${n.toFixed(2)}` : "—"; }
function fmtVol(v) {
  const n = num(v);
  if (!Number.isFinite(n) || n <= 0) return "—";
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(Math.round(n));
}

function priceContextHtml(history) {
  const pts = history && Array.isArray(history.points) ? history.points : [];
  if (pts.length < 2) return "";
  const last = pts[pts.length - 1];
  const prev = pts[pts.length - 2];
  const current = num(last.close);
  // 52-week window: points within ~1 year of the latest date.
  const lastDate = new Date(last.date);
  const cutoff = new Date(lastDate); cutoff.setFullYear(cutoff.getFullYear() - 1);
  const yr = pts.filter((p) => new Date(p.date) >= cutoff);
  const highs = yr.map((p) => num(p.high != null ? p.high : p.close));
  const lows = yr.map((p) => num(p.low != null ? p.low : p.close)).filter((x) => x > 0);
  const hi52 = highs.length ? Math.max(...highs) : current;
  const lo52 = lows.length ? Math.min(...lows) : current;
  const prevClose = num(prev.close);
  const chg = prevClose ? (current - prevClose) / prevClose : 0;
  const chgCls = chg > 0 ? "label-strong" : chg < 0 ? "label-weak" : "";
  const sign = chg > 0 ? "+" : "";
  // Position within the 52-week band (0 = at low, 100 = at high).
  const band = hi52 > lo52 ? Math.round(((current - lo52) / (hi52 - lo52)) * 100) : 50;
  return `
    <div class="kpi-grid price-context">
      <div class="kpi"><div class="k-label">Current price</div><div class="k-value">${fmtPrice(current)}</div><div class="k-note ${chgCls}">${sign}${(chg * 100).toFixed(2)}% vs prior close</div></div>
      <div class="kpi"><div class="k-label">52-week high</div><div class="k-value">${fmtPrice(hi52)}</div><div class="k-note">${band}% of 52-week range</div></div>
      <div class="kpi"><div class="k-label">52-week low</div><div class="k-value">${fmtPrice(lo52)}</div><div class="k-note">last close vs yearly band</div></div>
      <div class="kpi"><div class="k-label">Latest volume</div><div class="k-value">${fmtVol(last.volume)}</div><div class="k-note">shares on last session</div></div>
    </div>
    <p class="meta">Price context is informational only — it is not part of the evidence score or a return forecast.</p>`;
}

function pillarHtml(d) {
  const names = {quality: "Quality", moat: "Durability proxy", safety: "Safety", valuation: "Valuation", cycle: "Cycle"};
  return `<div class="pillars">${Object.entries(names).map(([key, name]) => {
    const p = d.pillars?.[key] || {};
    const ci = p.credible_interval_90 || [p.score, p.score];
    return `<div class="pillar"><div class="name">${esc(name)}</div><div class="val ${scoreClass(p.score)}">${num(p.score).toFixed(2)}</div><div class="interval">90% ${num(ci[0]).toFixed(1)}–${num(ci[1]).toFixed(1)} · ${pct(p.evidence_coverage)} evidence</div></div>`;
  }).join("")}</div>`;
}

function postureHtml(d) {
  const p = d.posture || {};
  const items = Array.isArray(p.indicators) ? p.indicators : [];
  if (!items.length) return "";
  const cards = items.map((it) => `
    <div class="posture-item posture-tone-${esc(it.tone || "muted")}">
      <div class="p-label">${esc(it.label || "")}</div>
      <div class="p-value">${esc(it.value || "")}</div>
      <div class="p-desc">${esc(it.description || "")}</div>
    </div>`).join("");
  return `
    <section class="posture">
      <div class="posture-head"><h2>Investor Posture</h2><span class="posture-caption">${esc(p.caption || "")}</span></div>
      <div class="posture-grid">${cards}</div>
    </section>`;
}

function renderAnalysis(d, history) {
  const u = d.uncertainty || {};
  const source = d.source || d.data_quality?.source || "unknown";
  const updated = d.updated_at || d.data_quality?.fetched_at || "—";
  const isWatched = getWatchlist().includes(d.ticker);
  $("analyze-out").innerHTML = `
    <article class="card score-card">
      <div class="score-top">
        <div>
          <h1 class="company-name">${esc(d.name || d.ticker)} <span class="meta">${esc(d.ticker)}</span></h1>
          <div class="meta">${esc(d.sector || "Sector unavailable")}${d.industry ? ` · ${esc(d.industry)}` : ""} · ${formatCap(d.market_cap)}</div>
          <div class="score-hero">
            <span class="score-num ${scoreClass(d.composite)}">${num(d.composite).toFixed(2)}</span><span class="score-denom">/ 10</span>
            <span class="label-chip ${scoreClass(d.composite)}">${esc(d.label)}</span>
            <span class="confidence-chip ${confidenceClass(u.confidence)}">${esc(u.confidence || "Low")} confidence</span>
          </div>
        </div>
        <div class="score-actions">
          <button class="icon-button ${isWatched ? "active" : ""}" data-watch-toggle="${esc(d.ticker)}" aria-pressed="${isWatched ? "true" : "false"}">${isWatched ? "★ Saved" : "☆ Watch"}</button>
          <button class="icon-button" data-print="1" title="Print or save this analysis as PDF">🖨 Print / PDF</button>
        </div>
      </div>
      ${plainRead(d)}
      ${priceContextHtml(history)}
      ${metricKpis(d)}
      ${pillarHtml(d)}
      ${postureHtml(d)}
      <div class="thesis">${esc(String(d.thesis || "").replaceAll("**", ""))}</div>
      <p class="meta">Source: ${esc(source)} · Updated: ${esc(updated)} · Engine: ${esc(d.engine_version)}${d.cached ? " · cached score" : ""}</p>
      <details><summary>Inspect model evidence</summary><pre class="detail">${esc(JSON.stringify({uncertainty: d.uncertainty, data_quality: d.data_quality, pillars: d.pillars}, null, 2))}</pre></details>
    </article>
    <div class="two-col">
      <section class="card chart-card"><h2>Evidence profile</h2><canvas id="analysis-radar" class="chart-canvas chart-sm" role="img" aria-label="Radar chart of five FinCompass evidence pillar scores"></canvas><div class="canvas-note">Durability is a financial proxy, not a direct qualitative moat measurement.</div></section>
      <section class="card chart-card"><h2>${esc(d.ticker)} price context</h2>${history?.points?.length ? '<canvas id="analysis-price" class="chart-canvas chart-sm" role="img" aria-label="Five year closing price line chart"></canvas><div class="canvas-note">Price history is context only and is not used as a return forecast.</div>' : '<div class="empty-state"><span>Price history unavailable.</span></div>'}</section>
    </div>`;
  syncStarButtons();
  registerChart("analysis-radar", () => drawRadar("analysis-radar", d.pillars, d.composite));
  if (history?.points?.length) registerChart("analysis-price", () => drawLine("analysis-price", history.points));
}

async function analyze() {
  const ticker = $("ticker").value.trim().toUpperCase();
  if (!ticker) return;
  $("ticker").value = ticker;
  const out = $("analyze-out");
  out.innerHTML = '<div class="card loading">Analyzing evidence and uncertainty…</div>';
  $("btn-analyze").disabled = true;
  try {
    const [data, history] = await Promise.all([
      api(`/api/v1/analyze/${encodeURIComponent(ticker)}`),
      fetchHistory(ticker),
    ]);
    renderAnalysis(data, history);
  } catch (error) {
    out.innerHTML = `<div class="error">${esc(error.message)}</div>`;
  } finally {
    $("btn-analyze").disabled = false;
  }
}

// Price history for the analysis chart. Guards the chart-period against an
// invalid stored value (which the server rejects with 400) and retries once
// after a brief backoff, since free price providers occasionally throttle a
// request that races the parallel analyze call — the cause of intermittent
// "Price history unavailable".
async function fetchHistory(ticker) {
  const valid = ["1y", "3y", "5y", "10y", "max"];
  let period = getRuntimeSettings().chartPeriod;
  if (!valid.includes(period)) period = "10y";
  const url = `/api/v1/history/${encodeURIComponent(ticker)}?period=${encodeURIComponent(period)}`;
  let h = await api(url).catch(() => null);
  if (!h || !(h.points && h.points.length)) {
    await new Promise((r) => setTimeout(r, 700));
    h = await api(url).catch(() => null);
  }
  return h;
}

function screenerQuery() {
  const q = new URLSearchParams();
  q.set("min_score", String(clamp(num($("min-score").value), 0, 10)));
  const sector = $("sector-filter").value.trim();
  if (sector) q.set("sector", sector);
  q.set("min_coverage", String(clamp(num($("coverage-filter").value), 0, 1)));
  const confidence = $("confidence-filter").value;
  if (confidence) q.set("confidence", confidence);
  q.set("limit", "200");
  return q;
}

function sortedRows() {
  const rows = [...state.screenerRows];
  const key = state.sortKey;
  const dir = state.sortDir === "asc" ? 1 : -1;
  rows.sort((a, b) => {
    const av = a[key]; const bv = b[key];
    if (typeof av === "number" || typeof bv === "number") return (num(av) - num(bv)) * dir;
    return String(av || "").localeCompare(String(bv || "")) * dir;
  });
  return rows;
}

function sortHeader(label, key) {
  const active = state.sortKey === key;
  const arrow = active ? (state.sortDir === "asc" ? " ↑" : " ↓") : "";
  return `<button class="sort-button" data-sort-key="${key}" aria-pressed="${active ? "true" : "false"}">${esc(label)}${arrow}</button>`;
}

function renderScreener() {
  const rows = sortedRows();
  const out = $("screener-out");
  if (!rows.length) {
    out.innerHTML = '<div class="empty-state"><strong>No cached rows match these filters.</strong><span>Refresh source data to populate or rebuild the universe.</span></div>';
    return;
  }
  out.innerHTML = `
    <div class="score-top"><div><strong>${rows.length} companies</strong><div class="meta">Ranked by evidence score and data strength.</div></div><div class="meta">Click a header to sort.</div></div>
    <div class="table-wrap">
      <table><thead><tr>
        <th scope="col">Watch</th><th scope="col">${sortHeader("Ticker", "ticker")}</th><th scope="col">${sortHeader("Score", "composite")}</th><th scope="col">${sortHeader("Confidence", "confidence")}</th><th scope="col">${sortHeader("Evidence", "evidence_coverage")}</th><th scope="col">90% interval</th><th scope="col">Quality</th><th scope="col">Durability</th><th scope="col">Safety</th><th scope="col">Valuation</th><th scope="col">Cycle</th><th scope="col">Sector</th>
      </tr></thead><tbody>
      ${rows.map((r) => {
        const watched = getWatchlist().includes(r.ticker);
        return `<tr><td><button class="table-action ${watched ? "starred" : ""}" data-watch-toggle="${esc(r.ticker)}" aria-pressed="${watched ? "true" : "false"}">${watched ? "★ Saved" : "☆ Watch"}</button></td><td><button class="table-action" data-analyze-ticker="${esc(r.ticker)}">${esc(r.ticker)}</button><div class="meta">${esc(r.name || "")}</div></td><td class="score-cell ${scoreClass(r.composite)}">${num(r.composite).toFixed(2)}</td><td><span class="confidence-chip ${confidenceClass(r.confidence)}">${esc(r.confidence)}</span></td><td><span class="coverage-meter"><progress max="1" value="${clamp(num(r.evidence_coverage),0,1)}">${pct(r.evidence_coverage)}</progress>${pct(r.evidence_coverage)}</span></td><td>${num(r.interval_low).toFixed(2)}–${num(r.interval_high).toFixed(2)}</td><td>${num(r.quality).toFixed(1)}</td><td>${num(r.moat).toFixed(1)}</td><td>${num(r.safety).toFixed(1)}</td><td>${num(r.valuation).toFixed(1)}</td><td>${num(r.cycle).toFixed(1)}</td><td>${esc(r.sector || "—")}</td></tr>`;
      }).join("")}
      </tbody></table>
    </div>
    <div class="card chart-card"><h2>Risk/reward research map</h2><canvas id="screener-scatter" class="chart-canvas" role="img" aria-label="Scatter plot of valuation and quality scores sized by evidence coverage"></canvas><div class="canvas-note">Horizontal: valuation evidence. Vertical: quality evidence. Point size: evidence coverage.</div></div>`;
  syncStarButtons();
  registerChart("screener-scatter", () => drawScatter("screener-scatter", rows));
}

const _knownSectors = new Set();
function populateSectorFilter(rows) {
  const sel = $("sector-filter");
  if (!sel) return;
  (rows || []).forEach((r) => { if (r && r.sector) _knownSectors.add(String(r.sector)); });
  const current = sel.value;
  const opts = ['<option value="">All sectors</option>']
    .concat([..._knownSectors].sort((a, b) => a.localeCompare(b)).map((s) => `<option value="${esc(s)}">${esc(s)}</option>`));
  sel.innerHTML = opts.join("");
  sel.value = current; // preserve selection (empty if it was cleared)
}


async function loadMarketMeta() {
  try {
    const meta = await api("/api/v1/market/meta");
    const sel = $("sector-filter");
    if (sel && Array.isArray(meta.sectors)) {
      const current = sel.value;
      meta.sectors.forEach((name) => { if (name) _knownSectors.add(String(name)); });
      const opts = ['<option value="">All sectors</option>']
        .concat([..._knownSectors].sort((a,b)=>a.localeCompare(b)).map((name)=>`<option value="${esc(name)}">${esc(name)}</option>`));
      sel.innerHTML = opts.join("");
      sel.value = current;
    }
  } catch (_) {}
}

function renderMarketBrowse(data) {
  const out = $("market-browse-out");
  if (!out) return;
  out.hidden = false;
  if (!data || data.available === false) {
    out.innerHTML = `<div class="error"><strong>Broad market discovery is unavailable.</strong><br>${esc(data?.reason || "Market provider unavailable.")} The locally cached FinCompass screener remains available.</div>`;
    return;
  }
  const rows = Array.isArray(data.results) ? data.results : [];
  if (!rows.length) {
    out.innerHTML = '<div class="empty-state"><strong>No companies returned for this market scope.</strong><span>Try another sector or region.</span></div>';
    return;
  }
  out.innerHTML = `
    <div class="score-top"><div><strong>${rows.length} market results</strong><div class="meta">${esc((data.region || "").toUpperCase())}${data.sector ? ` · ${esc(data.sector)}` : ""} · on-demand discovery beyond the starter universe</div></div><div class="meta">Select a ticker to run full FinCompass analysis.</div></div>
    <div class="table-wrap"><table><thead><tr><th>Ticker</th><th>Company</th><th>Sector</th><th>Industry</th><th>Exchange</th><th>Price</th><th>Market cap</th></tr></thead><tbody>
      ${rows.map((r)=>`<tr><td><button class="table-action" data-analyze-ticker="${esc(r.ticker)}">${esc(r.ticker)}</button></td><td>${esc(r.name || "—")}</td><td>${esc(r.sector || "—")}</td><td>${esc(r.industry || "—")}</td><td>${esc(r.exchange || "—")}</td><td>${r.price == null ? "—" : num(r.price).toLocaleString(undefined,{maximumFractionDigits:2})}</td><td>${r.market_cap == null ? "—" : formatCap(r.market_cap)}</td></tr>`).join("")}
    </tbody></table></div>
    <div class="button-row">
      <button class="secondary" data-market-page="${Math.max(0,num(data.offset)-num(data.limit))}" ${num(data.offset)<=0?"disabled":""}>Previous</button>
      <button class="secondary" data-market-page="${num(data.offset)+num(data.limit)}" ${data.has_more?"":"disabled"}>Next</button>
    </div>
    <p class="meta">Provider: ${esc(data.provider || "market provider")}. Showing ${num(data.offset)+1}–${num(data.offset)+rows.length}${data.provider_total != null ? ` of ${esc(data.provider_total)} matching records` : ""}. Use Previous/Next to traverse the provider result set; FinCompass does not impose the 72-name starter list as a market boundary.</p>`;
}

async function browseMarketSector(offset=0) {
  const btn = $("btn-market-browse");
  const out = $("market-browse-out");
  if (!btn || !out) return;
  btn.disabled = true; out.hidden = false; out.innerHTML = '<div class="loading">Searching the selected market scope…</div>';
  const q = new URLSearchParams();
  const sector = $("sector-filter")?.value?.trim();
  const region = $("market-region")?.value?.trim() || "us";
  if (sector) q.set("sector", sector);
  q.set("region", region); q.set("limit", "250"); q.set("offset", String(Math.max(0, Number(offset)||0)));
  try { renderMarketBrowse(await api(`/api/v1/market/search?${q.toString()}`)); }
  catch (error) { out.innerHTML = `<div class="error">${esc(error.message)}</div>`; }
  finally { btn.disabled = false; }
}

async function loadScreener() {
  $("btn-screener").disabled = true;
  $("screener-out").innerHTML = '<div class="loading">Loading cached research universe…</div>';
  try {
    state.screenerRows = await api(`/api/v1/screener?${screenerQuery().toString()}`);
    populateSectorFilter(state.screenerRows);
    renderScreener();
  } catch (error) {
    $("screener-out").innerHTML = `<div class="error">${esc(error.message)}</div>`;
  } finally {
    $("btn-screener").disabled = false;
  }
}

function renderRefreshStatus(status) {
  const panel = $("refresh-panel");
  panel.hidden = false;
  const total = Math.max(1, num(status.total, 1));
  const completed = clamp(num(status.completed), 0, total);
  $("refresh-progress").max = total;
  $("refresh-progress").value = completed;
  const companyTotal = num(status.companies_total, status.total);
  const phaseCompleted = status.phase === "score" ? Math.max(0, completed - companyTotal) : Math.min(completed, companyTotal);
  $("refresh-count").textContent = status.phase === "complete" ? `${companyTotal} companies` : `${phaseCompleted}/${companyTotal}`;
  const phase = status.phase ? ` · ${status.phase}` : "";
  const last = status.last_ticker ? ` · ${status.last_ticker}` : "";
  $("refresh-text").textContent = `${status.status || "unknown"}${phase}${last}`;
}

async function pollRefresh() {
  try {
    const status = await api("/api/v1/screener/status");
    renderRefreshStatus(status);
    if (["complete", "completed", "failed", "error", "idle"].includes(String(status.status || "").toLowerCase())) {
      clearInterval(state.refreshTimer);
      state.refreshTimer = null;
      $("btn-refresh").disabled = false;
      if (["complete", "completed"].includes(String(status.status || "").toLowerCase())) loadScreener();
    }
  } catch (_) {
    clearInterval(state.refreshTimer);
    state.refreshTimer = null;
    $("btn-refresh").disabled = false;
  }
}

async function startRefresh() {
  $("btn-refresh").disabled = true;
  try {
    const status = await api("/api/v1/screener/refresh", {method: "POST"});
    renderRefreshStatus(status);
    if (state.refreshTimer) clearInterval(state.refreshTimer);
    state.refreshTimer = setInterval(pollRefresh, 1800);
    pollRefresh();
  } catch (error) {
    $("btn-refresh").disabled = false;
    $("refresh-panel").hidden = false;
    $("refresh-text").textContent = error.message;
  }
}

function exportScreener() {
  const q = screenerQuery();
  q.delete("limit");
  window.location.assign(`/api/v1/export/screener.csv?${q.toString()}`);
}

async function compare() {
  const tickers = $("compare-tickers").value.split(",").map((x) => x.trim().toUpperCase()).filter(Boolean).slice(0, 10);
  const out = $("compare-out");
  if (!tickers.length) return;
  $("compare-tickers").value = tickers.join(",");
  $("btn-compare").disabled = true;
  out.innerHTML = '<div class="card loading">Comparing evidence distributions…</div>';
  try {
    const data = await api(`/api/v1/compare?tickers=${encodeURIComponent(tickers.join(","))}`);
    const rows = data.results || [];
    if (!rows.length) throw new Error("No comparison results available.");
    out.innerHTML = `
      <div class="card"><div class="table-wrap"><table><thead><tr><th>Ticker</th><th>Score</th><th>Confidence</th><th>Evidence</th><th>90% interval</th><th>Quality</th><th>Durability</th><th>Safety</th><th>Valuation</th><th>Cycle</th></tr></thead><tbody>
      ${rows.map((r) => { const u=r.uncertainty||{}; const ci=u.credible_interval||[r.composite,r.composite]; return `<tr><td><strong>${esc(r.ticker)}</strong><div class="meta">${esc(r.name||"")}</div></td><td class="score-cell ${scoreClass(r.composite)}">${num(r.composite).toFixed(2)}</td><td><span class="confidence-chip ${confidenceClass(u.confidence)}">${esc(u.confidence||"Low")}</span></td><td>${pct(u.evidence_coverage)}</td><td>${num(ci[0]).toFixed(2)}–${num(ci[1]).toFixed(2)}</td><td>${num(r.pillars?.quality?.score).toFixed(1)}</td><td>${num(r.pillars?.moat?.score).toFixed(1)}</td><td>${num(r.pillars?.safety?.score).toFixed(1)}</td><td>${num(r.pillars?.valuation?.score).toFixed(1)}</td><td>${num(r.pillars?.cycle?.score).toFixed(1)}</td></tr>`; }).join("")}
      </tbody></table></div></div>
      <div class="card chart-card"><h2>Pillar comparison</h2><canvas id="compare-bars" class="chart-canvas" role="img" aria-label="Grouped bar chart comparing FinCompass pillar scores"></canvas><div class="canvas-note">Scores are evidence-model outputs, not expected returns.</div></div>`;
    registerChart("compare-bars", () => drawBars("compare-bars", rows));
  } catch (error) {
    out.innerHTML = `<div class="error">${esc(error.message)}</div>`;
  } finally {
    $("btn-compare").disabled = false;
  }
}

function nameForTicker(ticker) {
  return state.universe.find((e) => e.ticker === ticker)?.name || ticker;
}

function renderWatchlist() {
  const out = $("watchlist-out");
  if (!out) return;
  const items = getWatchlist();
  updateWatchCount();
  $("btn-watch-compare").disabled = items.length < 2;
  if (!items.length) {
    out.innerHTML = '<div class="empty-state"><strong>Your watchlist is empty.</strong><span>Use ☆ Watch from an analysis or screener row. It stays only in this browser.</span></div>';
    return;
  }
  const cached = new Map(state.screenerRows.map((r) => [r.ticker, r]));
  out.innerHTML = `<div class="watch-grid">${items.map((ticker) => {
    const r = cached.get(ticker);
    return `<article class="watch-card"><div class="watch-card-top"><div><div class="watch-ticker">${esc(ticker)}</div><div class="watch-name">${esc(nameForTicker(ticker))}</div></div>${r ? `<span class="score-cell ${scoreClass(r.composite)}">${num(r.composite).toFixed(2)}</span>` : ""}</div>${r ? `<div class="meta">${esc(r.confidence)} confidence · ${pct(r.evidence_coverage)} evidence</div>` : '<div class="meta">Load the screener to show cached score.</div>'}<div class="watch-actions"><label class="watch-check"><input type="checkbox" class="watch-select" value="${esc(ticker)}" checked> Compare</label><button class="table-action" data-analyze-ticker="${esc(ticker)}">Analyze</button><button class="table-action starred" data-watch-toggle="${esc(ticker)}" aria-pressed="true">★ Saved</button></div></article>`;
  }).join("")}</div>`;
  syncStarButtons();
}

function compareWatchlist() {
  const boxes = Array.from(document.querySelectorAll(".watch-select"));
  let items = boxes.filter((b) => b.checked).map((b) => b.value);
  if (!items.length) items = getWatchlist();
  items = items.slice(0, 10);
  if (items.length < 2) { alert("Select at least 2 stocks to compare (up to 10)."); return; }
  $("compare-tickers").value = items.join(",");
  showPage("compare");
  compare();
}

async function loadMethodology() {
  const out = $("method-out");
  try {
    const m = await api("/api/v4/methodology");
    state.methodLoaded = true;
    const statLabels = {
      metric_transform: "Continuous metric transforms",
      aggregation: "Bayesian aggregation",
      missing_data: "Missing data",
      peer_model: "Peer model",
      uncertainty: "Uncertainty propagation",
      probability_scope: "Probability scope",
    };
    out.innerHTML = `
      <h1>${esc(m.name)}</h1>
      <p class="meta">App ${esc(m.version)} · engine ${esc(m.engine_version)}</p>
      <div class="notice"><strong>Critical interpretation:</strong> ${esc(m.statistics?.probability_scope || "")}</div>
      <h2>Five evidence pillars</h2>
      <div class="method-grid">${Object.entries(m.pillars || {}).map(([name, v]) => `<div class="method-item"><h3>${esc(name)} · ${pct(v.weight)}</h3><p>${esc(v.focus)}</p></div>`).join("")}</div>
      <h2>Statistical architecture</h2>
      <ul class="method-list">${Object.entries(m.statistics || {}).map(([k,v]) => `<li><strong>${esc(statLabels[k] || k)}:</strong> ${esc(v)}</li>`).join("")}</ul>
      <h2>Evidence score vs forecast</h2>
      <p class="muted">The 0–10 evidence score does not estimate expected return or probability of profit. The separate forecasting engine may estimate a defined forward outperformance event only when a real historical model passes the validation gate recorded in its manifest.</p>
      ${m.forecasting ? `<div class="notice"><strong>Forecast engine:</strong> ${esc(m.forecasting.probability_scope||"")}</div><details><summary>Forecasting validation architecture</summary><pre class="detail">${esc(JSON.stringify(m.forecasting,null,2))}</pre></details>` : ""}${m.realtime ? `<div class="notice"><strong>Adaptive live engine:</strong> ${esc(m.realtime.architecture||"")}</div><details><summary>Realtime governance architecture</summary><pre class="detail">${esc(JSON.stringify(m.realtime,null,2))}</pre></details>` : ""}
      <details><summary>Guardrails and labels</summary><pre class="detail">${esc(JSON.stringify({labels:m.labels, guardrails:m.guardrails, philosophy:m.philosophy, disclaimer:m.disclaimer}, null, 2))}</pre></details>`;
  } catch (error) {
    out.innerHTML = `<div class="error">${esc(error.message)}</div>`;
  }
}

function canvasSetup(id) {
  const canvas = $(id);
  if (!canvas || canvas.offsetParent === null) return null;
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(300, rect.width || 300);
  const height = Math.max(180, rect.height || 260);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  return {ctx, width, height};
}

function colors() {
  const s = getComputedStyle(document.documentElement);
  const get = (name) => s.getPropertyValue(name).trim();
  return {text:get("--text"), muted:get("--muted"), border:get("--border"), accent:get("--accent"), accent2:get("--accent2"), green:get("--green"), amber:get("--amber"), red:get("--red"), surface2:get("--surface2")};
}

function registerChart(id, draw) {
  state.charts.set(id, draw);
  window.requestAnimationFrame(draw);
}

function redrawCharts() {
  state.charts.forEach((draw, id) => { if ($(id)) draw(); else state.charts.delete(id); });
}

function drawRadar(id, pillars, composite) {
  const setup = canvasSetup(id); if (!setup) return;
  const {ctx,width,height}=setup; const c=colors();
  // Colour the shape by the overall score's health so a glance reads good/mixed/weak.
  const comp = num(composite);
  const line = comp >= 8 ? (c.green || "#5fe09b") : comp >= 6 ? (c.amber || "#ffc861") : (c.red || "#ff7b83");
  const fill = comp >= 8 ? "rgba(95,224,155,.18)" : comp >= 6 ? "rgba(255,200,97,.18)" : "rgba(255,123,131,.18)";
  const keys=["quality","moat","safety","valuation","cycle"]; const labels=["Quality","Durability","Safety","Valuation","Cycle"];
  const cx=width/2, cy=height/2+3, radius=Math.min(width,height)*.34;
  ctx.font="12px system-ui"; ctx.textAlign="center"; ctx.textBaseline="middle";
  for (let level=2; level<=10; level+=2) {
    ctx.beginPath();
    keys.forEach((_,i)=>{ const a=-Math.PI/2+i*2*Math.PI/keys.length; const r=radius*level/10; const x=cx+Math.cos(a)*r, y=cy+Math.sin(a)*r; i?ctx.lineTo(x,y):ctx.moveTo(x,y); });
    ctx.closePath(); ctx.strokeStyle=c.border; ctx.lineWidth=1; ctx.stroke();
  }
  keys.forEach((_,i)=>{ const a=-Math.PI/2+i*2*Math.PI/keys.length; ctx.beginPath(); ctx.moveTo(cx,cy); ctx.lineTo(cx+Math.cos(a)*radius,cy+Math.sin(a)*radius); ctx.strokeStyle=c.border; ctx.stroke(); const lr=radius+20; ctx.fillStyle=c.muted; ctx.fillText(labels[i],cx+Math.cos(a)*lr,cy+Math.sin(a)*lr); });
  ctx.beginPath();
  keys.forEach((key,i)=>{ const a=-Math.PI/2+i*2*Math.PI/keys.length; const r=radius*clamp(num(pillars?.[key]?.score),0,10)/10; const x=cx+Math.cos(a)*r,y=cy+Math.sin(a)*r; i?ctx.lineTo(x,y):ctx.moveTo(x,y); });
  ctx.closePath(); ctx.fillStyle=fill; ctx.fill(); ctx.strokeStyle=line; ctx.lineWidth=2.3; ctx.stroke();
}

function drawLine(id, points) {
  const setup=canvasSetup(id); if(!setup) return; const {ctx,width,height}=setup; const c=colors();
  const vals=(points||[]).map((p)=>num(p.close,NaN)).filter(Number.isFinite); if(vals.length<2)return;
  const maxPoints=360, step=Math.max(1,Math.ceil(vals.length/maxPoints)), data=vals.filter((_,i)=>i%step===0 || i===vals.length-1);
  let min=Math.min(...data), max=Math.max(...data); if(max===min){max+=1;min-=1;} const pad={l:48,r:12,t:14,b:26}; const w=width-pad.l-pad.r,h=height-pad.t-pad.b;
  ctx.font="11px system-ui"; ctx.textAlign="right"; ctx.textBaseline="middle";
  for(let i=0;i<=4;i++){const y=pad.t+h*i/4; const v=max-(max-min)*i/4; ctx.strokeStyle=c.border;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(width-pad.r,y);ctx.stroke();ctx.fillStyle=c.muted;ctx.fillText(v.toFixed(0),pad.l-7,y);}
  ctx.beginPath(); data.forEach((v,i)=>{const x=pad.l+w*i/(data.length-1), y=pad.t+h*(max-v)/(max-min); i?ctx.lineTo(x,y):ctx.moveTo(x,y);}); ctx.strokeStyle=c.accent2;ctx.lineWidth=2;ctx.stroke();
  ctx.textAlign="left";ctx.textBaseline="bottom";ctx.fillStyle=c.muted;ctx.fillText("older",pad.l,height-4);ctx.textAlign="right";ctx.fillText("recent",width-pad.r,height-4);
}

function drawScatter(id, rows) {
  const setup=canvasSetup(id); if(!setup) return; const {ctx,width,height}=setup; const c=colors(); const pad={l:42,r:20,t:18,b:38}, w=width-pad.l-pad.r,h=height-pad.t-pad.b;
  ctx.font="11px system-ui";
  for(let i=0;i<=5;i++){const val=i*2,x=pad.l+w*val/10,y=pad.t+h-h*val/10;ctx.strokeStyle=c.border;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,pad.t);ctx.lineTo(x,pad.t+h);ctx.stroke();ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(pad.l+w,y);ctx.stroke();ctx.fillStyle=c.muted;ctx.textAlign="center";ctx.fillText(String(val),x,height-16);ctx.textAlign="right";ctx.fillText(String(val),pad.l-7,y+3);}
  (rows||[]).forEach((r)=>{const x=pad.l+w*clamp(num(r.valuation),0,10)/10, y=pad.t+h-h*clamp(num(r.quality),0,10)/10, rad=3+4*clamp(num(r.evidence_coverage),0,1);ctx.beginPath();ctx.arc(x,y,rad,0,Math.PI*2);ctx.fillStyle=num(r.composite)>=8?c.green:num(r.composite)>=6?c.amber:c.red;ctx.globalAlpha=.72;ctx.fill();ctx.globalAlpha=1;});
  ctx.fillStyle=c.muted;ctx.textAlign="center";ctx.fillText("Valuation evidence →",pad.l+w/2,height-3);ctx.save();ctx.translate(12,pad.t+h/2);ctx.rotate(-Math.PI/2);ctx.fillText("Quality evidence →",0,0);ctx.restore();
}

function drawBars(id, rows) {
  const setup=canvasSetup(id); if(!setup)return; const {ctx,width,height}=setup;const c=colors();const keys=["quality","moat","safety","valuation","cycle"],labels=["Quality","Durability","Safety","Valuation","Cycle"];const pad={l:42,r:14,t:24,b:52},w=width-pad.l-pad.r,h=height-pad.t-pad.b;
  ctx.font="11px system-ui";
  for(let i=0;i<=5;i++){const val=i*2,y=pad.t+h-h*val/10;ctx.strokeStyle=c.border;ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(width-pad.r,y);ctx.stroke();ctx.fillStyle=c.muted;ctx.textAlign="right";ctx.fillText(String(val),pad.l-7,y+3);}
  const groupW=w/keys.length, n=Math.max(1,rows.length), barW=Math.min(18,(groupW*.72)/n); const palette=[c.accent,c.accent2,c.green,c.amber,c.red];
  keys.forEach((key,ki)=>{const center=pad.l+groupW*(ki+.5); rows.forEach((r,ri)=>{const v=clamp(num(r.pillars?.[key]?.score),0,10),bh=h*v/10,x=center-(n*barW)/2+ri*barW,y=pad.t+h-bh;ctx.fillStyle=palette[ri%palette.length];ctx.globalAlpha=.83;ctx.fillRect(x+1,y,Math.max(2,barW-2),bh);ctx.globalAlpha=1;});ctx.fillStyle=c.muted;ctx.textAlign="center";ctx.fillText(labels[ki],center,height-31);});
  rows.forEach((r,ri)=>{const x=pad.l+ri*(Math.min(120,w/Math.max(1,rows.length)))+4;ctx.fillStyle=palette[ri%palette.length];ctx.fillRect(x,height-13,9,9);ctx.fillStyle=c.muted;ctx.textAlign="left";ctx.fillText(r.ticker,x+13,height-5);});
}


function getRuntimeSettings() {
  const defaults = {chartPeriod:"10y", minCoverage:"0", probabilityFormat:"percent", modelId:"", liveRefreshSeconds:"0"};
  try { return {...defaults, ...JSON.parse(storageGet(SETTINGS_KEY, "{}") || "{}")}; } catch (_) { return defaults; }
}

function probabilityText(value) {
  const v = num(value, NaN); if (!Number.isFinite(v)) return "—";
  return getRuntimeSettings().probabilityFormat === "decimal" ? v.toFixed(3) : pct(v, 1);
}

function populateModelSelects(status) {
  const models = Array.isArray(status?.models) ? status.models.filter((m)=>["validated_research","validated_market"].includes(m.validation_tier)) : [];
  [$("forecast-model"), $("live-model"), $("setting-model")].forEach((select)=>{
    if (!select) return;
    const current = select.value;
    select.innerHTML = '<option value="">Active model (default)</option>' + models.map((m)=>{
      const t=m.target||{}; const horizon=t.horizon_months?`${t.horizon_months}M`:`${t.horizon_trading_days||"?"}d`; const tierLabel=FCP.describeModelTier(m.validation_tier).label; const label=`${horizon} vs ${FCP.friendlyBenchmark(t.benchmark)} · ${tierLabel}`;
      return `<option value="${esc(m.model_id)}">${esc(label)}</option>`;
    }).join("");
    select.value = current || getRuntimeSettings().modelId || "";
  });
}

function renderForecastStatus(status) {
  state.forecastRegistry=status; state.forecastStatusLoaded=true; populateModelSelects(status);
  const out=$("forecast-status"); const usable=num(status.usable_models); const market=num(status.market_validated_models);
  const active=String(status.active_model||""); const tier=status.active_tier||"none";
  $("forecast-tier-badge").textContent=active?String(tier).replaceAll("_"," "):"No active model";
  if(!usable){
    out.innerHTML=`<div class="notice"><strong>No validated forecast candidate is installed.</strong> Train a Model Lab recipe from retained local data and inspect the locked-test gates. Candidates that fail remain rejected; the synthetic fixture is never live.</div>`; return;
  }
  const activationNote=active?`Active model: <strong>${esc(active)}</strong>.`:`<strong>${usable} validated candidate${usable===1?"":"s"} available, but none is active.</strong> Review an experiment and explicitly activate an eligible candidate.`;
  out.innerHTML=`<div class="notice">${activationNote}</div><div class="forecast-grid"><div class="kpi"><div class="k-label">Validated candidates</div><div class="k-value">${usable}</div></div><div class="kpi"><div class="k-label">Market-validated</div><div class="k-value">${market}</div></div><div class="kpi"><div class="k-label">Active tier</div><div class="k-value validation-tier">${esc(active?tier.replaceAll("_"," "):"none")}</div></div><div class="kpi"><div class="k-label">Forecast engine</div><div class="k-value">${esc(status.forecast_engine_version||"—")}</div></div></div>`;
}

async function loadForecastStatus(){
  $("forecast-status").innerHTML='<div class="loading">Checking validated model registry…</div>';
  try{const status=await api("/api/v4/forecast/status"); renderForecastStatus(status);}catch(error){$("forecast-status").innerHTML=`<div class="error">${esc(error.message)}</div>`;}
}

function renderBuildStatus(s){
  const box=$("build-status"); if(!box)return;
  const st=String(s.status||"idle");
  state.modelBuildRunning=st==="running";
  if(st==="idle"){ box.hidden=true; renderRecipeReadiness(); return; }
  box.hidden=false;
  const total=num(s.total)||0, done=num(s.completed)||0;
  const pctDone=total?Math.min(100,Math.round(done/total*100)):(st==="complete"?100:0);
  const phase=esc(String(s.phase||"").replaceAll("_"," "));
  if(st==="running"){
    const stages=FCP.describeTrainingStages(s.phase).map((st)=>`<li class="stage stage-${st.state}"><span class="stage-dot" aria-hidden="true"></span>${esc(st.label)}${st.state==="active"?' <span class="stage-now">in progress…</span>':""}</li>`).join("");
    box.innerHTML=`<div class="notice"><strong>Training in progress…</strong></div><ol class="stage-list">${stages}</ol><p class="meta">${esc(s.message||"")}</p><p class="meta">This runs in the background — you can keep using the app; leave this tab open to watch progress.</p>`;
    return;
  }
  if(st==="not_ready"){
    const o=FCP.describeExperimentOutcome("not_ready");
    box.innerHTML=`<div class="notice readiness-strip readiness-needs"><strong>${esc(o.title)}.</strong> ${esc(o.blurb)}</div><p class="meta">${esc(s.message||"")}</p><p class="meta">Use <em>Update missing data</em>, then train.</p>`;
    renderRecipeReadiness();
    return;
  }
  if(st==="failed"){
    const o=FCP.describeExperimentOutcome("failed");
    box.innerHTML=`<div class="error"><strong>${esc(o.title)}.</strong> ${esc(o.blurb)} <span class="meta">${esc(s.message||"")}</span></div>`;
    return;
  }
  // complete
  const usable=!!s.usable;
  const outcome=FCP.describeExperimentOutcome(usable?"validated":"rejected",s.validation_tier,s.failed_gates||[]);
  const reasons=outcome.reasons.length?`<ul class="meta">${outcome.reasons.map((r)=>`<li>${esc(r)}</li>`).join("")}</ul>`:"";
  const rawGates=Array.isArray(s.failed_gates)&&s.failed_gates.length?`<p class="meta advanced-only"><strong>Failed gates:</strong> ${s.failed_gates.map(esc).join(", ")}</p>`:"";
  box.innerHTML=`<div class="notice"><strong>${esc(outcome.title)}.</strong></div><p class="meta">${esc(outcome.blurb)}</p>${reasons}${rawGates}`;
  renderRecipeReadiness();
}

let _researchPollTimer=null;
let _guidedRecipeAfterRefresh=null;

function renderResearchData(d){
  const audit=d?.audit||{}; const refresh=d?.refresh||{}; const rows=num(audit.rows); const covered=num(audit.symbols_with_data);
  const badge=$("research-data-badge"); if(badge)badge.textContent=covered?`${covered} symbols · ${rows.toLocaleString()} rows`:"No seed data";
  const out=$("research-data-status"); if(!out)return;
  const coverage=Array.isArray(audit.coverage)?audit.coverage.filter((x)=>num(x.rows)>0):[];
  const ranges=coverage.slice(0,12).map((x)=>`${esc(x.symbol)}: ${esc(x.earliest||"?")}→${esc(x.latest||"?")} (${num(x.rows).toLocaleString()})`).join(" · ");
  out.innerHTML=`<strong>Local corpus:</strong> ${covered} populated symbols / ${num(audit.symbols_catalogued)} catalogued · ${rows.toLocaleString()} rows · ${num(audit.revisions)} retained revisions · ${num(audit.quality_issue_count)} quality flags.<br><strong>Refresh:</strong> ${esc(refresh.status||"idle")}${refresh.message?` — ${esc(refresh.message)}`:""}${ranges?`<br><span class="meta">${ranges}</span>`:""}`;
}

async function renderRecipeReadiness(){
  const select=$("build-recipe"), out=$("recipe-readiness"), btn=$("btn-build-model");
  if(!select||!out)return;
  const recipe=state.modelLabRecipes.find((row)=>row.recipe_id===select.value);
  if(!recipe){out.textContent="Recipe readiness unavailable.";if(btn)btn.disabled=true;return;}
  // Hard data-readiness gates decide whether training can start at all.
  if(btn)btn.disabled=true;
  out.innerHTML='<div class="loading">Checking whether FinCompass can train this model…</div>';
  let result=null;
  try{result=await api(`/api/v4/model-lab/recipes/${encodeURIComponent(recipe.recipe_id)}/readiness`);}catch(_){}
  const r=FCP.describeReadiness(result||{});
  const rows=r.checklist.map((c)=>`<li class="chk ${c.ok?'chk-ok':'chk-bad'}"><span aria-hidden="true">${c.ok?'✓':'✕'}</span> ${esc(c.label)}${c.ok?'':' <span class="chk-tag">needs attention</span>'}</li>`).join("");
  const actions=r.actions.length?`<div class="readiness-actions"><strong>To fix:</strong><ul>${r.actions.map((a)=>`<li>${esc(a.text)}</li>`).join("")}</ul></div>`:"";
  out.innerHTML=`<div class="readiness-panel ${r.ready?'is-ready':'is-not-ready'}"><h3>Can FinCompass train this model?</h3><ul class="readiness-checklist">${rows}</ul><p class="readiness-headline">${r.ready?'✓ ':'✕ '}${esc(r.headline)}</p>${actions}</div>`;
  const ready=result?!!result.ready:false;
  if(btn)btn.disabled=state.modelBuildRunning||!ready;
  const guided=$("guided-model-message"), guidedBtn=$("btn-guided-update-train");
  if(guided){
    const recommended=recipe.recipe_id===state.modelLabRecommended;
    const prefix=recommended?"Recommended: ":"Selected: ";
    if(ready){
      guided.innerHTML=`<strong>${prefix}${esc(recipe.name)}.</strong> Local data are ready. Training will still have to pass calibration and locked-test gates before activation is possible.`;
      if(guidedBtn)guidedBtn.textContent="Train recommended model";
    }else{
      guided.innerHTML=`<strong>${prefix}${esc(recipe.name)}.</strong> Local history is incomplete. FinCompass can update only the required symbols, then train if the data become sufficient. ${esc(state.modelLabRecommendedReason||"")}`;
      if(guidedBtn)guidedBtn.textContent="Update data & train recommended model";
    }
  }
  if(guidedBtn)guidedBtn.disabled=state.modelBuildRunning;
}

function renderExperiments(payload){
  const out=$("model-lab-experiments"); if(!out)return; const experiments=Array.isArray(payload?.experiments)?payload.experiments:[]; const active=payload?.active?.model_id||"";
  if(!experiments.length){out.innerHTML='<h2>Experiments</h2><p class="meta">No Model Lab experiment has been run yet.</p>';return;}
  out.innerHTML='<h2>Experiments</h2>'+experiments.map((e)=>{
    const failed=Array.isArray(e.failed_gates)?e.failed_gates:[]; const isActive=active&&e.model_id===active;
    const eligible=e.status==="validated"&&e.model_id&&e.lineage?.live_eligible_target!==false;
    const action=isActive?'<span class="badge">Active</span>':eligible?`<button class="secondary" data-activate-experiment="${esc(e.experiment_id)}">Activate</button>`:'';
    const outcome=FCP.describeExperimentOutcome(e.status,e.validation_tier,failed);
    const reasons=outcome.reasons.length?`<ul class="meta">${outcome.reasons.map((r)=>`<li>${esc(r)}</li>`).join("")}</ul>`:"";
    const rawGates=failed.length?`<p class="meta advanced-only"><strong>Failed gates:</strong> ${failed.map(esc).join(", ")}</p>`:"";
    return `<details class="experiment-row"><summary><strong>${esc(e.recipe_id)}</strong> · ${esc(outcome.title)} · ${esc(String(e.experiment_id||"").slice(0,10))} ${action}</summary><p class="meta">${esc(outcome.blurb||e.message||"")}</p>${reasons}${rawGates}<pre class="detail advanced-only">${esc(JSON.stringify({status:e.status,validation_tier:e.validation_tier,model_id:e.model_id,metrics:e.metrics,lineage:e.lineage},null,2))}</pre></details>`;
  }).join('');
}

async function loadModelLab(){
  try{
    const [data, recipes, experiments]=await Promise.all([api('/api/v4/model-lab/data'),api('/api/v4/model-lab/recipes'),api('/api/v4/model-lab/experiments')]);
    renderResearchData(data); renderExperiments(experiments);
    state.modelLabRecipes=Array.isArray(recipes.recipes)?recipes.recipes:[];
    state.modelLabRecommended=recipes.recommended_recipe_id||null;
    state.modelLabRecommendedReason=recipes.recommended_reason||"";
    const select=$("build-recipe"); if(select){
      const current=select.value;
      select.innerHTML=state.modelLabRecipes.map((r)=>{const ready=r.readiness?.trainable?"ready":"needs local data";const tag=r.recipe_id===state.modelLabRecommended?" · recommended":"";return `<option value="${esc(r.recipe_id)}">${esc(r.name)} · ${num(r.horizon_trading_days)}d vs ${esc(FCP.friendlyBenchmark(r.benchmark))} · ${ready}${tag}</option>`;}).join('');
      const keepCurrent=current&&[...select.options].some((o)=>o.value===current)&&getExperienceMode()==="research";
      if(keepCurrent)select.value=current;
      else if(state.modelLabRecommended&&[...select.options].some((o)=>o.value===state.modelLabRecommended))select.value=state.modelLabRecommended;
      else{const firstReady=state.modelLabRecipes.find((r)=>r.readiness?.trainable);if(firstReady)select.value=firstReady.recipe_id;}
      renderRecipeReadiness();
    }
  }catch(error){const out=$("model-lab-experiments");if(out)out.innerHTML=`<div class="error">${esc(error.message)}</div>`;}
}

function renderRefreshProgress(status){
  const total=num(status.total)||0, done=num(status.completed)||0;
  const pct=total?Math.min(100,Math.round(done/total*100)):0;
  const line=esc(status.message||"Updating local data…");
  const bar=`<div class="build-bar"><span style="width:${pct}%"></span></div>`;
  const out=$("research-data-status");
  if(out)out.innerHTML=`<div class="notice"><strong>${line}</strong>${total?` <span class="meta">${done}/${total} symbols</span>`:""}</div>${bar}`;
  const g=$("guided-model-message");
  if(g&&_guidedRecipeAfterRefresh)g.innerHTML=`<strong>Updating local data…</strong> <span class="meta">${line}</span>${bar}<p class="meta">Training will start automatically once the data are ready.</p>`;
}

async function pollResearchRefresh(){
  try{
    const status=await api('/api/v4/model-lab/data/refresh/status');
    if(status.status==="running"){renderRefreshProgress(status);_researchPollTimer=setTimeout(pollResearchRefresh,1500);return;}
    _researchPollTimer=null;
    await loadModelLab();
    if($("btn-update-research-data"))$("btn-update-research-data").disabled=false;
    if($("btn-guided-update-train"))$("btn-guided-update-train").disabled=false;
    if(_guidedReplanAfterRefresh){ _guidedReplanAfterRefresh=false; runGuidedFlow(); return; }
    if(_guidedRecipeAfterRefresh){
      const wanted=_guidedRecipeAfterRefresh; _guidedRecipeAfterRefresh=null;
      const select=$("build-recipe"); if(select)select.value=wanted; renderRecipeReadiness();
      const recipe=state.modelLabRecipes.find((row)=>row.recipe_id===wanted);
      if(recipe?.readiness?.trainable){await startModelBuild();}
      else{const out=$("guided-model-message");if(out)out.innerHTML=`<strong>Data update finished, but the recommended recipe is still not trainable.</strong> Check provider status or switch to Research mode to inspect the missing symbols.`;}
    }
  }catch(error){
    _researchPollTimer=null;_guidedRecipeAfterRefresh=null;_guidedReplanAfterRefresh=false;
    if($("btn-update-research-data"))$("btn-update-research-data").disabled=false;
    if($("btn-guided-update-train"))$("btn-guided-update-train").disabled=false;
  }
}

async function startResearchRefresh(){
  _guidedRecipeAfterRefresh=null;
  const btn=$("btn-update-research-data");if(btn)btn.disabled=true;
  try{const s=await api('/api/v4/model-lab/data/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(s.status==="running"){if(_researchPollTimer)clearTimeout(_researchPollTimer);pollResearchRefresh();}else{if(btn)btn.disabled=false;await loadModelLab();}}catch(error){if(btn)btn.disabled=false;const out=$("research-data-status");if(out)out.innerHTML=`<span class="error">${esc(error.message)}</span>`;}
}

async function guidedUpdateAndTrain(){
  const recipeId=state.modelLabRecommended||$("build-recipe")?.value;
  const recipe=state.modelLabRecipes.find((row)=>row.recipe_id===recipeId);
  const btn=$("btn-guided-update-train");
  if(!recipe){if($("guided-model-message"))$("guided-model-message").textContent="No recommended recipe is configured.";return;}
  if($("build-recipe"))$("build-recipe").value=recipe.recipe_id;
  renderRecipeReadiness();
  if(recipe.readiness?.trainable){await startModelBuild();return;}
  if(btn)btn.disabled=true;
  _guidedRecipeAfterRefresh=recipe.recipe_id;
  const symbols=[recipe.benchmark,...(recipe.tickers||[])].filter(Boolean);
  try{
    const result=await api('/api/v4/model-lab/data/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({symbols})});
    if($("guided-model-message"))$("guided-model-message").innerHTML=`<strong>Updating ${symbols.length} required symbol${symbols.length===1?"":"s"}.</strong> Existing local history is retained; only missing/overlap data are requested.`;
    if(result.status==="running"){if(_researchPollTimer)clearTimeout(_researchPollTimer);pollResearchRefresh();}
    else{await pollResearchRefresh();}
  }catch(error){
    _guidedRecipeAfterRefresh=null;if(btn)btn.disabled=false;
    if($("guided-model-message"))$("guided-model-message").innerHTML=`<span class="error">${esc(error.message)}</span>`;
  }
}

async function activateExperiment(experimentId){
  try{await api(`/api/v4/model-lab/experiments/${encodeURIComponent(experimentId)}/activate`,{method:'POST'});await Promise.all([loadModelLab(),loadForecastStatus()]);}catch(error){const out=$("model-lab-experiments");if(out)out.insertAdjacentHTML('afterbegin',`<div class="error">${esc(error.message)}</div>`);}
}

async function resumeBuildStatus(){
  // On opening the Forecast tab, reflect any build already in progress and
  // resume polling — without triggering the settle-time status refresh loop.
  try{
    const s=await api("/api/v4/forecast/build/status");
    renderBuildStatus(s);
    if(s.status==="running"){ if($("btn-build-model"))$("btn-build-model").disabled=true; if(_buildPollTimer)clearTimeout(_buildPollTimer); pollBuildStatus(); }
  }catch(_e){/* status is best-effort */}
}

let _buildPollTimer=null;
async function pollBuildStatus(){
  try{
    const s=await api("/api/v4/forecast/build/status");
    renderBuildStatus(s);
    if(s.status==="running"){ _buildPollTimer=setTimeout(pollBuildStatus,3000); }
    else{
      _buildPollTimer=null; $("btn-build-model").disabled=false;
      loadForecastStatus(); // refresh the registry/tier badge once a build settles
      loadModelLab();
      if(_guidedReplanAfterBuild){
        _guidedReplanAfterBuild=false;
        if(s.usable){ runGuidedFlow(); }
        else{
          const o=FCP.describeExperimentOutcome(s.status==="not_ready"?"not_ready":(s.status==="failed"?"failed":"rejected"),s.validation_tier,s.failed_gates||[]);
          const reasons=(o.reasons||[]).map((r)=>`<li>${esc(r)}</li>`).join("");
          const out=$("forecast-out"); if(out)out.innerHTML=`<article class="card readiness-strip readiness-unsupported"><h3>${esc(o.title)}</h3><p>${esc(o.blurb)}</p>${reasons?`<ul class="meta">${reasons}</ul>`:""}<p class="meta">Your existing forecasts are unaffected. You can try a different time period.</p></article>`;
        }
      }
    }
  }catch(error){
    renderBuildStatus({status:"failed",message:error.message});
    _buildPollTimer=null; $("btn-build-model").disabled=false; _guidedReplanAfterBuild=false;
  }
}

async function startModelBuild(){
  const btn=$("btn-build-model"); if(!btn)return;
  const recipeId=($("build-recipe")&&$("build-recipe").value)||"core-us-6m";
  const recipe=state.modelLabRecipes.find((row)=>row.recipe_id===recipeId);
  if(recipe&&recipe.readiness&&!recipe.readiness.trainable){renderRecipeReadiness();return;}
  const profile=($("build-profile")&&$("build-profile").value)||null;
  btn.disabled=true;
  renderBuildStatus({status:"running",phase:"queued",message:"Starting offline Model Lab build…",total:0,completed:0});
  try{
    const body={recipe_id:recipeId}; if(profile)body.profile=profile;
    const s=await api("/api/v4/forecast/build",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    renderBuildStatus(s);
    if(s.status==="running"){ if(_buildPollTimer)clearTimeout(_buildPollTimer); pollBuildStatus(); }
    else{ btn.disabled=false; }
  }catch(error){
    renderBuildStatus({status:"failed",message:error.message}); btn.disabled=false;
  }
}

async function activateSelectedForecastModel(){
  const modelId=$('forecast-model')?.value||'';
  if(!modelId){
    const out=$('forecast-status'); if(out)out.insertAdjacentHTML('afterbegin','<div class="notice">Select a validated model first. The default option refers to the model that is already active.</div>');
    return;
  }
  const btn=$('btn-activate-selected-model'); if(btn)btn.disabled=true;
  try{
    await api(`/api/v4/forecast/models/${encodeURIComponent(modelId)}/activate`,{method:'POST'});
    await Promise.all([loadForecastStatus(),loadRealtimeStatus?.()]);
  }catch(error){const out=$('forecast-status');if(out)out.insertAdjacentHTML('afterbegin',`<div class="error">${esc(error.message)}</div>`);}
  finally{if(btn)btn.disabled=false;}
}

async function deactivateActiveModel(){
  const btn=$("btn-deactivate-model"); if(btn)btn.disabled=true;
  try{await api("/api/v4/model-lab/active/deactivate",{method:"POST"});await Promise.all([loadForecastStatus(),loadModelLab()]);}
  catch(error){const out=$("forecast-status");if(out)out.insertAdjacentHTML("afterbegin",`<div class="error">${esc(error.message)}</div>`);}
  finally{if(btn)btn.disabled=false;}
}

async function runForecastModelCompare(){
  const ticker=$("forecast-ticker").value.trim().toUpperCase(); if(!ticker)return; $("forecast-ticker").value=ticker;
  const out=$("forecast-model-compare-out");
  const models=(state.forecastRegistry?.models||[]).filter((m)=>["validated_research","validated_market"].includes(m.validation_tier)).slice(0,8);
  if(!models.length){out.innerHTML='<div class="notice">No validated models are available to compare.</div>';return;}
  out.innerHTML='<div class="card loading">Comparing validated anchors…</div>';
  try{
    const rows=await Promise.all(models.map(async (m)=>{
      try{const d=await api(`/api/v4/forecast/${encodeURIComponent(ticker)}?model_id=${encodeURIComponent(m.model_id)}`);return {ok:true,model:m,result:d};}
      catch(error){return {ok:false,model:m,error:error.message};}
    }));
    const body=rows.map((row)=>{
      const m=row.model||{}; const target=m.target||{};
      if(!row.ok)return `<tr><td>${esc(String(m.model_id||"").slice(0,10))}</td><td>${esc(FCP.describeModelTier(m.validation_tier).label)}</td><td>${num(target.horizon_trading_days)||"—"}</td><td>${esc(FCP.friendlyBenchmark(target.benchmark))}</td><td colspan="3">${esc(row.error||"unavailable")}</td></tr>`;
      const d=row.result||{}, p=d.probability||{}, metrics=d.validation_summary?.locked_test_metrics||{};
      return `<tr><td>${esc(String(d.model_id||"").slice(0,10))}</td><td>${esc(FCP.describeModelTier(d.validation_tier).label)}</td><td>${num(d.target?.horizon_trading_days)||"—"}</td><td>${esc(FCP.friendlyBenchmark(d.target?.benchmark))}</td><td>${probabilityText(p.probability_outperform)}</td><td>${Number.isFinite(Number(metrics.brier_skill))?pct(metrics.brier_skill,1):"—"}</td><td>${Number.isFinite(Number(metrics.roc_auc))?num(metrics.roc_auc).toFixed(3):"—"}</td></tr>`;
    }).join("");
    out.innerHTML=`<article class="card"><h2>${esc(ticker)} model comparison</h2><p class="meta">Each row keeps its own horizon, benchmark and validation record. A higher probability from a different target contract is not automatically a better model.</p><div class="table-wrap"><table><thead><tr><th>Model</th><th>Tier</th><th>Horizon</th><th>Benchmark</th><th>Probability</th><th>Brier skill</th><th>ROC AUC</th></tr></thead><tbody>${body}</tbody></table></div></article>`;
  }catch(error){out.innerHTML=`<div class="error">${esc(error.message)}</div>`;}
}

// Simple horizontal probability scale around 50%. Color is backed by text labels
// (never color alone) and it is not a speedometer/gauge implying certainty.
function probScaleHtml(p){
  const v=Math.max(0,Math.min(1,Number(p))); if(!isFinite(v))return "";
  const left=(v*100).toFixed(1);
  return `<div class="prob-scale" role="img" aria-label="Estimated probability ${Math.round(v*100)} percent on a scale from 0 to 100 percent, where 50 percent is even">`
    +`<div class="ps-track"><span class="ps-neutral"></span><span class="ps-marker" style="left:${left}%"></span></div>`
    +`<div class="ps-labels"><span>0%</span><span>50% · even</span><span>100%</span></div></div>`;
}

// Shared Guided forecast result card (used by both the direct and plan-driven flows).
function forecastCardHtml(d){
  const p=d.probability||{}; const target=d.target||{}; const ci=p.uncertainty_interval||[]; const metrics=d.validation_summary?.locked_test_metrics||{};
  const fp=FCP.describeForecastProbability(p.probability_outperform,p.abstain,target);
  const tier=FCP.describeModelTier(d.validation_tier);
  const ev=FCP.describeEvidenceStrength(metrics);
  const horizon=FCP.horizonWords(target); const bench=esc(FCP.friendlyBenchmark(target.benchmark));
  return `<article class="card guided-forecast"><div class="gf-head"><h1 class="company-name">${esc(d.ticker)} outlook</h1><div class="meta">over ${esc(horizon)} vs ${bench} · as of ${esc(d.as_of)}</div></div>`
    +`<div class="gf-hero"><span class="gf-prob band-${esc(fp.band)}">${probabilityText(p.probability_outperform)}</span><span class="gf-denom">Estimated chance of outperforming ${bench} over ${esc(horizon)}</span></div>`
    +`<p class="gf-interp"><strong>${esc(fp.headline)}.</strong> ${esc(fp.interpretation)}</p>`
    +probScaleHtml(p.probability_outperform)
    +`<div class="gf-block"><h3>What this means</h3><p>${esc(fp.meaning)}</p></div>`
    +`<div class="gf-block"><h3>How much confidence should I place in this?</h3><p><strong>${esc(ev.label)}</strong> <span class="muted">— based on how well the model predicted unseen historical outcomes.</span></p></div>`
    +`<div class="gf-badge badge-${esc(tier.level)}"><span class="badge-dot"></span><div><strong>${esc(tier.label)}</strong><span class="badge-blurb">${esc(tier.blurb)}</span></div></div>`
    +`<div class="gf-block"><h3>Confidence range</h3><p><span class="gf-range">${ci.length?`${probabilityText(ci[0])} – ${probabilityText(ci[1])}`:"—"}</span> <span class="muted">— how sure the model is; a wider range means less certainty.</span></p></div>`
    +`<details class="gf-tech"><summary>Technical details — model ID, calibration metrics, JSON</summary><div class="table-wrap"><table><tbody>`
      +`<tr><th>Model ID</th><td>${esc(d.model_id)}</td></tr>`
      +`<tr><th>Validation tier</th><td>${esc(String(d.validation_tier||"").replaceAll("_"," "))}</td></tr>`
      +`<tr><th>Defined event</th><td>outperform ${bench} over ${esc(horizon)} by more than ${pct(target.excess_return_threshold||0,1)}</td></tr>`
      +`<tr><th>Locked-test Brier skill</th><td>${Number.isFinite(Number(metrics.brier_skill))?pct(metrics.brier_skill,1):"—"}</td></tr>`
      +`<tr><th>Locked-test ROC AUC</th><td>${Number.isFinite(Number(metrics.roc_auc))?num(metrics.roc_auc).toFixed(3):"—"}</td></tr>`
      +`<tr><th>Calibration error (ECE)</th><td>${Number.isFinite(Number(metrics.ece_10))?pct(metrics.ece_10,1):"—"}</td></tr>`
    +`</tbody></table></div><pre class="detail">${esc(JSON.stringify({probability:p,validation:d.validation_summary,target:d.target},null,2))}</pre></details>`
    +`<p class="meta">${esc(d.disclaimer||"")}</p></article>`;
}

async function runForecast(){
  const ticker=$("forecast-ticker").value.trim().toUpperCase(); if(!ticker)return; $("forecast-ticker").value=ticker;
  const modelId=$("forecast-model").value; const q=new URLSearchParams(); if(modelId)q.set("model_id",modelId);
  $("forecast-out").innerHTML='<div class="card loading">Checking whether a validated model applies to this instrument…</div>'; $("btn-forecast").disabled=true;
  try{
    // Mandatory applicability preflight. Guided mode auto-resolves the
    // model; a forecast runs only when data + computational + scientific checks
    // all pass. A failed preflight is NEVER silently ignored.
    const pf=await api(`/api/v4/forecast/${encodeURIComponent(ticker)}/preflight${q.toString()?`?${q}`:""}`);
    const guide=FCP.describeForecastPreflight(pf);
    if(!guide.canRun){
      if(guide.noModel){
        $("forecast-out").innerHTML=`<article class="card readiness-strip readiness-unsupported"><h3>No validated model for this instrument yet</h3><p>FinCompass does not yet have a validated model for this market and forecast period. It will not show a probability it cannot stand behind.</p><p class="meta">You can build and validate a model in Model Lab.</p></article>`;
      }else{
        const cls=guide.status==="needs_data"?"needs":"unsupported";
        const title=guide.status==="needs_data"?"More data needed":"Not supported for this instrument";
        $("forecast-out").innerHTML=`<article class="card readiness-strip readiness-${cls}"><h3>${esc(title)}</h3><ul>${guide.reasons.map((r)=>`<li>${esc(r)}</li>`).join("")||"<li>This model cannot be used for this instrument right now.</li>"}</ul>${guide.action&&guide.status==="needs_data"?`<p class="meta">Suggested action: <strong>${esc(guide.action)}</strong>.</p>`:""}</article>`;
      }
      return;
    }
    $("forecast-out").innerHTML='<div class="card loading">Running validated probability model…</div>';
    const d=await api(`/api/v4/forecast/${encodeURIComponent(ticker)}${q.toString()?`?${q}`:""}`);
    if(!d.available){
      const reasons=(d.reasons||[]).map((r)=>FCP.describeForecastReason(r.code,r.message_data));
      $("forecast-out").innerHTML=`<article class="card readiness-strip readiness-unsupported"><h3>Forecast unavailable</h3><ul>${reasons.map((r)=>`<li>${esc(r)}</li>`).join("")||`<li>${esc(d.message||"No validated forecast is available.")}</li>`}</ul></article>`;
      return;
    }
    $("forecast-out").innerHTML=forecastCardHtml(d);
  }catch(error){
    const pl=error&&error.payload;
    if(error&&(error.status===409||(pl&&pl.available===false))){
      $("forecast-out").innerHTML=`<div class="notice"><strong>No active validated forecast model is available.</strong> Use Model Lab to update/import local data, train a recipe, inspect its locked-test gates, and explicitly activate an eligible validated candidate. Rejected candidates and the bundled synthetic fixture never become live.</div>`;
    } else {
      $("forecast-out").innerHTML=`<div class="error">${esc(error.message)}</div>`;
    }
  }finally{$("btn-forecast").disabled=false;}
}

// ---- Guided single-flow (plan-driven): identify -> data -> model -> forecast -> Live ----
let _guidedReplanAfterRefresh=false;
let _guidedReplanAfterBuild=false;
let _lastGuidedPlan=null;

async function runGuidedFlow(){
  const ticker=$("forecast-ticker").value.trim().toUpperCase(); if(!ticker)return; $("forecast-ticker").value=ticker;
  const horizon=$("forecast-horizon")?.value||"1y";
  const out=$("forecast-out"); if(out)out.innerHTML=`<div class="card loading">Working out the best forecast for ${esc(ticker)}…</div>`;
  if($("btn-forecast"))$("btn-forecast").disabled=true;
  try{
    const plan=await api(`/api/v4/forecast-plan/${encodeURIComponent(ticker)}?horizon=${encodeURIComponent(horizon)}`);
    _lastGuidedPlan=plan;
    await renderGuidedPlan(plan,ticker);
  }catch(e){ if(out)out.innerHTML=`<div class="error">${esc(e.message)}</div>`; }
  finally{ if($("btn-forecast"))$("btn-forecast").disabled=false; }
}

function planHeaderHtml(plan){
  const inst=FCP.describeInstrument(plan.instrument||{});
  const bench=(plan.benchmark||{}).benchmark_name;
  const hz=FCP.horizonWords({horizon_months:plan.horizon_months});
  return `<div class="plan-head"><h2 class="company-name">${esc(inst.title)}</h2>${inst.subtitle?`<div class="meta">${esc(inst.subtitle)}</div>`:""}<div class="meta">${esc(hz)} outlook${bench?` vs ${esc(bench)}`:""}</div></div>`;
}

async function renderGuidedPlan(plan,ticker){
  const out=$("forecast-out"); if(!out)return; const head=planHeaderHtml(plan); const action=plan.recommended_action;
  if(action==="forecast"){
    const fr=FCP.describeFreshness(plan.model_freshness);
    out.innerHTML=`<article class="card">${head}<div class="loading">Producing your forecast…</div></article>`;
    let d=null; try{ d=await api(`/api/v4/forecast/${encodeURIComponent(ticker)}`); }catch(e){ d=(e&&e.payload)||null; }
    if(!d||!d.available){
      const reasons=((d&&d.reasons)||[]).map((r)=>FCP.describeForecastReason(r.code,r.message_data));
      out.innerHTML=`<article class="card">${head}<div class="readiness-strip readiness-unsupported"><h3>Forecast unavailable</h3><ul>${reasons.map((r)=>`<li>${esc(r)}</li>`).join("")||`<li>${esc((d&&d.message)||"No validated forecast is available.")}</li>`}</ul></div></article>`;
      return;
    }
    const bClass=fr.level==='ok'?'ACTIVE':(fr.level==='bad'?'BASE_ONLY_DRIFT':(fr.level==='warn'?'BASE_ONLY_STALE':''));
    const frBanner=(fr.label&&fr.level!=="muted")?`<div class="live-banner banner-${bClass}"><span class="badge-dot"></span><div><strong>${esc(fr.label)}</strong><span class="badge-blurb">${esc(fr.blurb)}</span></div></div>`:"";
    const updateBtn=fr.level==='bad'?`<button class="secondary" data-guided-update="${esc(ticker)}">Update model data</button>`:"";
    out.innerHTML=forecastCardHtml(d)+`<div class="card">${frBanner}<div class="button-row"><button class="primary" data-start-live="${esc(d.model_id||'')}">Start Live — keep this forecast updated</button>${updateBtn}</div><p class="meta">Live keeps this forecast as its base and only applies adjustments once it has enough evidence.</p></div>`;
    return;
  }
  if(action==="update_data"){
    const ds=plan.data_status||{};
    out.innerHTML=`<article class="card readiness-strip readiness-needs">${head}<h3>Data update needed</h3><p>${esc(plan.message||"More market history is needed.")}</p>${ds.ticker_latest?`<p class="meta">Local history for ${esc(ticker)} ends ${esc(ds.ticker_latest)}.</p>`:""}<div class="button-row"><button class="primary" data-guided-update="${esc(ticker)}">Update data and continue</button></div></article>`;
    return;
  }
  if(action==="train"){
    const rec=(plan.models.trainable[0]||{});
    out.innerHTML=`<article class="card readiness-strip readiness-needs">${head}<h3>A model can be built</h3><p>FinCompass does not yet have a validated ${esc(FCP.horizonWords({horizon_months:plan.horizon_months}))} model for this security, but one can be trained from the available data.</p><div class="button-row"><button class="primary" data-guided-train="${esc(rec.recipe_id||'')}">Build model</button></div><p class="meta">FinCompass chooses the recommended scientific configuration automatically. Nothing is activated until it passes validation.</p></article>`;
    return;
  }
  const alts=(plan.alternatives||[]).map((m)=>m.horizon_months?`<button class="secondary" data-guided-alt="${m.horizon_months}m">${esc(FCP.horizonWords({horizon_months:m.horizon_months}))} — validated model available</button>`:"").join("");
  out.innerHTML=`<article class="card readiness-strip readiness-unsupported">${head}<h3>No validated forecast for this yet</h3><p>${esc(plan.message||"FinCompass does not yet have a validated model for this market and period.")}</p>${alts?`<p class="meta">Available instead:</p><div class="button-row">${alts}</div>`:""}<p class="meta">FinCompass will not show a probability it cannot stand behind.</p></article>`;
}

async function guidedStartLive(modelId){
  if(!modelId)return;
  if(!window.confirm("Use this validated model for Live updates?\n\nFinCompass will keep the original forecast as its base and only apply live adjustments when they have enough evidence."))return;
  try{
    await api(`/api/v4/forecast/models/${encodeURIComponent(modelId)}/activate`,{method:'POST'});
    const t=$("forecast-ticker").value.trim().toUpperCase(); if($("live-ticker"))$("live-ticker").value=t;
    const tab=$("tab-btn-live"); if(tab)tab.click();
    if(typeof runLive==="function")runLive(false);
  }catch(e){ const out=$("forecast-out"); if(out)out.insertAdjacentHTML("afterbegin",`<div class="error">${esc(e.message)}</div>`); }
}

async function guidedUpdateData(ticker){
  _guidedReplanAfterRefresh=true; _guidedRecipeAfterRefresh=null;
  // Fetch exactly the symbols the plan says are needed to close the gap
  // (benchmark + recipe universe for training; ticker + benchmark for a forecast).
  // Symbols already present get a fast incremental tail update; only missing
  // symbols do a first-time history fetch.
  const symbols=(_lastGuidedPlan&&Array.isArray(_lastGuidedPlan.update_symbols)&&_lastGuidedPlan.update_symbols.length)?_lastGuidedPlan.update_symbols:[ticker];
  const out=$("forecast-out"); if(out)out.innerHTML=`<div class="card loading">Updating market data for ${symbols.length} instrument${symbols.length===1?"":"s"}… <span class="meta">already-stored history updates quickly; missing instruments are downloaded once.</span></div>`;
  try{
    const s=await api('/api/v4/model-lab/data/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({symbols})});
    if(s.status==="running"){ if(_researchPollTimer)clearTimeout(_researchPollTimer); pollResearchRefresh(); }
    else { _guidedReplanAfterRefresh=false; runGuidedFlow(); }
  }catch(e){ _guidedReplanAfterRefresh=false; if(out)out.innerHTML=`<div class="error">${esc(e.message)}</div>`; }
}

async function guidedBuildModel(recipeId){
  if(!recipeId)return; _guidedReplanAfterBuild=true;
  if($("build-recipe"))$("build-recipe").value=recipeId;
  const out=$("forecast-out"); if(out)out.innerHTML=`<div class="card loading">Building your forecast model…</div>`;
  try{ await startModelBuild(); }catch(e){ if(out)out.innerHTML=`<div class="error">${esc(e.message)}</div>`; }
}

function initGuidedForecastDelegation(){
  const out=$("forecast-out"); if(!out)return;
  out.addEventListener("click",(e)=>{
    const el=e.target.closest("[data-start-live],[data-guided-update],[data-guided-train],[data-guided-alt]"); if(!el)return;
    if(el.hasAttribute("data-start-live")) return guidedStartLive(el.getAttribute("data-start-live"));
    if(el.hasAttribute("data-guided-update")) return guidedUpdateData(el.getAttribute("data-guided-update"));
    if(el.hasAttribute("data-guided-train")) return guidedBuildModel(el.getAttribute("data-guided-train"));
    if(el.hasAttribute("data-guided-alt")){ if($("forecast-horizon"))$("forecast-horizon").value=el.getAttribute("data-guided-alt"); return runGuidedFlow(); }
  });
}

function applyRuntimeSettings(settings){
  if($("setting-chart-period"))$("setting-chart-period").value=settings.chartPeriod||"10y";
  if($("setting-min-coverage"))$("setting-min-coverage").value=settings.minCoverage||"0";
  if($("setting-prob-format"))$("setting-prob-format").value=settings.probabilityFormat||"percent";
  if($("coverage-filter"))$("coverage-filter").value=settings.minCoverage||"0";
  if($("setting-model"))$("setting-model").value=settings.modelId||"";
  if($("forecast-model"))$("forecast-model").value=settings.modelId||"";
  if($("live-model"))$("live-model").value=settings.modelId||"";
  if($("setting-live-refresh"))$("setting-live-refresh").value=String(settings.liveRefreshSeconds||"0");
}

async function loadSettings(){
  try{
    const data=await api("/api/v4/settings/schema"); state.settingsLoaded=true; renderForecastStatus(data.forecast_registry||{});
    const fProfile=$("settings-profile").value||"strict"; const savedForecast=storageGet(TRAINING_SETTINGS_KEY); const fBase=data.forecast?.profiles?.[fProfile]||{}; $("training-settings-json").value=savedForecast||JSON.stringify(fBase,null,2);
    const rProfile=$("realtime-settings-profile").value||"balanced"; const savedRealtime=storageGet(REALTIME_SETTINGS_KEY); const rBase=data.realtime?.profiles?.[rProfile]||{}; $("realtime-settings-json").value=savedRealtime||JSON.stringify(rBase,null,2);
    applyRuntimeSettings(getRuntimeSettings());
  }catch(error){$("settings-validation-note").textContent=error.message;}
}

function saveRuntimeSettings(){
  const settings={chartPeriod:$("setting-chart-period").value,minCoverage:$("setting-min-coverage").value,probabilityFormat:$("setting-prob-format").value,modelId:$("setting-model").value,liveRefreshSeconds:$("setting-live-refresh").value};
  storageSet(SETTINGS_KEY,JSON.stringify(settings)); applyRuntimeSettings(settings); scheduleLiveTimer(); $("settings-validation-note").textContent="Runtime preferences saved in this browser.";
}

async function validateTrainingSettings(){
  const note=$("settings-validation-note");
  try{const payload=JSON.parse($("training-settings-json").value); payload._profile=$("settings-profile").value; const result=await api("/api/v4/forecast/settings/validate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); storageSet(TRAINING_SETTINGS_KEY,JSON.stringify(result.settings,null,2)); $("training-settings-json").value=JSON.stringify(result.settings,null,2); note.innerHTML=`<span class="validation-pass">Valid configuration.</span> ${esc(result.note||"")}`;}catch(error){note.innerHTML=`<span class="validation-fail">Invalid configuration:</span> ${esc(error.message)}`;}
}

async function validateRealtimeSettings(){
  const note=$("realtime-settings-validation-note");
  try{const payload=JSON.parse($("realtime-settings-json").value); payload._profile=$("realtime-settings-profile").value; const result=await api("/api/v4/realtime/settings/validate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); storageSet(REALTIME_SETTINGS_KEY,JSON.stringify(result.settings,null,2)); $("realtime-settings-json").value=JSON.stringify(result.settings,null,2); note.innerHTML=`<span class="validation-pass">Valid adaptive contract.</span> fingerprint ${esc(result.settings_fingerprint||"")} · ${esc(result.note||"")}`;}catch(error){note.innerHTML=`<span class="validation-fail">Invalid configuration:</span> ${esc(error.message)}`;}
}

function downloadJsonTextarea(id,filename,noteId){
  try{const payload=JSON.parse($(id).value); const blob=new Blob([JSON.stringify(payload,null,2)+"\n"],{type:"application/json"}); const url=URL.createObjectURL(blob); const a=document.createElement("a");a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);}catch(error){$(noteId).textContent=`Cannot export: ${error.message}`;}
}
function downloadTrainingSettings(){downloadJsonTextarea("training-settings-json","fincompass-forecast-settings.json","settings-validation-note");}
function downloadRealtimeSettings(){downloadJsonTextarea("realtime-settings-json","fincompass-realtime-settings.json","realtime-settings-validation-note");}

function resetSettings(){storageSet(SETTINGS_KEY,"{}");storageSet(TRAINING_SETTINGS_KEY,"");storageSet(REALTIME_SETTINGS_KEY,"");state.settingsLoaded=false;loadSettings();}

async function changeSettingsProfile(){
  try{const data=await api("/api/v4/settings/schema");const profile=$("settings-profile").value;$("training-settings-json").value=JSON.stringify(data.forecast?.profiles?.[profile]||{},null,2);$("settings-validation-note").textContent="Profile loaded. Validate or edit before exporting.";}catch(error){$("settings-validation-note").textContent=error.message;}
}
async function changeRealtimeSettingsProfile(){
  try{const data=await api("/api/v4/realtime/settings/schema");const profile=$("realtime-settings-profile").value;$("realtime-settings-json").value=JSON.stringify(data.settings?.profiles?.[profile]||{},null,2);$("realtime-settings-validation-note").textContent="Adaptive profile loaded. Validate before operational use.";}catch(error){$("realtime-settings-validation-note").textContent=error.message;}
}

function scheduleLiveTimer(){
  if(state.liveTimer){clearInterval(state.liveTimer);state.liveTimer=null;}
  const seconds=Math.max(0,num(getRuntimeSettings().liveRefreshSeconds,0));
  const panel=$("page-live"); if(seconds>=30 && panel && !panel.hidden){state.liveTimer=setInterval(()=>runLive(true),seconds*1000);}
}

function renderSourceHealth(sourceHealth){
  return Object.entries(sourceHealth||{}).map(([name,v])=>`<div class="kpi"><div class="k-label">${esc(name)} source</div><div class="k-value">${v.verified_recently?"verified":"stale/unverified"}</div><div class="k-note">event age ${v.event_age_seconds==null?"—":Math.round(num(v.event_age_seconds)/60)+" min"} · last success ${esc(v.last_success_at||"—")}</div></div>`).join("");
}

async function loadLiveStatus(){
  const out=$("live-status"); out.innerHTML='<div class="loading">Checking realtime/adaptive registry…</div>';
  try{const d=await api("/api/v4/realtime/status");state.liveStatusLoaded=true;const ar=d.adaptive_registry||{}, fr=d.anchor_registry||{};$("live-state-badge").textContent=ar.live_eligible_artifacts?"Adaptive eligible":"Anchor-only / warming";out.innerHTML=`<div class="forecast-grid"><div class="kpi"><div class="k-label">Validated anchors</div><div class="k-value">${num(fr.usable_models)}</div></div><div class="kpi"><div class="k-label">Adaptive artifacts</div><div class="k-value">${num(ar.artifacts_total)}</div><div class="k-note">${num(ar.live_eligible_artifacts)} live-eligible</div></div><div class="kpi"><div class="k-label">Realtime engine</div><div class="k-value">${esc(d.realtime_engine_version||"—")}</div></div><div class="kpi"><div class="k-label">Pending labels</div><div class="k-value">${num(d.store_counts?.pending_labels)}</div></div></div><details><summary>Aggregate provider health</summary><pre class="detail">${esc(JSON.stringify(d.provider_health||{},null,2))}</pre></details><p class="meta">${esc(d.privacy_note||"")}</p>`;}catch(error){out.innerHTML=`<div class="error">${esc(error.message)}</div>`;}
}

async function runLive(silent=false){
  const ticker=$("live-ticker").value.trim().toUpperCase(); if(!ticker)return; $("live-ticker").value=ticker;
  const q=new URLSearchParams(); const modelId=$("live-model").value; if(modelId)q.set("model_id",modelId); q.set("realtime_profile",$("live-profile").value||"balanced");
  if(!silent)$("live-out").innerHTML='<div class="card loading">Refreshing timestamped information state…</div>'; $("btn-live").disabled=true;
  try{
    if(!silent){try{await api("/api/v4/adaptive/process-matured",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({limit:100})});}catch(_){/* maintenance is best-effort; live gate still fails closed */}}
    const d=await api(`/api/v4/realtime/${encodeURIComponent(ticker)}?${q}`); const gate=d.gate||{}; const gm=gate.metrics||{}; $("live-state-badge").textContent=gate.status||"warming";
    let events=[]; try{events=(await api(`/api/v4/realtime/${encodeURIComponent(ticker)}/events?limit=12`)).events||[];}catch(_){events=[];}
    const contributions=(d.top_contributions||[]).map((c)=>`<tr><td>${esc(c.feature)}</td><td>${num(c.value).toFixed(3)}</td><td>${num(c.log_odds_contribution).toFixed(4)}</td></tr>`).join("");
    const eventRows=events.map((e)=>`<tr><td>${esc(e.source_time||"")}</td><td>${esc(e.source)}</td><td>${esc(e.event_type)}</td><td>${esc(e.payload?.form||e.payload?.note||"")}</td></tr>`).join("");
    const st=FCP.liveStateFromSnapshot(d);
    const applied=!!d.adaptive_shift_applied;
    const change=FCP.describeProbabilityChange(d.anchor_probability,d.adaptive_applied_probability);
    const ltarget=d.target||{}; const lbench=esc(FCP.friendlyBenchmark(ltarget.benchmark)); const lhorizon=esc(FCP.horizonWords(ltarget));
    const changePts=(applied&&change.deltaPoints!==null)?`${change.deltaPoints>0?"+":""}${change.deltaPoints} percentage point${Math.abs(change.deltaPoints)===1?"":"s"}`:"none applied";
    const changeSentence=applied?change.sentence:st.blurb;
    const eventCards=events.slice(0,5).map((e)=>`<tr><td>${esc(FCP.describeEventCategory(e.source,e.event_type))}</td><td>${esc(e.payload?.form||e.payload?.note||e.event_type||"")}</td><td>${esc(e.source_time||"")}</td></tr>`).join("");
    $("live-out").innerHTML=`<article class="card guided-forecast guided-live"><div class="gf-head"><h1 class="company-name">${esc(d.ticker)} live forecast</h1><div class="meta">over ${lhorizon} vs ${lbench} · as of ${esc(d.as_of)}</div></div>`
      +`<div class="live-banner banner-${esc(st.code)}"><span class="badge-dot"></span><div><strong>${esc(st.label)}</strong><span class="badge-blurb">${esc(st.blurb)}</span></div></div>`
      +`<div class="gf-hero"><span class="gf-prob">${probabilityText(d.adaptive_applied_probability)}</span><span class="gf-denom">Current forecast</span></div>`
      +`<p class="live-change">Original forecast: <strong>${probabilityText(d.anchor_probability)}</strong> · Change from new information: <strong>${esc(changePts)}</strong></p>`
      +`<p class="gf-interp">${esc(changeSentence)}</p>`
      +`<div class="gf-block"><h3>What changed?</h3>${eventCards?`<div class="table-wrap"><table><thead><tr><th>Information</th><th>What arrived</th><th>When</th></tr></thead><tbody>${eventCards}</tbody></table></div>`:'<p class="muted">No new information has arrived yet.</p>'}</div>`
      +`<div class="gf-block"><h3>Forecast model</h3><p class="muted">This is the model currently activated for Live${d.base_model_id?"":" (none active)"}.</p></div>`
      +`<details class="gf-tech"><summary>Technical details — gate, drift, contributions, provenance</summary>`
        +`<div class="table-wrap"><table><tbody><tr><th>Anchor (base) model</th><td>${esc(d.base_model_id||"—")}</td></tr><tr><th>Gate status</th><td>${esc(gate.status||"warming")} · ${num(gm.unique_dates)} dates · ${num(gm.span_days)} day span</td></tr><tr><th>Adaptive candidate</th><td>${probabilityText(d.adaptive_candidate_probability)} (${d.adaptive_shift_applied?"applied":"gated off"})</td></tr><tr><th>Settings fingerprint</th><td>${esc(d.settings_fingerprint||"—")}</td></tr></tbody></table></div>`
        +`${renderSourceHealth(d.source_health)}`
        +`<h3>Adaptive log-odds contributions</h3><div class="table-wrap"><table><thead><tr><th>Feature</th><th>Value</th><th>Log-odds contribution</th></tr></thead><tbody>${contributions||'<tr><td colspan="3">No adaptive contribution yet.</td></tr>'}</tbody></table></div>`
        +`<h3>Event chronology</h3><div class="table-wrap"><table><thead><tr><th>Source time</th><th>Source</th><th>Type</th><th>Context</th></tr></thead><tbody>${eventRows||'<tr><td colspan="4">No stored events.</td></tr>'}</tbody></table></div>`
        +`<pre class="detail">${esc(JSON.stringify({gate:d.gate,drift:d.drift,features:d.features,source_health:d.source_health,target:d.target,state_key:d.state_key,state_source:d.state_source},null,2))}</pre></details>`
      +`<p class="meta">${esc(d.disclaimer||"")}</p></article>`;
  }catch(error){if(!silent)$("live-out").innerHTML=`<div class="error">${esc(error.message)}</div>`;}finally{$("btn-live").disabled=false;}
}

async function runLiveCompare(){
  const ticker=$("live-ticker").value.trim().toUpperCase(); if(!ticker)return; $("live-ticker").value=ticker;
  const q=new URLSearchParams(); const modelId=$("live-model").value; if(modelId)q.set("model_id",modelId);
  const out=$("live-compare-out"); const btn=$("btn-live-compare"); if(btn)btn.disabled=true;
  out.innerHTML='<div class="card loading">Comparing conservative, balanced and responsive conditions…</div>';
  try{
    const d=await api(`/api/v4/realtime/${encodeURIComponent(ticker)}/compare${q.toString()?`?${q}`:""}`);
    const conditions=d.conditions||[];
    const PROFILE_SUB={conservative:"reacts least to new information",balanced:"a middle setting",responsive:"reacts most to new information"};
    const anyApplied=conditions.some((row)=>row.adaptive_shift_applied);
    const cards=conditions.map((row)=>{const st=FCP.liveStateFromSnapshot({gate:{status:row.gate_status},adaptive_shift_applied:row.adaptive_shift_applied});return `<article class="condition-card"><h3>${esc(row.profile)}</h3><p class="meta">${esc(PROFILE_SUB[String(row.profile).toLowerCase()]||"")}</p><div class="condition-prob">${probabilityText(row.adaptive_applied_probability)}</div><p class="meta">current live forecast</p><p class="meta">base forecast ${probabilityText(row.anchor_probability)} · <strong>${esc(st.label)}</strong></p></article>`;}).join("");
    const lead=anyApplied?"Each sensitivity setting applies new information differently, within validated limits.":"Not enough completed outcomes yet (learning in progress), so every sensitivity setting currently returns the same validated base forecast. Differences appear only once live updates activate.";
    out.innerHTML=`<article class="card"><h2>${esc(ticker)} — sensitivity comparison</h2><p>${esc(lead)}</p><div class="condition-grid">${cards}</div><details class="gf-tech"><summary>Technical details — comparison contract</summary><p class="meta">${esc(d.comparison_contract||"")} No learning observation is queued by this comparison.</p></details><p class="meta">${esc(d.disclaimer||"")}</p></article>`;
  }catch(error){out.innerHTML=`<div class="error">${esc(error.message)}</div>`;}finally{if(btn)btn.disabled=false;}
}

async function processMatured(){
  const btn=$("btn-process-matured");btn.disabled=true;
  try{const d=await api("/api/v4/adaptive/process-matured",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});$("live-status").insertAdjacentHTML("afterbegin",`<div class="notice"><strong>Matured-label maintenance:</strong> ${num(d.processed)} processed · ${num(d.skipped)} skipped.</div>`);await loadLiveStatus();}catch(error){$("live-status").insertAdjacentHTML("afterbegin",`<div class="error">${esc(error.message)}</div>`);}finally{btn.disabled=false;}
}

function initEvents() {
  $("btn-analyze").addEventListener("click", analyze);
  $("btn-screener").addEventListener("click", loadScreener);
  if($("btn-market-browse"))$("btn-market-browse").addEventListener("click", browseMarketSector);
  $("btn-refresh").addEventListener("click", startRefresh);
  $("btn-export").addEventListener("click", exportScreener);
  $("btn-compare").addEventListener("click", compare);
  $("compare-tickers").addEventListener("keydown", (e) => { if (e.key === "Enter") compare(); });
  $("btn-watch-compare").addEventListener("click", compareWatchlist);
  $("btn-forecast").addEventListener("click", runGuidedFlow);
  initGuidedForecastDelegation();
  if($("btn-forecast-compare-models"))$("btn-forecast-compare-models").addEventListener("click", runForecastModelCompare);
  if($("btn-activate-selected-model"))$("btn-activate-selected-model").addEventListener("click", activateSelectedForecastModel);
  if($("btn-deactivate-model"))$("btn-deactivate-model").addEventListener("click", deactivateActiveModel);
  $("forecast-ticker").addEventListener("keydown", (e) => { if (e.key === "Enter") runGuidedFlow(); });
  if($("forecast-horizon"))$("forecast-horizon").addEventListener("change", runGuidedFlow);
  $("btn-forecast-status").addEventListener("click", loadForecastStatus);
  if($("btn-build-model"))$("btn-build-model").addEventListener("click", startModelBuild);
  if($("btn-guided-update-train"))$("btn-guided-update-train").addEventListener("click", guidedUpdateAndTrain);
  if($("build-recipe"))$("build-recipe").addEventListener("change", renderRecipeReadiness);
  if($("btn-update-research-data"))$("btn-update-research-data").addEventListener("click", startResearchRefresh);
  if($("btn-research-data"))$("btn-research-data").addEventListener("click", loadModelLab);
  if($("btn-refresh-experiments"))$("btn-refresh-experiments").addEventListener("click", loadModelLab);
  if($("model-lab-experiments"))$("model-lab-experiments").addEventListener("click",(event)=>{const btn=event.target.closest("[data-activate-experiment]");if(btn){event.preventDefault();activateExperiment(btn.dataset.activateExperiment);}});
  $("btn-live").addEventListener("click", ()=>runLive(false));
  if($("btn-live-compare"))$("btn-live-compare").addEventListener("click", runLiveCompare);
  $("live-ticker").addEventListener("keydown", (e) => { if (e.key === "Enter") runLive(false); });
  $("btn-live-status").addEventListener("click", loadLiveStatus);
  $("btn-process-matured").addEventListener("click", processMatured);
  if($("experience-mode"))$("experience-mode").addEventListener("change", changeExperienceMode);
  $("btn-save-runtime-settings").addEventListener("click", saveRuntimeSettings);
  $("btn-reset-settings").addEventListener("click", resetSettings);
  $("btn-validate-settings").addEventListener("click", validateTrainingSettings);
  $("btn-download-settings").addEventListener("click", downloadTrainingSettings);
  $("settings-profile").addEventListener("change", changeSettingsProfile);
  $("btn-validate-realtime-settings").addEventListener("click", validateRealtimeSettings);
  $("btn-download-realtime-settings").addEventListener("click", downloadRealtimeSettings);
  $("realtime-settings-profile").addEventListener("change", changeRealtimeSettingsProfile);
  $("screener-out").addEventListener("click", (event) => {
    const sort = event.target.closest("[data-sort-key]");
    if (sort) {
      const key=sort.dataset.sortKey; if(state.sortKey===key) state.sortDir=state.sortDir==="asc"?"desc":"asc"; else {state.sortKey=key;state.sortDir=key==="ticker"?"asc":"desc";} renderScreener(); return;
    }
  });
  document.addEventListener("click", (event) => {
    const watch=event.target.closest("[data-watch-toggle]"); if(watch){toggleWatch(watch.dataset.watchToggle);return;}
    const marketPageButton=event.target.closest("[data-market-page]"); if(marketPageButton && !marketPageButton.disabled){browseMarketSector(Number(marketPageButton.dataset.marketPage)||0);return;}
    const analyzeButton=event.target.closest("[data-analyze-ticker]"); if(analyzeButton){$("ticker").value=analyzeButton.dataset.analyzeTicker;showPage("analyze");analyze();return;}
    const printBtn=event.target.closest("[data-print]"); if(printBtn){window.print();}
  });
  let resizeTimer=null;
  window.addEventListener("resize",()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(redrawCharts,120);});
}

async function bootstrap() {
  initConsent(); initTabs(); initAutocomplete(); initEvents(); updateWatchCount(); applyExperienceMode(getExperienceMode()); applyRuntimeSettings(getRuntimeSettings());
  await Promise.all([loadUniverse(), loadMarketMeta(), api("/api/v1/health").then((h)=>{$("engine-badge").textContent=`Evidence ${h.engine_version} · Forecast ${h.forecast_engine_version||"—"} · Adaptive ${h.realtime_engine_version||"—"}`; if(h.forecast_registry){state.forecastRegistry=h.forecast_registry;populateModelSelects(h.forecast_registry);}}).catch(()=>{})]);
  renderWatchlist();
  api("/api/v1/screener/status").then((s)=>{if(String(s.status||"").toLowerCase().includes("running")){renderRefreshStatus(s);state.refreshTimer=setInterval(pollRefresh,1800);}}).catch(()=>{});
}

document.addEventListener("DOMContentLoaded", bootstrap);
