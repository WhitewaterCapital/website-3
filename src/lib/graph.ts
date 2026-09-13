import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { GraphExport } from "@/lib/models/graph-export";

// The single seam for WW-GRAPH data. Reads the JSON the engine writes to
// public/data/graph/latest.json (via `python -m ge.export` in the
// graph-engine package). Same swap-to-Supabase seam as Incepta/Aurora/
// Intra-Exitus.
const FILE = path.join(process.cwd(), "public", "data", "graph", "latest.json");
const HISTORY_FILE = path.join(process.cwd(), "public", "data", "graph", "history.jsonl");

export async function getGraphExport(): Promise<GraphExport | null> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    return JSON.parse(raw) as GraphExport;
  } catch {
    return null; // not exported yet — UI shows "not synced"
  }
}

// Real replay history — one full GraphExport-shaped line per day the engine
// has been run (see graph-engine/ge/export.py's `append_history`, written by
// `python -m ge.export`). Returns null (not an empty array) when the file
// doesn't exist yet or has no parseable lines, so callers can tell "no
// history log yet" apart from "log exists but is empty" — VisualsClient
// falls back to the single latest snapshot in both null and <2-entry cases,
// since real scrubbing needs at least two distinct days to be meaningful.
export async function getGraphHistory(): Promise<GraphExport[] | null> {
  try {
    const raw = await fs.readFile(HISTORY_FILE, "utf8");
    const lines = raw
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    if (lines.length === 0) return null;
    const entries = lines
      .map((l) => {
        try {
          return JSON.parse(l) as GraphExport;
        } catch {
          return null; // one corrupt line shouldn't sink the whole history read
        }
      })
      .filter((e): e is GraphExport => e != null);
    return entries.length > 0 ? entries : null;
  } catch {
    return null; // no history log yet — UI falls back to the single latest snapshot
  }
}
