/*
  FinCompass data proxy — a tiny Cloudflare Worker that lets the static browser
  app fetch public market prices. Browsers block direct calls to Yahoo (no CORS
  headers); this Worker fetches on the app's behalf and adds the CORS header.

  Free: the Cloudflare Workers free plan allows 100,000 requests/day with no
  credit card. This Worker only relays public daily price JSON — no secrets, no
  user data, no storage. Responses are cached for an hour to stay well inside
  the free tier.

  Deploy: see cloudflare/SETUP.md (about 5 minutes, all in the browser).
*/
export default {
  async fetch(request) {
    const cors = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
    };
    if (request.method === "OPTIONS") return new Response(null, {headers: cors});

    const url = new URL(request.url);
    const ticker = url.searchParams.get("ticker") || "";
    const range = url.searchParams.get("range") || "3y";
    const kind = url.searchParams.get("kind") || "chart";
    // Allow only plausible Yahoo symbols (letters, digits, . - ^ =).
    if (!/^[A-Za-z0-9.^=-]{1,15}$/.test(ticker)) {
      return json({error: "invalid ticker"}, 400, cors);
    }
    if (!/^(1y|2y|3y|5y|10y|max)$/.test(range)) {
      return json({error: "invalid range"}, 400, cors);
    }

    let yahoo;
    if (kind === "fundamentals") {
      // Annual fundamentals for the DCF (free cash flow, revenue, shares, debt,
      // cash). This timeseries endpoint is public and needs no crumb, unlike
      // quoteSummary. A wide fixed window covers all reported annual periods.
      const types = [
        "annualFreeCashFlow", "annualTotalRevenue", "annualDilutedAverageShares",
        "annualTotalDebt", "annualCashAndCashEquivalents",
        "annualCashCashEquivalentsAndShortTermInvestments",
      ].join(",");
      yahoo = `https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/` +
        `${encodeURIComponent(ticker)}?symbol=${encodeURIComponent(ticker)}&type=${types}` +
        `&period1=1420070400&period2=2000000000`;
    } else {
      yahoo = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}` +
        `?range=${range}&interval=1d`;
    }
    try {
      const upstream = await fetch(yahoo, {
        headers: {"User-Agent": "Mozilla/5.0 (FinCompass data proxy)"},
        cf: {cacheTtl: 3600, cacheEverything: true},
      });
      const body = await upstream.text();
      return new Response(body, {
        status: upstream.status,
        headers: {"Content-Type": "application/json", "Cache-Control": "public, max-age=3600", ...cors},
      });
    } catch (e) {
      return json({error: "upstream fetch failed"}, 502, cors);
    }
  },
};

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {"Content-Type": "application/json", ...cors},
  });
}
