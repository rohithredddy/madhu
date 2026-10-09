// Copy the built UI into the backend, so one Java process serves everything
// (docs/02 section 4, "single-server mode"). Run with `npm run build:backend`.
// The target folder is git-ignored: it is a build output, rebuilt from source.
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const dist = resolve(here, "..", "dist");
const target = resolve(here, "..", "..", "backend", "src", "main", "resources", "static");

if (!existsSync(dist)) {
  console.error("No dist/ folder. Run `npm run build` first.");
  process.exit(1);
}
rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });
cpSync(dist, target, { recursive: true });
console.log(`copied ${dist} -> ${target}`);
