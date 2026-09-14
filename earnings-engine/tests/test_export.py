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


if __name__ == "__main__":
    unittest.main()
