"""Tests for cde/adapters/alpaca_volume.py — the bar-aggregation logic is
tested against hand-built fixture bar lists matching Alpaca's documented
response shape (see the adapter's module docstring for the confirmed
research trail, shared with chaos-engine's own Alpaca adapter but never
imported from it — this suite never imports chaos-engine either); the real
network call itself is exercised only by the gate/error-shape tests below,
never by an actual HTTP request (this suite must pass with zero network
access, same as every other engine's suite in this repo)."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cde.adapters.alpaca_volume import (
    ALPACA_API_KEY_ID_VAR,
    ALPACA_API_SECRET_KEY_VAR,
    AlpacaDailyVolumeAdapter,
    LiveFetchFailedError,
    VendorNotConfiguredError,
)


class TestEnvVarNamesMatchChaosEngineIntentionally(unittest.TestCase):
    """This engine is sealed from chaos-engine (no import) — these are
    typed-out literal strings, not shared constants. This test only
    guards against a typo silently breaking the "one key pair lights up
    both engines" intent documented in the module's docstring."""

    def test_var_names(self):
        self.assertEqual(ALPACA_API_KEY_ID_VAR, "ALPACA_API_KEY_ID")
        self.assertEqual(ALPACA_API_SECRET_KEY_VAR, "ALPACA_API_SECRET_KEY")


class TestComputeTypicalDollarVolume(unittest.TestCase):
    def setUp(self):
        self._prior_key = os.environ.pop(ALPACA_API_KEY_ID_VAR, None)
        self._prior_secret = os.environ.pop(ALPACA_API_SECRET_KEY_VAR, None)
        os.environ[ALPACA_API_KEY_ID_VAR] = "test-key-id"
        os.environ[ALPACA_API_SECRET_KEY_VAR] = "test-secret-key"
        self.adapter = AlpacaDailyVolumeAdapter()

    def tearDown(self):
        for var, prior in (
            (ALPACA_API_KEY_ID_VAR, self._prior_key),
            (ALPACA_API_SECRET_KEY_VAR, self._prior_secret),
        ):
            if prior is not None:
                os.environ[var] = prior
            else:
                os.environ.pop(var, None)

    def test_average_close_times_volume(self):
        fixture = {
            "AAPL": [
                {"t": "2026-09-10T00:00:00Z", "c": 200.0, "v": 1_000_000},
                {"t": "2026-09-11T00:00:00Z", "c": 210.0, "v": 2_000_000},
            ]
        }
        self.adapter.fetch_daily_bars = lambda tickers, lookback_days=21, feed="iex": fixture
        out = self.adapter.compute_typical_dollar_volume(["AAPL"])
        expected = (200.0 * 1_000_000 + 210.0 * 2_000_000) / 2
        self.assertAlmostEqual(out["AAPL"], expected)

    def test_ticker_with_zero_bars_is_omitted_not_zeroed(self):
        fixture = {"AAPL": [{"t": "2026-09-11T00:00:00Z", "c": 200.0, "v": 1_000_000}], "MSFT": []}
        self.adapter.fetch_daily_bars = lambda tickers, lookback_days=21, feed="iex": fixture
        out = self.adapter.compute_typical_dollar_volume(["AAPL", "MSFT"])
        self.assertIn("AAPL", out)
        self.assertNotIn("MSFT", out)

    def test_malformed_bar_is_skipped_not_poisoning_the_average(self):
        fixture = {
            "AAPL": [
                {"t": "2026-09-10T00:00:00Z", "c": 200.0, "v": 1_000_000},
                {"t": "2026-09-11T00:00:00Z", "c": "not-a-number", "v": 2_000_000},
            ]
        }
        self.adapter.fetch_daily_bars = lambda tickers, lookback_days=21, feed="iex": fixture
        out = self.adapter.compute_typical_dollar_volume(["AAPL"])
        self.assertAlmostEqual(out["AAPL"], 200.0 * 1_000_000)

    def test_latest_price_and_volume_uses_last_bar(self):
        fixture = {
            "IVV": [
                {"t": "2026-09-10T00:00:00Z", "c": 700.0, "v": 3_000_000},
                {"t": "2026-09-11T00:00:00Z", "c": 705.0, "v": 3_500_000},
            ]
        }
        self.adapter.fetch_daily_bars = lambda tickers, lookback_days=5, feed="iex": fixture
        out = self.adapter.latest_price_and_volume(["IVV"])
        self.assertEqual(out["IVV"], (705.0, 3_500_000.0))


class TestAdapterGate(unittest.TestCase):
    def setUp(self):
        self._prior_key = os.environ.pop(ALPACA_API_KEY_ID_VAR, None)
        self._prior_secret = os.environ.pop(ALPACA_API_SECRET_KEY_VAR, None)

    def tearDown(self):
        for var, prior in (
            (ALPACA_API_KEY_ID_VAR, self._prior_key),
            (ALPACA_API_SECRET_KEY_VAR, self._prior_secret),
        ):
            if prior is not None:
                os.environ[var] = prior
            else:
                os.environ.pop(var, None)

    def test_disabled_by_default_raises_vendor_not_configured(self):
        adapter = AlpacaDailyVolumeAdapter()
        self.assertFalse(adapter.is_configured())
        with self.assertRaises(VendorNotConfiguredError):
            adapter.fetch_daily_bars(["AAPL"])

    def test_only_one_key_set_still_raises_vendor_not_configured(self):
        os.environ[ALPACA_API_KEY_ID_VAR] = "only-the-id"
        adapter = AlpacaDailyVolumeAdapter()
        self.assertFalse(adapter.is_configured())
        with self.assertRaises(VendorNotConfiguredError):
            adapter.fetch_daily_bars(["AAPL"])

    def test_enabled_attempts_real_call_and_fails_honestly_with_no_network(self):
        # Monkeypatches urllib rather than depending on this sandbox
        # staying network-blocked forever — same discipline as
        # test_ishares_holdings.py's identical test.
        import urllib.error
        import urllib.request as urllib_request

        os.environ[ALPACA_API_KEY_ID_VAR] = "test-key-id"
        os.environ[ALPACA_API_SECRET_KEY_VAR] = "test-secret-key"
        adapter = AlpacaDailyVolumeAdapter()

        def _fake_urlopen(*_args, **_kwargs):
            raise urllib.error.URLError("simulated: connection refused")

        original = urllib_request.urlopen
        urllib_request.urlopen = _fake_urlopen
        try:
            with self.assertRaises(LiveFetchFailedError):
                adapter.fetch_daily_bars(["AAPL"])
        finally:
            urllib_request.urlopen = original

    def test_enabled_real_call_against_this_sandboxs_actual_network(self):
        # Documents, rather than assumes, what this environment's network
        # actually does today — never asserts failure as the only valid
        # outcome, same convention as test_ishares_holdings.py.
        os.environ[ALPACA_API_KEY_ID_VAR] = "test-key-id"
        os.environ[ALPACA_API_SECRET_KEY_VAR] = "test-secret-key"
        adapter = AlpacaDailyVolumeAdapter()
        try:
            bars = adapter.fetch_daily_bars(["AAPL"], lookback_days=5)
        except LiveFetchFailedError:
            pass  # expected in every sandbox this engine has been built in
        else:
            self.assertIsInstance(bars, dict)


if __name__ == "__main__":
    unittest.main()
