"""Quality & financial-health scores: Piotroski F-score and Altman Z-score.

Both take dicts of standardized fundamentals (field -> value). Missing inputs are
handled honestly: the F-score reports how many of the 9 signals were *computable*
(`max_possible`) rather than silently scoring a 0. Altman Z carries the caveat
that it was calibrated on manufacturers (dossier §5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Piotroski:
    score: int = 0
    max_possible: int = 0
    components: dict = field(default_factory=dict)


def _get(d: dict, k: str) -> Optional[float]:
    v = d.get(k)
    return float(v) if v is not None else None


def piotroski_f_score(curr: dict, prev: dict) -> Piotroski:
    p = Piotroski()

    def add(name: str, condition: Optional[bool]):
        if condition is None:
            return  # not computable → don't count toward max
        p.max_possible += 1
        got = 1 if condition else 0
        p.score += got
        p.components[name] = got

    a_c, a_p = _get(curr, "assets"), _get(prev, "assets")
    ni_c, ni_p = _get(curr, "net_income"), _get(prev, "net_income")
    cfo_c = _get(curr, "operating_cash_flow")
    ltd_c, ltd_p = _get(curr, "long_term_debt"), _get(prev, "long_term_debt")
    ca_c, ca_p = _get(curr, "current_assets"), _get(prev, "current_assets")
    cl_c, cl_p = _get(curr, "current_liabilities"), _get(prev, "current_liabilities")
    sh_c, sh_p = _get(curr, "shares_outstanding"), _get(prev, "shares_outstanding")
    gp_c, gp_p = _get(curr, "gross_profit"), _get(prev, "gross_profit")
    rev_c, rev_p = _get(curr, "revenue"), _get(prev, "revenue")

    roa_c = (ni_c / a_c) if (ni_c is not None and a_c) else None
    roa_p = (ni_p / a_p) if (ni_p is not None and a_p) else None

    # Profitability
    add("roa_positive", (roa_c > 0) if roa_c is not None else None)
    add("cfo_positive", (cfo_c > 0) if cfo_c is not None else None)
    add("roa_improving", (roa_c > roa_p) if (roa_c is not None and roa_p is not None) else None)
    add("accrual_quality",
        (cfo_c / a_c > roa_c) if (cfo_c is not None and a_c and roa_c is not None) else None)

    # Leverage / liquidity / source of funds
    lev_c = (ltd_c / a_c) if (ltd_c is not None and a_c) else None
    lev_p = (ltd_p / a_p) if (ltd_p is not None and a_p) else None
    add("leverage_down", (lev_c < lev_p) if (lev_c is not None and lev_p is not None) else None)

    cr_c = (ca_c / cl_c) if (ca_c is not None and cl_c) else None
    cr_p = (ca_p / cl_p) if (ca_p is not None and cl_p) else None
    add("current_ratio_up", (cr_c > cr_p) if (cr_c is not None and cr_p is not None) else None)

    add("no_dilution", (sh_c <= sh_p) if (sh_c is not None and sh_p is not None) else None)

    # Operating efficiency
    gm_c = (gp_c / rev_c) if (gp_c is not None and rev_c) else None
    gm_p = (gp_p / rev_p) if (gp_p is not None and rev_p) else None
    add("gross_margin_up", (gm_c > gm_p) if (gm_c is not None and gm_p is not None) else None)

    at_c = (rev_c / a_c) if (rev_c is not None and a_c) else None
    at_p = (rev_p / a_p) if (rev_p is not None and a_p) else None
    add("asset_turnover_up", (at_c > at_p) if (at_c is not None and at_p is not None) else None)

    return p


@dataclass
class Altman:
    z: Optional[float] = None
    zone: str = "unknown"
    note: str = "Altman Z calibrated on manufacturers; treat as indicative for others."


def altman_z(fundamentals: dict, market_cap: Optional[float]) -> Altman:
    a = _get(fundamentals, "assets")
    ca = _get(fundamentals, "current_assets")
    cl = _get(fundamentals, "current_liabilities")
    re = _get(fundamentals, "retained_earnings")
    ebit = _get(fundamentals, "operating_income")
    liab = _get(fundamentals, "liabilities")
    sales = _get(fundamentals, "revenue")
    if not a or a <= 0 or liab is None or liab <= 0 or market_cap is None:
        return Altman()
    if None in (ca, cl, re, ebit, sales):
        return Altman()

    x1 = (ca - cl) / a
    x2 = re / a
    x3 = ebit / a
    x4 = market_cap / liab
    x5 = sales / a
    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
    zone = "safe" if z > 2.99 else ("distress" if z < 1.81 else "grey")
    return Altman(z=float(z), zone=zone)
