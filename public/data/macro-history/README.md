# public/data/macro-history/ — SYNTHETIC TEST FIXTURES, NOT A REAL ARCHIVE

**Read this before treating anything in this directory as real historical
macro data.**

## What this is

Four dated `MacroContractV2`-shaped JSON files (`2026-05-01.json` through
`2026-08-01.json`), used ONLY to prove that the IMP-06 point-in-time
mechanism works: given a `?timestamp=`, `src/app/api/macro/point-in-time`
picks the correct dated file, never look-ahead, always the same answer for
the same input.

## What this is NOT

This is **not** a real historical archive of past Aurora macro snapshots.
The actual Aurora macro engine lives in a separate repository this
environment does not have access to, and no real point-in-time history of
its output exists here — only the one current snapshot committed at
`public/data/aurora/latest.json`. Building a genuine PIT archive means
running Aurora on a schedule and committing (or otherwise durably storing)
each run's output over time; that has not happened yet.

Every number in every file in this directory is invented for the purpose of
exercising the lookup mechanism — plausible-looking, deliberately varied
across the four dates so a lookup test can tell them apart, but **not**
derived from any real macro data, any real Aurora run, or any real economic
history. Each file also carries two explicit marker fields for anyone
reading the raw JSON directly:

```json
"__synthetic_test_fixture__": true,
"__source_note__": "Invented for IMP-06 PIT mechanism testing — not a real historical Aurora snapshot. See public/data/macro-history/README.md."
```

## Consequence for the point-in-time endpoint

`GET /api/macro/point-in-time?timestamp=...` is honest about this limit:

- It only ever returns a snapshot that is *actually one of these four
  files* — the nearest one at or before the requested timestamp.
- A timestamp before `2026-05-01` (the earliest fixture) gets a `404` with
  an explicit "no snapshot available" message, never a silent fallback to
  the live `latest.json`.
- The response body is unchanged on repeat calls for the same timestamp
  (static files, no randomness, no `Date.now()` in the selection path) —
  see `selectPointInTimeSnapshot` in `src/lib/models/macro-contract-v2.ts`.

## Extending this to a real archive later

The mechanism (`selectPointInTimeSnapshot`, the route handler, the
`MacroContractV2` shape) does not change when real history becomes
available. The only thing that changes is what populates this directory:
swap these four synthetic files for real dated Aurora snapshots (e.g. one
committed per weekly/daily Aurora run), drop the two marker fields, and
delete this README's "not a real archive" caveat once it no longer applies.
