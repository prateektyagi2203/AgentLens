import { expect, test, type Page } from "@playwright/test";

// Loads every page of the static DEMO_MODE export (served from out/). No numbers are asserted: the snapshot is regenerated.
const PAGES: { path: string; nav: string; heading: RegExp }[] = [
  { path: "/", nav: "overview", heading: /How AI agents shop your store/ },
  { path: "/agents/", nav: "agents", heading: /Which agents visit/ },
  { path: "/funnel/", nav: "funnel", heading: /Where agents drop off/ },
  { path: "/blockers/", nav: "blockers", heading: /costing you agent sales/ },
  { path: "/sessions/", nav: "sessions", heading: /Session Explorer/ },
  { path: "/replays/", nav: "replays", heading: /Proof, not guesses/ },
  { path: "/compare/", nav: "compare", heading: /Did the fix work/ },
  { path: "/settings/", nav: "settings", heading: /Tune it and share it/ },
];

const watch = (page: Page) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => {
    if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`);
  });
  return errors;
};

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
});

for (const p of PAGES) {
  test(`page ${p.path} renders from the static snapshot`, async ({ page }) => {
    const errors = watch(page);
    await page.goto(p.path);
    await expect(page.getByRole("heading", { level: 1, name: p.heading })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("error-state")).toHaveCount(0);
    await expect(page.getByTestId("demo-badge")).toHaveText(/synthetic/i);
    await expect(page.getByTestId(`nav-${p.nav}`)).toHaveAttribute("aria-current", "page");
    expect(errors).toEqual([]);
  });
}

test("overview shows KPIs and the chart", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("kpi-risk")).toContainText("₹");
  await expect(page.getByTestId("timeseries-chart")).toBeVisible();
});

test("blockers: table row opens the detail with a recommendation", async ({ page }) => {
  await page.goto("/blockers/");
  const rows = page.getByTestId("blockers-table").locator("tbody tr");
  await expect(rows.first()).toBeVisible();
  await rows.first().click();
  await expect(page.getByTestId("blocker-detail")).toBeVisible();
  await expect(page.getByTestId("recommendation")).toBeVisible();
  await expect(page.getByTestId("error-state")).toHaveCount(0);
});

test("sessions: a row opens a timeline", async ({ page }) => {
  await page.goto("/sessions/");
  await page.getByTestId("sessions-list").locator("tbody tr").first().click();
  await expect(page.getByTestId("session-timeline")).toBeVisible();
  await expect(page.getByTestId("error-state")).toHaveCount(0);
});

test("compare: before/after renders", async ({ page }) => {
  await page.goto("/compare/");
  await expect(page.getByTestId("delta-conversion")).toBeVisible();
  await expect(page.getByTestId("error-state")).toHaveCount(0);
});
