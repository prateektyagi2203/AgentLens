import { describe, expect, it } from "vitest";
import {
  formatCompact,
  formatCount,
  formatDate,
  formatDateTime,
  formatDeltaPercent,
  formatDuration,
  formatInr,
  formatInrFull,
  formatMs,
  formatPercent,
  formatPp,
} from "./format";

describe("formatInr", () => {
  it("formats lakh values", () => {
    expect(formatInr(1_260_000)).toBe("₹12.6 L");
    expect(formatInr(100_000)).toBe("₹1 L");
    expect(formatInr(840_000)).toBe("₹8.4 L");
  });
  it("formats crore values", () => {
    expect(formatInr(12_000_000)).toBe("₹1.2 Cr");
    expect(formatInr(10_000_000)).toBe("₹1 Cr");
    expect(formatInr(250_000_000)).toBe("₹25 Cr");
  });
  it("promotes lakh rounding overflow to crore", () => {
    expect(formatInr(9_999_000)).toBe("₹1 Cr");
  });
  it("uses en-IN grouping below one lakh", () => {
    expect(formatInr(82_400)).toBe("₹82,400");
    expect(formatInr(999)).toBe("₹999");
    expect(formatInr(0)).toBe("₹0");
  });
  it("handles negatives and missing values", () => {
    expect(formatInr(-1_260_000)).toBe("-₹12.6 L");
    expect(formatInr(null)).toBe("—");
    expect(formatInr(undefined)).toBe("—");
  });
  it("formats exact rupees with Indian grouping", () => {
    expect(formatInrFull(1_260_000)).toBe("₹12,60,000");
  });
});

describe("percent and deltas", () => {
  it("formats fractions", () => {
    expect(formatPercent(0.31)).toBe("31.0%");
    expect(formatPercent(0.0345, 2)).toBe("3.45%");
    expect(formatPercent(null)).toBe("—");
  });
  it("formats percentage points and relative deltas with sign", () => {
    expect(formatPp(0.057)).toBe("+5.7 pp");
    expect(formatPp(-0.012)).toBe("-1.2 pp");
    expect(formatDeltaPercent(0.123)).toBe("+12.3%");
    expect(formatDeltaPercent(-0.5, 0)).toBe("-50%");
  });
});

describe("counts, durations and dates", () => {
  it("formats counts", () => {
    expect(formatCount(1240)).toBe("1,240");
    expect(formatCount(1_234_567)).toBe("12,34,567");
    expect(formatCompact(950)).toBe("950");
    expect(formatCompact(12_400)).toBe("12.4K");
    expect(formatCompact(120_000)).toBe("1.2L");
    expect(formatCompact(34_000_000)).toBe("3.4Cr");
  });
  it("formats durations", () => {
    expect(formatDuration(4)).toBe("4s");
    expect(formatDuration(65)).toBe("1m 05s");
    expect(formatDuration(7380)).toBe("2h 03m");
    expect(formatMs(850)).toBe("850 ms");
    expect(formatMs(1300)).toBe("1.3 s");
  });
  it("formats dates in IST", () => {
    expect(formatDate("2026-11-13")).toBe("13 Nov");
    expect(formatDateTime("2026-11-13T08:30:00Z")).toBe("13 Nov, 14:00");
  });
});
