import type { AgentClass, Annotation, Filters, Segment, SessionQuery, SessionRow } from "./types";

export const SEGMENTS: { value: Segment; label: string }[] = [
  { value: "all_agents", label: "All agents" },
  { value: "verified", label: "Verified" },
  { value: "declared", label: "Declared" },
  { value: "suspected", label: "Suspected" },
  { value: "humans", label: "Humans" },
];

export const AGENT_CLASSES: { value: AgentClass; label: string }[] = [
  { value: "user_fetcher", label: "User fetcher" },
  { value: "browsing_agent", label: "Browsing agent" },
];

export const DEFAULT_SEGMENT: Segment = "all_agents";

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 86_400_000;

/** URL-safe slug used for demo snapshot file names (`agents/<operator>/<agent>.json`). */
export const slug = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

export const isDay = (v: string | null | undefined): v is string =>
  !!v && DAY_RE.test(v) && !Number.isNaN(Date.parse(v));

export const segmentLabel = (s: Segment | undefined): string =>
  SEGMENTS.find((x) => x.value === (s ?? DEFAULT_SEGMENT))?.label ?? "All agents";

export function addDays(day: string, n: number): string {
  return new Date(Date.parse(day) + n * DAY_MS).toISOString().slice(0, 10);
}

/** Inclusive number of days between two day strings. */
export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(to) - Date.parse(from)) / DAY_MS) + 1;
}

export function eachDay(from: string, to: string): string[] {
  const out: string[] = [];
  for (let d = from; d <= to; d = addDays(d, 1)) out.push(d);
  return out;
}

/** Parse the shareable filter query params; invalid values are dropped. */
export function parseFilters(get: (key: string) => string | null | undefined): Filters {
  const f: Filters = {};
  const from = get("from");
  const to = get("to");
  if (isDay(from)) f.from = from;
  if (isDay(to)) f.to = to;
  const segment = get("segment");
  if (SEGMENTS.some((s) => s.value === segment)) f.segment = segment as Segment;
  const operator = get("operator");
  if (operator) f.operator = operator;
  const cls = get("agent_class");
  if (AGENT_CLASSES.some((c) => c.value === cls)) f.agent_class = cls as AgentClass;
  return f;
}

/** Serialise filters to query params; the default segment is omitted to keep URLs short. */
export function filtersToQuery(f: Filters): Record<string, string> {
  const q: Record<string, string> = {};
  if (f.from) q.from = f.from;
  if (f.to) q.to = f.to;
  if (f.segment && f.segment !== DEFAULT_SEGMENT) q.segment = f.segment;
  if (f.operator) q.operator = f.operator;
  if (f.agent_class) q.agent_class = f.agent_class;
  return q;
}

export function toSearch(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const hasActiveFilters = (f: Filters): boolean =>
  !!(f.from || f.to || (f.segment && f.segment !== DEFAULT_SEGMENT) || f.operator || f.agent_class);

export interface WindowPreset {
  id: string;
  label: string;
  from: string;
  to: string;
}

/**
 * Presets for the date picker. Around the most recent config_change/marked_fixed annotation we
 * suggest "before fix" / "after fix" windows of equal length (capped to 7 days).
 */
export function buildPresets(
  bounds: { min: string; max: string } | null,
  annotations: Pick<Annotation, "ts" | "type" | "label">[] = [],
): WindowPreset[] {
  if (!bounds) return [];
  const presets: WindowPreset[] = [{ id: "all", label: "All data", from: bounds.min, to: bounds.max }];
  const last7 = addDays(bounds.max, -6);
  presets.push({ id: "7d", label: "Last 7 days", from: last7 < bounds.min ? bounds.min : last7, to: bounds.max });
  const latest = (type: Annotation["type"]) =>
    [...annotations].filter((a) => a.type === type).sort((a, b) => b.ts.localeCompare(a.ts))[0];
  const change = latest("config_change") ?? latest("marked_fixed");
  if (change) {
    const day = change.ts.slice(0, 10);
    const span = Math.min(7, daysBetween(bounds.min, addDays(day, -1)), daysBetween(day, bounds.max));
    if (span >= 1) {
      presets.push({ id: "before", label: "Before fix", from: addDays(day, -span), to: addDays(day, -1) });
      presets.push({ id: "after", label: "After fix", from: day, to: addDays(day, span - 1) });
    }
  }
  return presets;
}

const tierOfSegment: Record<Exclude<Segment, "all_agents">, string> = {
  verified: "verified",
  declared: "declared",
  suspected: "suspected",
  humans: "human",
};

export function sessionMatchesFilters(row: SessionRow, f: Filters): boolean {
  const day = row.start_ts.slice(0, 10);
  if (f.from && day < f.from) return false;
  if (f.to && day > f.to) return false;
  const segment = f.segment ?? DEFAULT_SEGMENT;
  if (segment === "all_agents") {
    if (row.identity_tier === "human") return false;
  } else if (row.identity_tier !== tierOfSegment[segment]) {
    return false;
  }
  if (f.operator && row.operator !== f.operator) return false;
  if (f.agent_class && row.agent_class !== f.agent_class) return false;
  return true;
}

/** Client-side equivalent of GET /sessions, used for static demo snapshots. */
export function filterSessions(
  rows: SessionRow[],
  f: Filters,
  q: SessionQuery,
): { total: number; items: SessionRow[]; page: number; page_size: number } {
  const needle = q.q?.trim().toLowerCase();
  let out = rows.filter((r) => sessionMatchesFilters(r, f));
  if (q.identity_tier) out = out.filter((r) => r.identity_tier === q.identity_tier);
  if (q.blocker_id) out = out.filter((r) => r.terminal_blocker_id === q.blocker_id);
  if (q.max_stage) out = out.filter((r) => r.max_stage === q.max_stage);
  if (q.converted !== undefined) out = out.filter((r) => r.converted === q.converted);
  if (needle) {
    out = out.filter((r) =>
      [r.session_id, r.operator, r.agent_name, r.entry_page, r.exit_page, r.terminal_blocker_id, r.terminal_blocker_name]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(needle)),
    );
  }
  const sort = q.sort ?? "start_ts";
  const dir = (q.order ?? "desc") === "desc" ? -1 : 1;
  out = [...out].sort((a, b) => {
    const av = a[sort] ?? 0;
    const bv = b[sort] ?? 0;
    return av < bv ? -dir : av > bv ? dir : 0;
  });
  const page_size = q.page_size ?? 25;
  const page = q.page ?? 1;
  return { total: out.length, items: out.slice((page - 1) * page_size, page * page_size), page, page_size };
}
