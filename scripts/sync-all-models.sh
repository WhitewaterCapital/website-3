#!/usr/bin/env bash
# Refresh EVERY quant engine's website export in one command, instead of
# remembering a different `cd <engine> && venv && pip install && python -m
# X.export` incantation for each one separately.
#
# Why this exists: as of 2026-09-13, every export under public/data/*/
# latest.json was stale — Aurora ~5 weeks, Incepta ~19 days, Intra/Exitus ~1
# month, WW-Factor and WW-Graph still on synthetic-demo data even though
# their own .env files already have a real TIINGO_API_KEY (their last run
# just predates that key being added) — because none of the engines below
# had been re-run recently. Neither of the two sandboxes available to Claude
# this session can do it: the on-device sandbox (device_bash) blocks PyPI
# outright, and Claude's own cloud workspace can reach PyPI but not
# api.tiingo.com. Only your own Mac's normal network has both, so this has
# to run here, in your own Terminal.
#
# Usage:
#   ./scripts/sync-all-models.sh              # refresh everything
#   ./scripts/sync-all-models.sh factor graph # only these engines
#
# Safe to re-run any time. Every engine's export is idempotent (same real
# inputs -> same output) and each engine's own live-vs-synthetic-demo gate is
# decided purely by whether TIINGO_API_KEY is set in THAT engine's own .env —
# this script never touches those files, it only runs what's already there.
# A missing TIINGO_API_KEY in a given engine's .env means that engine will
# keep producing (clearly labeled) synthetic-demo output, not an error.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO_ROOT="$(pwd)"

OK=()
FAILED=()
SKIPPED=()

want() {
  # No args at all -> run everything. Otherwise only run names given.
  [ "${#FILTER[@]}" -eq 0 ] && return 0
  for f in "${FILTER[@]}"; do
    [ "$f" = "$1" ] && return 0
  done
  return 1
}

FILTER=("$@")

run_module_engine() {
  local name="$1" dir="$2" module="$3"
  want "$name" || { SKIPPED+=("$name"); return; }
  echo ""
  echo "── $name ($dir) ──────────────────────────────────────────"
  if [ ! -d "$REPO_ROOT/$dir" ]; then
    echo "  ✗ $dir not found — skipping"
    FAILED+=("$name: directory not found")
    return
  fi
  (
    set -e
    cd "$REPO_ROOT/$dir"
    if [ ! -d ".venv" ]; then
      echo "  setting up .venv (first run only, ~1 min)…"
      python3 -m venv .venv
    fi
    # shellcheck disable=SC1091
    source .venv/bin/activate
    pip install -q -r requirements.txt
    python -m "$module"
  )
  if [ $? -eq 0 ]; then
    OK+=("$name")
  else
    FAILED+=("$name: export failed — see output above")
  fi
}

# --- The five self-contained engines: fixed universe, zero args needed ----
run_module_engine "factor" "factor-engine" "fac.export"
run_module_engine "graph" "graph-engine" "ge.export"
run_module_engine "weekly" "weekly-engine" "wf.export"
run_module_engine "intra-exitus" "intra-exitus-engine" "ie.export"
run_module_engine "chaos" "chaos-engine" "chaos.export"

# --- Incepta: needs an explicit ticker list (ingest, then export) ---------
# Reusing the same 5-ticker universe already live in public/data/incepta/
# latest.json (AAPL/MSFT/NVDA/KO/F) — same names Intra/Exitus already covers
# — rather than inventing a new one. Broaden this list yourself if you want
# more names covered; every step below just forwards whatever's here.
INCEPTA_TICKERS=(AAPL MSFT NVDA KO F)
if want "incepta"; then
  echo ""
  echo "── incepta (engine) ────────────────────────────────────────"
  if [ ! -d "$REPO_ROOT/engine" ]; then
    echo "  ✗ engine/ not found — skipping"
    FAILED+=("incepta: directory not found")
  else
    (
      set -e
      cd "$REPO_ROOT/engine"
      if [ ! -d ".venv" ]; then
        echo "  setting up .venv (first run only, ~1 min)…"
        python3 -m venv .venv
      fi
      # shellcheck disable=SC1091
      source .venv/bin/activate
      pip install -q -r requirements.txt
      python -m incepta.cli ingest "${INCEPTA_TICKERS[@]}"
      python -m incepta.cli export "${INCEPTA_TICKERS[@]}"
    )
    if [ $? -eq 0 ]; then OK+=("incepta"); else FAILED+=("incepta: ingest/export failed — see output above"); fi
  fi
else
  SKIPPED+=("incepta")
fi

# --- Aurora: a separate sibling repo — this only copies its export over ---
if want "aurora"; then
  echo ""
  echo "── aurora (npm run sync:aurora) ────────────────────────────"
  echo "  Aurora lives in its own sibling repo (~/Desktop/aurora-macro-engine"
  echo "  by default) with its own refresh cycle — this only copies its"
  echo "  latest export into this repo. If that repo needs refreshing first,"
  echo "  do that there, then re-run this."
  npm run sync:aurora --silent
  if [ $? -eq 0 ]; then OK+=("aurora"); else FAILED+=("aurora: sync failed — see output above (often just means the sibling repo/export isn't there yet)"); fi
else
  SKIPPED+=("aurora")
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "Done. ${#OK[@]} refreshed, ${#FAILED[@]} failed, ${#SKIPPED[@]} skipped."
[ "${#OK[@]}" -gt 0 ] && printf '  ✓ %s\n' "${OK[@]}"
[ "${#FAILED[@]}" -gt 0 ] && printf '  ✗ %s\n' "${FAILED[@]}"
echo ""
echo "Restart nothing — the Next.js dev server reads these files live, no"
echo "server restart needed. Refresh the page."
[ "${#FAILED[@]}" -eq 0 ]
