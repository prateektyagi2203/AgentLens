import { describe, expect, it } from "vitest";
import { generateCatalog } from "../../lib/seed";
import { loadCatalog } from "../../lib/catalog";

describe("catalogue invariants", () => {
  const catalog = loadCatalog();
  const variants = catalog.products.flatMap((p) => p.variants);

  it("has 60 products in 4 categories", () => {
    expect(catalog.products).toHaveLength(60);
    expect(catalog.categories.map((c) => c.name)).toEqual(["Men's sneakers", "Women's kurtas", "Men's shirts", "Accessories"]);
    expect(new Set(catalog.products.map((p) => p.slug)).size).toBe(60);
  });
  it("has about 10% out-of-stock variants and keeps one in stock per product", () => {
    const oos = variants.filter((v) => v.stock === 0).length / variants.length;
    expect(oos).toBeGreaterThan(0.08);
    expect(oos).toBeLessThan(0.12);
    for (const p of catalog.products) expect(p.variants.some((v) => v.stock > 0)).toBe(true);
  });
  it("flags exactly 2 products for the price mismatch with a different cart price", () => {
    const flagged = catalog.products.filter((p) => p.price_mismatch);
    expect(flagged).toHaveLength(2);
    for (const p of flagged) expect(p.cart_price).not.toBe(p.price);
    for (const p of catalog.products.filter((x) => !x.price_mismatch)) expect(p.cart_price).toBeNull();
  });
  it("carries every PRD 8.1 field", () => {
    for (const p of catalog.products) {
      expect(p.price).toBeGreaterThan(0);
      expect(p.mrp).toBeGreaterThanOrEqual(p.price);
      expect(p.images.length).toBeGreaterThan(0);
      expect(p.size_chart.html).toContain("<table");
      expect(p.size_chart.image).toMatch(/^\/img\/size\//);
      expect(p.return_policy.window_days).toBeGreaterThan(0);
      expect(p.rating.value).toBeGreaterThanOrEqual(1);
      expect(p.rating.value).toBeLessThanOrEqual(5);
      expect(p.variants.length).toBeGreaterThan(1);
    }
  });
  it("matches the seed script output (deterministic)", () => {
    expect(JSON.parse(JSON.stringify(generateCatalog(catalog.seed)))).toEqual(JSON.parse(JSON.stringify(catalog)));
  });
});
