import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { EarningsExport } from "@/lib/models/earnings-export";

// The single seam for WW-EARNINGS data. Reads the JSON the engine writes to
// public/data/earnings/latest.json (via `python -m ee.export` in
// earnings-engine/). Same swap-to-Supabase seam as Factor/Incepta/Aurora/
// Intra-Exitus/WW-GRAPH/WW-WEEKLY.
const FILE = path.join(process.cwd(), "public", "data", "earnings", "latest.json");

export async function getEarningsExport(): Promise<EarningsExport | null> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    return JSON.parse(raw) as EarningsExport;
  } catch {
    return null; // not exported yet — UI/model shows "not synced"
  }
}

// Convenience read used by earnings-move.ts: the export's own event for one
// ticker, or null if that ticker has nothing upcoming in the exported
// window (which is a real "nothing scheduled soon" answer, not a failure).
export async function getUpcomingEarningsFor(ticker: string) {
  const data = await getEarningsExport();
  if (!data) return { status: "not_exported" as const };
  const event = data.events.find((e) => e.ticker.toUpperCase() === ticker.toUpperCase());
  if (!event) return { status: "none_scheduled" as const, data_provenance: data.data_provenance };
  return { status: "scheduled" as const, event, data_provenance: data.data_provenance, as_of: data.as_of };
}
