import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { IntraExitusExport } from "@/lib/models/intra-exitus-export";

// The single seam for Intra/Exitus data. Reads the JSON the engine writes to
// public/data/intra-exitus/latest.json (via `python -m ie.export` in the
// intra-exitus-engine). Same swap-to-Supabase seam as Incepta/Aurora.
const FILE = path.join(process.cwd(), "public", "data", "intra-exitus", "latest.json");

export async function getIntraExitusExport(): Promise<IntraExitusExport | null> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    return JSON.parse(raw) as IntraExitusExport;
  } catch {
    return null; // not exported yet — UI shows "not synced"
  }
}
