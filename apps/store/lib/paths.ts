import fs from "node:fs";
import path from "node:path";

let cachedRoot: string | null = null;

/** Repo root: AGENTLENS_REPO_ROOT (set by server.mjs) or the nearest ancestor holding pnpm-workspace.yaml. */
export function repoRoot(): string {
  if (process.env.AGENTLENS_REPO_ROOT) return process.env.AGENTLENS_REPO_ROOT;
  if (cachedRoot) return cachedRoot;
  let dir = process.cwd();
  for (;;) {
    if (fs.existsSync(path.join(dir, "pnpm-workspace.yaml"))) {
      cachedRoot = dir;
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  cachedRoot = path.resolve(process.cwd(), "../..");
  return cachedRoot;
}

export function storeDir(): string {
  return path.join(repoRoot(), "apps", "store");
}

/** AGENTLENS_DATA_DIR (relative values resolve against the repo root, never the cwd). */
export function dataDir(): string {
  const configured = process.env.AGENTLENS_DATA_DIR;
  if (!configured) return path.join(repoRoot(), "data");
  return path.isAbsolute(configured) ? configured : path.resolve(repoRoot(), configured);
}

export const logsDir = () => path.join(dataDir(), "logs");
export const ordersFile = () => path.join(dataDir(), "orders.jsonl");
export const catalogFile = () => path.join(storeDir(), "data", "catalog.json");

export function frictionFile(): string {
  const override = process.env.AGENTLENS_FRICTION_FILE;
  if (override) return path.isAbsolute(override) ? override : path.resolve(repoRoot(), override);
  return path.join(storeDir(), "config", "friction.json");
}
