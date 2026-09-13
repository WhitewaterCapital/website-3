import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { FactorExport } from "@/lib/models/factor-export";

// The single seam for WW-FACTOR data. Reads the JSON the engine writes to
// public/data/factor/latest.json (via `python -m fac.export` in
// factor-engine/). Same swap-to-Supabase seam as Incepta/Aurora/Intra-Exitus/
// WW-GRAPH/WW-WEEKLY.
const FILE = path.join(process.cwd(), "public", "data", "factor", "latest.json");

export async function getFactorExport(): Promise<FactorExport | null> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    return JSON.parse(raw) as FactorExport;
  } catch {
    return null; // not exported yet — UI shows "not synced"
  }
}
