#!/usr/bin/env python3
"""Package-level smoke test for a running FinCompass instance.

A green unit suite does not prove that a *packaged* application boots, serves its
bundled assets, and behaves safely on the real request paths. This exercises a
running instance (the desktop package or `uvicorn api:app`) over HTTP and checks
more than startup:

  * health + bundled model/data asset presence
  * deterministic analytics endpoint
  * a supported new-ticker Forecast (produces a probability, or degrades safely)
  * the Guided forecast plan (recommended_action present)
  * an unsupported ticker fails safely (no 500)
  * Start Live (begin tracking) responds
  * the bundled document endpoint serves
  * the glossary/reference registry serves (resources/ bundled)

Network-dependent checks (analytics, forecast) accept a *safe* degraded response
so the smoke test is meaningful offline; only a crash (HTTP 5xx) or a missing
bundled asset is a hard failure.

Usage:
  python tools/package_smoke_test.py [--base http://127.0.0.1:8000] [--ticker AAPL]
Exit code 0 = all required checks passed.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

TIMEOUT = 30


def _get(base, path, method="GET"):
    url = base.rstrip("/") + path
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read()
            ctype = r.headers.get("Content-Type", "")
            data = json.loads(body) if "application/json" in ctype else body
            return r.status, data
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read())
        except Exception:
            data = None
        return e.code, data
    except Exception as e:  # connection refused, timeout, etc.
        return 0, {"_error": str(e)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--ticker", default="AAPL")
    args = ap.parse_args()
    base, tk = args.base, args.ticker
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    # 1. Health + bundled asset presence.
    st, h = _get(base, "/api/health")
    h = h if isinstance(h, dict) else {}
    check("health responds 200", st == 200, f"status={st}")
    check("engine/version reported", bool(h.get("version")), str(h.get("version")))
    check("universe assets present", int(h.get("universe_size") or 0) > 0, f"universe_size={h.get('universe_size')}")
    check("forecast registry present", isinstance(h.get("forecast_registry"), dict), "")

    # 2. Deterministic analytics.
    st, a = _get(base, f"/api/v2/analytics/{tk}/overview")
    a = a if isinstance(a, dict) else {}
    check("analytics overview not a crash", st < 500, f"status={st}")
    check("analytics returns a shape", ("available" in a) or ("performance" in a), "")

    # 3. Supported new-ticker Forecast: a probability OR a safe degraded response.
    st, f = _get(base, f"/api/v4/forecast/{tk}")
    f = f if isinstance(f, dict) else {}
    forecast_safe = st < 500
    produced = bool(((f.get("probability") or {}).get("probability_outperform")) is not None)
    degraded = (f.get("available") is False) or st in (404, 409, 422)
    check("forecast path does not 5xx", forecast_safe, f"status={st}")
    check("forecast produced or degraded safely", produced or degraded,
          "produced" if produced else "degraded")

    # 4. Guided forecast plan.
    st, p = _get(base, f"/api/v4/forecast-plan/{tk}")
    p = p if isinstance(p, dict) else {}
    check("forecast plan has recommended_action", "recommended_action" in p, str(p.get("recommended_action")))

    # 5. Unsupported ticker fails safely (no 500).
    st, u = _get(base, "/api/v4/forecast/NOTAREALTICKER999")
    check("unsupported ticker fails safely (no 5xx)", st < 500, f"status={st}")

    # 6. Start Live (begin tracking) responds without crashing.
    st, lv = _get(base, f"/api/v4/realtime/{tk}")
    check("Start Live responds (no 5xx)", st < 500, f"status={st}")

    # 7. Bundled document endpoint.
    st, _ = _get(base, "/user-manual.pdf")
    check("bundled user manual serves", st == 200, f"status={st}")

    # 8. Glossary/reference registry (resources/ bundled).
    st, g = _get(base, "/api/v2/glossary")
    g = g if isinstance(g, dict) else {}
    check("glossary registry serves", st == 200 and g.get("available") is True and len(g.get("terms") or []) > 0,
          f"terms={len(g.get('terms') or [])}")

    width = max(len(n) for n, _, _ in results)
    print(f"\nFinCompass package smoke test — {base} (ticker {tk})\n" + "=" * (width + 14))
    failed = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"  [{mark}] {name.ljust(width)}  {detail}")
    print("=" * (width + 14))
    print(f"{len(results) - failed}/{len(results)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
