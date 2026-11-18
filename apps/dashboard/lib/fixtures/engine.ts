import { addDays, daysBetween, eachDay } from "../filters";
import type {
  BlockerId,
  BlockerItem,
  Filters,
  FunnelSeries,
  ReplayStatus,
  Segment,
  Settings,
  StageBlocker,
  StageId,
} from "../types";
import {
  BLOCKERS,
  BLOCKER_BY_ID,
  EFFORT_WEIGHT,
  HUMAN_STAGE_REACH,
  STAGES,
  STAGE_P,
  UNITS,
  stageNum,
  type BlockerDef,
  type UnitDef,
} from "./catalog";
import { distribute } from "./prng";

/** The demo story: 14 days, friction toggles F03/F05/F06 switched off on CHANGE_DAY. */
export const FIRST_DAY = "2026-11-05";
export const LAST_DAY = "2026-11-18";
export const CHANGE_DAY = "2026-11-12";
export const DAYS = eachDay(FIRST_DAY, LAST_DAY);

type Phase = "before" | "after";
const phaseOf = (day: string): Phase => (day < CHANGE_DAY ? "before" : "after");

// Thu..Wed, each phase sums to 7 so the 7-day totals in the catalog are exact.
const DAY_WEIGHTS: Record<Phase, number[]> = {
  before: [1.04, 1.08, 0.9, 0.82, 1.06, 1.12, 0.98],
  after: [1.06, 1.05, 0.92, 0.8, 1.1, 1.07, 1.0],
};
const CONVERTED: Record<Phase, number> = { before: 145, after: 325 };
const AOV_BASE: Record<Phase, number> = { before: 2200, after: 2290 };
const HUMAN_WEEK_SESSIONS = 24_000;
const HUMAN_CONVERSION = 0.042;

export const DEFAULT_SETTINGS: Settings = {
  impact: {
    recoverable_rate: { low: 0.4, base: 0.6, high: 0.8 },
    p_stage_band: 0.2,
    default_aov_inr: 2200,
    agent_vs_human_factor: 1.0,
    min_sample: 30,
    effort_weights: { S: 1, M: 2, L: 4 },
  },
  identification: {
    signature: { clock_skew_s: 60, key_cache_ttl_s: 3600, offline_mode: false },
    suspicion: {
      threshold: 60,
      page_velocity_per_min: 15,
      weights: {
        no_beacon_with_browser_ua: 25,
        no_assets: 15,
        headless_hint: 30,
        missing_sec_fetch: 10,
        regular_timing: 10,
        high_velocity: 10,
        deep_link_cart_rush: 5,
        atypical_accept: 5,
        invalid_signature: 30,
      },
    },
    sessions: { timeout_min_human: 30, timeout_min_agent: 10 },
  },
  thresholds: { slow_response_ms: 5000, significance_min_sessions: 100 },
};

export type BlockedCounts = Partial<Record<BlockerId, number>>;

export interface UnitAgg {
  sessions: number;
  converted: number;
  revenue: number;
  pages: number;
  blocked: BlockedCounts;
}

export interface AgentAgg extends UnitAgg {
  byUnit: Record<string, UnitAgg>;
}

interface Cell extends UnitAgg {
  day: string;
  unit: string;
}

interface HumanCell {
  day: string;
  sessions: number;
  converted: number;
}

export function applies(def: BlockerDef, u: UnitDef): boolean {
  switch (def.affinity) {
    case "F":
      return u.agent_class === "user_fetcher";
    case "B":
      return u.agent_class === "browsing_agent";
    case "A_unverified":
      return u.tier !== "verified";
    default:
      return true;
  }
}

function build(): { cells: Cell[]; humans: HumanCell[] } {
  const cells: Cell[] = [];
  const humans: HumanCell[] = [];
  for (const phase of ["before", "after"] as Phase[]) {
    const days = DAYS.filter((d) => phaseOf(d) === phase);
    const w = DAY_WEIGHTS[phase];
    const blockedByDay = Object.fromEntries(
      BLOCKERS.map((b) => [b.id, distribute(b[phase], w)]),
    ) as Record<BlockerId, number[]>;
    const convByDay = distribute(CONVERTED[phase], w);
    days.forEach((day, di) => {
      const dayCells = UNITS.map<Cell>((u) => ({
        day, unit: u.id, sessions: 0, converted: 0, revenue: 0, pages: 0, blocked: {},
      }));
      for (const def of BLOCKERS) {
        const parts = distribute(blockedByDay[def.id][di], UNITS.map((u) => (applies(def, u) ? u.share : 0)));
        parts.forEach((n, ui) => {
          if (n > 0) dayCells[ui].blocked[def.id] = n;
        });
      }
      const conv = distribute(convByDay[di], UNITS.map((u) => u.convShare));
      dayCells.forEach((c, ui) => {
        c.converted = conv[ui];
        const blocked = Object.values(c.blocked).reduce((a, b) => a + (b ?? 0), 0);
        c.sessions = blocked + c.converted;
        const wobble = phase === "after" ? 1 + 0.04 * Math.sin(di * 1.7 + ui) : 1;
        c.revenue = c.converted * Math.round(AOV_BASE[phase] * wobble);
        c.pages = c.sessions * UNITS[ui].pages;
        cells.push(c);
      });
      const sessions = Math.round((HUMAN_WEEK_SESSIONS / 7) * w[di]);
      humans.push({
        day,
        sessions,
        converted: Math.round(sessions * (HUMAN_CONVERSION + 0.002 * Math.sin(di * 1.3))),
      });
    });
  }
  return { cells, humans };
}

const { cells: CELLS, humans: HUMAN_CELLS } = build();

export const unitById = (id: string): UnitDef => UNITS.find((u) => u.id === id) as UnitDef;

export function unitMatches(u: UnitDef, f: Filters): boolean {
  const segment: Segment = f.segment ?? "all_agents";
  if (segment === "humans") return false;
  if (segment !== "all_agents" && u.tier !== segment) return false;
  if (f.operator && u.operator !== f.operator) return false;
  if (f.agent_class && u.agent_class !== f.agent_class) return false;
  return true;
}

const emptyUnit = (): UnitAgg => ({ sessions: 0, converted: 0, revenue: 0, pages: 0, blocked: {} });

function add(target: UnitAgg, c: UnitAgg) {
  target.sessions += c.sessions;
  target.converted += c.converted;
  target.revenue += c.revenue;
  target.pages += c.pages;
  for (const [k, v] of Object.entries(c.blocked)) {
    const id = k as BlockerId;
    target.blocked[id] = (target.blocked[id] ?? 0) + (v ?? 0);
  }
}

export interface Win {
  from: string;
  to: string;
}

export function aggregateAgents(w: Win, f: Filters): AgentAgg {
  const agg: AgentAgg = { ...emptyUnit(), byUnit: {} };
  for (const c of CELLS) {
    if (c.day < w.from || c.day > w.to) continue;
    const u = unitById(c.unit);
    if (!unitMatches(u, f)) continue;
    add(agg, c);
    add((agg.byUnit[u.id] ??= emptyUnit()), c);
  }
  return agg;
}

export function humanAgg(w: Win): { sessions: number; converted: number } {
  let sessions = 0;
  let converted = 0;
  for (const h of HUMAN_CELLS) {
    if (h.day < w.from || h.day > w.to) continue;
    sessions += h.sessions;
    converted += h.converted;
  }
  return { sessions, converted };
}

export interface DayStats {
  date: string;
  human: number;
  humanConverted: number;
  verified: number;
  declared: number;
  suspected: number;
  agentSessions: number;
  agentConverted: number;
}

export function dailyStats(w: Win, f: Filters): DayStats[] {
  const out: DayStats[] = [];
  for (const day of eachDay(w.from, w.to)) {
    if (day < FIRST_DAY || day > LAST_DAY) continue;
    const h = HUMAN_CELLS.find((x) => x.day === day);
    const s: DayStats = {
      date: day, human: h?.sessions ?? 0, humanConverted: h?.converted ?? 0,
      verified: 0, declared: 0, suspected: 0, agentSessions: 0, agentConverted: 0,
    };
    for (const c of CELLS) {
      if (c.day !== day) continue;
      const u = unitById(c.unit);
      if (!unitMatches(u, f)) continue;
      s[u.tier] += c.sessions;
      s.agentSessions += c.sessions;
      s.agentConverted += c.converted;
    }
    out.push(s);
  }
  return out;
}

export function blockerTrend(id: BlockerId, w: Win, f: Filters): { date: string; sessions_blocked: number }[] {
  return eachDay(w.from, w.to)
    .filter((d) => d >= FIRST_DAY && d <= LAST_DAY)
    .map((date) => {
      let n = 0;
      for (const c of CELLS) {
        if (c.day === date && unitMatches(unitById(c.unit), f)) n += c.blocked[id] ?? 0;
      }
      return { date, sessions_blocked: n };
    });
}

export function failedSessions(a: UnitAgg): number {
  return a.sessions - a.converted;
}

// ------------------------------------------------------------------ funnel
export function agentReach(a: UnitAgg): number[] {
  const reach: number[] = [a.sessions];
  for (let n = 2; n <= 8; n++) {
    let lost = 0;
    for (const def of BLOCKERS) if (stageNum(def.stage) <= n) lost += a.blocked[def.id] ?? 0;
    reach.push(a.sessions - lost);
  }
  return reach;
}

export function humanReach(h: { sessions: number; converted: number }): number[] {
  const reach = HUMAN_STAGE_REACH.map((p) => Math.round(h.sessions * p));
  reach[0] = h.sessions;
  reach[7] = h.converted;
  return reach;
}

export function toSeries(segment: Segment, reach: number[]): FunnelSeries {
  const first = reach[0] || 0;
  return {
    segment,
    sessions: first,
    conversion: first ? reach[7] / first : 0,
    steps: STAGES.map((s, i) => ({
      stage_id: s.id,
      name: s.name,
      sessions: reach[i],
      step_conversion: i === 0 ? 1 : reach[i - 1] ? reach[i] / reach[i - 1] : 0,
      drop_off: i === 0 ? 0 : reach[i - 1] ? 1 - reach[i] / reach[i - 1] : 0,
      overall_conversion: first ? reach[i] / first : 0,
    })),
  };
}

export function funnelSeries(segment: Segment, w: Win, f: Filters): FunnelSeries {
  if (segment === "humans") return toSeries(segment, humanReach(humanAgg(w)));
  return toSeries(segment, agentReach(aggregateAgents(w, { ...f, segment })));
}

// ------------------------------------------------------------------ impact
export interface ImpactResult {
  items: BlockerItem[];
  totalRiskBase: number;
  totalFailed: number;
  diagnosisCoverage: number;
  aov: number;
  k: number;
}

export function computeImpact(
  agg: UnitAgg,
  days: number,
  impact: Settings["impact"],
  replayStatus: (id: BlockerId) => ReplayStatus,
): ImpactResult {
  const k = 30 / Math.max(1, days);
  const failed = failedSessions(agg);
  const aov = agg.converted > 0 ? agg.revenue / agg.converted : impact.default_aov_inr;
  const { recoverable_rate: r, p_stage_band: band, effort_weights: ew } = impact;
  const items: BlockerItem[] = [];
  for (const def of BLOCKERS) {
    const L = agg.blocked[def.id] ?? 0;
    if (L <= 0) continue;
    const p = STAGE_P[def.stage];
    const risk = (rate: number, pm: number) =>
      def.id === "B99" ? 0 : Math.round(L * rate * Math.min(1, p * pm) * aov * k);
    const risk_inr = {
      low: risk(r.low, 1 - band),
      base: risk(r.base, 1),
      high: risk(r.high, 1 + band),
    };
    items.push({
      blocker_id: def.id,
      name: def.name,
      stage: def.stage,
      sessions_blocked: L,
      share_of_failed: failed ? L / failed : 0,
      risk_inr,
      replay_status: replayStatus(def.id),
      effort: def.effort,
      priority_score: Math.round(risk_inr.base / (ew[def.effort] ?? EFFORT_WEIGHT[def.effort])),
      low_confidence: L < impact.min_sample,
    });
  }
  items.sort((a, b) => b.risk_inr.base - a.risk_inr.base || b.sessions_blocked - a.sessions_blocked);
  const unknown = agg.blocked.B99 ?? 0;
  return {
    items,
    totalRiskBase: items.reduce((s, i) => s + i.risk_inr.base, 0),
    totalFailed: failed,
    diagnosisCoverage: failed ? 1 - unknown / failed : 1,
    aov,
    k,
  };
}

export function stageBlockers(items: BlockerItem[]): Record<StageId, StageBlocker[]> {
  const out = Object.fromEntries(STAGES.map((s) => [s.id, [] as StageBlocker[]])) as Record<StageId, StageBlocker[]>;
  for (const i of items) {
    out[i.stage].push({
      blocker_id: i.blocker_id,
      name: i.name,
      sessions_blocked: i.sessions_blocked,
      share_of_failed: i.share_of_failed,
      risk_inr_base: i.risk_inr.base,
    });
  }
  for (const list of Object.values(out)) list.sort((a, b) => b.sessions_blocked - a.sessions_blocked);
  return out;
}

export const windowOf = (from: string, to: string) => ({ from, to, days: daysBetween(from, to) });

export function previousWindow(w: Win): Win {
  const days = daysBetween(w.from, w.to);
  return { from: addDays(w.from, -days), to: addDays(w.from, -1) };
}

export const blockerName = (id: BlockerId): string => BLOCKER_BY_ID[id].name;
