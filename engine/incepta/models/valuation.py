"""Valuation ratios from point-in-time fundamentals + price.

Every ratio guards its denominator and returns NaN (with a `flags` note) where it
is meaningless — e.g. P/E for a loss-making company. The dossier is explicit that
these break down for banks/insurers/REITs/early-stage/commodity names; this module
computes the generic ratios and FLAGS unreliability, it does not pretend the
number is meaningful when it isn't.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


@dataclass
class Valuation:
    market_cap: Optional[float] = None
    pe: Optional[float] = None
    earnings_yield: Optional[float] = None
    pb: Optional[float] = None
    ps: Optional[float] = None
    fcf_yield: Optional[float] = None
    ev: Optional[float] = None
    ev_sales: Optional[float] = None
    flags: list = field(default_factory=list)


def compute_valuation(
    price: float,
    shares_outstanding: Optional[float],
    net_income: Optional[float],
    stockholders_equity: Optional[float],
    revenue: Optional[float],
    operating_cash_flow: Optional[float] = None,
    capex: Optional[float] = None,
    long_term_debt: Optional[float] = None,
    cash_and_equivalents: Optional[float] = None,
    sic: Optional[str] = None,
) -> Valuation:
    v = Valuation()
    if not shares_outstanding or shares_outstanding <= 0:
        v.flags.append("no share count → cannot value")
        return v

    mktcap = price * shares_outstanding
    v.market_cap = mktcap

    if net_income is not None and net_income > 0:
        v.pe = _safe_div(mktcap, net_income)
        v.earnings_yield = _safe_div(net_income, mktcap)
    else:
        v.flags.append("negative/zero earnings → P/E not meaningful")

    if stockholders_equity is not None and stockholders_equity > 0:
        v.pb = _safe_div(mktcap, stockholders_equity)
    else:
        v.flags.append("negative/zero book equity → P/B not meaningful")

    v.ps = _safe_div(mktcap, revenue)

    if operating_cash_flow is not None and capex is not None:
        fcf = operating_cash_flow - abs(capex)
        v.fcf_yield = _safe_div(fcf, mktcap)

    if long_term_debt is not None or cash_and_equivalents is not None:
        v.ev = mktcap + (long_term_debt or 0.0) - (cash_and_equivalents or 0.0)
        v.ev_sales = _safe_div(v.ev, revenue)

    # sector reliability flags (SIC ranges are coarse but catch the big cases)
    if sic:
        try:
            code = int(sic)
            if 6000 <= code <= 6199:
                v.flags.append("bank/finance (SIC): EV/EBITDA & FCF unreliable; use P/B, P/TBV")
            elif 6200 <= code <= 6499:
                v.flags.append("insurer/REIT (SIC): use P/B/NAV/FFO, not P/E or EV")
        except ValueError:
            pass
    return v
