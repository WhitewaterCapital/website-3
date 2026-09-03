"""Small injectable storage seam shared by `trial_log.py` and `graduation.py`.

Mirrors the codebase's documented "swap only the seam" philosophy already
used for the feature store (`store/base.py` is the Protocol, `store/duckdb_store.py`
is today's implementation, and the website reads through a single function in
`src/lib/*.ts` that can later be swapped for Supabase without anything upstream
changing). Here the seam is a tiny append-only record store: swap
`JsonlRecordStore` for a Supabase-backed implementation of the same three
methods and nothing that calls `log_trial`/`report`/graduation helpers needs
to change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Protocol


class RecordStore(Protocol):
    """Append-only, per-key JSON record store."""

    def append(self, key: str, record: dict) -> None:
        """Add one record under `key`. Never mutates or removes prior records
        — the trial log's whole point is that abandoned trials stay logged."""
        ...

    def list(self, key: str) -> list[dict]:
        """All records under `key`, oldest first."""
        ...

    def get(self, key: str, index: int) -> Optional[dict]:
        """The record at position `index` (0-based) under `key`, or None."""
        ...


class JsonlRecordStore:
    """Local JSON-lines implementation: one `<key>.jsonl` file per key under
    `base_dir`, opened in append mode so a crash mid-run can never silently
    drop or rewrite an earlier trial/record."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in key)
        return self.base_dir / f"{safe}.jsonl"

    def append(self, key: str, record: dict) -> None:
        with open(self._path(key), "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def list(self, key: str) -> list[dict]:
        p = self._path(key)
        if not p.exists():
            return []
        out: list[dict] = []
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def get(self, key: str, index: int) -> Optional[dict]:
        records = self.list(key)
        if 0 <= index < len(records):
            return records[index]
        return None
