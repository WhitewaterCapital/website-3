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




class TestBuildExportLiveWiring(unittest.TestCase):
    """Verifies build_export's LIVE path actually WIRES IN the new NAV
    (adapters/ishares_nav.py) and Alpaca typical_volume
    (adapters/alpaca_volume.py) adapters -- TestBuildExportLiveGate above
    only proves the honest-failure path when nothing is reachable, which
    is what every sandbox this engine has run in actually does. This class
    proves the wiring itself is correct using fake adapters injected via
    mock.patch, so it needs zero real network access, same discipline as
    every other test in this repo. `fund_snapshots_path` is also patched
    to a temp file so this test can never write into this engine's real
    `state/fund_snapshots.jsonl`."""

    def setUp(self):
        import os

        self._prior = os.environ.pop("CASCADE_LIVE_HOLDINGS", None)
        os.environ["CASCADE_LIVE_HOLDINGS"] = "1"

    def tearDown(self):
        import os

        if self._prior is not None:
            os.environ["CASCADE_LIVE_HOLDINGS"] = self._prior
        else:
            os.environ.pop("CASCADE_LIVE_HOLDINGS", None)

    def test_live_export_uses_real_nav_and_alpaca_typical_volume_when_available(self):
        from unittest.mock import patch

        from cde.adapters.ishares_holdings import FundSnapshot
        from cde.adapters.ishares_nav import NavSnapshot

        today = date(2026, 9, 14)
        fake_snapshot = FundSnapshot(
            fund=FUNDS[0],
            as_at_date=today,
            holdings=[
                {
                    "constituent": "AAPL",
                    "weight": 0.5,
                    "name": "APPLE",
                    "sector": None,
                    "asset_class": "Equity",
                },
                {
                    "constituent": "MSFT",
                    "weight": 0.5,
                    "name": "MICROSOFT",
                    "sector": None,
                    "asset_class": "Equity",
                },
            ],
            shares_outstanding=1_000_000_000.0,
            source_url="https://example.invalid/fake-holdings",
        )

        def fake_get_holdings(self, fund, as_of=None):
            from cde.adapters.ishares_holdings import LiveFetchFailedError

            if fund.ticker != FUNDS[0].ticker:
                raise LiveFetchFailedError(f"{fund.ticker}: not stubbed in this test")
            return fake_snapshot

        def fake_get_nav(self, fund, as_of=None):
            return NavSnapshot(
                fund=fund,
                as_at_date=today,
                nav_per_share=100.0,
                nav_as_of_label="Sep 14, 2026",
                source_url="https://example.invalid/fake-nav",
            )

        with TemporaryDirectory() as d:
            tmp_snapshots_path = Path(d) / "fund_snapshots.jsonl"
            with patch("cde.export.fund_snapshots_path", lambda: tmp_snapshots_path), patch(
                "cde.adapters.ishares_holdings.IsharesHoldingsAdapter.get_holdings",
                fake_get_holdings,
            ), patch(
                "cde.adapters.ishares_nav.IsharesNavAdapter.get_nav", fake_get_nav
            ), patch(
                "cde.adapters.alpaca_volume.AlpacaDailyVolumeAdapter.is_configured",
                lambda self: True,
            ), patch(
                "cde.adapters.alpaca_volume.AlpacaDailyVolumeAdapter.compute_typical_dollar_volume",
                lambda self, tickers, lookback_days=21, feed="iex": {t: 5e8 for t in tickers},
            ), patch(
                "cde.adapters.alpaca_volume.AlpacaDailyVolumeAdapter.latest_price_and_volume",
                lambda self, tickers, feed="iex": {t: (105.0, 2_000_000.0) for t in tickers},
            ):
                payload = build_export(today=today)

        self.assertEqual(payload["data_provenance"], "live")
        self.assertEqual(payload["typical_volume_provenance"], "live-alpaca")
        self.assertIn(FUNDS[0].ticker, payload["funds_used"])
        by_name = {r["constituent"]: r for r in payload["pressure"]}
        self.assertIn("AAPL", by_name)
        self.assertIn("MSFT", by_name)
        # First-ever run for this fund (no prior snapshot in the temp state
        # file) -> the direct shares-outstanding method has nothing to
        # diff against -> the proxy method (fed by the fake NAV + fake
        # Alpaca fund-level price/volume above) should have produced a
        # real, non-NaN flow, which combined with the fake non-zero
        # typical_volume should yield a real, non-NaN pressure number.
        self.assertIsNotNone(by_name["AAPL"]["pressure"])
        self.assertTrue(by_name["AAPL"]["any_proxy"])

    def test_alpaca_not_configured_leaves_typical_volume_empty_but_still_live(self):
        from unittest.mock import patch

        from cde.adapters.ishares_holdings import FundSnapshot, LiveFetchFailedError
        from cde.adapters.ishares_nav import LiveFetchFailedError as NavLiveFetchFailedError

        today = date(2026, 9, 14)
        fake_snapshot = FundSnapshot(
            fund=FUNDS[0],
            as_at_date=today,
            holdings=[
                {"constituent": "AAPL", "weight": 1.0, "name": "APPLE", "sector": None, "asset_class": "Equity"}
            ],
            shares_outstanding=1_000_000_000.0,
            source_url="https://example.invalid/fake-holdings",
        )

        def fake_get_holdings(self, fund, as_of=None):
            if fund.ticker != FUNDS[0].ticker:
                raise LiveFetchFailedError(f"{fund.ticker}: not stubbed in this test")
            return fake_snapshot

        def fake_get_nav(self, fund, as_of=None):
            raise NavLiveFetchFailedError("simulated: NAV unavailable in this test")

        with TemporaryDirectory() as d:
            tmp_snapshots_path = Path(d) / "fund_snapshots.jsonl"
            with patch("cde.export.fund_snapshots_path", lambda: tmp_snapshots_path), patch(
                "cde.adapters.ishares_holdings.IsharesHoldingsAdapter.get_holdings",
                fake_get_holdings,
            ), patch(
                "cde.adapters.ishares_nav.IsharesNavAdapter.get_nav", fake_get_nav
            ), patch(
                "cde.adapters.alpaca_volume.AlpacaDailyVolumeAdapter.is_configured",
                lambda self: False,
            ):
                payload = build_export(today=today)

        self.assertEqual(payload["data_provenance"], "live")
        self.assertEqual(payload["typical_volume_provenance"], "not-configured")
        by_name = {r["constituent"]: r for r in payload["pressure"]}
        # No NAV, no prior snapshot, no typical_volume -> honest NaN, never
        # a fabricated number.
        self.assertIsNone(by_name["AAPL"]["pressure"])
        self.assertTrue(
            any("typical_volume not sourced" in w for w in payload["warnings"])
        )

if __name__ == "__main__":
    unittest.main()
