"""WW-SIZING — append-only sizing-decision ledger (IMP-17).

"Log both numbers on every sizing decision so the binding constraint is
always identifiable afterwards." This module is the log. It is a small,
self-contained, append-only record store — it mirrors the style of
`engine/incepta/validation/store.py`'s `JsonlRecordStore` (one JSON object
per line, opened in append mode so a crash mid-run can never silently drop
or rewrite an earlier decision) but does not import from `engine/`: this
package is a sealed root, same as every other `quant-infra/*` subpackage.

Two backends are provided behind the same three-method interface:
  - `InMemorySizingLedger` — a plain list, for tests and for callers that
    persist elsewhere.
  - `JsonlSizingLedger` — one `<strategy_id>.jsonl` file per strategy under
    a base directory, for a real append-only on-disk trail.

Both record a `SizingDecision` (from `ceiling.py`) together with the
strategy id and a timestamp, and both expose the same read-back API so
"the binding constraint is always identifiable after the fact" is
satisfiable regardless of which backend a caller wires up.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Protocol

from ceiling import SizingDecision


@dataclass(frozen=True)
class SizingLedgerEntry:
    """One durable record of a sizing decision."""

    strategy_id: str
    timestamp: float  # seconds since epoch (time.time()); caller-injectable for tests
    approved_size: float
    allocator_budget: float
    portfolio_risk_ceiling: float
    binding_constraint: str

    @classmethod
    def from_decision(
        cls, strategy_id: str, decision: SizingDecision, timestamp: Optional[float] = None
    ) -> "SizingLedgerEntry":
        return cls(
            strategy_id=strategy_id,
            timestamp=time.time() if timestamp is None else float(timestamp),
            approved_size=decision.approved_size,
            allocator_budget=decision.allocator_budget,
            portfolio_risk_ceiling=decision.portfolio_risk_ceiling,
            binding_constraint=decision.binding_constraint,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SizingLedgerEntry":
        return cls(
            strategy_id=d["strategy_id"],
            timestamp=float(d["timestamp"]),
            approved_size=float(d["approved_size"]),
            allocator_budget=float(d["allocator_budget"]),
            portfolio_risk_ceiling=float(d["portfolio_risk_ceiling"]),
            binding_constraint=d["binding_constraint"],
        )


class SizingLedger(Protocol):
    """Append-only sizing-decision ledger. Never mutates or removes a prior
    entry — the whole point is that the binding constraint on every past
    decision stays identifiable."""

    def record(
        self, strategy_id: str, decision: SizingDecision, timestamp: Optional[float] = None
    ) -> SizingLedgerEntry: ...

    def entries_for(self, strategy_id: str) -> list[SizingLedgerEntry]: ...

    def all_entries(self) -> list[SizingLedgerEntry]: ...


class InMemorySizingLedger:
    """Plain in-memory append-only ledger, keyed by strategy id."""

    def __init__(self) -> None:
        self._by_strategy: dict[str, list[SizingLedgerEntry]] = {}

    def record(
        self, strategy_id: str, decision: SizingDecision, timestamp: Optional[float] = None
    ) -> SizingLedgerEntry:
        entry = SizingLedgerEntry.from_decision(strategy_id, decision, timestamp)
        self._by_strategy.setdefault(strategy_id, []).append(entry)
        return entry

    def entries_for(self, strategy_id: str) -> list[SizingLedgerEntry]:
        return list(self._by_strategy.get(strategy_id, []))

    def all_entries(self) -> list[SizingLedgerEntry]:
        out: list[SizingLedgerEntry] = []
        for entries in self._by_strategy.values():
            out.extend(entries)
        out.sort(key=lambda e: e.timestamp)
        return out


class JsonlSizingLedger:
    """One append-mode `<strategy_id>.jsonl` file per strategy under
    `base_dir`. Mirrors `JsonlRecordStore`'s on-disk shape but is a
    self-contained implementation local to this package."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, strategy_id: str) -> Path:
        safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in strategy_id)
        return self.base_dir / f"{safe}.jsonl"

    def record(
        self, strategy_id: str, decision: SizingDecision, timestamp: Optional[float] = None
    ) -> SizingLedgerEntry:
        entry = SizingLedgerEntry.from_decision(strategy_id, decision, timestamp)
        with open(self._path(strategy_id), "a") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")
        return entry

    def entries_for(self, strategy_id: str) -> list[SizingLedgerEntry]:
        p = self._path(strategy_id)
        if not p.exists():
            return []
        out: list[SizingLedgerEntry] = []
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(SizingLedgerEntry.from_dict(json.loads(line)))
        return out

    def all_entries(self) -> list[SizingLedgerEntry]:
        out: list[SizingLedgerEntry] = []
        for path in self.base_dir.glob("*.jsonl"):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        out.append(SizingLedgerEntry.from_dict(json.loads(line)))
        out.sort(key=lambda e: e.timestamp)
        return out
