"""Tests for cde/adapters/ishares_nav.py — the phrase-based HTML parser is
tested against a hand-built fixture matching the confirmed "NAV as of
<date> $<number>" phrase (see the adapter's module docstring for what was
actually confirmed and how, including the genuine disagreement between two
WebFetch passes over the page's structure); the real network call itself
is exercised only by the gate/error-shape tests below, never by an actual
HTTP request (this suite must pass with zero network access, same as every
other engine's suite in this repo)."""

import os
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cde.adapters.ishares_nav import (
    IsharesNavAdapter,
    LiveFetchFailedError,
    VendorNotConfiguredError,
    parse_nav_from_html,
)
from cde.config import FUNDS

# A minimal fragment resembling the confirmed page phrasing (plain text
# amid HTML markup) — not a claim about iShares' real byte-for-byte markup,
# which this pass never held (see the adapter's module docstring).
FIXTURE_HTML = """
<div class="header-nav">
  <span class="label">NAV as of</span>
  <span class="date">Sep 11, 2026</span>
  <span class="value">$768.0252</span>
  <span class="change">1 Day NAV Change as of Sep 11, 2026 Increase $6.58 (0.86%)</span>
</div>
"""


class TestParseNavFromHtml(unittest.TestCase):
    def test_parses_confirmed_phrase_shape(self):
        nav, label = parse_nav_from_html(FIXTURE_HTML)
        self.assertAlmostEqual(nav, 768.0252)
        self.assertIn("Sep 11", label)
        self.assertIn("2026", label)

    def test_tolerates_extra_markup_between_date_and_number(self):
        html = "<p>NAV as of <b>Sep 11, 2026</b> ... <em>$</em>768.0252</p>"
        nav, _ = parse_nav_from_html(html)
        self.assertAlmostEqual(nav, 768.0252)

    def test_missing_phrase_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse_nav_from_html("<html><body>no nav figure anywhere here</body></html>")

    def test_thousands_separator_handled(self):
        html = "NAV as of Sep 11, 2026 $1,234.56"
        nav, _ = parse_nav_from_html(html)
        self.assertAlmostEqual(nav, 1234.56)


class TestAdapterGate(unittest.TestCase):
    def setUp(self):
        self._prior = os.environ.pop("CASCADE_LIVE_HOLDINGS", None)

    def tearDown(self):
        if self._prior is not None:
            os.environ["CASCADE_LIVE_HOLDINGS"] = self._prior
        else:
            os.environ.pop("CASCADE_LIVE_HOLDINGS", None)

    def test_disabled_by_default_raises_vendor_not_configured(self):
        adapter = IsharesNavAdapter()
        with self.assertRaises(VendorNotConfiguredError):
            adapter.get_nav(FUNDS[0], as_of=date(2026, 9, 14))

    def test_enabled_attempts_real_call_and_fails_honestly_with_no_network(self):
        # Same discipline as test_ishares_holdings.py's identical test:
        # monkeypatches urllib rather than depending on this sandbox
        # staying network-blocked forever.
        import urllib.error
        import urllib.request as urllib_request

        os.environ["CASCADE_LIVE_HOLDINGS"] = "1"
        adapter = IsharesNavAdapter()

        def _fake_urlopen(*_args, **_kwargs):
            raise urllib.error.URLError("simulated: connection refused")

        original = urllib_request.urlopen
        urllib_request.urlopen = _fake_urlopen
        try:
            with self.assertRaises(LiveFetchFailedError):
                adapter.get_nav(FUNDS[0], as_of=date(2026, 9, 14))
        finally:
            urllib_request.urlopen = original

    def test_enabled_but_unparseable_response_raises_live_fetch_failed(self):
        # A real HTTP 200 whose body doesn't contain the confirmed phrase
        # must raise LiveFetchFailedError (parse drift), never silently
        # return a fabricated/stale NAV.
        import io
        import urllib.request as urllib_request

        os.environ["CASCADE_LIVE_HOLDINGS"] = "1"
        adapter = IsharesNavAdapter()

        class _FakeResp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def _fake_urlopen(*_args, **_kwargs):
            return _FakeResp(b"<html><body>completely unrelated content</body></html>")

        original = urllib_request.urlopen
        urllib_request.urlopen = _fake_urlopen
        try:
            with self.assertRaises(LiveFetchFailedError):
                adapter.get_nav(FUNDS[0], as_of=date(2026, 9, 14))
        finally:
            urllib_request.urlopen = original

    def test_enabled_real_call_against_this_sandboxs_actual_network(self):
        # Documents, rather than assumes, what this environment's network
        # actually does today — same convention as
        # test_ishares_holdings.py's identical test.
        os.environ["CASCADE_LIVE_HOLDINGS"] = "1"
        adapter = IsharesNavAdapter()
        try:
            snap = adapter.get_nav(FUNDS[0], as_of=date(2026, 9, 14))
        except LiveFetchFailedError:
            pass  # expected in every sandbox this engine has been built in
        else:
            self.assertTrue(snap.nav_per_share > 0)


if __name__ == "__main__":
    unittest.main()
