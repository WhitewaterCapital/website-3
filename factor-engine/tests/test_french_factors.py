"""Unit tests for fac/adapters/french_factors.py against a MOCKED,
realistic Kenneth French Data Library response -- this sandbox has no
outbound network access, so `requests.Session.get` is monkeypatched to
return an in-memory zip built to match the library's real, documented file
shape (banner lines before the header, percent-formatted values, and a
trailing lower-granularity section that must be excluded) -- see
french_factors.py's module docstring for the exact format this mirrors,
verified live against the Ken French library and a GitHub mirror of the real
5-factor daily file via WebFetch (2026-09). No real network call is made or
attempted anywhere in this file.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest

from fac.adapters.french_factors import (
    FrenchDataError,
    fetch_5_factor_daily,
    fetch_factor_panel,
    fetch_momentum_daily,
    parse_french_daily_csv,
)


def _zip_bytes(csv_text: str, name: str = "data.CSV") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, csv_text)
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, content_by_url: dict[str, bytes]):
        self._content_by_url = content_by_url
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        return _FakeResponse(self._content_by_url[url])


# Realistic 5-factor daily CSV text: two banner lines, a blank line, the
# header, several data rows -- copied verbatim in spirit from the real file
# (see french_factors.py's module docstring for the exact confirmed
# reference row), followed by a trailing MONTHLY-granularity chunk (6-digit
# YYYYMM date) to prove the daily-only filter actually excludes it, since
# this sandbox could not confirm from a live fetch whether the real daily
# file ever carries such a trailing section (see README "Current status").
REALISTIC_5_FACTOR_CSV = """This file was created by CMPT_ME_BEME_OP_INV_RETS_DAILY using the 202601 CRSP database.,,,,,,
The 1-month TBill return is from Ibbotson and Associates, Inc.,,,,,
,,,,,,
Date,Mkt-RF,SMB,HML,RMW,CMA,RF
19630701,-0.67,0.00,-0.31,0.01,0.15,0.012
19630702,0.79,-0.27,0.26,-0.08,-0.19,0.012
19630703,0.63,-0.17,-0.09,0.19,-0.33,0.012

  Monthly Factors,,,,,,
196307,1.23,-0.45,0.67,0.11,-0.22,0.30
"""

REALISTIC_MOMENTUM_CSV = """This file was created using the 202601 CRSP database. It contains a momentum factor.,
,
Date,Mom
19630701,0.45
19630702,-0.12
19630703,0.30
"""

# Same as REALISTIC_5_FACTOR_CSV but with the lower-granularity (6-digit
# YYYYMM) row immediately following the daily rows, with NO intervening
# blank line or text line -- this isolates the actual discriminator
# (`_DAILY_DATE_RE`, an 8-digit-width check) from "stop at the first blank
# line", proving the parser rejects a 6-digit date on width alone rather
# than accidentally relying on the blank line to have already ended the table.
NO_BLANK_LINE_BEFORE_MONTHLY_SECTION = """Date,Mkt-RF,SMB,HML,RMW,CMA,RF
19630701,-0.67,0.00,-0.31,0.01,0.15,0.012
19630702,0.79,-0.27,0.26,-0.08,-0.19,0.012
196307,1.23,-0.45,0.67,0.11,-0.22,0.30
"""


def test_parse_finds_header_after_banner_lines_and_converts_percent_to_decimal():
    df = parse_french_daily_csv(REALISTIC_5_FACTOR_CSV, ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"])
    assert list(df.columns) == ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]
    assert len(df) == 3  # the trailing monthly row must NOT be included
    assert df.index[0] == pd.Timestamp("1963-07-01")
    assert df.loc[pd.Timestamp("1963-07-01"), "Mkt-RF"] == pytest.approx(-0.0067)
    assert df.loc[pd.Timestamp("1963-07-01"), "RF"] == pytest.approx(0.00012)


def test_parse_excludes_trailing_lower_granularity_section_by_date_width_alone():
    # No blank line precedes the 6-digit-date row here -- proves the parser
    # stops on the date-width mismatch itself, not merely on a blank line.
    df = parse_french_daily_csv(
        NO_BLANK_LINE_BEFORE_MONTHLY_SECTION, ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]
    )
    assert len(df) == 2
    assert df.index.max() == pd.Timestamp("1963-07-02")


def test_parse_momentum_file():
    df = parse_french_daily_csv(REALISTIC_MOMENTUM_CSV, ["Mom"])
    assert list(df.columns) == ["Mom"]
    assert len(df) == 3
    assert df.loc[pd.Timestamp("1963-07-02"), "Mom"] == pytest.approx(-0.0012)


def test_parse_missing_date_header_raises():
    with pytest.raises(FrenchDataError, match="Date"):
        parse_french_daily_csv("just,some,junk,text\n1,2,3,4\n", ["Mkt-RF"])


def test_parse_missing_expected_column_raises():
    text = "Date,Mkt-RF,SMB\n19630701,-0.67,0.00\n"
    with pytest.raises(FrenchDataError, match="missing expected"):
        parse_french_daily_csv(text, ["Mkt-RF", "SMB", "HML"])


def test_parse_malformed_row_raises():
    text = "Date,Mkt-RF,SMB\n19630701,-0.67\n"  # one field short
    with pytest.raises(FrenchDataError, match="Malformed"):
        parse_french_daily_csv(text, ["Mkt-RF", "SMB"])


def test_parse_zero_data_rows_raises():
    text = "Date,Mkt-RF,SMB\n"
    with pytest.raises(FrenchDataError, match="zero"):
        parse_french_daily_csv(text, ["Mkt-RF", "SMB"])


def test_fetch_5_factor_daily_uses_cache_on_second_call(tmp_path, monkeypatch):
    import fac.config as config

    monkeypatch.setattr(config, "cache_dir", lambda: tmp_path)
    import fac.adapters.french_factors as ff

    monkeypatch.setattr(ff, "cache_dir", lambda: tmp_path)

    session = _FakeSession({config.FRENCH_5_FACTOR_DAILY_URL: _zip_bytes(REALISTIC_5_FACTOR_CSV)})
    df1 = fetch_5_factor_daily(session=session)
    assert session.calls == 1
    assert len(df1) == 3

    # Second call within the TTL must hit the on-disk cache, not the network.
    df2 = fetch_5_factor_daily(session=session)
    assert session.calls == 1
    pd.testing.assert_frame_equal(df1, df2)


def test_fetch_5_factor_daily_force_refresh_bypasses_cache(tmp_path, monkeypatch):
    import fac.config as config
    import fac.adapters.french_factors as ff

    monkeypatch.setattr(config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(ff, "cache_dir", lambda: tmp_path)

    session = _FakeSession({config.FRENCH_5_FACTOR_DAILY_URL: _zip_bytes(REALISTIC_5_FACTOR_CSV)})
    fetch_5_factor_daily(session=session)
    assert session.calls == 1
    fetch_5_factor_daily(session=session, force_refresh=True)
    assert session.calls == 2


def test_fetch_factor_panel_inner_joins_5_factor_and_momentum(tmp_path, monkeypatch):
    import fac.config as config
    import fac.adapters.french_factors as ff

    monkeypatch.setattr(config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(ff, "cache_dir", lambda: tmp_path)

    session = _FakeSession(
        {
            config.FRENCH_5_FACTOR_DAILY_URL: _zip_bytes(REALISTIC_5_FACTOR_CSV),
            config.FRENCH_MOMENTUM_DAILY_URL: _zip_bytes(REALISTIC_MOMENTUM_CSV),
        }
    )
    panel = fetch_factor_panel(session=session)
    assert list(panel.columns) == ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom", "RF"]
    assert len(panel) == 3
    assert panel.loc[pd.Timestamp("1963-07-01"), "Mom"] == pytest.approx(0.0045)


def test_fetch_multiple_csvs_in_zip_raises():
    content = _zip_bytes(REALISTIC_5_FACTOR_CSV, name="a.CSV")
    buf = io.BytesIO(content)
    # Append a second CSV member into the same zip.
    with zipfile.ZipFile(buf, "a") as zf:
        zf.writestr("b.CSV", REALISTIC_5_FACTOR_CSV)
    content2 = buf.getvalue()

    from fac.adapters.french_factors import _extract_single_csv_text

    with pytest.raises(FrenchDataError, match="exactly one CSV"):
        _extract_single_csv_text(content2)
