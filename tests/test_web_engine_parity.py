"""The browser engine (web/engine.js) must match the Python analytics kernel it
was ported from. This runs the JS engine under Node and compares its output to
the Python functions across a grid of inputs. Skips cleanly if Node is absent."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from analytics import options as OPT
from analytics import fixed_income as FI
from analytics import valuation as VAL
from analytics import portfolio as PF

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js not available")

_ABS = 1e-4  # A&S erf approximation is ~1.5e-7; 1e-4 is comfortable for parity.


def _js(expr: str):
    """Evaluate a JS expression against the engine and return the parsed JSON."""
    script = f'const FC=require({json.dumps(str(ROOT / "web" / "engine.js"))}); ' \
             f'process.stdout.write(JSON.stringify({expr}));'
    out = subprocess.check_output([NODE, "-e", script], cwd=str(ROOT))
    return json.loads(out.decode("utf-8"))


def _close(a, b, abs_=_ABS):
    if a is None or (isinstance(a, float) and math.isnan(a)):
        return b is None or (isinstance(b, float) and math.isnan(b))
    return abs(float(a) - float(b)) <= abs_ * max(1.0, abs(float(b)))


def test_black_scholes_price_and_greeks_parity():
    cases = [("call", 100, 100, 0.05, 0.2, 1.0), ("put", 120, 100, 0.03, 0.35, 0.5),
             ("call", 55, 60, 0.04, 0.5, 2.0), ("put", 100, 100, 0.0, 0.15, 0.25)]
    for typ, S, K, r, vol, T in cases:
        assert _close(_js(f'FC.bsPrice("{typ}",{S},{K},{r},{vol},{T},0)'),
                      OPT.price(typ, S, K, r, vol, T, 0.0))
        g = _js(f'FC.greeks("{typ}",{S},{K},{r},{vol},{T},0)')
        assert _close(g["delta"], OPT.delta(typ, S, K, r, vol, T, 0.0))
        assert _close(g["gamma"], OPT.gamma(S, K, r, vol, T, 0.0))
        assert _close(g["vega"], OPT.vega(S, K, r, vol, T, 0.0))
        assert _close(g["theta"], OPT.theta(typ, S, K, r, vol, T, 0.0))
        assert _close(g["rho"], OPT.rho(typ, S, K, r, vol, T, 0.0))


def test_bond_analytics_parity():
    cases = [(1000, 0.05, 0.05, 10, 2), (1000, 0.04, 0.06, 5, 2), (100, 0.08, 0.03, 20, 1)]
    for face, cr, ytm, yrs, fq in cases:
        assert _close(_js(f'FC.bondPrice({face},{cr},{ytm},{yrs},{fq})'), FI.bond_price(face, cr, ytm, yrs, fq))
        assert _close(_js(f'FC.macaulayDuration({face},{cr},{ytm},{yrs},{fq})'), FI.macaulay_duration(face, cr, ytm, yrs, fq))
        assert _close(_js(f'FC.modifiedDuration({face},{cr},{ytm},{yrs},{fq})'), FI.modified_duration(face, cr, ytm, yrs, fq))
        assert _close(_js(f'FC.convexity({face},{cr},{ytm},{yrs},{fq})'), FI.convexity(face, cr, ytm, yrs, fq))
        assert _close(_js(f'FC.dv01({face},{cr},{ytm},{yrs},{fq})'), FI.dv01(face, cr, ytm, yrs, fq))
        # Reverse: recover the yield from the price.
        price = FI.bond_price(face, cr, ytm, yrs, fq)
        assert _close(_js(f'FC.yieldToMaturity({price},{face},{cr},{yrs},{fq})'), ytm, abs_=1e-3)


def test_dcf_parity():
    path = VAL.three_stage_growth_path(0.12, 0.03, 5, 5)
    py = VAL.dcf_from_free_cash_flow(100.0, path, 0.09, 0.025, -50.0, 15.0)
    js = _js('FC.dcfFromFCF(100,FC.threeStageGrowthPath(0.12,0.03,5,5),0.09,0.025,-50,15)')
    assert _close(js["valuePerShare"], py["value_per_share"])
    assert _close(js["terminalValue"], py["terminal_value"])
    assert _close(js["pvTerminalValue"], py["pv_terminal_value"])
    ig = _js('FC.impliedFcfGrowth(184.0442,100,0.09,0.025,-50,15,5,5,0.03)')
    assert _close(ig, VAL.implied_fcf_growth(184.0442, 100.0, 0.09, 0.025, -50.0, 15.0, 5, 5, 0.03))


def test_portfolio_parity():
    weights = [0.5, 0.5]
    cov = [[0.04, 0.006], [0.006, 0.09]]
    js = _js(f'FC.riskContributions({weights},{cov})')
    py_rc = PF.risk_contributions(weights, cov)
    assert _close(js["volatility"], PF.portfolio_volatility(weights, cov))
    for i in range(2):
        assert _close(js["percent"][i], py_rc["percent"][i])
        assert _close(js["component"][i], py_rc["component"][i])
