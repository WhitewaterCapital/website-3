import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { WeeklyExport } from "@/lib/models/weekly-export";

// The single seam for WW-WEEKLY data. Reads the JSON the engine writes to
// public/data/weekly/latest.json (via `python -m wf.export` in weekly-engine/).
// Same swap-to-Supabase seam as Incepta/Aurora/Intra-Exitus.
const FILE = path.join(process.cwd(), "public", "data", "weekly", "latest.json");

export async function getWeeklyExport(): Promise<WeeklyExport | null> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    return JSON.parse(raw) as WeeklyExport;
  } catch {
    return null; // not exported yet — UI shows "not synced"
  }
}
