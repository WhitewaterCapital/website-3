import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { GraphExport } from "@/lib/models/graph-export";

// The single seam for WW-GRAPH data. Reads the JSON the engine writes to
// public/data/graph/latest.json (via `python -m ge.export` in the
// graph-engine package). Same swap-to-Supabase seam as Incepta/Aurora/
// Intra-Exitus.
const FILE = path.join(process.cwd(), "public", "data", "graph", "latest.json");

export async function getGraphExport(): Promise<GraphExport | null> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    return JSON.parse(raw) as GraphExport;
  } catch {
    return null; // not exported yet — UI shows "not synced"
  }
}
