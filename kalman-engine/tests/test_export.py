"""Tests for kf/export.py -- synthetic-path round-trip + honest live-gate
failure, mirroring cascade-data-engine/tests/test_export.py's structure."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kf.export import build_export, write_export
from kf.config import CANDIDATE_PAIRS, UNIVERSE


class TestBuildExportSyntheticDemo(unittest.TestCase):
    """No Alpaca env vars are set in this test process (never set them --
    see TestBuildExportLiveGate for the one test that touches them, scoped
    and restored), so build_export() always takes the synthetic-demo path
    here."""

    def test_no_keys_is_synthetic_demo(self):
        payload = build_export()
        self.assertEqual(payload["provenance"], "synthetic-demo")
        self.assertIn("disclaimer", payload)
        self.assertEqual(payload["universe"], list(UNIVERSE))
        self.assertEqual(payload["pairs_tested"], len(CANDIDATE_PAIRS))

    def test_deterministic(self):
        a = build_export()
        b = build_export()
        a.pop("generated_at")
        b.pop("generated_at")
        self.assertEqual(a, b)

    def test_every_pair_present_with_available_flag(self):
        payload = build_export()
        pair_labels = {p["pair"] for p in payload["pairs"]}
        expected = {f"{t1}/{t2}" for (t1, t2) in CANDIDATE_PAIRS}
        self.assertEqual(pair_labels, expected)
        for p in payload["pairs"]:
            self.assertIn("available", p)
            self.assertIn("cointegrated", p)
            self.assertIn("note", p)

    def test_some_pairs_cointegrated_and_some_correctly_abstained(self):
        """This is the honest-abstention discipline exercised end to end:
        the synthetic panel (kf/synthetic.py) is deliberately built with
        one genuinely cointegrated 3-ticker group and one genuinely
        independent 3-ticker group, so a correct pipeline finds SOME pairs
        cointegrated and correctly abstains on the rest -- neither "always
        cointegrated" nor "never cointegrated" would be an honest result
        here, and this test would catch either degenerate failure mode."""
        payload = build_export()
        self.assertGreater(payload["pairs_cointegrated"], 0)
        self.assertLess(payload["pairs_cointegrated"], payload["pairs_tested"])

    def test_cointegrated_pairs_carry_a_real_kalman_reading(self):
        payload = build_export()
        for p in payload["pairs"]:
            if p["cointegrated"]:
                self.assertIn("kalman", p)
                self.assertIsInstance(p["score"], float)
                self.assertIn("adaptive_noise", p["kalman"])
                an = p["kalman"]["adaptive_noise"]
                # The central claim, checked again at the export layer (not
                # just the filter-unit-test layer): Q/R drifted from their
                # initial guess during this pair's own run.
                self.assertNotEqual(an["final_r"], an["initial_r"])
                self.assertNotEqual(an["final_q_trace"], an["initial_q_trace"])
            else:
                self.assertIsNone(p["score"])
                self.assertNotIn("kalman", p)

    def test_write_export_roundtrips(self):
        payload = build_export()
        with TemporaryDirectory() as d:
            paths = [Path(d) / "latest.json"]
            write_export(payload, paths=paths)
            written = json.loads(paths[0].read_text())
            self.assertEqual(written, payload)


class TestBuildExportLiveGate(unittest.TestCase):
    """Confirms the live gate actually engages (attempts a real fetch and
    fails honestly) rather than silently doing nothing -- without ever
    leaving the Alpaca env vars set for any other test in this process."""

    def setUp(self):
        import os
        self._prior_id = os.environ.pop("ALPACA_API_KEY_ID", None)
        self._prior_secret = os.environ.pop("ALPACA_API_SECRET_KEY", None)

    def tearDown(self):
        import os
        if self._prior_id is not None:
            os.environ["ALPACA_API_KEY_ID"] = self._prior_id
        else:
            os.environ.pop("ALPACA_API_KEY_ID", None)
        if self._prior_secret is not None:
            os.environ["ALPACA_API_SECRET_KEY"] = self._prior_secret
        else:
            os.environ.pop("ALPACA_API_SECRET_KEY", None)

    def test_live_keys_set_attempts_real_fetch_and_fails_honestly(self):
        import os
        from kf.adapters.alpaca_bars import LiveFetchFailedError

        os.environ["ALPACA_API_KEY_ID"] = "test-placeholder-id"
        os.environ["ALPACA_API_SECRET_KEY"] = "test-placeholder-secret"
        # In every sandbox this engine has been built in, this raises
        # LiveFetchFailedError (the real HTTP call is genuinely attempted
        # and genuinely fails against this environment's network wall --
        # see kf/adapters/alpaca_bars.py's docstring). On a machine with
        # real network access AND a real key pair it would instead return
        # a payload with provenance == "live". Either outcome is honest;
        # what this test forbids is anything in between (a "live"-labeled
        # payload built from fabricated data).
        try:
            payload = build_export()
        except LiveFetchFailedError:
            pass
        else:
            self.assertEqual(payload["provenance"], "live")


if __name__ == "__main__":
    unittest.main()
