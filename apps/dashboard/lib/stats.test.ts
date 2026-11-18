import { describe, expect, it } from "vitest";
import { normalCdf, twoProportionZTest } from "./stats";

describe("normalCdf", () => {
  it("matches known values", () => {
    expect(normalCdf(0)).toBeCloseTo(0.5, 6);
    expect(normalCdf(1.96)).toBeCloseTo(0.975, 3);
    expect(normalCdf(-1.96)).toBeCloseTo(0.025, 3);
  });
});

describe("twoProportionZTest", () => {
  it("returns 'not enough data' under 100 sessions per window", () => {
    const r = twoProportionZTest(5, 99, 20, 500);
    expect(r.enough_data).toBe(false);
    expect(r.z).toBeNull();
    expect(r.significant).toBe(false);
    expect(r.note).toMatch(/Not enough data/);
  });
  it("detects a clear lift", () => {
    // 3.5% of 4000 vs 9% of 4000
    const r = twoProportionZTest(140, 4000, 360, 4000);
    expect(r.enough_data).toBe(true);
    expect(r.significant).toBe(true);
    expect(r.z).toBeGreaterThan(10);
    expect(r.p_value).toBeLessThan(0.001);
  });
  it("matches a textbook example", () => {
    // 45/200 vs 30/200 -> pooled p = .1875, z = 2.4 -> p ~= 0.0164
    const r = twoProportionZTest(30, 200, 45, 200);
    expect(r.z).toBeCloseTo(1.9, 0);
    expect(r.p_value).toBeGreaterThan(0.04);
    expect(r.p_value).toBeLessThan(0.07);
  });
  it("is not significant for near-identical rates", () => {
    const r = twoProportionZTest(50, 1000, 52, 1000);
    expect(r.significant).toBe(false);
  });
  it("handles zero variance", () => {
    const r = twoProportionZTest(0, 200, 0, 200);
    expect(r.significant).toBe(false);
    expect(r.p_value).toBe(1);
  });
});
