import { describe, expect, it } from "vitest";
import {
  addDays,
  buildPresets,
  daysBetween,
  filterSessions,
  filtersToQuery,
  parseFilters,
  sessionMatchesFilters,
} from "./filters";
import type { SessionRow } from "./types";

const params = (q: string) => {
  const sp = new URLSearchParams(q);
  return (k: string) => sp.get(k);
};

const row = (over: Partial<SessionRow>): SessionRow => ({
  session_id: "s1",
  start_ts: "2026-11-10T08:00:00Z",
  duration_s: 30,
  request_count: 8,
  page_count: 3,
  identity_tier: "declared",
  operator: "OpenAI",
  agent_name: "ChatGPT-User",
  agent_class: "user_fetcher",
  identity_confidence: 0.7,
  entry_page: "/",
  exit_page: "/p/x",
  max_stage: "S2",
  converted: false,
  order_value_inr: null,
  terminal_blocker_id: "B03",
  terminal_blocker_name: "JS-only content",
  blocker_confidence: 0.8,
  diagnosis_method: "rule",
  ...over,
});

describe("filters <-> URL", () => {
  it("parses valid params and drops invalid ones", () => {
    const f = parseFilters(params("from=2026-11-05&to=nope&segment=verified&operator=OpenAI&agent_class=bogus"));
    expect(f).toEqual({ from: "2026-11-05", segment: "verified", operator: "OpenAI" });
  });
  it("omits the default segment when serialising", () => {
    expect(filtersToQuery({ segment: "all_agents", from: "2026-11-05" })).toEqual({ from: "2026-11-05" });
    expect(filtersToQuery({ segment: "humans", agent_class: "browsing_agent" })).toEqual({
      segment: "humans",
      agent_class: "browsing_agent",
    });
  });
});

describe("date helpers", () => {
  it("adds days and counts inclusive spans", () => {
    expect(addDays("2026-11-30", 1)).toBe("2026-12-01");
    expect(daysBetween("2026-11-05", "2026-11-11")).toBe(7);
  });
  it("suggests before/after windows around the latest fix annotation", () => {
    const p = buildPresets({ min: "2026-11-05", max: "2026-11-18" }, [
      { ts: "2026-11-12T06:00:00Z", type: "config_change", label: "fix" },
    ]);
    expect(p.find((x) => x.id === "before")).toMatchObject({ from: "2026-11-05", to: "2026-11-11" });
    expect(p.find((x) => x.id === "after")).toMatchObject({ from: "2026-11-12", to: "2026-11-18" });
    expect(p.find((x) => x.id === "7d")).toMatchObject({ from: "2026-11-12", to: "2026-11-18" });
  });
  it("has only generic presets without annotations", () => {
    expect(buildPresets({ min: "2026-11-05", max: "2026-11-18" }).map((p) => p.id)).toEqual(["all", "7d"]);
  });
});

describe("session filtering", () => {
  it("applies segment, operator and window", () => {
    expect(sessionMatchesFilters(row({}), { segment: "all_agents" })).toBe(true);
    expect(sessionMatchesFilters(row({}), { segment: "humans" })).toBe(false);
    expect(sessionMatchesFilters(row({ identity_tier: "human" }), { segment: "humans" })).toBe(true);
    expect(sessionMatchesFilters(row({}), { operator: "Anthropic" })).toBe(false);
    expect(sessionMatchesFilters(row({}), { from: "2026-11-11" })).toBe(false);
    expect(sessionMatchesFilters(row({}), { to: "2026-11-10" })).toBe(true);
  });
  it("searches, sorts and paginates", () => {
    const rows = [
      row({ session_id: "a", duration_s: 5 }),
      row({ session_id: "b", duration_s: 50, terminal_blocker_id: "B05", terminal_blocker_name: "Pincode wall" }),
      row({ session_id: "c", duration_s: 20 }),
    ];
    expect(filterSessions(rows, {}, { q: "pincode" }).items.map((r) => r.session_id)).toEqual(["b"]);
    expect(filterSessions(rows, {}, { sort: "duration_s", order: "desc" }).items.map((r) => r.session_id)).toEqual([
      "b",
      "c",
      "a",
    ]);
    const paged = filterSessions(rows, {}, { page: 2, page_size: 2, sort: "duration_s", order: "asc" });
    expect(paged.total).toBe(3);
    expect(paged.items.map((r) => r.session_id)).toEqual(["b"]);
  });
});
