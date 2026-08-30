# FinCompass Model Lab offline bootstrap corpus

This directory contains the small **real historical** starter corpus used to
prove that a fresh FinCompass installation can run Model Lab without network
access. It is an acceptance/bootstrap dataset, not evidence of current market
skill and not a substitute for the operator's current cross-asset research
corpus.

## What is bundled

- `GOOG`: 1,047 daily observations from the Matplotlib sample-data archive,
  2004-08-19 through 2008-10-14. The original `matplotlib-goog.npz` bytes are
  retained under `source-originals/` and in the seed raw archive.
- `MSFT`: 7,983 daily observations distributed with the pmdarima sample
  datasets, 1986-03-13 through 2017-11-10. pmdarima documents this series as
  originating from the Kaggle US stocks/ETFs price-volume dataset. The original
  `pmdarima-msft.tar.gz` bytes are retained.

The package/license notices used for this bootstrap are retained under
`licenses/`. `SEED_MANIFEST.json` binds every source and the SQLite seed by
SHA-256.

## First-run behavior

`services.research_store.ResearchStore` copies `market_seed.db` into the user's
writable FinCompass data directory using SQLite's backup API. The packaged seed
is never modified. A later FinCompass package can add seed rows to an existing
user store without overwriting the user's own prices, revisions, experiments,
or price-basis contracts.

The `bootstrap-real-1m` recipe uses this corpus strictly as an offline acceptance
exercise. Its target is deliberately marked `live_eligible_target=false`, so it
cannot be activated for live forecasts even if its statistical gates happen to
pass.

## Building the seed

Rebuild the bundled bootstrap deterministically from the retained source
artifacts:

```bash
python tools/build_builtin_seed.py
```

To import an operator-owned/local market corpus instead:

```bash
python tools/import_market_seed.py --entry SPY=/path/SPY.csv --entry AAPL=/path/AAPL.csv
```

## Incremental current-data workflow

For ordinary research use, Model Lab's **Update local market data** action
requests only a short overlap before each symbol's latest retained date. New
rows are appended, unchanged overlap rows are ignored, genuine revisions are
journaled, and the exact provider frame used for ingestion is stored with a
SHA-256. A failed/interrupted refresh never truncates existing history.

Current broad-universe data obtained from external providers are user-local
runtime data and are intentionally not redistributed in the source repository.
