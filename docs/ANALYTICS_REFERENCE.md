# FinCompass Analytics Reference

Auto-derived from the in-code formula registry (analytics/registry.py). Every metric is a native, provider-independent reimplementation verified by hand-calculated unit tests. No external analytics package or paid provider is required at runtime.

Ratios consume ONLY canonical statement fields (see analytics/statements.py) — provider vocabulary never reaches a formula. A non-positive or missing denominator yields NaN (never a silently-zero input). Value-at-Risk is a confidence-level loss threshold, not a maximum possible loss.

| Metric | ID | Version | Formula | Inputs | Units | Supported assets | Reference |
|---|---|---|---|---|---|---|---|
| Annualized return | `performance.annualized_return.v1` | 1 | prod(1+r)^(P/N) - 1 | returns | ratio_percent | equity, etf, index | standard definition |
| Beta | `performance.beta.v1` | 1 | cov(asset, market) / var(market) | asset_returns, market_returns | ratio | equity, etf, index | standard definition |
| Calmar ratio | `performance.calmar.v1` | 1 | annualized_return / /max_drawdown/ | returns | ratio | equity, etf, index | standard definition |
| Information ratio | `performance.information_ratio.v1` | 1 | active_annual_return / tracking_error | asset_returns, benchmark_returns | ratio | equity, etf, index | standard definition |
| Maximum drawdown | `performance.max_drawdown.v1` | 1 | min(wealth/cummax(wealth) - 1) | returns | ratio_percent | equity, etf, index | standard definition |
| Sharpe ratio | `performance.sharpe.v1` | 1 | mean(r-rf)/std(r-rf) * sqrt(P) | returns, rf | ratio | equity, etf, index | standard definition |
| Sortino ratio | `performance.sortino.v1` | 1 | ann_excess / downside_deviation | returns, mar | ratio | equity, etf, index | standard definition |
| Tracking error | `performance.tracking_error.v1` | 1 | std(asset - benchmark) * sqrt(P) | asset_returns, benchmark_returns | ratio_percent | equity, etf, index | standard definition |
| Annualized volatility | `performance.volatility.v1` | 1 | std(r, ddof=1) * sqrt(P) | returns | ratio_percent | equity, etf, index | standard definition |
| Asset turnover | `ratio.asset_turnover.v1` | 1 | revenue / avg(total_assets) | revenue, total_assets | ratio | equity | standard financial-statement analysis |
| Book value per share | `ratio.book_value_per_share.v1` | 1 | total_equity / shares_diluted | total_equity, shares_diluted | currency_per_share | equity | standard financial-statement analysis |
| Cash conversion | `ratio.cash_conversion.v1` | 1 | free_cash_flow / net_income | free_cash_flow, net_income | ratio | equity | standard financial-statement analysis |
| Cash ratio | `ratio.cash_ratio.v1` | 1 | cash / current_liabilities | cash_and_equivalents, current_liabilities | ratio | equity | standard financial-statement analysis |
| Current ratio | `ratio.current_ratio.v1` | 1 | current_assets / current_liabilities | current_assets, current_liabilities | ratio | equity | standard financial-statement analysis |
| Days inventory | `ratio.days_inventory.v1` | 1 | 365 / inventory_turnover | cost_of_revenue, inventory | ratio | equity | standard financial-statement analysis |
| Days sales outstanding | `ratio.days_sales_outstanding.v1` | 1 | 365 / receivables_turnover | revenue, receivables | ratio | equity | standard financial-statement analysis |
| Debt to assets | `ratio.debt_to_assets.v1` | 1 | total_debt / total_assets | total_debt, total_assets | ratio | equity | standard financial-statement analysis |
| Debt to equity | `ratio.debt_to_equity.v1` | 1 | total_debt / total_equity | total_debt, total_equity | ratio | equity | standard financial-statement analysis |
| EPS (diluted) | `ratio.eps_diluted.v1` | 1 | net_income / shares_diluted | net_income, shares_diluted | currency_per_share | equity | standard financial-statement analysis |
| Free cash-flow margin | `ratio.fcf_margin.v1` | 1 | free_cash_flow / revenue | free_cash_flow, revenue | ratio_percent | equity | standard financial-statement analysis |
| Free cash flow per share | `ratio.fcf_per_share.v1` | 1 | free_cash_flow / shares_diluted | free_cash_flow, shares_diluted | currency_per_share | equity | standard financial-statement analysis |
| Free cash-flow yield | `ratio.fcf_yield.v1` | 1 | free_cash_flow / market_cap | free_cash_flow, market_cap | ratio_percent | equity | standard financial-statement analysis |
| Gross margin | `ratio.gross_margin.v1` | 1 | gross_profit / revenue | gross_profit, revenue | ratio_percent | equity | standard financial-statement analysis |
| Interest coverage | `ratio.interest_coverage.v1` | 1 | EBIT / interest_expense | ebit, interest_expense | ratio | equity | standard financial-statement analysis |
| Inventory turnover | `ratio.inventory_turnover.v1` | 1 | cost_of_revenue / avg(inventory) | cost_of_revenue, inventory | ratio | equity | standard financial-statement analysis |
| Net debt to EBITDA | `ratio.net_debt_to_ebitda.v1` | 1 | (total_debt - cash) / EBITDA; negative EBITDA -> NaN | total_debt, cash_and_equivalents, ebitda | ratio | equity | standard financial-statement analysis |
| Net margin | `ratio.net_margin.v1` | 1 | net_income / revenue | net_income, revenue | ratio_percent | equity | standard financial-statement analysis |
| Operating cash-flow margin | `ratio.ocf_margin.v1` | 1 | operating_cash_flow / revenue | operating_cash_flow, revenue | ratio_percent | equity | standard financial-statement analysis |
| Operating margin | `ratio.operating_margin.v1` | 1 | operating_income / revenue | operating_income, revenue | ratio_percent | equity | standard financial-statement analysis |
| Quick ratio | `ratio.quick_ratio.v1` | 1 | (current_assets - inventory) / current_liabilities | current_assets, inventory, current_liabilities | ratio | equity | standard financial-statement analysis |
| Receivables turnover | `ratio.receivables_turnover.v1` | 1 | revenue / avg(receivables) | revenue, receivables | ratio | equity | standard financial-statement analysis |
| Return on assets | `ratio.return_on_assets.v1` | 1 | net_income / avg(total_assets) | net_income, total_assets | ratio_percent | equity | standard financial-statement analysis |
| Return on equity | `ratio.return_on_equity.v1` | 1 | net_income / avg(total_equity); non-positive equity -> NaN | net_income, total_equity | ratio_percent | equity | standard financial-statement analysis |
| Return on invested capital | `ratio.return_on_invested_capital.v1` | 1 | EBIT*(1-eff_tax) / (total_debt+equity-cash) | ebit, tax_expense, pretax_income, total_debt, total_equity, cash_and_equivalents | ratio_percent | equity | standard financial-statement analysis |
| Conditional VaR (expected shortfall) | `risk.cvar.v1` | 1 | -mean(r / r <= VaR quantile) | returns, confidence | ratio_percent | equity, etf, index | standard definition |
| EWMA volatility | `risk.ewma_volatility.v1` | 1 | RiskMetrics EWMA(var, lambda); annualized | returns, lambda | ratio_percent | equity, etf, index | standard definition |
| Maximum drawdown | `risk.max_drawdown.v1` | 1 | min(wealth/cummax(wealth) - 1) | returns | ratio_percent | equity, etf, index | standard definition |
| Max drawdown duration | `risk.max_drawdown_duration.v1` | 1 | longest run below a prior wealth peak | returns | periods | equity, etf, index | standard definition |
| Gaussian VaR | `risk.var.gaussian.v1` | 1 | -(mean + z_{1-conf} * std) | returns, confidence | ratio_percent | equity, etf, index | standard definition |
| Historical VaR | `risk.var.historical.v1` | 1 | -quantile(r, 1-confidence) | returns, confidence | ratio_percent | equity, etf, index | empirical quantile |
| Annualized volatility | `risk.volatility.v1` | 1 | std(r, ddof=1) * sqrt(P) | returns | ratio_percent | equity, etf, index | standard definition |
