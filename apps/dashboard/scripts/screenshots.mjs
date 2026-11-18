/** Captures P1/P3/P4 in light and dark into docs/screenshots (needs the dev server on :3101 with NEXT_PUBLIC_USE_MOCKS=1). */
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const base = process.env.BASE_URL ?? "http://localhost:3101";
const out = join(process.cwd(), "..", "..", "docs", "screenshots");
mkdirSync(out, { recursive: true });
const win = "from=2026-11-05&to=2026-11-11";
const shots = [
  ["overview", `/?${win}`, "kpi-risk"],
  ["funnel", `/funnel?${win}`, "funnel-bars"],
  ["blockers", `/blockers?${win}`, "blockers-table"],
  ["blocker-detail", `/blockers?id=B05&${win}`, "blocker-detail"],
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
