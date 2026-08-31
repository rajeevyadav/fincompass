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
