"use strict";
/*
  FinCompass Web — probabilistic Forecast, ported from the Python kernel:
    forecasting/features.py (build_monthly_relative_features) and
    forecasting/{bayesian,calibration,baseline}.py inference.

  The bundled Guided model is a Bayesian logistic classifier + calibrator. The
  browser loads the model's exported coefficients and its OWN precomputed
  posterior draws (web/models/forecast-<h>m.json) and reproduces the desktop
  point probability and credible interval bit-for-bit — no Python, no RNG.

  Parity is enforced by tests/test_web_forecast_parity.py (Node vs Python).
*/
const FCForecast = (() => {
  const sigmoid = (z) => 1 / (1 + Math.exp(-z));
  const clip = (p) => Math.min(Math.max(p, 1e-6), 1 - 1e-6);

  // ---- month-end resampling: last close per calendar month, ascending ----
  function monthEndClose(bars) {
    const byMonth = new Map();
    for (const b of bars) {
      if (!b || b.close == null || !Number.isFinite(Number(b.close))) continue;
      const ym = String(b.date).slice(0, 7); // YYYY-MM
      byMonth.set(ym, Number(b.close));       // later bar in the month overwrites -> last close
    }
    return [...byMonth.entries()].sort((a, b) => (a[0] < b[0] ? -1 : 1));
  }

  const pctChange = (arr, i, lag) => (i - lag >= 0 && arr[i - lag] ? arr[i] / arr[i - lag] - 1 : NaN);

  function sampleStd(xs) {
    const v = xs.filter(Number.isFinite);
    if (v.length < 2) return NaN;
    const m = v.reduce((s, x) => s + x, 0) / v.length;
    return Math.sqrt(v.reduce((s, x) => s + (x - m) ** 2, 0) / (v.length - 1));
  }
  const mean = (xs) => { const v = xs.filter(Number.isFinite); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : NaN; };
  const maxOf = (xs) => { const v = xs.filter(Number.isFinite); return v.length ? Math.max(...v) : NaN; };

  // The 8 features the reference model uses, computed at the latest aligned month.
  function buildFeatures(stockBars, benchBars) {
    const s = monthEndClose(stockBars), b = monthEndClose(benchBars);
    const bMap = new Map(b);
    const months = s.map(([ym]) => ym).filter((ym) => bMap.has(ym));
    if (months.length < 13) return null; // need ~13 months for the 12m features
    const close = months.map((ym) => s.find((r) => r[0] === ym)[1]);
    const bclose = months.map((ym) => bMap.get(ym));
    const i = months.length - 1;

    const relRet = (lag) => pctChange(close, i, lag) - pctChange(bclose, i, lag);
    // monthly simple returns; index k return uses close[k]/close[k-1]-1
    const ret = (arr) => arr.map((_, k) => (k >= 1 ? arr[k] / arr[k - 1] - 1 : NaN));
    const sRet = ret(close), bRet = ret(bclose);
    // rolling std over a window ending at i, requiring >= minP valid values
    const rollStd = (arr, win, minP) => { const w = arr.slice(Math.max(0, i - win + 1), i + 1).filter(Number.isFinite); return w.length >= minP ? sampleStd(w) : NaN; };
    const win = (arr, w) => arr.slice(Math.max(0, i - w + 1), i + 1);

    const vol6 = rollStd(sRet, 6, 3) * Math.sqrt(12);
    const bvol6 = rollStd(bRet, 6, 3) * Math.sqrt(12);
    const dd12win = win(close, 12); const dd12 = dd12win.filter(Number.isFinite).length >= 6 ? close[i] / maxOf(dd12win) - 1 : NaN;
    const sma3win = win(close, 3), sma12win = win(close, 12);
    const sma3 = sma3win.filter(Number.isFinite).length >= 3 ? mean(sma3win) : NaN;
    const sma12 = sma12win.filter(Number.isFinite).length >= 6 ? mean(sma12win) : NaN;
    const sma_3_12 = Number.isFinite(sma3) && Number.isFinite(sma12) ? sma3 / sma12 - 1 : NaN;

    return {
      asOf: months[i],
      features: {
        rel_ret_1m: relRet(1), rel_ret_3m: relRet(3), rel_ret_6m: relRet(6), rel_ret_12m: relRet(12),
        vol_6m: vol6, benchmark_vol_6m: bvol6, drawdown_12m: dd12, sma_3_12,
      },
    };
  }

  // ---- inference from the exported model + its shipped posterior draws ----
  function _decodeDraws(js) {
    const bin = atob(js.beta_draws_b64);
    const bytes = new Uint8Array(bin.length);
    for (let k = 0; k < bin.length; k++) bytes[k] = bin.charCodeAt(k);
    return new Float32Array(bytes.buffer); // draws * (n+1), row-major, little-endian
  }
  function _calibrate(cal, p) {
    p = clip(p);
    if (cal.method === "sigmoid") { const x = Math.log(p / (1 - p)); return clip(sigmoid(cal.a * x + cal.b)); }
    // isotonic: clamped linear interpolation over (x -> y)
    const xs = cal.x, ys = cal.y;
    if (p <= xs[0]) return clip(ys[0]);
    if (p >= xs[xs.length - 1]) return clip(ys[ys.length - 1]);
    let k = 1; while (k < xs.length && xs[k] < p) k++;
    const t = (p - xs[k - 1]) / (xs[k] - xs[k - 1] || 1);
    return clip(ys[k - 1] + t * (ys[k] - ys[k - 1]));
  }
  // numpy default 'linear' quantile on a sorted array.
  function quantile(sorted, q) {
    const N = sorted.length; if (!N) return NaN;
    const pos = q * (N - 1), lo = Math.floor(pos), frac = pos - lo;
    return lo + 1 < N ? sorted[lo] + frac * (sorted[lo + 1] - sorted[lo]) : sorted[lo];
  }

  function forecast(js, featureObj) {
    const names = js.feature_names, n = js.coef.length;
    const raw = names.map((nm) => Number(featureObj[nm]));
    const med = js.medians, mean_ = js.means, scale = js.scales;
    const Xs = raw.map((x, k) => ((Number.isFinite(x) ? x : med[k]) - mean_[k]) / scale[k]);
    const Xa = [1, ...Xs];                       // intercept + standardized features
    const beta = _decodeDraws(js), draws = js.draws;
    const probs = new Float64Array(draws);
    for (let d = 0; d < draws; d++) {
      let z = 0; const off = d * n;
      for (let k = 0; k < n; k++) z += Xa[k] * beta[off + k];
      probs[d] = sigmoid(z);
    }
    const sorted = Array.from(probs).sort((a, b) => a - b);
    const rawMean = probs.reduce((s, x) => s + x, 0) / draws;
    const tail = (1 - js.credible_level) / 2;
    const point = _calibrate(js.calibrator, rawMean);
    let lo = _calibrate(js.calibrator, quantile(sorted, tail));
    let hi = _calibrate(js.calibrator, quantile(sorted, 1 - tail));
    if (lo > hi) { const t = lo; lo = hi; hi = t; }
    const abstain = (lo <= 0.5 && 0.5 <= hi) || Math.abs(point - 0.5) <= 0.03;
    return {probability_outperform: point, uncertainty_interval: [lo, hi], abstain,
      evidence_tier: js.validation_tier, horizon_months: js.horizon_months,
      benchmark: js.benchmark, event: js.event, as_of: featureObj.__asOf || null,
      disclaimer: js.disclaimer};
  }

  return {monthEndClose, buildFeatures, forecast, _calibrate, quantile};
})();
if (typeof module !== "undefined" && module.exports) module.exports = FCForecast;
