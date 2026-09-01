"use strict";
/*
  FinCompass Web — market-data layer. Browsers cannot call Yahoo directly (no
  CORS), so daily prices are fetched through a small free Cloudflare Worker
  (see cloudflare/SETUP.md). The Worker URL is stored in this browser only.
*/
const FCData = (() => {
  const KEY = "fc_data_proxy";
  let proxy = "";
  try { proxy = window.localStorage.getItem(KEY) || ""; } catch (_) { /* ignore */ }

  const getProxy = () => proxy;
  const hasProxy = () => !!proxy;
  function setProxy(url) {
    proxy = (url || "").trim().replace(/\/+$/, "");
    try { proxy ? window.localStorage.setItem(KEY, proxy) : window.localStorage.removeItem(KEY); } catch (_) {}
  }

  // Daily [{date:'YYYY-MM-DD', close}] for a Yahoo symbol, via the proxy.
  async function dailyBars(ticker, range = "3y") {
    if (!proxy) throw new Error("no_proxy");
    const url = `${proxy}?ticker=${encodeURIComponent(ticker)}&range=${encodeURIComponent(range)}`;
    let r;
    try { r = await fetch(url); } catch (e) { throw new Error("Could not reach the data proxy."); }
    if (!r.ok) throw new Error(`Data request failed (${r.status}).`);
    const j = await r.json();
    const res = j && j.chart && j.chart.result && j.chart.result[0];
    if (!res || !res.timestamp) throw new Error(`No price data for ${ticker}.`);
    const ts = res.timestamp;
    const close = res.indicators && res.indicators.quote && res.indicators.quote[0] ? res.indicators.quote[0].close : [];
    const bars = [];
    for (let i = 0; i < ts.length; i++) {
      const c = close[i];
      if (c != null && Number.isFinite(Number(c))) {
        bars.push({date: new Date(ts[i] * 1000).toISOString().slice(0, 10), close: Number(c)});
      }
    }
    if (bars.length < 260) throw new Error(`Not enough price history for ${ticker}.`);
    return bars;
  }

  // Annual fundamentals for the DCF. Returns newest-first arrays where relevant.
  async function fundamentals(ticker) {
    if (!proxy) throw new Error("no_proxy");
    const url = `${proxy}?ticker=${encodeURIComponent(ticker)}&kind=fundamentals`;
    let r;
    try { r = await fetch(url); } catch (e) { throw new Error("Could not reach the data proxy."); }
    if (!r.ok) throw new Error(`Fundamentals request failed (${r.status}).`);
    const j = await r.json();
    const series = {};
    for (const res of (j && j.timeseries && j.timeseries.result) || []) {
      const type = res && res.meta && res.meta.type && res.meta.type[0];
      if (!type || !res[type]) continue;
      const vals = res[type].map((x) => (x && x.reportedValue ? Number(x.reportedValue.raw) : null))
        .filter((v) => v != null && Number.isFinite(v));
      if (vals.length) series[type] = vals; // ascending by year
    }
    const newestFirst = (a) => (series[a] ? series[a].slice().reverse() : []);
    const latest = (a) => (series[a] && series[a].length ? series[a][series[a].length - 1] : null);
    const debt = latest("annualTotalDebt");
    const cash = latest("annualCashCashEquivalentsAndShortTermInvestments") ?? latest("annualCashAndCashEquivalents");
    return {
      fcf_history: newestFirst("annualFreeCashFlow"),
      revenue_history: newestFirst("annualTotalRevenue"),
      shares: latest("annualDilutedAverageShares"),
      net_debt: (debt != null ? debt : 0) - (cash != null ? cash : 0),
    };
  }

  // Annualized volatility from ~1 year of daily closes (for the option desk).
  function historicalVol(bars) {
    const c = bars.map((x) => x.close), r = [];
    for (let i = 1; i < c.length; i++) if (c[i] > 0 && c[i - 1] > 0) r.push(Math.log(c[i] / c[i - 1]));
    const recent = r.slice(-252);
    if (recent.length < 20) return null;
    const m = recent.reduce((s, x) => s + x, 0) / recent.length;
    const v = recent.reduce((s, x) => s + (x - m) ** 2, 0) / (recent.length - 1);
    return Math.sqrt(v) * Math.sqrt(252);
  }

  return {getProxy, setProxy, hasProxy, dailyBars, fundamentals, historicalVol};
})();
if (typeof module !== "undefined" && module.exports) module.exports = FCData;
