import fs from "node:fs";

export default function globalTeardown() {
  const dir = process.env.AGENTLENS_E2E_DIR;
  if (dir && !process.env.AGENTLENS_E2E_KEEP) fs.rmSync(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
}
