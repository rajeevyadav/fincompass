# Free data proxy for the browser Forecast (Cloudflare Worker)

The browser app's calculators and glossary need no server. The **Forecast** tab
additionally needs daily market prices, and browsers block direct calls to
Yahoo (no CORS headers). This tiny Cloudflare Worker fetches the prices on the
app's behalf and adds the CORS header.

**It is free with no credit card:** the Cloudflare Workers free plan allows
**100,000 requests/day**. The Worker relays only public daily price JSON — no
secrets, no user data, no storage — and caches responses for an hour, so it
stays far inside the free tier no matter how many people use the app.

## Deploy (about 5 minutes, all in the browser)

1. Create a free account at <https://dash.cloudflare.com/sign-up> (no card).
2. In the dashboard: **Workers & Pages → Create → Create Worker**.
3. Name it e.g. `fincompass-data` → **Deploy** (it creates a placeholder).
4. Click **Edit code**, replace the entire contents with `cloudflare/worker.js`
   from this repo, then **Deploy**.
5. Copy the Worker URL shown at the top, e.g.
   `https://fincompass-data.<your-subdomain>.workers.dev`.

## Connect the app

1. Open the browser app (`/app`) → **Forecast** tab.
2. Paste the Worker URL into the one-time **data source** box and save. It is
   stored in your browser only.
3. Enter a ticker (e.g. `AAPL`) and run a Forecast.

That's it. The same Worker serves everyone who uses your hosted app.

## Notes

- The Worker only accepts plausible Yahoo symbols and a fixed set of ranges; it
  cannot be used as a general open proxy.
- Public market data can be delayed, revised, or incomplete — the Forecast is
  educational, not advice.
- If you would rather not run any proxy, the Forecast is also available in the
  free desktop app, which fetches data directly.
