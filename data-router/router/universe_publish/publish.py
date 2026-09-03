"""Publish a dated universe snapshot to a JSON file — the artifact DATA-02
says models must read, never a live query.

``publish_universe_snapshot`` takes a membership table (any DataFrame
matching ``router.universe.UniverseBuilder``'s contract — the sample table in
``sample_membership.py`` for this sandbox, a real vendor-backed one later)
and an as-of date, computes the as-of membership via the existing
(unmodified) ``UniverseBuilder``, and writes one dated JSON file. A model
reads that file — via ``load_published_universe`` or directly, it's plain
JSON — and never calls ``UniverseBuilder`` itself at inference/backtest time.

Every published file states its universe name, its venue, its as-of date,
and its sample size, per DATA-02's "every cross sectional output states its
universe, its as at date and its sample size" — this file is the one place
those three facts are authoritatively recorded; anything built from it
should carry them forward rather than recomputing or guessing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from router.universe import UniverseBuilder

SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class PublishedMember:
    ticker: str
    entry_date: date
    exit_date: Optional[date]
    inclusion_reason: str


@dataclass(frozen=True)
class PublishedUniverse:
    schema_version: str
    universe_name: str
    venue: str
    as_of_date: date
    published_at: str  # ISO-8601 UTC timestamp of when the file was written
    sample_size: int
    members: list[PublishedMember]
    note: str


def _member_row(membership: pd.DataFrame, ticker: str) -> pd.Series:
    matches = membership.loc[membership["ticker"] == ticker]
    if matches.empty:
        raise KeyError(f"ticker {ticker!r} not found in membership table")
    return matches.iloc[0]


def build_published_universe(
    membership: pd.DataFrame,
    as_of: date,
    *,
    universe_name: str,
    venue: str,
    liquidity: Optional[pd.DataFrame] = None,
    liquidity_floor: Optional[float] = None,
    note: str = "",
    published_at: Optional[str] = None,
) -> PublishedUniverse:
    """Compute the as-of membership (via the existing, unmodified
    ``UniverseBuilder``) and assemble the dated snapshot object that
    ``publish_universe_snapshot`` serializes."""
    builder = UniverseBuilder(
        membership, liquidity=liquidity, liquidity_floor=liquidity_floor
    )
    tickers = builder.universe_as_of(as_of)

    members = []
    for t in tickers:
        row = _member_row(membership, t)
        exit_val = row["exit_date"]
        exit_date = None if pd.isna(exit_val) else exit_val
        members.append(
            PublishedMember(
                ticker=t,
                entry_date=row["entry_date"],
                exit_date=exit_date,
                inclusion_reason=str(row.get("inclusion_reason", "index_membership")),
            )
        )

    return PublishedUniverse(
        schema_version=SCHEMA_VERSION,
        universe_name=universe_name,
        venue=venue,
        as_of_date=as_of,
        published_at=published_at or datetime.now(timezone.utc).isoformat(),
        sample_size=len(members),
        members=members,
        note=note,
    )


def _to_json_dict(pu: PublishedUniverse) -> dict:
    return {
        "schema_version": pu.schema_version,
        "universe_name": pu.universe_name,
        "venue": pu.venue,
        "as_of_date": pu.as_of_date.isoformat(),
        "published_at": pu.published_at,
        "sample_size": pu.sample_size,
        "members": [
            {
                "ticker": m.ticker,
                "entry_date": m.entry_date.isoformat(),
                "exit_date": m.exit_date.isoformat() if m.exit_date else None,
                "inclusion_reason": m.inclusion_reason,
            }
            for m in pu.members
        ],
        "note": pu.note,
    }


def publish_universe_snapshot(
    membership: pd.DataFrame,
    as_of: date,
    out_path: Path,
    *,
    universe_name: str,
    venue: str,
    liquidity: Optional[pd.DataFrame] = None,
    liquidity_floor: Optional[float] = None,
    note: str = "",
    published_at: Optional[str] = None,
) -> Path:
    """Build the as-of snapshot and write it to ``out_path`` as JSON.
    Returns ``out_path`` for convenience."""
    pu = build_published_universe(
        membership,
        as_of,
        universe_name=universe_name,
        venue=venue,
        liquidity=liquidity,
        liquidity_floor=liquidity_floor,
        note=note,
        published_at=published_at,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(_to_json_dict(pu), indent=2, sort_keys=False) + "\n")
    return out_path


def load_published_universe(path: Path) -> PublishedUniverse:
    """Read a published snapshot back. This is the read path models use —
    plain file I/O, no query against any live universe/membership source."""
    raw = json.loads(Path(path).read_text())
    members = [
        PublishedMember(
            ticker=m["ticker"],
            entry_date=date.fromisoformat(m["entry_date"]),
            exit_date=date.fromisoformat(m["exit_date"]) if m["exit_date"] else None,
            inclusion_reason=m["inclusion_reason"],
        )
        for m in raw["members"]
    ]
    return PublishedUniverse(
        schema_version=raw["schema_version"],
        universe_name=raw["universe_name"],
        venue=raw["venue"],
        as_of_date=date.fromisoformat(raw["as_of_date"]),
        published_at=raw["published_at"],
        sample_size=raw["sample_size"],
        members=members,
        note=raw["note"],
    )
