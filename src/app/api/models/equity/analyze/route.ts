import { NextResponse } from "next/server";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { getEquityExport, findSecurity } from "@/lib/incepta";
import type { SecurityAnalysis } from "@/lib/models/incepta-export";

const run = promisify(execFile);

// This route SHELLS OUT to the Python engine, so it needs the Node runtime and
// a machine that has the engine + its venv (local / self-hosted worker — not
// Vercel serverless). Production will call an engine service instead; same
// schema, so the UI is unchanged.
export const runtime = "nodejs";
export const maxDuration = 120;

// Kept out of static analysis on purpose: a literal path to the venv binary
// makes the bundler try to bundle it (and choke on the venv's out-of-root
// symlink). Point INCEPTA_PYTHON at the engine's venv in .env.local.
const ENGINE_DIR = process.env.INCEPTA_ENGINE_DIR || path.join(process.cwd(), "engine");
const PYTHON = process.env.INCEPTA_PYTHON || "python3";

// Only real tickers — also prevents any argument/shell mischief.
const TICKER_RE = /^[A-Z][A-Z0-9.\-]{0,9}$/;

async function engineExport(ticker: string): Promise<SecurityAnalysis | null> {
  const out = path.join(os.tmpdir(), `incepta_${ticker}_${Date.now()}.json`);
  try {
    await run(PYTHON, ["-m", "incepta.cli", "export", ticker, "--out", out], {
      cwd: ENGINE_DIR,
      timeout: 90_000,
      maxBuffer: 1024 * 1024 * 8,
    });
    const raw = await fs.readFile(out, "utf8");
    const data = JSON.parse(raw);
    return data.securities?.[0] ?? null;
  } catch {
    return null;
  } finally {
    fs.unlink(out).catch(() => {});
  }
}

async function engineIngest(ticker: string): Promise<boolean> {
  try {
    await run(PYTHON, ["-m", "incepta.cli", "ingest", ticker], {
      cwd: ENGINE_DIR,
      timeout: 110_000,
      maxBuffer: 1024 * 1024 * 8,
    });
    return true;
  } catch {
    return false;
  }
}

function usable(s: SecurityAnalysis | null): boolean {
  return Boolean(
    s && (s.data_quality.has_prices || s.data_quality.has_fundamentals),
  );
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const ticker = String(body.ticker ?? "").trim().toUpperCase();

  if (!TICKER_RE.test(ticker)) {
    return NextResponse.json(
      { status: "invalid", message: "Enter a valid ticker (letters/numbers)." },
      { status: 400 },
    );
  }

  // 1) Already in the published universe? Return it instantly (real, no engine run).
  const published = await getEquityExport();
  if (published) {
    const s = findSecurity(published, ticker);
    if (s) return NextResponse.json({ status: "ok", source: "universe", security: s });
  }

  // 2) Try a fast export (works if the name is already in the engine's store).
  let sec = await engineExport(ticker);

  // 3) Not there yet → ingest it live (SEC + prices), then export.
  if (!usable(sec)) {
    const ok = await engineIngest(ticker);
    if (!ok) {
      return NextResponse.json({
        status: "unavailable",
        message: `Couldn't run the engine for ${ticker}. It may be an unknown ticker (no SEC CIK) or the engine isn't reachable here.`,
      });
    }
    sec = await engineExport(ticker);
  }

  if (!usable(sec)) {
    return NextResponse.json({
      status: "unavailable",
      message: `No usable data for ${ticker} — the engine abstains rather than show made-up numbers.`,
    });
  }

  return NextResponse.json({ status: "ok", source: "engine", security: sec });
}
