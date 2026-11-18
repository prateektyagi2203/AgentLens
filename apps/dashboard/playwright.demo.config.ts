import { defineConfig, devices } from "@playwright/test";

// Serves the static export (`pnpm --filter @agentlens/dashboard build:demo`) and checks every page renders from the snapshot.
// Run: pnpm --filter @agentlens/dashboard exec playwright test -c playwright.demo.config.ts
const PORT = Number(process.env.DEMO_PORT ?? 3111);

export default defineConfig({
  testDir: "./e2e",
  testMatch: /demo-smoke\.spec\.ts/,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure", viewport: { width: 1440, height: 900 } },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: `node scripts/serve-static.mjs out ${PORT}`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
