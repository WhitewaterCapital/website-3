import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";
import {
  selectPointInTimeSnapshot,
  type HistorySnapshotIndexEntry,
  type MacroContractV2,
} from "@/lib/models/macro-contract-v2";

// IMP-06 — GET /api/macro/point-in-time?timestamp=<ISO-8601>
//
// Returns the macro contract EXACTLY as it stood at `timestamp` — the
// endpoint a training job must use (never /api/macro/latest, which always
// answers with whatever is newest right now). Deterministic: the same
// `timestamp` always returns the same contract, because the lookup below
// only ever reads static files and the selection function
// (`selectPointInTimeSnapshot`) does no `Date.now()`/randomness of its own.
//
// ⚠️ HONESTY LIMIT, READ public/data/macro-history/README.md: the archive
// this endpoint searches is currently four hand-built SYNTHETIC fixture
// files, not a real history of past Aurora runs — the real Aurora engine
// lives in a separate repository this environment has no historical export
// from. This endpoint's MECHANISM (versioned contract, nearest-before
// lookup, no look-ahead, honest 404) is real and correct; the DATA it
// searches today is a labeled stand-in. Swapping in a real archive later
// requires no change here — only populating the directory with real dated
// snapshots.
const HISTORY_DIR = path.join(process.cwd(), "public", "data", "macro-history");

async function loadHistoryIndex(): Promise<
  { entry: HistorySnapshotIndexEntry; contract: MacroContractV2 }[]
> {
  let filenames: string[];
  try {
    filenames = await fs.readdir(HISTORY_DIR);
  } catch {
    return [];
  }

  const jsonFilenames = filenames.filter((f) => f.endsWith(".json"));
  const loaded = await Promise.all(
    jsonFilenames.map(async (file) => {
      const raw = await fs.readFile(path.join(HISTORY_DIR, file), "utf8");
      const contract = JSON.parse(raw) as MacroContractV2;
      return { entry: { as_of_time: contract.as_of_time, file }, contract };
    }),
  );
  return loaded;
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const timestamp = searchParams.get("timestamp");

  if (!timestamp || Number.isNaN(Date.parse(timestamp))) {
    return NextResponse.json(
      {
        error:
          "Query parameter `timestamp` is required and must be a parseable " +
          "ISO-8601 date or datetime (e.g. 2026-07-15 or 2026-07-15T00:00:00Z).",
      },
      { status: 400 },
    );
  }

  const indexed = await loadHistoryIndex();
  const selected = selectPointInTimeSnapshot(
    indexed.map((i) => i.entry),
    timestamp,
  );

  if (!selected) {
    // Honest "no data" — never a silent fallback to /api/macro/latest.
    return NextResponse.json(
      {
        error: "No macro snapshot is available at or before this timestamp.",
        requested_timestamp: timestamp,
        honesty_note:
          "public/data/macro-history/ is currently a small set of labeled " +
          "SYNTHETIC test fixtures, not a real historical archive — see " +
          "public/data/macro-history/README.md. This endpoint never " +
          "substitutes live/latest data for a past query it cannot answer.",
      },
      { status: 404 },
    );
  }

  const match = indexed.find((i) => i.entry.file === selected.file);
  // Cannot actually happen (selected came from indexed's own entries), but
  // fail loudly rather than silently if it ever did.
  if (!match) {
    return NextResponse.json(
      { error: "Internal error: selected snapshot could not be re-located." },
      { status: 500 },
    );
  }

  return NextResponse.json(match.contract);
}
