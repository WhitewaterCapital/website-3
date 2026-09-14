import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cde.export import append_fund_snapshots, _prior_snapshot


class TestAppendFundSnapshots(unittest.TestCase):
    def test_appends_and_reads_back(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "snap.jsonl"
            append_fund_snapshots(
                [{"ticker": "IVV", "as_at_date": "2026-09-13", "shares_outstanding": 1_000_000_000.0}],
                path=path,
            )
            append_fund_snapshots(
                [{"ticker": "IVV", "as_at_date": "2026-09-14", "shares_outstanding": 1_001_000_000.0}],
                path=path,
            )
            lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
            self.assertEqual(len(lines), 2)
            self.assertEqual({l["as_at_date"] for l in lines}, {"2026-09-13", "2026-09-14"})

    def test_same_day_rerun_replaces_not_duplicates(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "snap.jsonl"
            append_fund_snapshots(
                [{"ticker": "IVV", "as_at_date": "2026-09-14", "shares_outstanding": 1_000_000_000.0}],
                path=path,
            )
            append_fund_snapshots(
                [{"ticker": "IVV", "as_at_date": "2026-09-14", "shares_outstanding": 1_002_000_000.0}],
                path=path,
            )
            lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["shares_outstanding"], 1_002_000_000.0)

    def test_prior_snapshot_picks_most_recent_before_date(self):
        existing = [
            {"ticker": "IVV", "as_at_date": "2026-09-10", "shares_outstanding": 1.0},
            {"ticker": "IVV", "as_at_date": "2026-09-12", "shares_outstanding": 2.0},
            {"ticker": "IWF", "as_at_date": "2026-09-13", "shares_outstanding": 3.0},
        ]
        prior = _prior_snapshot(existing, "IVV", "2026-09-14")
        self.assertEqual(prior["as_at_date"], "2026-09-12")

    def test_prior_snapshot_none_when_no_earlier_entry(self):
        existing = [{"ticker": "IVV", "as_at_date": "2026-09-14", "shares_outstanding": 1.0}]
        self.assertIsNone(_prior_snapshot(existing, "IVV", "2026-09-14"))
        self.assertIsNone(_prior_snapshot(existing, "IWF", "2026-09-20"))


if __name__ == "__main__":
    unittest.main()
