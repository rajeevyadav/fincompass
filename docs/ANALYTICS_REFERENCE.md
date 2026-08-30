# FinCompass Analytics Reference

Auto-derived from the in-code formula registry (`analytics/registry.py`). Every metric is a native, provider-independent reimplementation verified by hand-calculated unit tests (`tests/test_analytics.py`). No external analytics package or paid provider is required at runtime.

Value-at-Risk is a confidence-level loss threshold (a positive loss fraction), **not** a maximum possible loss.

| Metric | ID | Version | Formula | Inputs | Units | Supported assets | Reference |
|---|---|---|---|---|---|---|---|
| Annualized return | `performance.annualized_return.v1` | 1 | prod(1+r)^(P/N) - 1 | returns | ratio_percent | equity, etf, index | standard definition |
| Beta | `performance.beta.v1` | 1 | cov(asset, market) / var(market) | asset_returns, market_returns | ratio | equity, etf, index | standard definition |
| Calmar ratio | `performance.calmar.v1` | 1 | annualized_return / \|max_drawdown\| | returns | ratio | equity, etf, index | standard definition |
| Information ratio | `performance.information_ratio.v1` | 1 | active_annual_return / tracking_error | asset_returns, benchmark_returns | ratio | equity, etf, index | standard definition |
| Maximum drawdown | `performance.max_drawdown.v1` | 1 | min(wealth/cummax(wealth) - 1) | returns | ratio_percent | equity, etf, index | standard definition |
| Sharpe ratio | `performance.sharpe.v1` | 1 | mean(r-rf)/std(r-rf) * sqrt(P) | returns, rf | ratio | equity, etf, index | standard definition |
| Sortino ratio | `performance.sortino.v1` | 1 | ann_excess / downside_deviation | returns, mar | ratio | equity, etf, index | standard definition |
| Tracking error | `performance.tracking_error.v1` | 1 | std(asset - benchmark) * sqrt(P) | asset_returns, benchmark_returns | ratio_percent | equity, etf, index | standard definition |
| Annualized volatility | `performance.volatility.v1` | 1 | std(r, ddof=1) * sqrt(P) | returns | ratio_percent | equity, etf, index | standard definition |
| Conditional VaR (expected shortfall) | `risk.cvar.v1` | 1 | -mean(r \| r <= VaR quantile) | returns, confidence | ratio_percent | equity, etf, index | standard definition |
| EWMA volatility | `risk.ewma_volatility.v1` | 1 | RiskMetrics EWMA(var, lambda); annualized | returns, lambda | ratio_percent | equity, etf, index | standard definition |
| Maximum drawdown | `risk.max_drawdown.v1` | 1 | min(wealth/cummax(wealth) - 1) | returns | ratio_percent | equity, etf, index | standard definition |
| Max drawdown duration | `risk.max_drawdown_duration.v1` | 1 | longest run below a prior wealth peak | returns | periods | equity, etf, index | standard definition |
| Gaussian VaR | `risk.var.gaussian.v1` | 1 | -(mean + z_{1-conf} * std) | returns, confidence | ratio_percent | equity, etf, index | standard definition |
| Historical VaR | `risk.var.historical.v1` | 1 | -quantile(r, 1-confidence) | returns, confidence | ratio_percent | equity, etf, index | empirical quantile |
| Annualized volatility | `risk.volatility.v1` | 1 | std(r, ddof=1) * sqrt(P) | returns | ratio_percent | equity, etf, index | standard definition |
