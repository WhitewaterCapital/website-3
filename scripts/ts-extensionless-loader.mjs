// Tiny Node ESM resolution hook used only by scripts/verify-roles-audit.mjs.
//
// src/lib/*.ts files import each other without file extensions (e.g.
// `from "./roles"`), which is valid under this project's TypeScript
// "moduleResolution": "bundler" setting (and how Next.js/SWC resolve it at
// build time). Plain Node's ESM resolver requires an explicit extension, so
// this hook retries an unresolved bare specifier with ".ts" appended before
// giving up. It exists purely so this repo's dependency-free node script can
// run the .ts sources directly with `--experimental-strip-types` — it is not
// used by the app itself and does not change any src/ file.
import { existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";

export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context);
  } catch (err) {
    if (
      (specifier.startsWith("./") || specifier.startsWith("../")) &&
      !specifier.endsWith(".ts") &&
      context.parentURL
    ) {
      const candidate = new URL(`${specifier}.ts`, context.parentURL);
      if (existsSync(fileURLToPath(candidate))) {
        return nextResolve(pathToFileURL(fileURLToPath(candidate)).href, context);
      }
    }
    throw err;
  }
}
