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

  return {getProxy, setProxy, hasProxy, dailyBars};
})();
if (typeof module !== "undefined" && module.exports) module.exports = FCData;
