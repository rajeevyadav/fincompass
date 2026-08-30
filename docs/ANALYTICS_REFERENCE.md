# FinCompass Analytics Reference

Auto-derived from the in-code formula registry (analytics/registry.py). Every metric is a native, provider-independent reimplementation verified by hand-calculated unit tests. No external analytics package or paid provider is required at runtime.

Ratios and DCF consume ONLY canonical statement fields (see analytics/statements.py) — provider vocabulary never reaches a formula. A DCF intrinsic value is a scenario/assumption estimate, NOT a probability or price target. Fixed-income measures are closed-form from user-supplied bond terms. VaR is a confidence-level loss threshold, not a maximum possible loss. Non-positive or missing denominators yield NaN.

| Metric | ID | Version | Formula | Inputs | Units | Supported assets | Reference |
|---|---|---|---|---|---|---|---|
| Bond price (PV of cash flows) | `fixedincome.bond_price.v1` | 1 | sum(CF_t / (1+ytm/freq)^t); CF includes coupon each period and face at maturity | face, coupon_rate, ytm, years, freq | currency | fixed_income | standard bond present-value; not a forecast or guaranteed return |
| Convexity | `fixedincome.convexity.v1` | 1 | sum(CF_t * t*(t+1) / (1+y)^(t+2)) / (price * freq^2) | face, coupon_rate, ytm, years, freq | years_squared | fixed_income | standard definition |
| Current yield | `fixedincome.current_yield.v1` | 1 | annual coupon / clean price | face, coupon_rate, price | ratio | fixed_income | standard definition |
| DV01 (price value of a basis point) | `fixedincome.dv01.v1` | 1 | price(ytm - 1bp) - price(ytm) | face, coupon_rate, ytm, years, freq | currency | fixed_income | standard definition |
| Macaulay duration | `fixedincome.macaulay_duration.v1` | 1 | sum((t/freq) * PV(CF_t)) / price | face, coupon_rate, ytm, years, freq | years | fixed_income | standard definition |
| Modified duration | `fixedincome.modified_duration.v1` | 1 | Macaulay / (1 + ytm/freq) | face, coupon_rate, ytm, years, freq | years | fixed_income | standard definition |
| Yield to maturity | `fixedincome.ytm.v1` | 1 | yield solving price = sum(CF_t/(1+ytm/freq)^t) via bisection | price, face, coupon_rate, years, freq | ratio | fixed_income | internal rate of return of the bond cash flows |
| Option price (Black-Scholes-Merton) | `options.bsm_price.v1` | 1 | call = S e^-qT N(d1) - K e^-rT N(d2); put via -d1,-d2; d1=(ln(S/K)+(r-q+σ²/2)T)/(σ√T) | option_type, spot, strike, rate, vol, expiry, div_yield | currency | option | Black-Scholes-Merton; not a forecast or probability of profit |
| Delta | `options.delta.v1` | 1 | e^-qT N(d1) [call]; e^-qT (N(d1)-1) [put] | option_type, spot, strike, rate, vol, expiry, div_yield | ratio | option | standard definition |
| Gamma | `options.gamma.v1` | 1 | e^-qT n(d1) / (S σ√T) | spot, strike, rate, vol, expiry, div_yield | per_currency | option | standard definition |
| Implied volatility | `options.implied_vol.v1` | 1 | vol solving BSM(price)=market_price via bisection | option_type, market_price, spot, strike, rate, expiry, div_yield | ratio | option | inversion of the BSM price; an implied, not forecast, volatility |
| Rho (per 1.00 rate) | `options.rho.v1` | 1 | K T e^-rT N(d2) [call]; -K T e^-rT N(-d2) [put] | option_type, spot, strike, rate, vol, expiry, div_yield | currency_per_rate | option | standard definition |
| Theta (per year) | `options.theta.v1` | 1 | -S e^-qT n(d1) σ/(2√T) -/+ r K e^-rT N(±d2) +/- q S e^-qT N(±d1) | option_type, spot, strike, rate, vol, expiry, div_yield | currency_per_year | option | standard definition |
| Vega (per 1.00 vol) | `options.vega.v1` | 1 | S e^-qT n(d1) √T | spot, strike, rate, vol, expiry, div_yield | currency_per_vol | option | standard definition |
| Annualized return | `performance.annualized_return.v1` | 1 | prod(1+r)^(P/N) - 1 | returns | ratio_percent | equity, etf, index | standard definition |
| Beta | `performance.beta.v1` | 1 | cov(asset, market) / var(market) | asset_returns, market_returns | ratio | equity, etf, index | standard definition |
| Calmar ratio | `performance.calmar.v1` | 1 | annualized_return / |max_drawdown| | returns | ratio | equity, etf, index | standard definition |
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
| Conditional VaR (expected shortfall) | `risk.cvar.v1` | 1 | -mean(r | r <= VaR quantile) | returns, confidence | ratio_percent | equity, etf, index | standard definition |
| EWMA volatility | `risk.ewma_volatility.v1` | 1 | RiskMetrics EWMA(var, lambda); annualized | returns, lambda | ratio_percent | equity, etf, index | standard definition |
| Maximum drawdown | `risk.max_drawdown.v1` | 1 | min(wealth/cummax(wealth) - 1) | returns | ratio_percent | equity, etf, index | standard definition |
| Max drawdown duration | `risk.max_drawdown_duration.v1` | 1 | longest run below a prior wealth peak | returns | periods | equity, etf, index | standard definition |
| Gaussian VaR | `risk.var.gaussian.v1` | 1 | -(mean + z_{1-conf} * std) | returns, confidence | ratio_percent | equity, etf, index | standard definition |
| Historical VaR | `risk.var.historical.v1` | 1 | -quantile(r, 1-confidence) | returns, confidence | ratio_percent | equity, etf, index | empirical quantile |
| Annualized volatility | `risk.volatility.v1` | 1 | std(r, ddof=1) * sqrt(P) | returns | ratio_percent | equity, etf, index | standard definition |
| DCF (unlevered FCFF) | `valuation.dcf.fcff.v1` | 1 | EV = sum(FCFF_t / (1+WACC)^t) + PV(terminal); FCFF = EBIT*(1-tax) + D&A - CapEx - dNWC | revenue, ebit, tax_rate, da, capex, nwc, wacc | currency | equity | standard unlevered DCF; intrinsic value is not a probability or price target |
| EV to equity per share | `valuation.equity_bridge.v1` | 1 | (EV - net_debt) / diluted_shares | enterprise_value, net_debt, shares_diluted | currency_per_share | equity | standard definition |
| Terminal value (exit multiple) | `valuation.terminal.exit_multiple.v1` | 1 | exit_multiple * EBITDA_H | ebitda_terminal, exit_multiple | currency | equity | standard definition |
| Terminal value (perpetual growth) | `valuation.terminal.perpetual.v1` | 1 | FCFF_H*(1+g)/(WACC-g) | fcff_terminal, wacc, terminal_growth | currency | equity | standard definition |
