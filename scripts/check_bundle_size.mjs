// Initial-route JS budget gate: < 300 KB gzipped (spec §6.5, CI-checked).
// Measures the entry chunks referenced by dist/index.html (script + modulepreload).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const BUDGET_BYTES = 300 * 1024;
const dist = process.argv[2] ?? "apps/web/dist";

const html = readFileSync(join(dist, "index.html"), "utf8");
const refs = [
  ...html.matchAll(/(?:src|href)="\/(assets\/[^"]+\.js)"/g),
].map((match) => match[1]);

if (refs.length === 0) {
  console.error("bundle gate: no JS entries found in dist/index.html");
  process.exit(1);
}

let total = 0;
for (const ref of [...new Set(refs)]) {
  const gzipped = gzipSync(readFileSync(join(dist, ref))).length;
  total += gzipped;
  console.log(`  ${ref}: ${(gzipped / 1024).toFixed(1)} KB gz`);
}

console.log(`initial-route JS: ${(total / 1024).toFixed(1)} KB gz (budget ${BUDGET_BYTES / 1024} KB)`);
if (total > BUDGET_BYTES) {
  console.error("bundle gate FAILED: initial route exceeds §6.5 budget");
  process.exit(1);
}
console.log("bundle gate passed.");
