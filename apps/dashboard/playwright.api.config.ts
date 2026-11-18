import { defineConfig, devices } from "@playwright/test";

// Runs the dashboard against the real API (agentlens serve on :8100); start both first, then:
//   pnpm --filter @agentlens/dashboard exec playwright test -c playwright.api.config.ts
export default defineConfig({
  testDir: "./e2e",
  testMatch: /api-smoke\.spec\.ts/,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://localhost:3101", trace: "retain-on-failure", viewport: { width: 1440, height: 900 } },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
