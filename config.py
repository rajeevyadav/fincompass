"""
FinCompass Configuration
"""
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# Application / scoring engine versions. The score cache is explicitly tied to
# SCORING_ENGINE_VERSION so a methodology change can never silently reuse a
# score produced by an older engine.
APP_VERSION = "1.4.0"
SCORING_ENGINE_VERSION = "1.0.0-evidence1"
DATA_SCHEMA_VERSION = "1.0.0-normalized1"

# Bayesian evidence aggregation. Metric scores are normalized to [0, 1] and
# treated as fractional evidence in a Beta conjugate model. This estimates
# uncertainty in the *FinCompass evidence score*; it is not a probability of
# future return, profit, or outperformance.
BAYES_PRIOR_ALPHA = 2.0
BAYES_PRIOR_BETA = 2.0
BAYES_EVIDENCE_SCALE = 4.0
BAYES_DRAWS = 6000
BAYES_CREDIBLE_LEVEL = 0.90

# Screener refresh runs out of band. Fetching remains deliberately sequential
# to be courteous to free upstream services; responsiveness comes from the
# background job rather than aggressive parallel requests.
SCREENER_JOB_STALE_MINUTES = max(5, int(os.getenv("SCREENER_JOB_STALE_MINUTES", "30")))

# Rate-limit storage. SQLite is process-safe on one host and is the no-extra-
# dependency default. Set RATE_LIMIT_BACKEND=redis + REDIS_URL for truly
# shared limits across multiple application hosts/containers.
RATE_LIMIT_BACKEND = os.getenv("RATE_LIMIT_BACKEND", "sqlite").strip().lower()
REDIS_URL = os.getenv("REDIS_URL", "").strip()

# Privacy-first audit logging. By default client IPs are represented by a
# rotating daily hash; set AUDIT_IP_MODE=raw only when an operator explicitly
# needs raw addresses for incident response.
AUDIT_IP_MODE = os.getenv("AUDIT_IP_MODE", "hash").strip().lower()
AUDIT_LOG_MAX_BYTES = max(1_000_000, int(os.getenv("AUDIT_LOG_MAX_BYTES", "5000000")))

# Paths
BASE_DIR = Path(__file__).parent
# Allow a persistent, writable data dir override (used by the packaged exe so
# local state survives outside the ephemeral bundle). Defaults to ./data.
DATA_DIR = Path(os.getenv("FINCOMPASS_DATA_DIR") or (BASE_DIR / "data"))
DB_PATH = DATA_DIR / "fincompass.db"
DATA_DIR.mkdir(exist_ok=True)

# API Keys
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
STOOQ_API_KEY = os.getenv("STOOQ_API_KEY", "").strip()

# Scoring weights (must sum to 1.0)
PILLAR_WEIGHTS = {
    "quality": 0.25,
    "moat": 0.20,
    "safety": 0.20,
    "valuation": 0.20,
    "cycle": 0.15,
}

SCORE_LABELS = {
    (8.0, 10.1): "Strong",
    (6.0, 8.0): "Acceptable",
    (0.0, 6.0): "Weak",
}

# Investor Posture indicators (presentation-layer, model-free; see D-001).
# Named thresholds mirror SCORE_LABELS so the derived indicators stay in lock-
# step with the pillar labels shown on the card. These drive display-only
# research signals — never a buy/sell recommendation or a combined verdict.
POSTURE_STRONG_MIN = 8.0          # pillar/composite "Strong" floor
POSTURE_WEAK_MAX = 6.0            # below this a pillar/composite reads "Weak"
POSTURE_FUNDAMENTALS_MIN = 7.0    # quality & durability floor for "strong fundamentals"
POSTURE_VALUATION_WEAK_MAX = 5.0  # valuation below this is "weak" (accumulation-zone shape)
POSTURE_VALUATION_RICH_MIN = 7.0  # valuation at/above this reads as already-priced

# Expanded universe – major US large & mid caps across sectors
DEFAULT_UNIVERSE = [
    # Tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "AVGO", "ORCL", "CRM", "ADBE",
    "CSCO", "ACN", "AMD", "INTC", "QCOM", "TXN", "IBM", "NOW", "INTU", "AMAT",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "AXP", "C", "SPGI",
    # Healthcare
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "TMO", "ABT", "PFE", "DHR", "BMY", "AMGN", "ISRG",
    # Consumer
    "WMT", "PG", "KO", "PEP", "COST", "MCD", "SBUX", "NKE", "HD", "LOW", "TGT", "CL",
    # Industrials / Energy / Other
    "XOM", "CVX", "CAT", "GE", "HON", "UPS", "RTX", "BA", "DE", "LMT",
    "NEE", "LIN", "PM", "MO", "DIS", "V", "MA", "BRK-B",
]

# Display names for the curated universe above, used only to power search-by-
# company-name in the UI (e.g. typing "apple" suggests AAPL). This is static
# reference data, not fetched — the ticker itself is still the source of
# truth sent to the scoring pipeline, and any valid ticker outside this list
# (not just these 72) still works via free-text entry; this list only powers
# suggestions, never restricts what can be analyzed.
TICKER_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet (Google)", "AMZN": "Amazon",
    "NVDA": "Nvidia", "META": "Meta Platforms", "AVGO": "Broadcom", "ORCL": "Oracle",
    "CRM": "Salesforce", "ADBE": "Adobe", "CSCO": "Cisco", "ACN": "Accenture",
    "AMD": "Advanced Micro Devices", "INTC": "Intel", "QCOM": "Qualcomm", "TXN": "Texas Instruments",
    "IBM": "IBM", "NOW": "ServiceNow", "INTU": "Intuit", "AMAT": "Applied Materials",
    "JPM": "JPMorgan Chase", "BAC": "Bank of America", "WFC": "Wells Fargo", "GS": "Goldman Sachs",
    "MS": "Morgan Stanley", "BLK": "BlackRock", "SCHW": "Charles Schwab", "AXP": "American Express",
    "C": "Citigroup", "SPGI": "S&P Global",
    "UNH": "UnitedHealth Group", "JNJ": "Johnson & Johnson", "LLY": "Eli Lilly", "ABBV": "AbbVie",
    "MRK": "Merck", "TMO": "Thermo Fisher Scientific", "ABT": "Abbott Laboratories", "PFE": "Pfizer",
    "DHR": "Danaher", "BMY": "Bristol-Myers Squibb", "AMGN": "Amgen", "ISRG": "Intuitive Surgical",
    "WMT": "Walmart", "PG": "Procter & Gamble", "KO": "Coca-Cola", "PEP": "PepsiCo",
    "COST": "Costco", "MCD": "McDonald's", "SBUX": "Starbucks", "NKE": "Nike",
    "HD": "Home Depot", "LOW": "Lowe's", "TGT": "Target", "CL": "Colgate-Palmolive",
    "XOM": "Exxon Mobil", "CVX": "Chevron", "CAT": "Caterpillar", "GE": "General Electric",
    "HON": "Honeywell", "UPS": "United Parcel Service", "RTX": "RTX Corporation", "BA": "Boeing",
    "DE": "Deere & Company", "LMT": "Lockheed Martin",
    "NEE": "NextEra Energy", "LIN": "Linde", "PM": "Philip Morris International", "MO": "Altria Group",
    "DIS": "Walt Disney", "V": "Visa", "MA": "Mastercard", "BRK-B": "Berkshire Hathaway",
}

CHART_PERIODS = ["1y", "3y", "5y", "10y", "max"]
DEFAULT_CHART_PERIOD = "5y"

FUNDAMENTALS_CACHE_HOURS = 24
PRICE_CACHE_HOURS = 24
MACRO_CACHE_HOURS = 24  # macro series update daily/weekly at most - one fetch a day is plenty

# FRED (Federal Reserve Economic Data) series used for the Cycle pillar's
# macro context. All free, no key beyond a free FRED_API_KEY.
# - Yield curve: 10Y minus 2Y treasury yield. Negative/near-zero = late-cycle
#   warning sign (every US recession since the 1960s was preceded by an
#   inversion here, per NY Fed research).
# - Credit spread: ICE BofA US High Yield Option-Adjusted Spread. Widening
#   spreads = credit markets pricing in more default risk = tightening
#   conditions, usually well ahead of equity markets.
FRED_SERIES = {
    "yield_curve": "T10Y2Y",
    "credit_spread": "BAMLH0A0HYM2",
}

# Commodity price series (also FRED, also free) used only as a sector-specific
# input for a small set of sectors where a commodity price genuinely explains
# part of the business — not a universal overlay. Each entry also carries a
# "direction": +1 for sectors that PRODUCE the commodity (a higher price is a
# tailwind — e.g. an oil producer benefits from higher crude), -1 for sectors
# that CONSUME it as a cost input (a higher price is a headwind — e.g. an
# airline's fuel bill). Sectors not listed here get no commodity signal.
COMMODITY_SERIES_BY_SECTOR = {
    "Energy": {"series": "DCOILWTICO", "name": "WTI crude oil", "direction": 1},
    "Basic Materials": {"series": "PCOPPUSDM", "name": "Copper", "direction": 1},
    "Utilities": {"series": "DHHNGSP", "name": "Henry Hub natural gas", "direction": -1},
    "Industrials": {"series": "PALUMUSDM", "name": "Aluminum", "direction": -1},
    "Consumer Cyclical": {"series": "DCOILWTICO", "name": "WTI crude oil (fuel cost)", "direction": -1},
    "Consumer Defensive": {"series": "PWHEAMTUSDM", "name": "Wheat", "direction": -1},
}
