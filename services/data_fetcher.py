"""
FinCompass Data Fetcher
Multi-source free data with automatic fallback.
Philosophy: Use every legitimate free source so the tool stays free and useful for everyone.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

try:
    import yfinance as yf
except ImportError:  # health/docs can still start; market-data routes will degrade cleanly
    yf = None
import pandas as pd
import requests

from config import FMP_API_KEY, ALPHA_VANTAGE_KEY, DATA_SCHEMA_VERSION

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FinCompass.DataFetcher")

# Applied to every outbound call so a hung/slow upstream can't block a
# worker thread indefinitely (yfinance/Stooq previously had no timeout at all).
REQUEST_TIMEOUT = 12


def _stamp(data: Dict[str, Any]) -> Dict[str, Any]:
    data["fetched_at"] = datetime.now(timezone.utc).isoformat()
    data["_data_schema_version"] = DATA_SCHEMA_VERSION
    return data


def _canonical_sector(value: Any) -> Any:
    if not isinstance(value, str) or not value.strip():
        return value
    raw = value.strip()
    aliases = {
        "TECHNOLOGY": "Technology",
        "FINANCE": "Financial Services",
        "FINANCIAL SERVICES": "Financial Services",
        "HEALTHCARE": "Healthcare",
        "LIFE SCIENCES": "Healthcare",
        "ENERGY": "Energy",
        "UTILITIES": "Utilities",
        "REAL ESTATE": "Real Estate",
        "BASIC MATERIALS": "Basic Materials",
        "COMMUNICATION SERVICES": "Communication Services",
        "CONSUMER CYCLICAL": "Consumer Cyclical",
        "CONSUMER DEFENSIVE": "Consumer Defensive",
        "INDUSTRIALS": "Industrials",
    }
    return aliases.get(raw.upper(), raw)


class DataFetcher:
    """Fetches market and fundamental data using free sources with fallbacks."""

    def __init__(self):
        self.fmp_key = FMP_API_KEY
        self.av_key = ALPHA_VANTAGE_KEY
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "FinCompass/3.0 (Free Educational Tool)"
        })
        # Operational visibility without exposing credentials. This is a
        # best-effort last-event snapshot, not a provider SLA monitor.
        self._provider_health = {
            "fmp": {"status": "not_checked", "configured": bool(self.fmp_key)},
            "alpha_vantage": {"status": "not_checked", "configured": bool(self.av_key)},
            "yfinance": {"status": "not_checked", "configured": True},
        }

    def _mark_provider(self, provider: str, status: str, http_status: Optional[int] = None) -> None:
        row = {
            "status": status,
            "configured": self._provider_health.get(provider, {}).get("configured", True),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        if http_status is not None:
            row["http_status"] = int(http_status)
        self._provider_health[provider] = row

    def health_snapshot(self) -> Dict[str, Any]:
        return {key: dict(value) for key, value in self._provider_health.items()}

    # ------------------------------------------------------------------
    # PRICE HISTORY (multiple free sources)
    # ------------------------------------------------------------------
    def get_price_history(self, ticker: str, period: str = "5y") -> Optional[pd.DataFrame]:
        ticker = ticker.upper().replace(".", "-")

        # 1. Primary: yfinance (Yahoo Finance - free, widely used)
        if yf is None:
            logger.warning("[Price] yfinance is not installed; using fallback sources")
        try:
            if yf is None:
                raise RuntimeError("yfinance unavailable")
            t = yf.Ticker(ticker)
            df = t.history(period=period, auto_adjust=True, timeout=REQUEST_TIMEOUT)
            if df is not None and not df.empty:
                df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                df.index = pd.to_datetime(df.index).tz_localize(None)
                self._mark_provider("yfinance", "ok")
                logger.info(f"[Price] yfinance OK → {ticker}")
                return df
        except Exception as e:
            self._mark_provider("yfinance", "degraded")
            logger.warning("[Price] yfinance failed %s: %s", ticker, type(e).__name__)

        # 2. Backup: Stooq (completely free, no key, good historical data)
        try:
            stooq_ticker = ticker.replace("-", ".") + ".US"
            url = f"https://stooq.com/q/d/l/?s={stooq_ticker.lower()}&i=d"
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            import io
            df = pd.read_csv(io.StringIO(resp.text))
            if df is not None and not df.empty and "Close" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"])
                df = df.set_index("Date").sort_index()
                df = df[["Open", "High", "Low", "Close", "Volume"]]
                # Approximate period filter
                if period != "max":
                    years = {"1y": 1, "3y": 3, "5y": 5, "10y": 10}.get(period, 5)
                    cutoff = df.index.max() - pd.DateOffset(years=years)
                    df = df[df.index >= cutoff]
                logger.info(f"[Price] Stooq OK → {ticker}")
                return df
        except Exception as e:
            logger.warning(f"[Price] Stooq failed {ticker}: {e}")

        logger.error(f"[Price] All free sources failed for {ticker}")
        return None

    def get_current_price(self, ticker: str) -> Optional[float]:
        try:
            if yf is None:
                return None
            t = yf.Ticker(ticker.upper().replace(".", "-"))
            info = t.fast_info
            price = getattr(info, "last_price", None) or getattr(info, "lastPrice", None)
            if price:
                return float(price)
            hist = t.history(period="5d", timeout=REQUEST_TIMEOUT)
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        except Exception as e:
            logger.warning(f"[Price] current price failed {ticker}: {e}")
        return None

    # ------------------------------------------------------------------
    # FUNDAMENTALS (free sources with fallback chain)
    # ------------------------------------------------------------------
    def get_fundamentals(self, ticker: str) -> Dict[str, Any]:
        # NOTE: previously this converted "-" to "." (e.g. BRK-B -> BRK.B) before
        # calling FMP/Alpha Vantage, which silently broke lookups for every
        # dash-form multi-class ticker (BRK-B is in DEFAULT_UNIVERSE) on the two
        # higher-priority sources — only the yfinance fallback used the correct
        # form. Keep the same normalized (dash) form across all three sources.
        ticker_clean = ticker.upper().replace(".", "-")

        # 1. Financial Modeling Prep (best free fundamentals when key available)
        if self.fmp_key:
            data = self._fetch_fmp(ticker_clean)
            if data:
                logger.info(f"[Fund] FMP OK → {ticker}")
                return data

        # 2. Alpha Vantage free tier
        if self.av_key:
            data = self._fetch_alpha_vantage(ticker_clean)
            if data:
                logger.info(f"[Fund] Alpha Vantage OK → {ticker}")
                return data

        # 3. yfinance (always free, no key)
        data = self._fetch_yfinance_fundamentals(ticker)
        if data:
            logger.info(f"[Fund] yfinance OK → {ticker}")
            return data

        logger.error(f"[Fund] All free sources failed for {ticker}")
        return {}

    def _fetch_fmp(self, ticker: str) -> Optional[Dict]:
        try:
            base = "https://financialmodelingprep.com/api/v3"
            params = {"apikey": self.fmp_key}
            metrics = self._get_json(f"{base}/key-metrics-ttm/{ticker}", params=params, provider="fmp")
            ratios  = self._get_json(f"{base}/ratios-ttm/{ticker}", params=params, provider="fmp")
            profile = self._get_json(f"{base}/profile/{ticker}", params=params, provider="fmp")

            metrics = metrics[0] if isinstance(metrics, list) and metrics else {}
            ratios  = ratios[0]  if isinstance(ratios, list)  and ratios  else {}
            profile = profile[0] if isinstance(profile, list) and profile else {}

            if not metrics and not ratios:
                return None

            return _stamp({
                "source": "fmp",
                "ticker": ticker,
                "name": profile.get("companyName"),
                "sector": _canonical_sector(profile.get("sector")),
                "industry": profile.get("industry"),
                "market_cap": profile.get("mktCap"),
                "pe": ratios.get("peRatioTTM") or metrics.get("peRatioTTM"),
                "pb": ratios.get("priceToBookRatioTTM"),
                "ps": ratios.get("priceToSalesRatioTTM"),
                "ev_ebitda": metrics.get("enterpriseValueOverEBITDATTM"),
                "roe": ratios.get("returnOnEquityTTM") or metrics.get("roeTTM"),
                "roa": ratios.get("returnOnAssetsTTM"),
                "roic": metrics.get("roicTTM"),
                "gross_margin": ratios.get("grossProfitMarginTTM"),
                "operating_margin": ratios.get("operatingProfitMarginTTM"),
                "net_margin": ratios.get("netProfitMarginTTM"),
                "debt_to_equity": ratios.get("debtEquityRatioTTM"),
                "current_ratio": ratios.get("currentRatioTTM"),
                "interest_coverage": ratios.get("interestCoverageTTM"),
                "dividend_yield": ratios.get("dividendYieldTTM"),
            })
        except Exception as e:
            self._mark_provider("fmp", "degraded")
            logger.warning("FMP parse error %s: %s", ticker, type(e).__name__)
            return None

    def _fetch_alpha_vantage(self, ticker: str) -> Optional[Dict]:
        try:
            url = "https://www.alphavantage.co/query"
            data = self._get_json(
                url,
                params={"function": "OVERVIEW", "symbol": ticker, "apikey": self.av_key},
                provider="alpha_vantage",
            )
            if not data or "Symbol" not in data:
                return None

            def f(key):
                try:
                    v = data.get(key)
                    return float(v) if v not in (None, "None", "-", "") else None
                except Exception:
                    return None

            return _stamp({
                "source": "alpha_vantage",
                "ticker": ticker,
                "name": data.get("Name"),
                "sector": _canonical_sector(data.get("Sector")),
                "industry": data.get("Industry"),
                "market_cap": f("MarketCapitalization"),
                "pe": f("PERatio"),
                "pb": f("PriceToBookRatio"),
                "ps": f("PriceToSalesRatioTTM"),
                "ev_ebitda": f("EVToEBITDA"),
                "roe": f("ReturnOnEquityTTM"),
                "roa": f("ReturnOnAssetsTTM"),
                "operating_margin": f("OperatingMarginTTM"),
                "net_margin": f("ProfitMargin"),
                "dividend_yield": f("DividendYield"),
                "revenue_growth": f("QuarterlyRevenueGrowthYOY"),
                "earnings_growth": f("QuarterlyEarningsGrowthYOY"),
            })
        except Exception as e:
            self._mark_provider("alpha_vantage", "degraded")
            logger.warning("Alpha Vantage parse error %s: %s", ticker, type(e).__name__)
            return None

    def _fetch_yfinance_fundamentals(self, ticker: str) -> Optional[Dict]:
        try:
            if yf is None:
                return None
            t = yf.Ticker(ticker.replace(".", "-"))
            info = t.info or {}

            def g(key, default=None):
                return info.get(key, default)

            total_revenue = g("totalRevenue")
            free_cashflow = g("freeCashflow")
            try:
                fcf_margin = float(free_cashflow) / float(total_revenue) if free_cashflow is not None and total_revenue else None
            except (TypeError, ValueError, ZeroDivisionError):
                fcf_margin = None

            debt_to_equity = g("debtToEquity")
            try:
                debt_to_equity = float(debt_to_equity) / 100.0 if debt_to_equity is not None else None
                # Yahoo's debtToEquity field is reported in percentage points
                # (e.g. 151 means 151% = 1.51x), unlike FMP's ratio convention.
            except (TypeError, ValueError):
                debt_to_equity = None

            self._mark_provider("yfinance", "ok")
            return _stamp({
                "source": "yfinance",
                "ticker": ticker,
                "name": g("longName") or g("shortName"),
                "sector": _canonical_sector(g("sector")),
                "industry": g("industry"),
                "market_cap": g("marketCap"),
                "pe": g("trailingPE") or g("forwardPE"),
                "pb": g("priceToBook"),
                "ps": g("priceToSalesTrailing12Months"),
                "ev_ebitda": g("enterpriseToEbitda"),
                "roe": g("returnOnEquity"),
                "roa": g("returnOnAssets"),
                "roic": g("returnOnInvestedCapital"),
                "gross_margin": g("grossMargins"),
                "operating_margin": g("operatingMargins"),
                "net_margin": g("profitMargins"),
                "debt_to_equity": debt_to_equity,
                "current_ratio": g("currentRatio"),
                "interest_coverage": g("interestCoverage"),
                "dividend_yield": g("dividendYield"),
                "payout_ratio": g("payoutRatio"),
                "revenue_growth": g("revenueGrowth"),
                "earnings_growth": g("earningsGrowth"),
                "fcf_margin": fcf_margin,
                "total_revenue": total_revenue,
                "free_cashflow": free_cashflow,
            })
        except Exception as e:
            self._mark_provider("yfinance", "degraded")
            logger.warning("yfinance fund error %s: %s", ticker, type(e).__name__)
            return None

    def _get_json(self, url: str, *, params: Optional[Dict[str, Any]] = None, provider: str = "upstream") -> Any:
        """GET JSON without ever logging a URL that may contain API credentials."""
        try:
            r = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429:
                self._mark_provider(provider, "rate_limited", 429)
                logger.warning("[%s] upstream rate limit (HTTP 429)", provider)
                return None
            if r.status_code != 200:
                self._mark_provider(provider, "degraded", r.status_code)
                logger.warning("[%s] upstream HTTP %s", provider, r.status_code)
                return None
            data = r.json()
            # Several free providers return quota/auth failures inside HTTP 200
            # JSON. Detect the common message envelopes before declaring health.
            if isinstance(data, dict):
                text = str(
                    data.get("Note") or data.get("Information") or data.get("Error Message")
                    or data.get("error") or data.get("message") or ""
                )
                lower = text.lower()
                if text and ("rate" in lower or "frequency" in lower or "limit" in lower or "quota" in lower):
                    self._mark_provider(provider, "rate_limited", 200)
                    logger.warning("[%s] upstream free-tier limit reported in response body", provider)
                    return None
                if text and ("api key" in lower or "apikey" in lower or "invalid key" in lower or "unauthorized" in lower):
                    self._mark_provider(provider, "auth_error", 200)
                    logger.warning("[%s] upstream API-key error reported in response body", provider)
                    return None
            self._mark_provider(provider, "ok", 200)
            return data
        except requests.RequestException as exc:
            self._mark_provider(provider, "degraded")
            logger.warning("[%s] upstream request failed: %s", provider, type(exc).__name__)
            return None
        except ValueError:
            self._mark_provider(provider, "degraded")
            logger.warning("[%s] upstream returned invalid JSON", provider)
            return None


# Singleton
fetcher = DataFetcher()
