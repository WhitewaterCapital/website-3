import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { AllocExport } from "@/lib/models/alloc-export";

// ---------------------------------------------------------------------------
// The single seam for WW-ALLOC (the capital allocator, quant-infra/alloc/
// solve.py).
//
// Today it reads the JSON at public/data/alloc/latest.json — a clearly-labeled
// SAMPLE export (see alloc-export.ts's module doc) standing in for a live
// solve.py run, since there is no Next.js-callable bridge to the Python
// process at request time. Production later swaps ONLY this function for a
// Supabase query (or a real export written by solve.py) returning the same
// AllocExport shape — no UI or route changes. Same pattern as
// src/lib/state.ts / src/lib/chaos.ts.
// ---------------------------------------------------------------------------

const FILE = path.join(process.cwd(), "public", "data", "alloc", "latest.json");

export async function getAllocExport(): Promise<AllocExport | null> {
  try {
    const raw = await fs.readFile(FILE, "utf8");
    return JSON.parse(raw) as AllocExport;
  } catch {
    // No export yet (no live allocator run wired in).
    return null;
  }
}
