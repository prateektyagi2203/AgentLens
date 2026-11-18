/* eslint-disable react-hooks/rules-of-hooks -- Playwright fixtures call `use`, which is not a React hook */
import fs from "node:fs";
import path from "node:path";
import { test as base, expect, type APIRequestContext, type Browser, type BrowserContext } from "@playwright/test";
import { loadCatalog, type Product } from "../../lib/catalog";
import { FRICTION_IDS, type FrictionId } from "../../lib/friction-meta";

export const BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36";
export const ADMIN_PASSWORD = "e2e-admin";
export const DEV_OTP = "123456";

let counter = Math.floor(Math.random() * 60_000);
/** A unique client address per test so state and rate-limit buckets never overlap. */
export const uniqueIp = () => {
  counter += 1;
  return `10.${(counter >> 8) & 255}.${counter & 255}.${1 + Math.floor(Math.random() * 250)}`;
};

export const runDir = () => process.env.AGENTLENS_E2E_DIR as string;
export const dataDir = () => path.join(runDir(), "data");
export const logsDir = () => path.join(dataDir(), "logs");

interface Fixtures {
  /** Plain HTTP client with a browser UA and its own client address and cookie jar. */
  client: APIRequestContext;
  /** Set exactly these toggles on; every other toggle is switched off. */
  setToggles: (...on: FrictionId[]) => Promise<void>;
  /** A fresh browser context (own sessionStorage, cookies and client address). */
  newPage: () => Promise<{ page: import("@playwright/test").Page; context: BrowserContext }>;
}

async function newBrowserContext(browser: Browser, baseURL: string): Promise<BrowserContext> {
  return browser.newContext({ baseURL, extraHTTPHeaders: { "x-forwarded-for": uniqueIp() } });
}

export const test = base.extend<Fixtures>({
  client: async ({ playwright, baseURL }, use) => {
    const ctx = await playwright.request.newContext({
      baseURL,
      extraHTTPHeaders: { "x-forwarded-for": uniqueIp(), "user-agent": BROWSER_UA },
    });
    await use(ctx);
    await ctx.dispose();
  },
  setToggles: async ({ playwright, baseURL }, use) => {
    await use(async (...on) => {
      const admin = await playwright.request.newContext({ baseURL, extraHTTPHeaders: { "x-admin-password": ADMIN_PASSWORD } });
      const toggles = Object.fromEntries(FRICTION_IDS.map((id) => [id, on.includes(id)]));
      const res = await admin.post("/api/admin/friction", { data: { toggles } });
      expect(res.status()).toBe(200);
      await admin.dispose();
    });
  },
  newPage: async ({ browser, baseURL }, use) => {
    const contexts: BrowserContext[] = [];
    await use(async () => {
      const context = await newBrowserContext(browser, baseURL as string);
      contexts.push(context);
      return { page: await context.newPage(), context };
    });
    await Promise.all(contexts.map((c) => c.close()));
  },
});

export { expect };

export const catalog = () => loadCatalog();

export function inStockProduct(index = 0): Product {
  return catalog().products.filter((p) => p.variants.every((v) => v.stock > 0) && !p.price_mismatch)[index];
}

export function pickInStock(p: Product) {
  return p.variants.find((v) => v.stock > 0)!;
}

export async function addToCart(client: APIRequestContext, p: Product = inStockProduct()) {
  const v = pickInStock(p);
  return client.post("/api/cart", { data: { product_id: p.id, size: v.size, colour: v.colour, qty: 1 } });
}

export const VALID_ORDER = {
  name: "E2E Buyer",
  phone: "+91 98765 43210",
  address: "12 Test Lane, Bengaluru 560001",
  payment_method: "UPI",
};

export function readAllLogLines(): Record<string, unknown>[] {
  const dir = logsDir();
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((f) => /^access-\d{4}-\d{2}-\d{2}\.jsonl$/.test(f))
    .flatMap((f) => fs.readFileSync(path.join(dir, f), "utf8").split("\n").filter(Boolean))
    .map((l) => JSON.parse(l));
}

/** Logging happens when the response closes, so poll briefly instead of assuming it is already on disk. */
export async function waitForLog(predicate: (rec: Record<string, unknown>) => boolean, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const hit = readAllLogLines().find(predicate);
    if (hit) return hit;
    if (Date.now() > deadline) throw new Error("log record not found");
    await new Promise((r) => setTimeout(r, 100));
  }
}
