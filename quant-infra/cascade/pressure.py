"""WW-CASCADE — mechanical flow pressure on constituents.

The doc: "Detects when flow into or out of a fund is mechanically moving its
constituents, estimates the pressure on each name... Pressure scales with the
weight the name carries and inversely with how much volume it can absorb...
Where a name sits in several products, sum across all of them."

**Chosen functional form** (documented, simple, testable):

    pressure_{p,i} = weight_{p,i} * flow_dollars_p / typical_volume_i
    pressure_i     = sum over all products p holding name i of pressure_{p,i}

`weight_{p,i}` is the constituent's portfolio weight in product `p` (signed —
a short sleeve can carry a negative weight). `flow_dollars_p` is the signed
dollar flow estimate for product `p` (positive = net creation/inflow,
negative = net redemption/outflow). `typical_volume_i` is the constituent's
typical (e.g. 21-day average) dollar volume. The product `weight * flow` is
the dollar notional of constituent `i` that product `p`'s flow mechanically
forces through the market; dividing by `typical_volume_i` expresses that as a
fraction of a normal day's liquidity — the quantity the doc calls "pressure".

Two ways to estimate `flow_dollars_p` are provided:

1. **Direct** (`estimate_flow_from_shares_outstanding`) — from the fund's own
   shares-outstanding change, which for a '40 Act / ETF wrapper is the ground
   truth of creation/redemption activity.
2. **Proxy** (`estimate_flow_proxy`) — when shares-outstanding data is not
   available, inferred from traded volume and the NAV premium/discount (a
   persistent premium with volume behind it is evidence of net creation
   demand). This path is explicitly labelled `is_proxy=True` in its output —
   callers must not treat it as equal-confidence to the direct measurement.

Every constituent-leg where the inputs are unusable (missing product flow,
NaN weight, non-positive/NaN typical volume) is **excluded from the sum**
rather than poisoning it with a NaN or silently treated as zero pressure; the
result records exactly which legs were used so a caller can tell a fully
covered name from a partially covered one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

import numpy as np
import pandas as pd

HOLDINGS_COLUMNS = ("product", "constituent", "weight", "as_at_date")


@dataclass(frozen=True)
class FlowEstimate:
    """A signed dollar-flow estimate for one product as of one date.

    `flow_dollars`: positive = net inflow/creation, negative = net
    redemption/outflow. `NaN` means "flow could not be estimated" and any
    product carrying it is excluded from `compute_pressure` (never coerced
    to zero, which would understate real pressure).
    """

    product: str
    as_at_date: object
    flow_dollars: float
    method: Literal["shares_outstanding", "proxy"]
    is_proxy: bool


@dataclass(frozen=True)
class PressureResult:
    """Per-constituent pressure, aggregated across every product it sits in."""

    pressure: pd.DataFrame  # constituent, pressure, n_products_total, n_products_used, any_proxy
    skipped_products: tuple[str, ...]
    warnings: tuple[str, ...]


def estimate_flow_from_shares_outstanding(
    product: str,
    as_at_date: object,
    shares_out_prev: float,
    shares_out_now: float,
    nav_per_share: float,
) -> FlowEstimate:
    """Direct flow estimate from a change in shares outstanding.

    flow_dollars = (shares_out_now - shares_out_prev) * nav_per_share

    Negative share counts or NAV are not physically meaningful and raise.
    Any NaN input yields `flow_dollars = NaN` (an explicit "unknown", not a
    silently-assumed zero).
    """
    inputs = (shares_out_prev, shares_out_now, nav_per_share)
    if any(v is not None and v < 0 for v in inputs if _is_number(v) and not np.isnan(v)):
        raise ValueError("shares outstanding and NAV per share must be non-negative")
    if any(_is_nan(v) for v in inputs):
        flow = float("nan")
    else:
        flow = float((shares_out_now - shares_out_prev) * nav_per_share)
    return FlowEstimate(
        product=product,
        as_at_date=as_at_date,
        flow_dollars=flow,
        method="shares_outstanding",
        is_proxy=False,
    )


def estimate_flow_proxy(
    product: str,
    as_at_date: object,
    volume_shares: float,
    price: float,
    nav_per_share: float,
    sensitivity: float = 1.0,
) -> FlowEstimate:
    """Proxy flow estimate from traded volume and the NAV premium/discount,
    for use when shares-outstanding data is not (yet) available.

    premium   = (price - nav_per_share) / nav_per_share
    flow_dollars = sensitivity * premium * volume_shares * price

    Rationale: a persistent premium accompanied by volume is evidence
    creations are being demanded (and vice versa for a discount); scaling by
    dollar volume traded converts that into a dollar-flow-like magnitude.
    `sensitivity` is an explicit, caller-tunable fudge factor — this is a
    proxy, not a measurement, and the result is labelled `is_proxy=True`.

    `nav_per_share <= 0` makes the premium undefined -> NaN flow (never a
    divide-by-zero). Negative volume or price is not physically meaningful
    and raises. Zero volume naturally yields zero flow (no trading, no
    inferable pressure) without a special case.
    """
    if _is_number(volume_shares) and not np.isnan(volume_shares) and volume_shares < 0:
        raise ValueError("volume_shares must be non-negative")
    if _is_number(price) and not np.isnan(price) and price < 0:
        raise ValueError("price must be non-negative")
    if _is_number(nav_per_share) and not np.isnan(nav_per_share) and nav_per_share < 0:
        raise ValueError("nav_per_share must be non-negative")

    if any(_is_nan(v) for v in (volume_shares, price, nav_per_share)):
        flow = float("nan")
    elif nav_per_share == 0:
        flow = float("nan")  # premium undefined
    else:
        premium = (price - nav_per_share) / nav_per_share
        flow = float(sensitivity * premium * volume_shares * price)

    return FlowEstimate(
        product=product,
        as_at_date=as_at_date,
        flow_dollars=flow,
        method="proxy",
        is_proxy=True,
    )


def compute_pressure(
    holdings: pd.DataFrame,
    flows: Sequence[FlowEstimate],
    typical_volume: Mapping[str, float] | pd.Series,
) -> PressureResult:
    """Sum weight*flow/typical_volume across every product a constituent sits in.

    `holdings` must have columns `product, constituent, weight, as_at_date`
    (extra columns are ignored). Empty holdings return an empty, well-formed
    result. A constituent-leg is excluded from the sum (never included as
    zero or NaN-poisoned) when: its product has no flow estimate or a NaN
    flow estimate, its weight is NaN, or its `typical_volume` is missing,
    NaN, zero or negative.
    """
    missing_cols = set(HOLDINGS_COLUMNS) - set(holdings.columns)
    if missing_cols:
        raise ValueError(f"holdings is missing required columns: {sorted(missing_cols)}")

    warnings: list[str] = []
    flow_map = {f.product: f for f in flows}

    if holdings.empty:
        empty = pd.DataFrame(
            columns=["constituent", "pressure", "n_products_total", "n_products_used", "any_proxy"]
        )
        return PressureResult(pressure=empty, skipped_products=(), warnings=())

    tv = typical_volume if isinstance(typical_volume, pd.Series) else pd.Series(typical_volume)

    skipped_products: list[str] = []
    legs = []  # (constituent, product, contribution, is_proxy)

    for product, group in holdings.groupby("product", sort=False):
        flow = flow_map.get(product)
        if flow is None:
            skipped_products.append(str(product))
            warnings.append(f"product {product!r} has no flow estimate; skipped")
            continue
        if _is_nan(flow.flow_dollars):
            skipped_products.append(str(product))
            warnings.append(f"product {product!r} has a NaN flow estimate; skipped")
            continue

        for _, row in group.iterrows():
            constituent = row["constituent"]
            weight = row["weight"]
            if _is_nan(weight):
                warnings.append(f"{constituent!r} in {product!r} has a NaN weight; leg skipped")
                continue
            v = tv.get(constituent, np.nan)
            if _is_nan(v) or v <= 0:
                warnings.append(
                    f"{constituent!r} has no usable typical_volume ({v!r}); "
                    f"leg from {product!r} skipped"
                )
                continue
            contribution = float(weight) * flow.flow_dollars / float(v)
            legs.append((constituent, product, contribution, flow.is_proxy))

    # total product count per constituent (for coverage reporting), independent
    # of whether that leg ended up usable.
    total_counts = holdings.groupby("constituent")["product"].nunique()

    if not legs:
        out = pd.DataFrame(
            {
                "constituent": total_counts.index,
                "pressure": np.nan,
                "n_products_total": total_counts.values,
                "n_products_used": 0,
                "any_proxy": False,
            }
        ).reset_index(drop=True)
        return PressureResult(
            pressure=out, skipped_products=tuple(skipped_products), warnings=tuple(warnings)
        )

    legs_df = pd.DataFrame(legs, columns=["constituent", "product", "contribution", "is_proxy"])
    agg = legs_df.groupby("constituent").agg(
        pressure=("contribution", "sum"),
        n_products_used=("product", "nunique"),
        any_proxy=("is_proxy", "any"),
    )
    out = agg.reindex(total_counts.index)
    out["n_products_total"] = total_counts
    # constituents with zero usable legs: pressure stays NaN (never a fake 0)
    out["pressure"] = out["pressure"].where(out["n_products_used"].notna())
    out["n_products_used"] = out["n_products_used"].fillna(0).astype(int)
    out["any_proxy"] = out["any_proxy"].fillna(False)
    out = out.reset_index()[
        ["constituent", "pressure", "n_products_total", "n_products_used", "any_proxy"]
    ]
    return PressureResult(
        pressure=out, skipped_products=tuple(skipped_products), warnings=tuple(warnings)
    )


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float, np.floating, np.integer))


def _is_nan(v: object) -> bool:
    try:
        return bool(np.isnan(v))
    except (TypeError, ValueError):
        return v is None
