#!/usr/bin/env node
// Sync the Aurora macro engine's latest export into this app's public/ tree.
//
// The Aurora engine is a SEPARATE repo that runs on its own schedule and writes
// exports/latest.json. This copies that file to public/data/aurora/latest.json
// so it (a) is served at /data/aurora/latest.json and (b) ships with the Vercel
// deployment — the sibling repo does NOT exist on Vercel, so committing the JSON
// here is what makes it deploy-safe.
//
// Run after the engine refreshes:  npm run sync:aurora
// Override the source with AURORA_EXPORT_PATH if the repo lives elsewhere.

import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";

const SRC =
  process.env.AURORA_EXPORT_PATH ||
  path.join(os.homedir(), "Desktop", "aurora-macro-engine", "exports", "latest.json");

const DEST = path.join(process.cwd(), "public", "data", "aurora", "latest.json");

async function main() {
  let raw;
  try {
    raw = await fs.readFile(SRC, "utf8");
  } catch {
    console.error(`✗ Aurora export not found at ${SRC}`);
    console.error("  Set AURORA_EXPORT_PATH, or run the engine's refresh first.");
    process.exit(1);
  }

  // Validate it parses and looks like the contract before writing.
  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    console.error(`✗ ${SRC} is not valid JSON.`);
    process.exit(1);
  }
  if (!data.schema_version || !data.scenarios) {
    console.error("✗ Source doesn't look like a MacroExport (missing schema_version/scenarios).");
    process.exit(1);
  }

  await fs.mkdir(path.dirname(DEST), { recursive: true });
  await fs.writeFile(DEST, raw);
  console.log(
    `✓ Synced Aurora ${data.schema_version} (as_of ${data.as_of}, ${data.scenarios.length} scenarios) → public/data/aurora/latest.json`,
  );
}

main();
