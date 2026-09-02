"""Standardized fundamental fields ↔ XBRL (us-gaap) concept candidates.

XBRL tagging is not uniform across filers, so each standardized field maps to an
ordered list of candidate us-gaap tags; the first one present for a company wins.
This is intentionally a *starter* set (slice 1). It is enough to prove the PIT
pipeline end to end; slice 3 expands it and adds sector-specific handling (banks,
REITs, insurers) where these tags are unreliable (see the dossier's valuation
section).

We keep the raw concept name alongside the standardized name, so nothing is lost:
the store holds every fact, and this map is just a convenience view.
"""

from __future__ import annotations

# standardized_field -> ordered candidate us-gaap concept tags
STANDARD_CONCEPTS: dict[str, list[str]] = {
    # Income statement (duration)
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "shares_diluted_wa": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    # Balance sheet (instantaneous)
    "assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "liabilities": ["Liabilities"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    "stockholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "shares_outstanding": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",  # dei taxonomy
    ],
    # Cash flow (duration)
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
}

# Concepts that live in the `dei` taxonomy rather than `us-gaap`.
DEI_CONCEPTS = {"EntityCommonStockSharesOutstanding"}

# The full set of concept tags we pull in slice 1 (union of the candidates).
def tracked_concepts() -> set[str]:
    out: set[str] = set()
    for tags in STANDARD_CONCEPTS.values():
        out.update(tags)
    return out
