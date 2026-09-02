import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { MacroExport } from "@/lib/models/aurora-export";

// ---------------------------------------------------------------------------
// The single seam for Aurora macro data.
//
// Reads the JSON synced into public/data/aurora/latest.json (via
// `npm run sync:aurora`, from the separate Aurora engine repo). Committing the
// file here is what makes it deploy-safe on Vercel — the engine repo doesn't
// exist there. Production later swaps ONLY this function for a Supabase query
// returning the same MacroExport shape; no UI change.
// ---------------------------------------------------------------------------

const FILE = path.join(process.cwd(), "public", "data", "aurora", "latest.json");

export async function getMacroExport(): Promise<MacroExport | null> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    return JSON.parse(raw) as MacroExport;
  } catch {
    return null; // not synced yet — UI shows "not yet available"
  }
}
