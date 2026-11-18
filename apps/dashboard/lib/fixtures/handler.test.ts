/* eslint-disable @typescript-eslint/no-explicit-any -- tests probe loosely-typed JSON payloads */
import { describe, expect, it, beforeEach } from "vitest";
import { mockRequest, resetMockState } from "./handler";

const get = (path: string, q: Record<string, string> = {}) => mockRequest("GET", path, q).data as any;

describe("mock story", () => {
  beforeEach(() => resetMockState());

  it("before window: pincode wall is ~31% of failed sessions and ~INR 12.6 lakh/month", () => {
    const b = get("/blockers", { from: "2026-11-05", to: "2026-11-11" });
    const top = b.items[0];
    expect(top.blocker_id).toBe("B05");
    expect(top.share_of_failed).toBeGreaterThan(0.3);
    expect(top.share_of_failed).toBeLessThan(0.32);
    expect(top.risk_inr.base).toBeGreaterThan(12_000_00);
    expect(top.risk_inr.base).toBeLessThan(13_200_00);
    expect(top.risk_inr.low).toBeLessThan(top.risk_inr.base);
    expect(top.risk_inr.high).toBeGreaterThan(top.risk_inr.base);
  });

  it("after window: B03/B05/B06 are gone and agent conversion jumps", () => {
    const b = get("/blockers", { from: "2026-11-12", to: "2026-11-18" });
    const ids = b.items.map((i: { blocker_id: string }) => i.blocker_id);
    for (const gone of ["B03", "B05", "B06"]) expect(ids).not.toContain(gone);
    const c = get("/compare", { a_from: "2026-11-05", a_to: "2026-11-11", b_from: "2026-11-12", b_to: "2026-11-18" });
    expect(c.b.conversion).toBeGreaterThan(c.a.conversion * 1.8);
    expect(c.significance.significant).toBe(true);
  });

  it("marking a recommendation fixed creates an annotation", () => {
    const r = mockRequest("PATCH", "/recommendations/rec_B05", {}, { status: "fixed" }).data as any;
    expect(r.recommendation.status).toBe("fixed");
    expect(r.annotation.type).toBe("marked_fixed");
    expect(get("/annotations").items.some((a: { type: string }) => a.type === "marked_fixed")).toBe(true);
  });

  it("rejects invalid settings with field errors", () => {
    const s = get("/settings");
    s.impact.recoverable_rate.base = 2;
    const res = mockRequest("PUT", "/settings", {}, s);
    expect(res.status).toBe(422);
    expect((res.data as any).error.fields["impact.recoverable_rate.base"]).toBeTruthy();
  });

  it("segment=humans yields no agent blockers", () => {
    expect(get("/blockers", { segment: "humans" }).items).toHaveLength(0);
  });
});
