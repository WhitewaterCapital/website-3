import json
import sys
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ee.export import build_export, write_export
from ee.synthetic import synthetic_events
from ee.config import UNIVERSE, LOOKAHEAD_DAYS

TIER_B_KEYS = {"eps_estimate_stdev", "estimate_source", "sue", "sue_abstain_reason"}


class TestSyntheticEvents(unittest.TestCase):
    def test_one_event_per_universe_ticker(self):
        evs = synthetic_events(date(2026, 9, 14))
        self.assertEqual(len(evs), len(UNIVERSE))
        self.assertEqual({e["ticker"] for e in evs}, set(UNIVERSE))

    def test_within_lookahead_window(self):
        today = date(2026, 9, 14)
        evs = synthetic_events(today)
        for e in evs:
            d = date.fromisoformat(e["report_date"])
            self.assertGreater(d, today)
            self.assertLessEqual((d - today).days, LOOKAHEAD_DAYS)

    def test_deterministic(self):
        a = synthetic_events(date(2026, 9, 14))
        b = synthetic_events(date(2026, 9, 14))
        self.assertEqual(a, b)

    def test_tier_b_fields_present_and_honestly_null(self):
        # Synthetic events must carry the same Tier-B keys a live event
        # does (schema consistency for the website's TS type) but every
        # value must be null/stated-abstain — a synthetic-demo calendar
        # must never look like it has a real estimate attached.
        evs = synthetic_events(date(2026, 9, 14))
        for e in evs:
            self.assertTrue(TIER_B_KEYS.issubset(e.keys()))
            self.assertIsNone(e["eps_estimate_stdev"])
            self.assertIsNone(e["estimate_source"])
            self.assertIsNone(e["sue"])
            self.assertIsInstance(e["sue_abstain_reason"], str)
            self.assertTrue(len(e["sue_abstain_reason"]) > 0)


class TestBuildExport(unittest.TestCase):
    def test_no_key_is_synthetic_demo(self):
        payload = build_export(today=date(2026, 9, 14))
        self.assertEqual(payload["data_provenance"], "synthetic-demo")
        self.assertEqual(len(payload["events"]), len(UNIVERSE))
        self.assertIn("disclaimer", payload)

    def test_write_export_roundtrips(self):
        payload = build_export(today=date(2026, 9, 14))
        with TemporaryDirectory() as d:
            paths = [Path(d) / "latest.json"]
            write_export(payload, paths=paths)
            written = json.loads(paths[0].read_text())
            self.assertEqual(written, payload)

    def test_every_event_has_tier_b_keys(self):
        # Regardless of provenance, every event dict must carry the full
        # Tier-B key set so the site's EarningsEvent TS type never sees a
        # missing field — additive schema, never a silently-absent one.
        payload = build_export(today=date(2026, 9, 14))
        for e in payload["events"]:
            self.assertTrue(TIER_B_KEYS.issubset(e.keys()))


if __name__ == "__main__":
    unittest.main()
