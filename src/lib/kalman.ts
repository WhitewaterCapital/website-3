import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { KalmanExport } from "@/lib/models/kalman-export";

// The single seam for WW-KALMAN data. Reads the JSON the engine writes to
// public/data/kalman/latest.json (via `python -m kf.export` in
// kalman-engine/). Same swap-to-Supabase seam as Factor/Earnings/Incepta/
// Aurora/Intra-Exitus/WW-GRAPH/WW-WEEKLY/WW-CASCADE/WW-CHAOS.
const FILE = path.join(process.cwd(), "public", "data", "kalman", "latest.json");

export async function getKalmanExport(): Promise<KalmanExport | null> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    return JSON.parse(raw) as KalmanExport;
  } catch {
    return null; // not exported yet — UI/model shows "not synced"
  }
}
