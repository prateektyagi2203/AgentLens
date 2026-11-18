import { expect, test, type Page } from "@playwright/test";

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

const noErrors = (page: Page) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
};

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
});

for (const p of PAGES) {
  test(`page ${p.path} renders with fixtures`, async ({ page }) => {
    const errors = noErrors(page);
    await page.goto(p.path);
    await expect(page.getByRole("heading", { level: 1, name: p.heading })).toBeVisible();
    await expect(page.getByTestId("error-state")).toHaveCount(0);
    await expect(page.getByTestId("demo-badge")).toHaveText("Mock data");
    await expect(page.getByTestId(`nav-${p.nav}`)).toHaveAttribute("aria-current", "page");
    expect(errors).toEqual([]);
  });
}

test("overview shows hero numbers and the annotation marker", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("kpi-risk")).toContainText("₹");
  await expect(page.getByTestId("timeseries-chart")).toBeVisible();
  await expect(page.getByTestId("annotation-list")).toContainText("Config change");
  await expect(page.getByTestId("top-fixes").locator("li")).toHaveCount(3);
});

test("global filters change the URL and the view", async ({ page }) => {
  await page.goto("/");
  const before = await page.getByTestId("kpi-agent-sessions").innerText();
  await page.getByRole("button", { name: "Verified", exact: true }).click();
  await expect(page).toHaveURL(/segment=verified/);
  await expect(page.getByTestId("kpi-agent-sessions")).not.toHaveText(before);

  await page.getByTestId("filter-preset").selectOption({ label: "Before fix" });
  await expect(page).toHaveURL(/from=2026-11-05/);
  await expect(page).toHaveURL(/segment=verified/);
  await page.getByTestId("nav-funnel").click();
  await expect(page).toHaveURL(/segment=verified/);
  await expect(page).toHaveURL(/from=2026-11-05/);
});

test("filters in the URL are restored on load (shareable)", async ({ page }) => {
  await page.goto("/blockers?from=2026-11-05&to=2026-11-11&segment=all_agents");
  const row = page.getByTestId("blockers-table").locator("tbody tr").first();
  await expect(row).toContainText("B05");
  await expect(row).toContainText("31");
  await expect(page.getByTestId("filter-from")).toHaveValue("2026-11-05");
});

test("funnel: clicking a stage shows its blockers", async ({ page }) => {
  await page.goto("/funnel?from=2026-11-05&to=2026-11-11");
  await expect(page.getByTestId("funnel-bars")).toBeVisible();
  await page.getByTestId("funnel-stage-S5").click();
  await expect(page.getByTestId("stage-blockers")).toContainText("Pincode wall");
});

test("blockers: detail opens and Mark as fixed works against the mock", async ({ page }) => {
  await page.goto("/blockers?from=2026-11-05&to=2026-11-11");
  await page.getByTestId("blockers-table").locator("tbody tr").first().click();
  await expect(page).toHaveURL(/id=B05/);
  await expect(page.getByTestId("blocker-detail")).toContainText("Pincode wall");
  await expect(page.getByTestId("replay-carousel")).toBeVisible();
  await expect(page.getByTestId("recommendation")).toContainText("Verify metric");
  await page.getByTestId("mark-fixed").click();
  await expect(page.getByTestId("fixed-badge")).toBeVisible();
  await expect(page.getByTestId("mark-fixed-msg")).toContainText(/annotation/i);
  await page.getByTestId("back-to-blockers").click();
  await expect(page).not.toHaveURL(/id=/);
});

test("sessions: list opens a timeline", async ({ page }) => {
  await page.goto("/sessions");
  await expect(page.getByTestId("sessions-list")).toBeVisible();
  await page.getByTestId("sessions-list").locator("tbody tr").first().click();
  await expect(page.getByTestId("session-detail")).toBeVisible();
  await expect(page.getByTestId("session-timeline")).toBeVisible();
});

test("replays: detail shows steps and network log", async ({ page }) => {
  await page.goto("/replays");
  await page.getByTestId("replays-table").locator("tbody tr").first().click();
  await expect(page.getByTestId("replay-detail")).toBeVisible();
  await expect(page.getByTestId("network-log")).toBeVisible();
});

test("agents: drawer opens and crawlers are listed", async ({ page }) => {
  await page.goto("/agents");
  await page.getByTestId("agents-table").locator("tbody tr").first().click();
  await expect(page.getByTestId("agent-detail")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByTestId("crawlers-section")).toBeVisible();
});

test("compare: before/after shows delta cards and significance", async ({ page }) => {
  await page.goto("/compare");
  await expect(page.getByTestId("delta-conversion")).toBeVisible();
  await expect(page.getByTestId("significance")).toContainText(/significant/i);
  await expect(page.getByTestId("blocker-shares")).toContainText("Pincode wall");
});

test("settings: validation, report links and pipeline run", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByTestId("report-md")).toHaveAttribute("href", /report/);
  await expect(page.getByTestId("report-pdf-disabled")).toBeVisible();
  await expect(page.getByTestId("eval-panel")).toContainText("Identity accuracy");
  await expect(page.getByTestId("limitations")).toContainText("Honest limitations");
  const input = page.getByTestId("setting-impact.recoverable_rate.base");
  await input.fill("2");
  await expect(page.getByTestId("settings-invalid")).toBeVisible();
  await expect(page.getByTestId("save-settings")).toBeDisabled();
  await input.fill("0.5");
  await page.getByTestId("save-settings").click();
  await expect(page.getByTestId("settings-status")).toContainText("Saved");
  await page.getByTestId("run-pipeline").click();
  await expect(page.getByTestId("run-status")).toContainText(/running|succeeded/);
});

test("story mode toggles and persists", async ({ page }) => {
  await page.goto("/");
  const html = page.locator("html");
  await expect(html).not.toHaveAttribute("data-story", "on");
  await page.getByTestId("story-toggle").click();
  await expect(html).toHaveAttribute("data-story", "on");
  await expect(page.getByTestId("story-hero")).toBeVisible();
  await page.reload();
  await expect(html).toHaveAttribute("data-story", "on");
  await page.getByTestId("nav-blockers").click();
  await expect(page.getByTestId("blockers-table")).toBeHidden();
  await expect(page.getByTestId("story-blockers")).toBeVisible();
  await page.getByTestId("story-toggle").click();
  await expect(html).not.toHaveAttribute("data-story", "on");
});

test("theme toggles and persists", async ({ page }) => {
  await page.goto("/");
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.getByTestId("theme-toggle").click();
  await expect(html).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => window.localStorage.getItem("agentlens-theme"))).toBe("dark");
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "dark");
});

test("keyboard: table rows are focusable and Enter opens the detail", async ({ page }) => {
  await page.goto("/blockers?from=2026-11-05&to=2026-11-11");
  const row = page.getByTestId("blockers-table").locator("tbody tr").first();
  await row.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/id=/);
});
