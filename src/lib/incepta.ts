import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { EquityExport, SecurityAnalysis } from "@/lib/models/incepta-export";

// ---------------------------------------------------------------------------
// The single seam for Incepta equity data.
//
// Today it reads the JSON the engine writes to public/data/incepta/latest.json.
// Production swaps ONLY this function for a Supabase query returning the same
// EquityExport shape — no UI or route changes. Everything else builds against
// the schema, not the file.
// ---------------------------------------------------------------------------

const FILE = path.join(process.cwd(), "public", "data", "incepta", "latest.json");

export async function getEquityExport(): Promise<EquityExport | null> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    return JSON.parse(raw) as EquityExport;
  } catch {
    // No data yet (engine hasn't exported, or table not populated).
    return null;
  }
}

export function findSecurity(
  data: EquityExport,
  ticker: string,
): SecurityAnalysis | undefined {
  const t = ticker.trim().toUpperCase();
  return data.securities.find((s) => s.ticker.toUpperCase() === t);
}
