import { expect, test, type Page } from "@playwright/test";

// Loads every page against the real FastAPI (API mode). No mock-specific numbers are asserted.
const PAGES: { path: string; nav: string; heading: RegExp }[] = [
  { path: "/", nav: "overview", heading: /How AI agents shop your store/ },
  { path: "/agents", nav: "agents", heading: /Which agents visit/ },
  { path: "/funnel", nav: "funnel", heading: /Where agents drop off/ },
  { path: "/blockers", nav: "blockers", heading: /costing you agent sales/ },
  { path: "/sessions", nav: "sessions", heading: /Session Explorer/ },
  { path: "/replays", nav: "replays", heading: /Proof, not guesses/ },
  { path: "/compare", nav: "compare", heading: /Did the fix work/ },
  { path: "/settings", nav: "settings", heading: /Tune it and share it/ },
];

const watch = (page: Page) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => {
    if (r.url().includes("/api/") && r.status() >= 500) errors.push(`${r.status()} ${r.url()}`);
  });
  return errors;
};

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
});

for (const p of PAGES) {
  test(`page ${p.path} renders against the real API`, async ({ page }) => {
    const errors = watch(page);
    await page.goto(p.path);
    await expect(page.getByRole("heading", { level: 1, name: p.heading })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("error-state")).toHaveCount(0);
    await expect(page.getByTestId("demo-badge")).toHaveCount(0);
    await expect(page.getByTestId(`nav-${p.nav}`)).toHaveAttribute("aria-current", "page");
    expect(errors).toEqual([]);
  });
}

test("overview shows real KPIs", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("kpi-risk")).toContainText("₹");
  await expect(page.getByTestId("timeseries-chart")).toBeVisible();
  await expect(page.getByTestId("error-state")).toHaveCount(0);
});

test("blockers: table and detail drawer", async ({ page }) => {
  await page.goto("/blockers");
  const rows = page.getByTestId("blockers-table").locator("tbody tr");
  await expect(rows.first()).toBeVisible();
  await rows.first().click();
  await expect(page).toHaveURL(/id=B\d+/);
  await expect(page.getByTestId("blocker-detail")).toBeVisible();
  await expect(page.getByTestId("recommendation")).toBeVisible();
  await expect(page.getByTestId("error-state")).toHaveCount(0);
});

test("sessions: list opens a timeline", async ({ page }) => {
  await page.goto("/sessions");
  await expect(page.getByTestId("sessions-list")).toBeVisible();
  await page.getByTestId("sessions-list").locator("tbody tr").first().click();
  await expect(page.getByTestId("session-detail")).toBeVisible();
  await expect(page.getByTestId("session-timeline")).toBeVisible();
});

test("agents: drawer opens and crawlers are listed", async ({ page }) => {
  await page.goto("/agents");
  await page.getByTestId("agents-table").locator("tbody tr").first().click();
  await expect(page.getByTestId("agent-detail")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("crawlers-section")).toBeVisible();
});

test("global filter changes the data via the API", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Verified", exact: true }).click();
  await expect(page).toHaveURL(/segment=verified/);
  await expect(page.getByTestId("error-state")).toHaveCount(0);
  await expect(page.getByTestId("kpi-agent-sessions")).toBeVisible();
});

test("compare: before/after renders", async ({ page }) => {
  await page.goto("/compare");
  await expect(page.getByTestId("delta-conversion")).toBeVisible();
  await expect(page.getByTestId("error-state")).toHaveCount(0);
});

test("settings: eval panel, validation and save", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByTestId("eval-panel")).toBeVisible();
  const input = page.getByTestId("setting-impact.recoverable_rate.base");
  await input.fill("2");
  await expect(page.getByTestId("settings-invalid")).toBeVisible();
  await expect(page.getByTestId("save-settings")).toBeDisabled();
});
