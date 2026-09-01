"use strict";
/* FinCompass Web — UI. All computation is client-side via engine.js (FC). */
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const fin = (x) => Number.isFinite(Number(x));
  const money = (x) => fin(x) ? Number(x).toLocaleString(undefined, {maximumFractionDigits: 2}) : "—";
  const pct = (x, d = 1) => fin(x) ? (Number(x) * 100).toFixed(d) + "%" : "—";
  const num = (x, d = 3) => fin(x) ? Number(x).toFixed(d) : "—";
  const kpi = (k, v, tip) => `<div class="kpi"><div class="k"${tip ? ` title="${esc(tip)}"` : ""}>${k}</div><div class="v">${v}</div></div>`;

  // ---- Tabs ----
  document.getElementById("tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]"); if (!b) return;
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + b.dataset.tab));
    if (b.dataset.tab === "reference") loadGlossary();
    if (b.dataset.tab === "forecast") refreshProxyUI();
  });
  const onSubmit = (id, fn) => $(id).addEventListener("submit", (e) => { e.preventDefault(); fn(new FormData(e.target)); });
  const val = (fd, n) => Number(fd.get(n));

  // ---- DCF ----
  onSubmit("f-dcf", (fd) => {
    const fcf = val(fd, "fcf"), gh = val(fd, "ghigh"), gs = val(fd, "gstable"), wacc = val(fd, "wacc"),
      tg = val(fd, "tg"), nd = val(fd, "netdebt"), sh = val(fd, "shares"), price = fd.get("price") ? val(fd, "price") : null;
    const base = FC.dcfFromFCF(fcf, FC.threeStageGrowthPath(gh, gs, 5, 5), wacc, tg, nd, sh);
    if (!base.valid) { $("o-dcf").innerHTML = `<p class="verdict warn">Check the inputs — a DCF needs a positive base cash flow, WACC above terminal growth, and shares.</p>`; return; }
    // A small WACC band for a range, so the answer is a scenario not a false point.
    const vals = [wacc - 0.01, wacc, wacc + 0.01, wacc + 0.02].filter((w) => w > tg).map((w) =>
      FC.dcfFromFCF(fcf, FC.threeStageGrowthPath(gh, gs, 5, 5), w, tg, nd, sh).valuePerShare).filter(fin);
    const lo = Math.min(...vals), hi = Math.max(...vals), mid = base.valuePerShare;
    const termPct = base.pvTerminalValue / base.enterpriseValue;
    const ig = price != null ? FC.impliedFcfGrowth(price, fcf, wacc, tg, nd, sh, 5, 5, gs) : null;
    let verdict = "", cls = "neutral";
    if (price != null && fin(price)) {
      if (price > hi) { cls = "warn"; verdict = `The market price (${money(price)}) is above this conservative estimate — it's pricing in stronger growth than assumed.`; }
      else if (price < lo) { cls = "good"; verdict = `The market price (${money(price)}) is below this estimate — it may be cheap, or the market expects the business to shrink.`; }
      else { verdict = `The market price (${money(price)}) sits inside the estimate — roughly fairly priced on these assumptions.`; }
    }
    $("o-dcf").innerHTML = `
      <p class="plain">Estimated fair value: <strong>${money(lo)} – ${money(hi)}</strong> per share (central ${money(mid)}).</p>
      ${verdict ? `<div class="verdict ${cls}">${esc(verdict)}</div>` : ""}
      ${ig != null ? `<p class="plain">Reverse DCF: at ${money(price)}, the market is pricing in about <strong>${pct(ig)}</strong> free-cash-flow growth a year for five years. Ask whether that's realistic — that number is what you're really betting on.</p>` : ""}
      <div class="kpis">
        ${kpi("Value / share", money(mid))}
        ${kpi("Terminal value", money(base.terminalValue))}
        ${kpi("Terminal % of EV", pct(termPct), "Share of the value that rests on the perpetual assumption. High = fragile.")}
        ${kpi("Enterprise value", money(base.enterpriseValue))}
        ${kpi("Equity value", money(base.equityValue))}
        ${ig != null ? kpi("Market-implied growth", pct(ig)) : ""}
      </div>
      <p class="meta">Conservative by design: models that assume higher growth or an exit multiple produce higher numbers. A DCF is one input, not a verdict — change growth a few points or the rate 1% and it swings a lot.</p>`;
  });

  // ---- Options ----
  onSubmit("f-opt", (fd) => {
    const type = fd.get("type"), S = val(fd, "spot"), K = val(fd, "strike"), r = val(fd, "rate"),
      vol = val(fd, "vol"), T = val(fd, "expiry"), q = val(fd, "div");
    const p = FC.bsPrice(type, S, K, r, vol, T, q), g = FC.greeks(type, S, K, r, vol, T, q);
    if (!fin(p)) { $("o-opt").innerHTML = `<p class="verdict warn">Check the inputs — spot, strike, volatility and time must be positive.</p>`; return; }
    const isCall = type === "call", be = isCall ? K + p : K - p;
    $("o-opt").innerHTML = `
      <p class="plain">This ${type} is worth <strong>${money(p)}</strong>. You profit if the stock is ${isCall ? "above" : "below"} <strong>${money(be)}</strong> at expiry; the most a long position can lose is the <strong>${money(p)}</strong> premium.</p>
      ${payoffSvg(type, K, p, S)}
      <div class="kpis">
        ${kpi("Price (premium)", money(p))}
        ${kpi("Break-even", money(be))}
        ${kpi("Delta", num(g.delta), "Change in option value per $1 move in the stock.")}
        ${kpi("Gamma", num(g.gamma), "Change in Delta per $1 move — how fast Delta shifts.")}
        ${kpi("Vega (per 1.00 vol)", money(g.vega), "Value change per 1.00 (100 percentage-point) change in volatility. Divide by 100 for per 1%.")}
        ${kpi("Theta (per year)", money(g.theta), "Value lost per year from time decay. Divide by 365 for per day.")}
        ${kpi("Rho", money(g.rho), "Value change per 1.00 change in the interest rate.")}
      </div>
      <p class="meta">European Black-Scholes-Merton: single volatility, constant rate, dividend yield ${pct(q)}. The chart is profit/loss <strong>at expiry</strong>; the Greeks describe the option's value <strong>before</strong> expiry.</p>`;
  });

  function payoffSvg(type, K, premium, spot) {
    const isCall = String(type) === "call";
    const be = isCall ? K + premium : K - premium;
    const anchors = [K, be, spot].filter((x) => fin(x) && x > 0);
    const lo = Math.max(0, Math.min(...anchors) * 0.7), hi = Math.max(...anchors) * 1.3, span = (hi - lo) || 1;
    const pl = (s) => (isCall ? Math.max(s - K, 0) : Math.max(K - s, 0)) - premium;
    const N = 60, pts = []; for (let i = 0; i <= N; i++) { const s = lo + span * i / N; pts.push([s, pl(s)]); }
    let ymin = Math.min(-premium, ...pts.map((p) => p[1])), ymax = Math.max(premium * 0.6, ...pts.map((p) => p[1]));
    const pad = ((ymax - ymin) * 0.12) || 1; ymin -= pad; ymax += pad;
    const W = 440, H = 200, mL = 52, mR = 14, mT = 14, mB = 32, pw = W - mL - mR, ph = H - mT - mB;
    const X = (s) => mL + (s - lo) / span * pw, Y = (v) => mT + (ymax - v) / (ymax - ymin) * ph;
    const path = pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ");
    const zeroY = Y(0);
    const vline = (s, col) => (fin(s) && s >= lo && s <= hi) ? `<line x1="${X(s).toFixed(1)}" y1="${mT}" x2="${X(s).toFixed(1)}" y2="${mT + ph}" stroke="${col}" stroke-width="1.2" stroke-dasharray="4 3"/>` : "";
    const lbl = (s, t, dy) => (fin(s) && s >= lo && s <= hi) ? `<text x="${X(s).toFixed(1)}" y="${dy}" fill="#9fb0c5" font-size="10" text-anchor="middle">${esc(t)}</text>` : "";
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Option profit and loss at expiry">
      <rect x="${mL}" y="${mT}" width="${pw}" height="${(zeroY - mT).toFixed(1)}" fill="rgba(46,158,91,.12)"/>
      <rect x="${mL}" y="${zeroY.toFixed(1)}" width="${pw}" height="${(mT + ph - zeroY).toFixed(1)}" fill="rgba(217,134,52,.12)"/>
      <line x1="${mL}" y1="${zeroY.toFixed(1)}" x2="${mL + pw}" y2="${zeroY.toFixed(1)}" stroke="#5a6a80" stroke-width="1"/>
      ${vline(K, "#3f7cc0")}${vline(be, "#d98634")}${fin(spot) ? vline(spot, "#e6edf6") : ""}
      <path d="${path}" fill="none" stroke="#7db1f0" stroke-width="2"/>
      <text x="${mL - 6}" y="${(zeroY + 3).toFixed(1)}" fill="#9fb0c5" font-size="10" text-anchor="end">$0</text>
      ${lbl(K, "strike " + money(K), mT - 3)}${lbl(be, "break-even", mT + ph + 22)}${fin(spot) ? lbl(spot, "now " + money(spot), mT - 3) : ""}
    </svg>`;
  }

  // ---- Bonds ----
  onSubmit("f-bond", (fd) => {
    const face = val(fd, "face"), cr = val(fd, "coupon"), ytm = val(fd, "ytm"), yrs = val(fd, "years"), fq = val(fd, "freq");
    const price = FC.bondPrice(face, cr, ytm, yrs, fq);
    if (!fin(price)) { $("o-bond").innerHTML = `<p class="verdict warn">Check the inputs — face, years and coupons/year must be positive.</p>`; return; }
    const disc = price < face ? "at a discount" : price > face ? "at a premium" : "at par";
    $("o-bond").innerHTML = `
      <p class="plain">This bond is worth about <strong>${money(price)}</strong> — trading ${disc} to its ${money(face)} face value. It pays a ${pct(cr)} coupon, priced to yield ${pct(ytm)} to maturity.</p>
      <div class="kpis">
        ${kpi("Price", money(price))}
        ${kpi("Current yield", pct(FC.currentYield(face, cr, price)), "Annual coupon ÷ price; ignores capital gain to maturity.")}
        ${kpi("Duration", num(FC.macaulayDuration(face, cr, ytm, yrs, fq), 2) + " yr", "PV-weighted average time to the cash flows.")}
        ${kpi("Modified duration", num(FC.modifiedDuration(face, cr, ytm, yrs, fq), 2), "Approx % price change for a 1-point yield move.")}
        ${kpi("Convexity", num(FC.convexity(face, cr, ytm, yrs, fq), 2), "Curvature of the price/yield curve; refines duration.")}
        ${kpi("DV01", num(FC.dv01(face, cr, ytm, yrs, fq), 4), "Price change for a 1 basis-point yield move.")}
      </div>
      <p class="meta"><strong>A Treasury yield is not the required yield for this bond.</strong> Treasury rates are risk-free references; a corporate or otherwise risky bond must be priced at the Treasury rate <em>plus a credit spread</em>. Enter the actual required yield, not a bare Treasury rate.</p>`;
  });

  // ---- Portfolio ----
  onSubmit("f-pf", (fd) => {
    const wa = val(fd, "wa"), wb = val(fd, "wb"), va = val(fd, "va"), vb = val(fd, "vb"), corr = val(fd, "corr");
    const cov = [[va * va, corr * va * vb], [corr * va * vb, vb * vb]];
    const rc = FC.riskContributions([wa, wb], cov);
    if (!fin(rc.volatility)) { $("o-pf").innerHTML = `<p class="verdict warn">Check the inputs.</p>`; return; }
    const vol = rc.volatility * 100, names = ["A", "B"];
    const wsum = wa + wb;
    const weightedAvg = wsum > 0 ? (wa * va + wb * vb) / wsum * 100 : NaN;
    const cut = weightedAvg - vol;
    const benefit = fin(cut) && cut > 0.05 ? ` On their own they'd average about ±${weightedAvg.toFixed(1)}%; mixing them trims that to <strong>${vol.toFixed(1)}%</strong> — a ${cut.toFixed(1)}% diversification benefit from not moving in lock-step.` : "";
    const bars = rc.percent.map((p, i) => `<div class="row"><span style="width:1.4em">${names[i]}</span><span class="bar"><span class="fill" style="width:${Math.max(0, Math.min(100, p * 100)).toFixed(1)}%"></span></span><span style="width:3em;text-align:right">${fin(p) ? (p * 100).toFixed(0) + "%" : "—"}</span></div>`).join("");
    const rows = rc.percent.map((p, i) => `<tr><td>${names[i]}</td><td>${num([wa, wb][i], 2)}</td><td>${num(rc.marginal[i], 4)}</td><td>${pct(rc.component[i], 2)}</td><td>${pct(p, 0)}</td></tr>`).join("");
    $("o-pf").innerHTML = `
      <p class="plain">Together these two holdings typically swing about ±<strong>${vol.toFixed(1)}%</strong> over a year.${benefit}</p>
      <p class="plain">Where the risk comes from — each holding's share of that swing:</p>
      <div class="bars">${bars}</div>
      <table class="mini"><thead><tr><th>Holding</th><th>Weight</th><th>Marginal</th><th>Component</th><th>% of risk</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="meta">The covariance is built from the volatilities and correlation you entered (a single annualized period), not a return history. Under stress, correlations move toward 1, so the diversification benefit shrinks when it's needed most.</p>`;
  });

  // ---- Forecast ----
  const MODEL_CACHE = {};
  const TIER_LABEL = {bayesian_baseline: "Limited evidence", validated_research: "Research validated", validated_market: "Market validated"};
  async function loadModel(h) {
    if (!MODEL_CACHE[h]) MODEL_CACHE[h] = await (await fetch(`models/forecast-${h}m.json`)).json();
    return MODEL_CACHE[h];
  }
  function refreshProxyUI() {
    const setup = $("proxy-setup"); if (!setup) return;
    setup.style.display = FCData.hasProxy() ? "none" : "block";
    if (FCData.hasProxy() && $("proxy-url")) $("proxy-url").value = FCData.getProxy();
  }
  function probGauge(p, lo, hi) {
    const W = 440, H = 52, mL = 10, mR = 10, y = 26, bw = W - mL - mR, X = (v) => mL + Math.max(0, Math.min(1, v)) * bw;
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Probability with uncertainty range">
      <text x="${mL}" y="14" fill="#9fb0c5" font-size="10">0%</text>
      <text x="${X(0.5).toFixed(1)}" y="14" fill="#9fb0c5" font-size="10" text-anchor="middle">50% · coin flip</text>
      <text x="${W - mR}" y="14" fill="#9fb0c5" font-size="10" text-anchor="end">100%</text>
      <rect x="${mL}" y="${y}" width="${bw}" height="10" rx="5" fill="#0b1220"/>
      <rect x="${X(lo).toFixed(1)}" y="${y}" width="${(X(hi) - X(lo)).toFixed(1)}" height="10" rx="5" fill="rgba(63,124,192,.55)"/>
      <line x1="${X(0.5).toFixed(1)}" y1="${y - 5}" x2="${X(0.5).toFixed(1)}" y2="${y + 15}" stroke="#5a6a80" stroke-dasharray="3 3"/>
      <circle cx="${X(p).toFixed(1)}" cy="${y + 5}" r="6" fill="#7db1f0"/>
    </svg>`;
  }
  function forecastHtml(ticker, fc, asOf, model) {
    const p = fc.probability_outperform, lo = fc.uncertainty_interval[0], hi = fc.uncertainty_interval[1];
    const watchOnly = fc.evidence_tier === "bayesian_baseline";
    const tl = TIER_LABEL[fc.evidence_tier] || fc.evidence_tier;
    return `
      <p class="plain">Estimated probability that <strong>${esc(ticker)}</strong> beats the S&amp;P 500 over <strong>${fc.horizon_months} months</strong>: <strong>${(p * 100).toFixed(0)}%</strong>.</p>
      ${probGauge(p, lo, hi)}
      <div class="kpis">
        ${kpi("Probability", (p * 100).toFixed(1) + "%")}
        ${kpi("Uncertainty range", `${(lo * 100).toFixed(0)}–${(hi * 100).toFixed(0)}%`, "90% credible interval from posterior coefficient uncertainty.")}
        ${kpi("Evidence", tl)}
        ${kpi("As of", asOf || "—")}
      </div>
      <div class="verdict ${p > 0.5 ? "good" : "neutral"}">${watchOnly ? "Limited evidence — a valid, calibrated probability, but stronger out-of-sample skill is not established. Treat as watch-only, not a buy/sell signal." : "Validated model."}</div>
      ${fc.abstain ? `<p class="meta"><strong>Too close to call:</strong> the range straddles 50%, so there is no clear directional signal.</p>` : ""}
      <p class="meta">Defined event: outperform ${esc(model.benchmark || "^GSPC")} over ${fc.horizon_months} months by more than ${((model.excess_return_threshold || 0) * 100).toFixed(0)}%. This is the same Bayesian reference model as the desktop app, run in your browser. ${esc(fc.disclaimer || "")}</p>
      <p class="meta">It does <strong>not</strong> mean the stock rises ${(p * 100).toFixed(0)}%, that the model is ${(p * 100).toFixed(0)}% accurate, or that you should buy or sell.</p>`;
  }
  $("f-fc").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const ticker = String(fd.get("ticker") || "").trim().toUpperCase(), h = fd.get("horizon"), out = $("o-fc");
    if (!ticker) { out.innerHTML = `<p class="verdict warn">Enter a ticker.</p>`; return; }
    if (!FCData.hasProxy()) { refreshProxyUI(); out.innerHTML = `<p class="verdict warn">Set the data source above first — it is a one-time step.</p>`; return; }
    out.innerHTML = `<p class="meta">Fetching prices and computing…</p>`;
    try {
      const model = await loadModel(h);
      const [sb, bb] = await Promise.all([FCData.dailyBars(ticker), FCData.dailyBars(model.benchmark || "^GSPC")]);
      const built = FCForecast.buildFeatures(sb, bb);
      if (!built) { out.innerHTML = `<p class="verdict warn">Not enough monthly price history for ${esc(ticker)} to compute the model features.</p>`; return; }
      out.innerHTML = forecastHtml(ticker, FCForecast.forecast(model, built.features), built.asOf, model);
    } catch (err) {
      out.innerHTML = `<p class="verdict warn">${esc(err.message === "no_proxy" ? "Set the data source above first." : err.message)}</p>`;
    }
  });
  if ($("save-proxy")) $("save-proxy").addEventListener("click", () => { FCData.setProxy($("proxy-url").value); refreshProxyUI(); });
  refreshProxyUI();

  // ---- Shared ticker: fill the DCF and Options desks from a real company ----
  const _cagr = (newestFirst) => {
    const v = (newestFirst || []).filter((x) => Number.isFinite(x) && x > 0);
    if (v.length < 2) return null;
    const n = v.length - 1;
    return (v[0] / v[v.length - 1]) ** (1 / n) - 1;
  };
  function dcfInputsFromFundamentals(f) {
    const hist = (f.fcf_history || []).filter(Number.isFinite);
    const positive = hist.slice(0, 3).filter((x) => x > 0);
    const baseFcf = positive.length >= 2 ? positive.reduce((s, x) => s + x, 0) / positive.length : (hist[0] || null);
    if (!Number.isFinite(baseFcf) || !(f.shares > 0)) return null;
    let g = _cagr(f.fcf_history); if (g == null) g = _cagr(f.revenue_history);
    g = Math.max(0.05, Math.min(0.20, g == null ? 0.08 : g));       // same band as desktop
    const stable = Math.min(0.03, Math.max(0.02, g * 0.5));
    return {fcf: baseFcf, ghigh: g, gstable: stable, wacc: 0.09, tg: 0.025, netdebt: f.net_debt || 0, shares: f.shares};
  }
  function setForm(id, values) {
    const form = $(id);
    Object.entries(values).forEach(([k, v]) => { const el = form.querySelector(`[name="${k}"]`); if (el && v != null && isFinite(v)) el.value = Number(v).toPrecision(6).replace(/\.?0+$/, ""); });
  }
  async function loadTicker() {
    const ticker = ($("load-ticker").value || "").trim().toUpperCase();
    const note = $("load-note");
    if (!ticker) { note.textContent = "Enter a ticker."; return; }
    if (!FCData.hasProxy()) {
      note.innerHTML = `Set the data source first — open the <strong>Forecast</strong> tab and paste your free data-proxy URL (one-time).`;
      document.querySelector('#tabs button[data-tab="forecast"]').click();
      return;
    }
    note.textContent = `Loading ${ticker}…`;
    try {
      const [bars, fund] = await Promise.all([FCData.dailyBars(ticker), FCData.fundamentals(ticker).catch(() => null)]);
      const spot = bars[bars.length - 1].close, vol = FCData.historicalVol(bars);
      setForm("f-opt", {spot, strike: spot, vol: vol || 0.3});
      $("f-opt").dispatchEvent(new Event("submit"));
      $("f-fc").querySelector('[name="ticker"]').value = ticker;
      let dcfMsg = "";
      const dcf = fund ? dcfInputsFromFundamentals(fund) : null;
      if (dcf) { setForm("f-dcf", dcf); $("f-dcf").dispatchEvent(new Event("submit")); dcfMsg = "DCF"; }
      else dcfMsg = "DCF (fundamentals unavailable — enter manually)";
      note.innerHTML = `<strong>${esc(ticker)}</strong> loaded — Options (spot ${money(spot)}, vol ${pct(vol)}) and ${dcfMsg} updated. Forecast ticker set.`;
    } catch (err) {
      note.textContent = err.message === "no_proxy" ? "Set the data source first (Forecast tab)." : err.message;
    }
  }
  $("load-ticker-btn").addEventListener("click", loadTicker);
  $("load-ticker").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); loadTicker(); } });

  // ---- Glossary ----
  let GLOSSARY = null;
  const gnorm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9 ]/g, "").replace(/\s+/g, " ").trim();
  async function loadGlossary() {
    if (!GLOSSARY) {
      try { GLOSSARY = await (await fetch("glossary.json")).json(); }
      catch (e) { GLOSSARY = {terms: [], categories: []}; }
      const sel = $("g-cat");
      (GLOSSARY.categories || []).forEach((c) => { const o = document.createElement("option"); o.value = c; o.textContent = c; sel.appendChild(o); });
      $("g-search").addEventListener("input", renderGlossary);
      $("g-cat").addEventListener("change", renderGlossary);
    }
    renderGlossary();
  }
  function renderGlossary() {
    const terms = (GLOSSARY && GLOSSARY.terms) || [], box = $("o-glossary");
    if (!terms.length) { box.innerHTML = `<p class="meta">Glossary unavailable.</p>`; return; }
    const q = gnorm($("g-search").value), cat = $("g-cat").value;
    const m = terms.filter((t) => (!cat || t.category === cat) && (!q || gnorm(t.term).includes(q) || gnorm(t.plain_meaning).includes(q) || gnorm(t.category).includes(q)));
    box.innerHTML = `<p class="meta">${m.length} of ${terms.length} terms.</p>` + m.map((t) => `
      <details class="g"><summary><strong>${esc(t.term)}</strong><span class="pill">${esc(t.category)}</span></summary>
        <p>${esc(t.plain_meaning)}</p>
        <dl class="gf">
          ${t.why_it_matters ? `<dt>Why it matters</dt><dd>${esc(t.why_it_matters)}</dd>` : ""}
          ${t.fincompass_use ? `<dt>How FinCompass uses it</dt><dd>${esc(t.fincompass_use)}</dd>` : ""}
          ${t.limitation ? `<dt>Limitation</dt><dd>${esc(t.limitation)}</dd>` : ""}
          ${t.technical_definition ? `<dt>Technical</dt><dd>${esc(t.technical_definition)}${t.formula ? ` <code>${esc(t.formula)}</code>` : ""}</dd>` : ""}
        </dl>
      </details>`).join("") || `<p class="meta">No terms match.</p>`;
  }

  // Compute the defaults on load so each tab shows a worked example immediately.
  ["f-dcf", "f-opt", "f-bond", "f-pf"].forEach((id) => $(id).dispatchEvent(new Event("submit")));
})();
