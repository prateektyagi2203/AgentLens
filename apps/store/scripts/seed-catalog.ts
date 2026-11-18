import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { generateCatalog } from "../lib/seed";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, "..", "data", "catalog.json");
const catalog = generateCatalog();
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, JSON.stringify(catalog, null, 2) + "\n");
console.log(`wrote ${catalog.products.length} products to ${out}`);
