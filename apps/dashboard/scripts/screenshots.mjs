/**
 * Captures P1/P3/P4 in light and dark into docs/screenshots.
 * Needs the dashboard on :3101 reading the REAL API (API on :8100 serving data/demo), e.g.
 *   $env:AGENTLENS_DATA_DIR="data/demo"; python -m agentlens.cli serve   (repo root)
 *   pnpm dev:dashboard
 * Windows default to the demo scenario (before: 2026-11-01..07, full: 2026-11-01..14); override with ALL_WINDOW / BEFORE_WINDOW / BLOCKER_ID.
 */
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const base = process.env.BASE_URL ?? "http://localhost:3101";
const out = join(process.cwd(), "..", "..", "docs", "screenshots");
mkdirSync(out, { recursive: true });
const all = process.env.ALL_WINDOW ?? "from=2026-11-01&to=2026-11-14";
const before = process.env.BEFORE_WINDOW ?? "from=2026-11-01&to=2026-11-07";
const blocker = process.env.BLOCKER_ID ?? "B06";
const shots = [
  ["overview", `/?${all}`, "kpi-risk"],
  ["funnel", `/funnel?${before}`, "funnel-bars"],
  ["blockers", `/blockers?${before}`, "blockers-table"],
  ["blocker-detail", `/blockers?id=${blocker}&${before}`, "blocker-detail"],
];

const browser = await chromium.launch();
for (const theme of ["light", "dark"]) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: theme });
  await ctx.addInitScript((t) => window.localStorage.setItem("agentlens-theme", t), theme);
  const page = await ctx.newPage();
  for (const [name, path, ready] of shots) {
    await page.goto(base + path);
    await page.getByTestId(ready).waitFor();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: join(out, `${name}-${theme}.png`), fullPage: true });
  }
  await ctx.close();
}
await browser.close();
console.log("screenshots written to", out);
