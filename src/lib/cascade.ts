import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { CascadeExport, CascadePressureRow } from "@/lib/models/cascade-export";

// The single seam for WW-CASCADE-DATA. Reads the JSON the engine writes to
// public/data/cascade/latest.json (via `python -m cde.export` in
// cascade-data-engine/). Same swap-to-Supabase seam as Factor/Incepta/
// Aurora/Intra-Exitus/WW-GRAPH/WW-WEEKLY/WW-EARNINGS.
//
// As shipped, the file this reads is "data_provenance": "synthetic-demo" —
// see cascade-data-engine/README.md for exactly why (the real endpoint is
// confirmed reachable from a normal network, but not from any sandbox this
// engine has actually run in). This reader makes no assumption either way;
// it surfaces whatever `data_provenance` the export actually carries and
// leaves it to the caller/UI to label accordingly, same discipline as
// getEarningsExport().
const FILE = path.join(process.cwd(), "public", "data", "cascade", "latest.json");

export async function getCascadeExport(): Promise<CascadeExport | null> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    return JSON.parse(raw) as CascadeExport;
  } catch {
    return null; // not exported yet — UI/model shows "not synced"
  }
}

// Convenience read: one constituent's pressure row, or an explicit status
// distinguishing "never exported", "not held by any tracked fund" (a real
// answer, not a failure), and "held but pressure is NaN" (partial/no
// coverage — see the row's own n_products_used/warnings for why) from an
// actual usable pressure reading.
export async function getCascadePressureFor(
  ticker: string
): Promise<
  | { status: "not_exported" }
  | { status: "not_tracked"; data_provenance: CascadeExport["data_provenance"] }
  | { status: "no_coverage"; row: CascadePressureRow; data_provenance: CascadeExport["data_provenance"] }
  | { status: "usable"; row: CascadePressureRow; data_provenance: CascadeExport["data_provenance"]; as_of: string }
> {
  const data = await getCascadeExport();
  if (!data) return { status: "not_exported" };
  const row = data.pressure.find((r) => r.constituent.toUpperCase() === ticker.toUpperCase());
  if (!row) return { status: "not_tracked", data_provenance: data.data_provenance };
  if (row.pressure === null || row.n_products_used === 0) {
    return { status: "no_coverage", row, data_provenance: data.data_provenance };
  }
  return { status: "usable", row, data_provenance: data.data_provenance, as_of: data.as_of };
}
