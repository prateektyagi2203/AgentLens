import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "@playwright/test";

const PORT = Number(process.env.STORE_E2E_PORT ?? 3100);

// Isolated run directory inside the package (git-ignored). Workers inherit the value from this process.
process.env.AGENTLENS_E2E_DIR ??= path.join(__dirname, ".e2e-tmp", `run-${Date.now()}`);
const runDir = process.env.AGENTLENS_E2E_DIR;
fs.mkdirSync(runDir, { recursive: true });

export default defineConfig({
  testDir: "./tests/e2e",
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  globalTeardown: "./tests/e2e/global-teardown.ts",
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "off" },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: {
    command: "node node_modules/next/dist/bin/next build && node server.mjs",
    url: `http://127.0.0.1:${PORT}/robots.txt`,
    timeout: 300_000,
    reuseExistingServer: false,
    env: {
      PORT: String(PORT),
      HOST: "127.0.0.1",
      AGENTLENS_DATA_DIR: path.join(runDir, "data"),
      AGENTLENS_FRICTION_FILE: path.join(runDir, "friction.json"),
      AGENTLENS_ADMIN_PASSWORD: "e2e-admin",
      AGENTLENS_IP_SALT: "e2e-salt",
      AGENTLENS_NGINX_LOG: "1",
      AGENTLENS_SYNTH_MODE: "0",
      DEMO_MODE: "0",
    },
  },
});
