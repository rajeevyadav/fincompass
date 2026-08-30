"""FinCompass deterministic analytics kernel.

Transparent, provider-independent quantitative metrics. Every metric is a native
reimplementation from its public formula (no runtime dependency on any external
analytics package or paid provider), carries a versioned formula-registry entry,
and is verified by independent hand-calculated unit tests.

Layout:
    common      shared transforms + centralized numerical conventions
    registry    versioned formula definitions + the universal result contract
    performance return/volatility/Sharpe/Sortino/Calmar/beta/drawdown
    risk        volatility/EWMA/VaR/CVaR/drawdown risk
"""
