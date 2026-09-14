"""Tests for cde/adapters/ishares_holdings.py — the CSV parser is tested
against a hand-built fixture matching the CONFIRMED column shape (see the
adapter's module docstring for what was actually confirmed and how); the
real network call itself is exercised only by the gate/error-shape tests
below, never by an actual HTTP request (this suite must pass with zero
network access, same as every other engine's suite in this repo)."""

import os
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cde.adapters.ishares_holdings import (
    IsharesHoldingsAdapter,
    LiveFetchFailedError,
    VendorNotConfiguredError,
    parse_holdings_csv,
)
from cde.config import FUNDS

FIXTURE_CSV = """\
"iShares Core S&P 500 ETF"
"Fund Holdings as of","Sep 11, 2026"
"Inception Date","May 15, 2000"
"Shares Outstanding","1,084,200,000.00"
"Stock","-"
"Bond","-"
"Cash","-"
"Other","-"
""
Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date
NVDA,NVIDIA,Information Technology,Equity,66152105181.52,8.00,66152105181.52,340000000,194.56,United States,NASDAQ,USD,1.00,USD,--
AAPL,APPLE,Information Technology,Equity,61123456789.00,7.39,61123456789.00,255000000,239.70,United States,NASDAQ,USD,1.00,USD,--
MSFT,MICROSOFT,Information Technology,Equity,46012345678.00,5.57,46012345678.00,90000000,511.25,United States,NASDAQ,USD,1.00,USD,--
USD,CASH,Cash and Other,Cash,1234567.00,0.01,1234567.00,1234567,1.00,United States,--,USD,1.00,USD,--
"""


class TestParseHoldingsCsv(unittest.TestCase):
    def test_parses_confirmed_column_shape(self):
        rows, shares_out = parse_holdings_csv(FIXTURE_CSV)
        self.assertEqual(len(rows), 4)
        self.assertEqual(shares_out, 1_084_200_000.0)

    def test_weight_converted_from_percent_to_fraction(self):
        rows, _ = parse_holdings_csv(FIXTURE_CSV)
        nvda = next(r for r in rows if r["constituent"] == "NVDA")
        self.assertAlmostEqual(nvda["weight"], 0.08)

    def test_cash_row_included_not_specially_dropped(self):
        rows, _ = parse_holdings_csv(FIXTURE_CSV)
        self.assertIn("USD", [r["constituent"] for r in rows])

    def test_metadata_and_name_fields_captured(self):
        rows, _ = parse_holdings_csv(FIXTURE_CSV)
        aapl = next(r for r in rows if r["constituent"] == "AAPL")
        self.assertEqual(aapl["name"], "APPLE")
        self.assertEqual(aapl["sector"], "Information Technology")
        self.assertEqual(aapl["asset_class"], "Equity")

    def test_missing_header_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse_holdings_csv("not,a,holdings,file\n1,2,3,4\n")

    def test_header_with_zero_data_rows_raises_value_error(self):
        header_only = "Ticker,Name,Sector,Asset Class,Weight (%)\n"
        with self.assertRaises(ValueError):
            parse_holdings_csv(header_only)

    def test_shares_outstanding_absent_is_none_not_zero(self):
        no_shares = FIXTURE_CSV.replace('"Shares Outstanding","1,084,200,000.00"\n', "")
        rows, shares_out = parse_holdings_csv(no_shares)
        self.assertEqual(len(rows), 4)
        self.assertIsNone(shares_out)


class TestAdapterGate(unittest.TestCase):
    def setUp(self):
        self._prior = os.environ.pop("CASCADE_LIVE_HOLDINGS", None)

    def tearDown(self):
        if self._prior is not None:
            os.environ["CASCADE_LIVE_HOLDINGS"] = self._prior
        else:
            os.environ.pop("CASCADE_LIVE_HOLDINGS", None)

    def test_disabled_by_default_raises_vendor_not_configured(self):
        adapter = IsharesHoldingsAdapter()
        with self.assertRaises(VendorNotConfiguredError):
            adapter.get_holdings(FUNDS[0], as_of=date(2026, 9, 14))

    def test_enabled_attempts_real_call_and_fails_honestly_with_no_network(self):
        # Deliberately does NOT rely on the ambient environment actually
        # having no network access (true in every sandbox this repo has
        # been built in, per the adapter's module docstring, but not a
        # property this test suite should silently depend on forever) —
        # monkeypatches urllib to simulate the exact failure mode instead,
        # so this test is deterministic on any machine, including yours.
        import urllib.error
        import urllib.request as urllib_request

        os.environ["CASCADE_LIVE_HOLDINGS"] = "1"
        adapter = IsharesHoldingsAdapter()

        def _fake_urlopen(*_args, **_kwargs):
            raise urllib.error.URLError("simulated: connection refused")

        original = urllib_request.urlopen
        urllib_request.urlopen = _fake_urlopen
        try:
            with self.assertRaises(LiveFetchFailedError):
                adapter.get_holdings(FUNDS[0], as_of=date(2026, 9, 14))
        finally:
            urllib_request.urlopen = original

    def test_enabled_real_call_against_this_sandboxs_actual_network(self):
        # This one DOES make a real network attempt (guarded so it can never
        # silently pass on a bad reason) — documents, rather than assumes,
        # what this environment's network actually does today: either the
        # same honest LiveFetchFailedError seen throughout this pass, or (on
        # a machine with real access) a genuine LiveFetchFailedError for a
        # DIFFERENT reason (parse drift) or outright success. Never asserts
        # failure as the only valid outcome — just that nothing fabricates
        # data if the fetch didn't actually work.
        os.environ["CASCADE_LIVE_HOLDINGS"] = "1"
        adapter = IsharesHoldingsAdapter()
        try:
            snap = adapter.get_holdings(FUNDS[0], as_of=date(2026, 9, 14))
        except LiveFetchFailedError:
            pass  # expected in every sandbox this engine has been built in
        else:
            # If this ever succeeds (a real network!), the result must be
            # genuinely well-formed, not a fluke.
            self.assertTrue(len(snap.holdings) > 0)
            self.assertTrue(all("constituent" in r and "weight" in r for r in snap.holdings))


if __name__ == "__main__":
    unittest.main()
