import { NextResponse } from "next/server";
import { getMacroExport } from "@/lib/aurora";
import { fromAuroraExport } from "@/lib/models/macro-contract-v2";

// IMP-06 — GET /api/macro/latest
//
// Returns the CURRENT machine-readable macro contract (MacroContractV2),
// built from the real Aurora export committed at
// public/data/aurora/latest.json (via src/lib/aurora.ts, unmodified — this
// route only reads through it). This is the "latest" of IMP-06's two
// endpoints; a training job must use /api/macro/point-in-time instead (see
// that route) — this one always reflects whatever the most recent Aurora
// sync produced, which is exactly what a training job must NOT rely on for
// a past timestamp (that would be look-ahead).
export async function GET() {
  const aurora = await getMacroExport();
  if (!aurora) {
    return NextResponse.json(
      {
        error:
          "No Aurora macro export is available yet (public/data/aurora/latest.json " +
          "has not been synced). Not returning a guess or a stale placeholder.",
      },
      { status: 404 },
    );
  }

  const contract = fromAuroraExport(aurora);
  return NextResponse.json(contract);
}
