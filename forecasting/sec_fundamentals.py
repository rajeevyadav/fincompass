"""Point-in-time annual SEC CompanyFacts feature extraction.

SEC filing dates, not fiscal period ends, are used as feature availability
dates. Annual filings are favored because cumulative quarterly XBRL facts are
not safely interchangeable without a more elaborate duration-normalization
layer.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
import requests

SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}

CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "Revenues"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "gross_profit": ["GrossProfit"],
    "assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "debt_current": ["LongTermDebtCurrent", "ShortTermBorrowings"],
    # Avoid falling back to total LongTermDebt here: adding that to a current
    # debt concept can double-count current maturities. Missing is safer.
    "debt_noncurrent": ["LongTermDebtNoncurrent"],
    "operating_cashflow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}


class SecClient:
    def __init__(
        self,
        user_agent: Optional[str] = None,
        cache_dir: str | Path = "data/sec_cache",
        cache_max_age_hours: Optional[float] = None,
        max_requests_per_second: Optional[float] = None,
    ):
        self.user_agent = (user_agent or os.getenv("SEC_USER_AGENT") or "").strip()
        if not self.user_agent:
            raise ValueError("SEC_USER_AGENT is required, e.g. 'FinCompass research contact@example.com'")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_max_age_hours = float(cache_max_age_hours if cache_max_age_hours is not None else os.getenv("SEC_CACHE_MAX_AGE_HOURS", "24"))
        self.max_requests_per_second = float(max_requests_per_second if max_requests_per_second is not None else os.getenv("SEC_MAX_REQUESTS_PER_SECOND", "8"))
        if self.cache_max_age_hours < 0:
            raise ValueError("SEC cache age must be non-negative")
        if self.max_requests_per_second <= 0 or self.max_requests_per_second > 10:
            raise ValueError("SEC_MAX_REQUESTS_PER_SECOND must be in (0,10]")
        self._last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"})

    def _json(self, url: str, cache_name: str) -> Dict[str, Any]:
        path = self.cache_dir / cache_name
        if path.exists():
            age_hours = max(0.0, (time.time() - path.stat().st_mtime) / 3600.0)
            if age_hours <= self.cache_max_age_hours:
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    pass
        min_interval = 1.0 / self.max_requests_per_second
        wait = min_interval - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        r = self.session.get(url, timeout=20)
        self._last_request_at = time.monotonic()
        r.raise_for_status()
        data = r.json()
        path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def ticker_to_cik(self) -> Dict[str, int]:
        raw = self._json(SEC_TICKER_URL, "company_tickers.json")
        out: Dict[str, int] = {}
        for row in raw.values() if isinstance(raw, dict) else []:
            try:
                out[str(row["ticker"]).upper().replace(".", "-")] = int(row["cik_str"])
            except Exception:
                continue
        return out

    def companyfacts(self, cik: int) -> Dict[str, Any]:
        return self._json(SEC_FACTS_URL.format(cik=int(cik)), f"CIK{int(cik):010d}.json")


def _concept_entries(companyfacts: Dict[str, Any], tags: Iterable[str]) -> List[Dict[str, Any]]:
    facts = (companyfacts.get("facts") or {}).get("us-gaap") or {}
    for tag in tags:
        concept = facts.get(tag)
        if not concept:
            continue
        units = concept.get("units") or {}
        preferred = []
        for unit_name in ("USD", "pure"):
            preferred.extend(units.get(unit_name, []))
        if not preferred:
            for values in units.values():
                preferred.extend(values or [])
        annual = [e for e in preferred if str(e.get("form")) in ANNUAL_FORMS and e.get("filed") and e.get("accn")]
        if annual:
            return annual
    return []


def _best_by_accession(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        accn = str(e.get("accn"))
        val = e.get("val")
        try:
            value = float(val)
        except Exception:
            continue
        candidate = dict(e)
        candidate["val"] = value
        old = out.get(accn)
        # The annual current-period fact normally has the latest end date in
        # that filing. This avoids selecting an older comparative period.
        if old is None or str(candidate.get("end") or "") > str(old.get("end") or ""):
            out[accn] = candidate
    return out


def extract_annual_fundamentals(companyfacts: Dict[str, Any]) -> pd.DataFrame:
    series = {name: _best_by_accession(_concept_entries(companyfacts, tags)) for name, tags in CONCEPTS.items()}
    accns = sorted(set().union(*(set(v) for v in series.values())))
    rows: List[Dict[str, Any]] = []
    for accn in accns:
        entries = [m[accn] for m in series.values() if accn in m]
        if not entries:
            continue
        filed = max(str(e.get("filed") or "") for e in entries)
        if not filed:
            continue
        fy_values = [e.get("fy") for e in entries if e.get("fy") is not None]
        row: Dict[str, Any] = {
            "available_date": filed,
            "filing_date": filed,
            "accession": accn,
            "form": entries[0].get("form"),
            "fiscal_year": int(max(fy_values)) if fy_values else None,
        }
        for name, mapping in series.items():
            row[name] = mapping.get(accn, {}).get("val")
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["available_date"] = pd.to_datetime(df["available_date"])
    df = df.sort_values(["available_date", "fiscal_year"], na_position="last").drop_duplicates(["accession"], keep="last")

    # Calculated features are available only from the filing date onward.
    rev = pd.to_numeric(df["revenue"], errors="coerce")
    net = pd.to_numeric(df["net_income"], errors="coerce")
    op = pd.to_numeric(df["operating_income"], errors="coerce")
    gross = pd.to_numeric(df["gross_profit"], errors="coerce")
    assets = pd.to_numeric(df["assets"], errors="coerce")
    ca = pd.to_numeric(df["current_assets"], errors="coerce")
    cl = pd.to_numeric(df["current_liabilities"], errors="coerce")
    eq = pd.to_numeric(df["equity"], errors="coerce")
    debt_current = pd.to_numeric(df["debt_current"], errors="coerce")
    debt_noncurrent = pd.to_numeric(df["debt_noncurrent"], errors="coerce")
    # Never infer zero leverage merely because SEC debt concepts are absent.
    # Add available components, but preserve NaN when neither component exists.
    debt_present = debt_current.notna() | debt_noncurrent.notna()
    debt = debt_current.fillna(0) + debt_noncurrent.fillna(0)
    debt = debt.where(debt_present, np.nan)
    cfo = pd.to_numeric(df["operating_cashflow"], errors="coerce")
    capex = pd.to_numeric(df["capex"], errors="coerce")

    # Filing-aware YoY growth. Amendments for the same fiscal year must compare
    # against the latest known prior fiscal year, not against the original filing
    # for the same year.
    latest_revenue_by_fy: Dict[int, float] = {}
    growth = []
    for fy, value in zip(df["fiscal_year"], rev):
        g = np.nan
        if pd.notna(fy) and pd.notna(value):
            fy_int = int(fy)
            prior = latest_revenue_by_fy.get(fy_int - 1)
            if prior is not None and np.isfinite(prior) and prior != 0:
                g = float(value) / float(prior) - 1.0
            latest_revenue_by_fy[fy_int] = float(value)
        growth.append(g)
    df["sec_revenue_growth_yoy"] = growth
    df["sec_net_margin"] = net / rev.replace(0, np.nan)
    df["sec_operating_margin"] = op / rev.replace(0, np.nan)
    df["sec_gross_margin"] = gross / rev.replace(0, np.nan)
    df["sec_current_ratio"] = ca / cl.replace(0, np.nan)
    df["sec_debt_to_equity"] = debt / eq.replace(0, np.nan)
    df["sec_fcf_margin"] = (cfo - capex) / rev.replace(0, np.nan)
    df["sec_roa"] = net / assets.replace(0, np.nan)
    keep = [
        "available_date", "filing_date", "fiscal_year", "accession", "form",
        "sec_revenue_growth_yoy", "sec_net_margin", "sec_operating_margin", "sec_gross_margin",
        "sec_current_ratio", "sec_debt_to_equity", "sec_fcf_margin", "sec_roa",
    ]
    return df[keep].replace([np.inf, -np.inf], np.nan)


def fetch_ticker_fundamental_history(ticker: str, client: SecClient) -> pd.DataFrame:
    mapping = client.ticker_to_cik()
    key = ticker.upper().replace(".", "-")
    cik = mapping.get(key)
    if cik is None:
        return pd.DataFrame()
    return extract_annual_fundamentals(client.companyfacts(cik))
