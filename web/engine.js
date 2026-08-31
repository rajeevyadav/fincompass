"use strict";
/*
  FinCompass Web — deterministic analytics engine, ported 1:1 from the Python
  kernel (analytics/options.py, fixed_income.py, valuation.py, portfolio.py).
  Runs entirely in the browser: no server, no data fetch, no dependencies.

  Every function fails safely to NaN on unusable inputs rather than throwing, so
  the UI can show "—" instead of crashing. Parity with the Python is covered by
  tests/test_web_engine_parity.py.
*/
const FC = (() => {
  const NaNv = Number.NaN;
  const isFinitePos = (...xs) => xs.every((x) => Number.isFinite(x) && x > 0);

  // erf via Abramowitz & Stegun 7.1.26 (max error ~1.5e-7) — JS has no Math.erf.
  function erf(x) {
    const s = x < 0 ? -1 : 1;
    x = Math.abs(x);
    const t = 1 / (1 + 0.3275911 * x);
    const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
    return s * y;
  }
  const normCdf = (x) => 0.5 * (1 + erf(x / Math.SQRT2));
  const normPdf = (x) => Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);

  // ---- Options: Black-Scholes-Merton (European) ----
  function _d1d2(S, K, r, q, vol, T) {
    const vs = vol * Math.sqrt(T);
    const d1 = (Math.log(S / K) + (r - q + 0.5 * vol * vol) * T) / vs;
    return [d1, d1 - vs];
  }
  function bsPrice(type, S, K, r, vol, T, q = 0) {
    if (!isFinitePos(S, K, vol, T)) return NaNv;
    const [d1, d2] = _d1d2(S, K, r, q, vol, T);
    const ds = S * Math.exp(-q * T), dk = K * Math.exp(-r * T);
    return type === "call" ? ds * normCdf(d1) - dk * normCdf(d2) : dk * normCdf(-d2) - ds * normCdf(-d1);
  }
  function greeks(type, S, K, r, vol, T, q = 0) {
    if (!isFinitePos(S, K, vol, T)) return {delta: NaNv, gamma: NaNv, vega: NaNv, theta: NaNv, rho: NaNv};
    const [d1, d2] = _d1d2(S, K, r, q, vol, T);
    const ds = S * Math.exp(-q * T), dk = K * Math.exp(-r * T), edqt = Math.exp(-q * T);
    const delta = type === "call" ? edqt * normCdf(d1) : edqt * (normCdf(d1) - 1);
    const gamma = edqt * normPdf(d1) / (S * vol * Math.sqrt(T));
    const vega = ds * normPdf(d1) * Math.sqrt(T);
    const term = -ds * normPdf(d1) * vol / (2 * Math.sqrt(T));
    const theta = type === "call"
      ? term - r * dk * normCdf(d2) + q * ds * normCdf(d1)
      : term + r * dk * normCdf(-d2) - q * ds * normCdf(-d1);
    const rho = type === "call" ? dk * T * normCdf(d2) : -dk * T * normCdf(-d2);
    return {delta, gamma, vega, theta, rho};
  }

  // ---- Fixed income ----
  function _cashFlows(face, couponRate, years, freq) {
    const n = Math.round(years * freq), coupon = face * couponRate / freq, out = [];
    for (let t = 1; t <= n; t++) out.push([t, coupon + (t === n ? face : 0)]);
    return out;
  }
  const _bondValid = (face, couponRate, years, freq) =>
    isFinitePos(face, years) && Number.isFinite(couponRate) && couponRate >= 0 && Number.isInteger(freq) && freq > 0;
  function bondPrice(face, couponRate, ytm, years, freq = 2) {
    if (!_bondValid(face, couponRate, years, freq) || !Number.isFinite(ytm)) return NaNv;
    const y = ytm / freq;
    if (y <= -1) return NaNv;
    return _cashFlows(face, couponRate, years, freq).reduce((s, [t, cf]) => s + cf / (1 + y) ** t, 0);
  }
  function yieldToMaturity(price, face, couponRate, years, freq = 2, lo = -0.5, hi = 2, iters = 200) {
    if (!isFinitePos(price) || !_bondValid(face, couponRate, years, freq)) return NaNv;
    const f = (y) => bondPrice(face, couponRate, y, years, freq) - price;
    let flo = f(lo), fhi = f(hi);
    if (!Number.isFinite(flo) || !Number.isFinite(fhi) || flo * fhi > 0) return NaNv;
    let mid = 0.5 * (lo + hi);
    for (let i = 0; i < iters; i++) {
      mid = 0.5 * (lo + hi);
      const fm = f(mid);
      if (!Number.isFinite(fm)) return NaNv;
      if (Math.abs(fm) < 1e-9) return mid;
      if (flo * fm < 0) { hi = mid; fhi = fm; } else { lo = mid; flo = fm; }
    }
    return mid;
  }
  const currentYield = (face, couponRate, price) =>
    isFinitePos(price) && _finiteN(face, couponRate) ? (face * couponRate) / price : NaNv;
  function macaulayDuration(face, couponRate, ytm, years, freq = 2) {
    const price = bondPrice(face, couponRate, ytm, years, freq);
    if (!(price > 0) || !Number.isFinite(ytm)) return NaNv;
    const y = ytm / freq;
    if (y <= -1) return NaNv;
    const w = _cashFlows(face, couponRate, years, freq).reduce((s, [t, cf]) => s + (t / freq) * cf / (1 + y) ** t, 0);
    return w / price;
  }
  function modifiedDuration(face, couponRate, ytm, years, freq = 2) {
    const mac = macaulayDuration(face, couponRate, ytm, years, freq);
    return Number.isFinite(mac) ? mac / (1 + ytm / freq) : NaNv;
  }
  function convexity(face, couponRate, ytm, years, freq = 2) {
    const price = bondPrice(face, couponRate, ytm, years, freq);
    if (!(price > 0) || !Number.isFinite(ytm)) return NaNv;
    const y = ytm / freq;
    if (y <= -1) return NaNv;
    const acc = _cashFlows(face, couponRate, years, freq).reduce((s, [t, cf]) => s + cf * t * (t + 1) / (1 + y) ** (t + 2), 0);
    return acc / (price * freq ** 2);
  }
  function dv01(face, couponRate, ytm, years, freq = 2) {
    const p0 = bondPrice(face, couponRate, ytm, years, freq);
    const p1 = bondPrice(face, couponRate, ytm - 0.0001, years, freq);
    return Number.isFinite(p0) && Number.isFinite(p1) ? p1 - p0 : NaNv;
  }

  // ---- DCF (three-stage FCF-to-equity + reverse DCF) ----
  function threeStageGrowthPath(gHigh, gStable, highYears = 5, transitionYears = 5) {
    const path = [];
    for (let i = 0; i < Math.max(0, highYears); i++) path.push(gHigh);
    const ty = Math.max(1, transitionYears);
    for (let i = 1; i <= ty; i++) path.push(gHigh + (gStable - gHigh) * i / ty);
    return path;
  }
  function dcfFromFCF(baseFcf, growthRates, wacc, terminalGrowth, netDebt, sharesDiluted) {
    const gs = (growthRates || []).map(Number);
    if (!gs.length || !Number.isFinite(baseFcf) || !(wacc > 0) || terminalGrowth >= wacc || !(sharesDiluted > 0))
      return {valid: false, valuePerShare: NaNv};
    const proj = []; let f = baseFcf;
    for (const g of gs) { f = f * (1 + g); proj.push(f); }
    const n = proj.length;
    const pv = proj.reduce((s, cf, i) => s + cf / (1 + wacc) ** (i + 1), 0);
    const terminal = proj[n - 1] * (1 + terminalGrowth) / (wacc - terminalGrowth);
    const pvTerminal = terminal / (1 + wacc) ** n;
    const ev = pv + pvTerminal, equity = ev - netDebt;
    return {valid: true, valuePerShare: equity / sharesDiluted, enterpriseValue: ev, equityValue: equity,
      terminalValue: terminal, pvTerminalValue: pvTerminal, pvExplicit: pv, projectedFcf: proj};
  }
  function impliedFcfGrowth(price, baseFcf, wacc, terminalGrowth, netDebt, shares, highYears = 5, transitionYears = 5, stableGrowth = null, lo = -0.2, hi = 0.8) {
    const gs = stableGrowth == null ? terminalGrowth : stableGrowth;
    if (!(price > 0) || !(baseFcf > 0) || !(shares > 0) || !(wacc > terminalGrowth)) return null;
    const value = (gh) => {
      const r = dcfFromFCF(baseFcf, threeStageGrowthPath(gh, gs, highYears, transitionYears), wacc, terminalGrowth, netDebt, shares);
      return r.valid ? r.valuePerShare : NaNv;
    };
    let vlo = value(lo), vhi = value(hi);
    if (!Number.isFinite(vlo) || !Number.isFinite(vhi)) return null;
    if (!(Math.min(vlo, vhi) <= price && price <= Math.max(vlo, vhi))) return null;
    for (let i = 0; i < 80; i++) {
      const mid = 0.5 * (lo + hi), vm = value(mid);
      if (!Number.isFinite(vm)) return null;
      if (Math.abs(vm - price) / price < 1e-5) return mid;
      if (vm < price) lo = mid; else hi = mid;
    }
    return 0.5 * (lo + hi);
  }

  // ---- Portfolio ----
  function portfolioVariance(weights, cov) {
    let v = 0;
    for (let i = 0; i < weights.length; i++)
      for (let j = 0; j < weights.length; j++) v += weights[i] * cov[i][j] * weights[j];
    return v;
  }
  function riskContributions(weights, cov) {
    const variance = portfolioVariance(weights, cov), vol = Math.sqrt(variance);
    const marginal = weights.map((_, i) => cov[i].reduce((s, c, j) => s + c * weights[j], 0) / (vol || NaNv));
    const component = weights.map((w, i) => w * marginal[i]);
    const percent = component.map((c) => c / (vol || NaNv));
    return {variance, volatility: vol, marginal, component, percent};
  }

  // ---- Ratios (from user-entered statement values) ----
  const _finiteN = (...xs) => xs.every((x) => Number.isFinite(x));
  const safeDiv = (a, b) => (_finiteN(a, b) && b !== 0 ? a / b : NaNv);

  return {
    erf, normCdf, normPdf,
    bsPrice, greeks,
    bondPrice, yieldToMaturity, currentYield, macaulayDuration, modifiedDuration, convexity, dv01,
    threeStageGrowthPath, dcfFromFCF, impliedFcfGrowth,
    portfolioVariance, riskContributions,
    safeDiv,
  };
})();
if (typeof module !== "undefined" && module.exports) module.exports = FC;
