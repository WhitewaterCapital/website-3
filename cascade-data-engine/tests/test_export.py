import json
import sys
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cde.export import build_export, write_export
from cde.config import FUNDS, SYNTHETIC_CONSTITUENTS


class TestBuildExportSyntheticDemo(unittest.TestCase):
    """CASCADE_LIVE_HOLDINGS is unset in this test process (never set it —
    see TestBuildExportLiveGate below for the one test that touches it,
    scoped and restored), so build_export() always takes the synthetic-demo
    path here, exactly the round-trip earnings-engine/tests/test_export.py's
    TestBuildExport class checks for its own engine."""

    def test_no_flag_is_synthetic_demo(self):
        payload = build_export(today=date(2026, 9, 14))
        self.assertEqual(payload["data_provenance"], "synthetic-demo")
        self.assertIn("disclaimer", payload)
        self.assertEqual(payload["skipped_funds"], [])
        self.assertEqual(set(payload["funds_used"]), {f.ticker for f in FUNDS})

    def test_every_synthetic_constituent_present_with_full_coverage(self):
        payload = build_export(today=date(2026, 9, 14))
        by_name = {r["constituent"]: r for r in payload["pressure"]}
        self.assertEqual(set(by_name), set(SYNTHETIC_CONSTITUENTS))
        for row in by_name.values():
            self.assertEqual(row["n_products_total"], len(FUNDS))
            self.assertEqual(row["n_products_used"], len(FUNDS))
            self.assertIsNotNone(row["pressure"])  # synthetic mode: fully non-NaN by design

    def test_deterministic(self):
        a = build_export(today=date(2026, 9, 14))
        b = build_export(today=date(2026, 9, 14))
        # generated_at legitimately differs (wall-clock) — compare everything else.
        a.pop("generated_at")
        b.pop("generated_at")
        self.assertEqual(a, b)

    def test_write_export_roundtrips(self):
        payload = build_export(today=date(2026, 9, 14))
        with TemporaryDirectory() as d:
            paths = [Path(d) / "latest.json"]
            write_export(payload, paths=paths)
            written = json.loads(paths[0].read_text())
            self.assertEqual(written, payload)


class TestBuildExportLiveGate(unittest.TestCase):
    """Confirms the live gate actually engages (attempts a real fetch and
    fails honestly) rather than silently doing nothing — without ever
    leaving CASCADE_LIVE_HOLDINGS set for any other test in this process."""

    def setUp(self):
        import os

        self._prior = os.environ.pop("CASCADE_LIVE_HOLDINGS", None)

    def tearDown(self):
        import os

        if self._prior is not None:
            os.environ["CASCADE_LIVE_HOLDINGS"] = self._prior
        else:
            os.environ.pop("CASCADE_LIVE_HOLDINGS", None)

    def test_live_flag_set_raises_honest_error_not_fabricated_export(self):
        import os

        from cde.export import LiveExportFailedError

        os.environ["CASCADE_LIVE_HOLDINGS"] = "1"
        # In every sandbox this engine has been built in, this raises
        # LiveExportFailedError (every fund's real fetch genuinely failed).
        # On a machine with real network access it would instead return a
        # payload with data_provenance == "live" — either outcome is
        # honest; what this test forbids is anything in between (a
        # "live"-labeled payload built from fabricated data).
        try:
            payload = build_export(today=date(2026, 9, 14))
        except LiveExportFailedError:
            pass
        else:
            self.assertEqual(payload["data_provenance"], "live")
            self.assertTrue(len(payload["funds_used"]) > 0)


if __name__ == "__main__":
    unittest.main()
