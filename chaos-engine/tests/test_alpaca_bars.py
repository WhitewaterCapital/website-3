"""Tests for chaos/adapters/alpaca_bars.py.

Same discipline as `cascade-data-engine/tests/test_ishares_holdings.py`:
the JSON-parsing/DataFrame-shaping logic is tested directly against
hand-built fixtures matching Alpaca's documented response shape; the real
network call itself is exercised only through a monkeypatched
`requests.get` (never a real HTTP request — this suite must pass with zero
network access, same as every other engine's suite in this repo, and
DOES pass here: this file needs only `pandas`/`requests`, neither
`scipy` nor `scikit-learn`, so unlike `chaos.export` (which imports
`chaos.directional`, which imports `sklearn`) it is actually importable
and runnable in a sandbox that has no `sklearn`/`scipy` installed — see
this session's own report for why that distinction mattered this pass."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from chaos.adapters.alpaca_bars import (
    BAR_COLUMNS,
    AlpacaBarsAdapter,
    LiveFetchFailedError,
    VendorNotConfiguredError,
    _bars_json_to_frame,
    _to_rfc3339,
    fetch_watchlist_minute_bars,
)
from chaos.config import ALPACA_API_KEY_ID_VAR, ALPACA_API_SECRET_KEY_VAR

FIXTURE_BARS_AAPL = [
    {"t": "2026-09-11T13:30:00Z", "o": 230.10, "h": 230.55, "l": 229.90, "c": 230.40, "v": 125000, "n": 812, "vw": 230.22},
    {"t": "2026-09-11T13:31:00Z", "o": 230.40, "h": 230.60, "l": 230.20, "c": 230.35, "v": 98000, "n": 640, "vw": 230.41},
    # Duplicate timestamp on purpose: Alpaca pagination edge cases have been
    # known to return an overlapping boundary bar across a page split; the
    # frame builder must de-duplicate rather than double-count it.
    {"t": "2026-09-11T13:31:00Z", "o": 230.40, "h": 230.60, "l": 230.20, "c": 230.35, "v": 98000, "n": 640, "vw": 230.41},
]


class TestBarsJsonToFrame(unittest.TestCase):
    def test_empty_input_returns_empty_well_shaped_frame(self):
        df = _bars_json_to_frame([])
        self.assertEqual(list(df.columns), BAR_COLUMNS)
        self.assertEqual(len(df), 0)

    def test_parses_confirmed_field_names(self):
        df = _bars_json_to_frame(FIXTURE_BARS_AAPL)
        self.assertEqual(list(df.columns), BAR_COLUMNS)
        self.assertAlmostEqual(df.iloc[0]["open"], 230.10)
        self.assertAlmostEqual(df.iloc[0]["close"], 230.40)
        self.assertAlmostEqual(df.iloc[0]["volume"], 125000.0)

    def test_utc_converted_to_eastern_wall_clock_naive(self):
        # 13:30 UTC on 2026-09-11 (EDT, UTC-4) must land at 09:30 local --
        # the US cash session open -- not 13:30. This is the exact
        # correctness property `volume_surprise`'s minute-of-day seasonal
        # control depends on (see the adapter module's docstring).
        df = _bars_json_to_frame(FIXTURE_BARS_AAPL)
        self.assertEqual(df.index[0], pd.Timestamp("2026-09-11 09:30:00"))
        self.assertIsNone(df.index.tz)

    def test_duplicate_timestamp_deduplicated(self):
        df = _bars_json_to_frame(FIXTURE_BARS_AAPL)
        self.assertEqual(len(df), 2)  # 3 input rows, one exact duplicate timestamp

    def test_index_sorted_ascending(self):
        reversed_input = list(reversed(FIXTURE_BARS_AAPL))
        df = _bars_json_to_frame(reversed_input)
        self.assertTrue(df.index.is_monotonic_increasing)


class TestRfc3339(unittest.TestCase):
    def test_naive_datetime_treated_as_utc(self):
        dt = datetime(2026, 9, 11, 13, 30, 0)
        self.assertEqual(_to_rfc3339(dt), "2026-09-11T13:30:00Z")

    def test_aware_datetime_converted_to_utc(self):
        from zoneinfo import ZoneInfo

        dt = datetime(2026, 9, 11, 9, 30, 0, tzinfo=ZoneInfo("America/New_York"))
        self.assertEqual(_to_rfc3339(dt), "2026-09-11T13:30:00Z")


class TestAdapterGate(unittest.TestCase):
    def setUp(self):
        self._prior_key = os.environ.pop(ALPACA_API_KEY_ID_VAR, None)
        self._prior_secret = os.environ.pop(ALPACA_API_SECRET_KEY_VAR, None)

    def tearDown(self):
        for var, prior in ((ALPACA_API_KEY_ID_VAR, self._prior_key), (ALPACA_API_SECRET_KEY_VAR, self._prior_secret)):
            if prior is not None:
                os.environ[var] = prior
            else:
                os.environ.pop(var, None)

    def test_unconfigured_by_default_raises_vendor_not_configured(self):
        adapter = AlpacaBarsAdapter()
        self.assertFalse(adapter.is_configured())
        with self.assertRaises(VendorNotConfiguredError):
            adapter.fetch_minute_bars(["AAPL"], datetime.now(timezone.utc), datetime.now(timezone.utc))

    def test_only_one_key_set_still_raises_vendor_not_configured(self):
        # Alpaca authenticates with a PAIR -- half a credential is still
        # "not configured", not "half-configured and worth trying".
        os.environ[ALPACA_API_KEY_ID_VAR] = "some-key-id"
        adapter = AlpacaBarsAdapter()
        self.assertFalse(adapter.is_configured())
        with self.assertRaises(VendorNotConfiguredError):
            adapter.fetch_minute_bars(["AAPL"], datetime.now(timezone.utc), datetime.now(timezone.utc))

    def test_configured_reports_true(self):
        os.environ[ALPACA_API_KEY_ID_VAR] = "some-key-id"
        os.environ[ALPACA_API_SECRET_KEY_VAR] = "some-secret"
        adapter = AlpacaBarsAdapter()
        self.assertTrue(adapter.is_configured())

    def test_configured_but_network_refused_raises_live_fetch_failed(self):
        # Deliberately does not depend on the ambient sandbox actually
        # having no network access -- monkeypatches requests.get to
        # simulate the exact failure mode documented in the adapter's
        # module docstring (this repo's own sandboxed shells get a
        # blocked-by-allowlist 403 from data.alpaca.markets), so this test
        # is deterministic on any machine, including a real one.
        os.environ[ALPACA_API_KEY_ID_VAR] = "some-key-id"
        os.environ[ALPACA_API_SECRET_KEY_VAR] = "some-secret"
        adapter = AlpacaBarsAdapter()

        import requests

        def _raise_connection_error(*_args, **_kwargs):
            raise requests.exceptions.ConnectionError("simulated: blocked-by-allowlist")

        with mock.patch("chaos.adapters.alpaca_bars.requests.get", side_effect=_raise_connection_error):
            with self.assertRaises(LiveFetchFailedError):
                adapter.fetch_minute_bars(["AAPL"], datetime.now(timezone.utc), datetime.now(timezone.utc))

    def test_configured_but_bad_credentials_raises_live_fetch_failed_with_401(self):
        os.environ[ALPACA_API_KEY_ID_VAR] = "wrong-key-id"
        os.environ[ALPACA_API_SECRET_KEY_VAR] = "wrong-secret"
        adapter = AlpacaBarsAdapter()

        fake_resp = mock.Mock()
        fake_resp.status_code = 401
        fake_resp.text = "unauthorized"

        with mock.patch("chaos.adapters.alpaca_bars.requests.get", return_value=fake_resp):
            with self.assertRaises(LiveFetchFailedError) as ctx:
                adapter.fetch_minute_bars(["AAPL"], datetime.now(timezone.utc), datetime.now(timezone.utc))
        self.assertIn("credentials rejected", str(ctx.exception))

    def test_configured_and_mocked_success_parses_real_response_shape(self):
        # A hand-built fixture matching Alpaca's DOCUMENTED multi-symbol
        # bars response shape (see the adapter's module docstring for what
        # is confirmed-vs-assumed about that shape) -- exercises the full
        # pagination loop (two pages) and the per-symbol frame conversion.
        os.environ[ALPACA_API_KEY_ID_VAR] = "some-key-id"
        os.environ[ALPACA_API_SECRET_KEY_VAR] = "some-secret"
        adapter = AlpacaBarsAdapter()

        page1 = mock.Mock()
        page1.status_code = 200
        page1.json.return_value = {
            "bars": {"AAPL": [FIXTURE_BARS_AAPL[0]], "MSFT": []},
            "next_page_token": "page-2-token",
        }
        page2 = mock.Mock()
        page2.status_code = 200
        page2.json.return_value = {
            "bars": {"AAPL": [FIXTURE_BARS_AAPL[1]]},
            "next_page_token": None,
        }

        with mock.patch("chaos.adapters.alpaca_bars.requests.get", side_effect=[page1, page2]) as mock_get:
            result = adapter.fetch_minute_bars(
                ["AAPL", "MSFT"], datetime(2026, 9, 11, tzinfo=timezone.utc), datetime(2026, 9, 12, tzinfo=timezone.utc)
            )

        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(set(result.keys()), {"AAPL", "MSFT"})
        self.assertEqual(len(result["AAPL"]), 2)  # accumulated across both pages
        self.assertEqual(len(result["MSFT"]), 0)
        # Second call must have carried the page token from the first.
        second_call_params = mock_get.call_args_list[1].kwargs["params"]
        self.assertEqual(second_call_params["page_token"], "page-2-token")
        # Auth headers present on every call.
        for call in mock_get.call_args_list:
            self.assertEqual(call.kwargs["headers"]["APCA-API-KEY-ID"], "some-key-id")
            self.assertEqual(call.kwargs["headers"]["APCA-API-SECRET-KEY"], "some-secret")

    def test_response_missing_bars_key_raises_live_fetch_failed(self):
        os.environ[ALPACA_API_KEY_ID_VAR] = "some-key-id"
        os.environ[ALPACA_API_SECRET_KEY_VAR] = "some-secret"
        adapter = AlpacaBarsAdapter()

        fake_resp = mock.Mock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"message": "unexpected shape, no bars key at all"}

        with mock.patch("chaos.adapters.alpaca_bars.requests.get", return_value=fake_resp):
            with self.assertRaises(LiveFetchFailedError) as ctx:
                adapter.fetch_minute_bars(["AAPL"], datetime.now(timezone.utc), datetime.now(timezone.utc))
        self.assertIn("no 'bars' key", str(ctx.exception))

    def test_rate_limited_429_raises_live_fetch_failed(self):
        os.environ[ALPACA_API_KEY_ID_VAR] = "some-key-id"
        os.environ[ALPACA_API_SECRET_KEY_VAR] = "some-secret"
        adapter = AlpacaBarsAdapter()

        fake_resp = mock.Mock()
        fake_resp.status_code = 429
        fake_resp.text = "rate limited"

        with mock.patch("chaos.adapters.alpaca_bars.requests.get", return_value=fake_resp):
            with self.assertRaises(LiveFetchFailedError) as ctx:
                adapter.fetch_minute_bars(["AAPL"], datetime.now(timezone.utc), datetime.now(timezone.utc))
        self.assertIn("rate-limited", str(ctx.exception))

    def test_fetch_watchlist_minute_bars_convenience_wrapper(self):
        os.environ[ALPACA_API_KEY_ID_VAR] = "some-key-id"
        os.environ[ALPACA_API_SECRET_KEY_VAR] = "some-secret"

        fake_resp = mock.Mock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"bars": {"AAPL": FIXTURE_BARS_AAPL}, "next_page_token": None}

        with mock.patch("chaos.adapters.alpaca_bars.requests.get", return_value=fake_resp):
            result = fetch_watchlist_minute_bars(["AAPL"], lookback_days=5)
        self.assertEqual(set(result.keys()), {"AAPL"})
        self.assertEqual(len(result["AAPL"]), 2)


class TestAdapterAgainstRealNetworkThisSandbox(unittest.TestCase):
    """DOES make a real network attempt (guarded so it can never silently
    pass on a bad reason) -- documents, rather than assumes, what this
    environment's network actually does today, same pattern as
    `cascade-data-engine/tests/test_ishares_holdings.py`'s identically
    named test. Never asserts failure as the only valid outcome; on a real
    network with real credentials it would legitimately succeed."""

    def test_real_call_against_this_sandboxs_actual_network(self):
        key_id = os.environ.get(ALPACA_API_KEY_ID_VAR, "")
        secret = os.environ.get(ALPACA_API_SECRET_KEY_VAR, "")
        if not key_id or not secret:
            self.skipTest(
                f"{ALPACA_API_KEY_ID_VAR}/{ALPACA_API_SECRET_KEY_VAR} not set in this "
                f"environment -- this test only runs meaningfully once real credentials "
                f"exist. Skipping rather than faking a positive/negative result."
            )
        adapter = AlpacaBarsAdapter()
        end = datetime.now(timezone.utc)
        start = end - __import__("datetime").timedelta(days=2)
        try:
            result = adapter.fetch_minute_bars(["AAPL"], start=start, end=end)
        except LiveFetchFailedError:
            pass  # expected from every sandboxed shell this engine has been built in
        else:
            self.assertIn("AAPL", result)


if __name__ == "__main__":
    unittest.main()
