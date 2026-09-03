import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { StateExport } from "@/lib/models/state-export";

// ---------------------------------------------------------------------------
// The single seam for WW-STATE (the market state vector).
//
// Today it reads the JSON the engine writes to public/data/state/latest.json.
// Production swaps ONLY this function for a Supabase query returning the same
// StateExport shape — no UI or route changes. Everything else builds against
// the schema, not the file (same pattern as src/lib/incepta.ts / aurora.ts).
// ---------------------------------------------------------------------------

const FILE = path.join(process.cwd(), "public", "data", "state", "latest.json");

export async function getStateExport(): Promise<StateExport | null> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    return JSON.parse(raw) as StateExport;
  } catch {
    // No data yet (engine hasn't exported the state vector).
    return null;
  }
}
