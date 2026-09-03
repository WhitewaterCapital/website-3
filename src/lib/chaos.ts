import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { ChaosExport } from "@/lib/models/chaos-export";

// ---------------------------------------------------------------------------
// The single seam for WW-CHAOS data.
//
// Reads the JSON written by `python -m chaos.export` (chaos-engine/chaos/
// export.py) to public/data/chaos/latest.json. Same swap-to-Supabase seam as
// Aurora/Incepta/Intra-Exitus: production later swaps ONLY this function for
// a query returning the same ChaosExport shape; no UI change required.
//
// Not wired into any page or src/lib/models/registry.ts yet — this is the
// export seam landing ahead of UI wiring, per chaos-engine's scope.
// ---------------------------------------------------------------------------

const FILE = path.join(process.cwd(), "public", "data", "chaos", "latest.json");

export async function getChaosExport(): Promise<ChaosExport | null> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    return JSON.parse(raw) as ChaosExport;
  } catch {
    return null; // not exported yet — UI shows "not yet available"
  }
}
