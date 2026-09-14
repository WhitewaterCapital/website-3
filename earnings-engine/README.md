# WW-EARNINGS — earnings calendar + pre-print positioning

Answers one narrow question honestly: for the platform's fixed cross-sectional
universe, which names have a confirmed earnings print inside the next
`LOOKAHEAD_DAYS`, and what do this repo's own already-real signals (WW-Insider,
WW-Factor) say about each name going into that print.

**Not** an earnings-surprise-direction predictor — see
`research/equity-model-research-dossier.md`'s own "Earnings-surprise
direction" row: Medium confidence, needs analyst-estimate data with poor
free coverage. This engine ships the honestly-buildable part (the calendar,
plus reuse of two already-real positioning signals) and abstains rather than
fabricate the rest. See `src/lib/models/impl/earnings-move.ts` for the
website-side model that consumes this export.

## Run it

```
cd earnings-engine
python -m ee.export
```

Writes `public/data/earnings/latest.json` (web-servable) and
`earnings-engine/exports/latest.json` (engine-side copy).

- `FMP_API_KEY` unset → deterministic synthetic-demo calendar (`ee/synthetic.py`).
- `FMP_API_KEY` set → real Financial Modeling Prep pull via
  `ee/adapters/fmp_calendar.py` — **the adapter is currently an honest stub**;
  see its module docstring for exactly what to implement. No sandbox this
  engine has been built in has outbound network access to verify this path
  live — same wall documented for Tiingo/Alpha Vantage/iShares in
  `PLATFORM_REBUILD_PLAN.md`'s Roadblocks. Try it from your own machine.

## Tests

```
python -m unittest discover -s tests -v
```

Pure standard library — no `requirements.txt`, nothing to `pip install`.
Deliberately kept dependency-free so this engine can be built and verified
even from a sandboxed shell with no PyPI access (confirmed working end to
end from exactly such a shell — see the commit this shipped in).

## Files

```
ee/
  config.py        universe, lookahead window, the one live/synthetic gate
  synthetic.py      seeded deterministic fallback calendar
  adapters/
    fmp_calendar.py  FMP adapter — honest stub, zero network calls, see its docstring
  export.py          builds + writes the website JSON
tests/
  test_export.py     synthetic-path + roundtrip tests (all passing, stdlib only)
```
