import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ee.revisions import (
    append_snapshots,
    read_snapshots,
    _prior_snapshot,
    _history_count,
    compute_revision,
    record_and_compute_revisions,
)


class TestAppendAndReadSnapshots(unittest.TestCase):
    # Mirrors cascade-data-engine/tests/test_fund_snapshots_history.py's own
    # test structure almost exactly (same append/read/same-day-replaces
    # cases) — the second of this repo's two real snapshot-log precedents
    # (graph-engine/ge/export.py's append_history is the other), which
    # ee/revisions.py's module docstring names as what this module mirrors
    # rather than inventing its own pattern.

    def test_appends_and_reads_back(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "snap.jsonl"
            append_snapshots(
                [{"ticker": "AAPL", "eps_estimate": 1.50, "as_of_date": "2026-09-13"}], path=path
            )
            append_snapshots(
                [{"ticker": "AAPL", "eps_estimate": 1.55, "as_of_date": "2026-09-14"}], path=path
            )
            recorded = read_snapshots(path)
            self.assertEqual(len(recorded), 2)
            self.assertEqual({r["as_of_date"] for r in recorded}, {"2026-09-13", "2026-09-14"})

    def test_same_day_rerun_replaces_not_duplicates(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "snap.jsonl"
            append_snapshots(
                [{"ticker": "AAPL", "eps_estimate": 1.50, "as_of_date": "2026-09-14"}], path=path
            )
            append_snapshots(
                [{"ticker": "AAPL", "eps_estimate": 1.60, "as_of_date": "2026-09-14"}], path=path
            )
            recorded = read_snapshots(path)
            self.assertEqual(len(recorded), 1)
            self.assertEqual(recorded[0]["eps_estimate"], 1.60)

    def test_missing_file_reads_as_empty(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "does_not_exist.jsonl"
            self.assertEqual(read_snapshots(path), [])

    def test_rotation_caps_entries_per_ticker(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "snap.jsonl"
            for i in range(5):
                append_snapshots(
                    [{"ticker": "AAPL", "eps_estimate": 1.0 + i, "as_of_date": f"2026-09-{10 + i:02d}"}],
                    path=path,
                    max_entries_per_ticker=3,
                )
            recorded = read_snapshots(path)
            self.assertEqual(len(recorded), 3)
            # The three most recent days survive; the two oldest are rotated out.
            self.assertEqual({r["as_of_date"] for r in recorded}, {"2026-09-12", "2026-09-13", "2026-09-14"})

    def test_multiple_tickers_capped_independently(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "snap.jsonl"
            append_snapshots(
                [
                    {"ticker": "AAPL", "eps_estimate": 1.0, "as_of_date": "2026-09-10"},
                    {"ticker": "AAPL", "eps_estimate": 1.1, "as_of_date": "2026-09-11"},
                    {"ticker": "MSFT", "eps_estimate": 2.0, "as_of_date": "2026-09-11"},
                ],
                path=path,
                max_entries_per_ticker=1,
            )
            recorded = read_snapshots(path)
            by_ticker = {r["ticker"] for r in recorded}
            self.assertEqual(by_ticker, {"AAPL", "MSFT"})
            self.assertEqual(len(recorded), 2)  # AAPL capped to its 1 most-recent; MSFT keeps its 1


class TestPriorSnapshotAndHistoryCount(unittest.TestCase):
    def test_prior_snapshot_picks_most_recent_before_date(self):
        existing = [
            {"ticker": "AAPL", "eps_estimate": 1.0, "as_of_date": "2026-09-10"},
            {"ticker": "AAPL", "eps_estimate": 1.1, "as_of_date": "2026-09-12"},
            {"ticker": "MSFT", "eps_estimate": 2.0, "as_of_date": "2026-09-13"},
        ]
        prior = _prior_snapshot(existing, "AAPL", "2026-09-14")
        self.assertEqual(prior["as_of_date"], "2026-09-12")

    def test_prior_snapshot_none_when_no_earlier_entry(self):
        existing = [{"ticker": "AAPL", "eps_estimate": 1.0, "as_of_date": "2026-09-14"}]
        self.assertIsNone(_prior_snapshot(existing, "AAPL", "2026-09-14"))
        self.assertIsNone(_prior_snapshot(existing, "MSFT", "2026-09-20"))

    def test_history_count_only_counts_strictly_earlier_entries(self):
        existing = [
            {"ticker": "AAPL", "eps_estimate": 1.0, "as_of_date": "2026-09-10"},
            {"ticker": "AAPL", "eps_estimate": 1.1, "as_of_date": "2026-09-12"},
        ]
        self.assertEqual(_history_count(existing, "AAPL", "2026-09-14"), 2)
        self.assertEqual(_history_count(existing, "AAPL", "2026-09-11"), 1)
        self.assertEqual(_history_count(existing, "AAPL", "2026-09-10"), 0)
        self.assertEqual(_history_count(existing, "MSFT", "2026-09-14"), 0)


class TestComputeRevision(unittest.TestCase):
    # Same (value, reason) exactly-one-populated contract ee/sue.py's
    # compute_sue tests exercise, applied to this module's pure function.

    def test_abstains_when_no_current_estimate(self):
        direction, pct, reason = compute_revision(
            None, {"eps_estimate": 1.0, "as_of_date": "2026-09-13"}, 1
        )
        self.assertIsNone(direction)
        self.assertIsNone(pct)
        self.assertIn("no consensus EPS estimate", reason)

    def test_abstains_on_first_ever_run_no_prior(self):
        direction, pct, reason = compute_revision(1.50, None, 0)
        self.assertIsNone(direction)
        self.assertIsNone(pct)
        self.assertIn("insufficient snapshot history", reason)
        self.assertIn("only 1 run", reason)

    def test_abstain_message_counts_this_run_as_the_nth(self):
        # history_count=1 (one real prior run) but prior=None would be an
        # inconsistent input in practice (record_and_compute_revisions never
        # produces it), yet the function must still not crash or fabricate —
        # it abstains on the missing prior regardless of the count given.
        direction, pct, reason = compute_revision(1.50, None, 1)
        self.assertIsNone(direction)
        self.assertIsNone(pct)
        self.assertIn("only 2 run", reason)

    def test_abstains_when_prior_estimate_missing(self):
        direction, pct, reason = compute_revision(
            1.50, {"eps_estimate": None, "as_of_date": "2026-09-13"}, 1
        )
        self.assertIsNone(direction)
        self.assertIsNone(pct)
        self.assertIn("no consensus", reason.lower())

    def test_abstains_on_near_zero_prior_estimate(self):
        direction, pct, reason = compute_revision(
            0.10, {"eps_estimate": 0.001, "as_of_date": "2026-09-13"}, 1
        )
        self.assertIsNone(direction)
        self.assertIsNone(pct)
        self.assertIn("numerical-stability floor", reason)

    def test_computes_real_raise(self):
        direction, pct, reason = compute_revision(
            1.65, {"eps_estimate": 1.50, "as_of_date": "2026-09-13"}, 1
        )
        self.assertIsNone(reason)
        self.assertEqual(direction, "raised")
        self.assertAlmostEqual(pct, 10.0)

    def test_computes_real_lower(self):
        direction, pct, reason = compute_revision(
            1.35, {"eps_estimate": 1.50, "as_of_date": "2026-09-13"}, 1
        )
        self.assertIsNone(reason)
        self.assertEqual(direction, "lowered")
        self.assertAlmostEqual(pct, -10.0)

    def test_unchanged(self):
        direction, pct, reason = compute_revision(
            1.50, {"eps_estimate": 1.50, "as_of_date": "2026-09-13"}, 1
        )
        self.assertIsNone(reason)
        self.assertEqual(direction, "unchanged")
        self.assertAlmostEqual(pct, 0.0)


class TestRecordAndComputeRevisions(unittest.TestCase):
    # The integration-shaped tests: exercise the exact function export.py
    # calls, including its own append-then-read-next-time behavior across
    # two simulated days — this is the same scenario verified live via
    # `python -m ee.export` run twice with EE_EXPORT_AS_OF_DATE set a day
    # apart (see README.md's Tier C section).

    def test_first_run_abstains_and_records(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "snap.jsonl"
            events = [{"ticker": "AAPL", "eps_estimate": 1.50}]
            record_and_compute_revisions(events, "2026-09-13", path=path)

            self.assertIsNone(events[0]["revision_direction"])
            self.assertIsNone(events[0]["revision_pct"])
            self.assertIn("insufficient snapshot history", events[0]["revision_abstain_reason"])

            recorded = read_snapshots(path)
            self.assertEqual(len(recorded), 1)
            self.assertEqual(recorded[0]["eps_estimate"], 1.50)
            self.assertEqual(recorded[0]["as_of_date"], "2026-09-13")

    def test_second_run_computes_real_revision(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "snap.jsonl"
            record_and_compute_revisions([{"ticker": "AAPL", "eps_estimate": 1.50}], "2026-09-13", path=path)

            day2 = [{"ticker": "AAPL", "eps_estimate": 1.65}]
            record_and_compute_revisions(day2, "2026-09-14", path=path)

            self.assertEqual(day2[0]["revision_direction"], "raised")
            self.assertAlmostEqual(day2[0]["revision_pct"], 10.0)
            self.assertIsNone(day2[0]["revision_abstain_reason"])

            # And the log now has two real, distinct days for AAPL.
            recorded = read_snapshots(path)
            self.assertEqual(len(recorded), 2)

    def test_never_borrows_another_tickers_history(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "snap.jsonl"
            record_and_compute_revisions([{"ticker": "AAPL", "eps_estimate": 1.0}], "2026-09-13", path=path)

            events = [
                {"ticker": "AAPL", "eps_estimate": 1.1},  # has real history -> real revision
                {"ticker": "MSFT", "eps_estimate": 2.0},  # brand new -> must still abstain
            ]
            record_and_compute_revisions(events, "2026-09-14", path=path)

            self.assertEqual(events[0]["revision_direction"], "raised")
            self.assertIsNone(events[1]["revision_direction"])
            self.assertIn("insufficient snapshot history", events[1]["revision_abstain_reason"])

    def test_same_day_rerun_does_not_fabricate_a_second_days_history(self):
        # Re-running twice on the SAME as_of_date (a human re-running by
        # hand, a retry) must not let the second same-day run see the first
        # same-day run as "real prior history" -- both still abstain.
        with TemporaryDirectory() as d:
            path = Path(d) / "snap.jsonl"
            record_and_compute_revisions([{"ticker": "AAPL", "eps_estimate": 1.0}], "2026-09-14", path=path)
            events = [{"ticker": "AAPL", "eps_estimate": 1.2}]
            record_and_compute_revisions(events, "2026-09-14", path=path)

            self.assertIsNone(events[0]["revision_direction"])
            self.assertIn("insufficient snapshot history", events[0]["revision_abstain_reason"])
            # And the log still has exactly one entry for that day (replaced, not duplicated).
            recorded = read_snapshots(path)
            self.assertEqual(len(recorded), 1)
            self.assertEqual(recorded[0]["eps_estimate"], 1.2)


if __name__ == "__main__":
    unittest.main()
