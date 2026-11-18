import { addDays, daysBetween, filterSessions, parseFilters, slug } from "../filters";
import { twoProportionZTest } from "../stats";
import { validateSettings } from "../settings-validation";
import type {
  AgentClass, AgentDetail, AgentList, AgentRow, Annotation, BlockerDetail, BlockerId, BlockerItem, BlockerList,
  ClassMixItem, Compare, CrawlerRow, Filters, Funnel, Health, Meta, OperatorMixItem, Overview, OverviewKpis,
  Recommendation, Run, Segment, Settings, SessionQuery, SignatureStatus, SiteCheck, SuggestedWindow, TierMix,
  WindowSummary,
} from "../types";
import { BLOCKER_BY_ID, CRAWLERS, OPERATORS, STAGES, UNITS } from "./catalog";
import {
  CHANGE_DAY, DAYS, DEFAULT_SETTINGS, FIRST_DAY, LAST_DAY, aggregateAgents, blockerTrend, computeImpact, dailyStats,
  failedSessions, funnelSeries, humanAgg, previousWindow, stageBlockers, windowOf, type UnitAgg, type Win,
} from "./engine";
import { distribute } from "./prng";
import { EVAL_RESULT, LAST_RUN, SEED_ANNOTATIONS, siteChecks } from "./misc";
import { REPLAY_ROWS, replayDetail, replayStatusFor } from "./replays";
import { SESSIONS, sampleSessionsFor, sessionDetail } from "./sessions";
import { reportMarkdown } from "./report";

export interface MockResponse {
  status: number;
  data: unknown;
}
export type Query = Record<string, string | undefined>;

const BOUNDS = { min: FIRST_DAY, max: LAST_DAY };
const AGENT_CLASSES: AgentClass[] = ["user_fetcher", "browsing_agent", "search_crawler", "training_crawler"];
const SEGMENTS: Segment[] = ["all_agents", "verified", "declared", "suspected", "humans"];
const RUN_MS = 4200;

// ---------------------------------------------------------------- state
interface RunRecord {
  run_id: string;
  kind: "pipeline" | "replay";
  startedMs: number;
}
interface State {
  annotations: Annotation[];
  fixed: Record<string, string>;
  settings: Settings;
  runs: RunRecord[];
  seq: number;
}

const STORAGE_KEY = "agentlens-mock-state-v1";
const fresh = (): State => ({
  annotations: structuredClone(SEED_ANNOTATIONS),
  fixed: {},
  settings: structuredClone(DEFAULT_SETTINGS),
  runs: [],
  seq: 1,
});
let state: State | null = null;

function st(): State {
  if (!state) {
    state = fresh();
    if (typeof window !== "undefined") {
      try {
        const raw = window.sessionStorage.getItem(STORAGE_KEY);
        if (raw) state = { ...state, ...(JSON.parse(raw) as Partial<State>) };
      } catch {
        /* ignore corrupt storage */
      }
    }
  }
  return state;
}
function persist() {
  if (typeof window === "undefined" || !state) return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* storage full or disabled */
  }
}
export function resetMockState() {
  state = fresh();
  persist();
}

const ok = (data: unknown, status = 200): MockResponse => ({ status, data });
const fail = (status: number, code: string, message: string, fields?: Record<string, string>): MockResponse => ({
  status,
  data: { error: { code, message, ...(fields ? { fields } : {}) } },
});

// ---------------------------------------------------------------- helpers
function resolveWindow(f: Filters): Win & { days: number } {
  let from = f.from && f.from >= FIRST_DAY ? f.from : FIRST_DAY;
  let to = f.to && f.to <= LAST_DAY ? f.to : LAST_DAY;
  if (from > to) [from, to] = [to, from];
  return windowOf(from, to);
}

const tierOf = (agg: UnitAgg & { byUnit?: Record<string, UnitAgg> }) => {
  const t = { verified: 0, declared: 0, suspected: 0 };
  for (const [id, u] of Object.entries(agg.byUnit ?? {})) t[UNITS.find((x) => x.id === id)!.tier] += u.sessions;
  return t;
};

function kpisFor(w: Win & { days: number }, f: Filters, impact: ReturnType<typeof computeImpact>): OverviewKpis {
  const agg = aggregateAgents(w, f);
  const allAgents = aggregateAgents(w, {});
  const human = humanAgg(w);
  const tiers = tierOf(agg);
  const risk = impact.items.reduce(
    (a, i) => ({ low: a.low + i.risk_inr.low, base: a.base + i.risk_inr.base, high: a.high + i.risk_inr.high }),
    { low: 0, base: 0, high: 0 },
  );
  const monthlyRevenue = agg.revenue * impact.k;
  return {
    agent_sessions: agg.sessions,
    total_sessions: human.sessions + allAgents.sessions,
    agent_share: human.sessions + allAgents.sessions ? agg.sessions / (human.sessions + allAgents.sessions) : 0,
    agent_converted: agg.converted,
    agent_conversion: agg.sessions ? agg.converted / agg.sessions : 0,
    human_sessions: human.sessions,
    human_conversion: human.sessions ? human.converted / human.sessions : 0,
    agent_revenue_inr: agg.revenue,
    risk_inr: risk,
    risk_pct_of_agent_revenue: monthlyRevenue ? risk.base / monthlyRevenue : 0,
    identity_coverage: agg.sessions ? (tiers.verified + tiers.declared) / agg.sessions : 0,
    verified_share: agg.sessions ? tiers.verified / agg.sessions : 0,
    diagnosis_coverage: impact.diagnosisCoverage,
  };
}

const impactFor = (w: Win & { days: number }, f: Filters) =>
  computeImpact(aggregateAgents(w, f), w.days, st().settings.impact, replayStatusFor);

function recommendationFor(item: BlockerItem | undefined, id: BlockerId, runId: string): Recommendation {
  const def = BLOCKER_BY_ID[id];
  const annotation = st().fixed[id];
  return {
    rec_id: `rec_${id}`,
    run_id: runId,
    blocker_id: id,
    blocker_name: def.name,
    title: def.rec.title,
    body: def.rec.body,
    why_it_helps: def.rec.why,
    how_to_verify: def.rec.verify,
    verify_metric: def.rec.verifyMetric,
    effort: def.effort,
    owner: def.owner,
    priority_score: item?.priority_score ?? 0,
    risk_inr_base: item?.risk_inr.base ?? 0,
    status: annotation ? "fixed" : "open",
    fixed_annotation_id: annotation ?? null,
    llm_explanation: null,
  };
}

function recommendations(w: Win & { days: number }, f: Filters): Recommendation[] {
  const { items } = impactFor(w, f);
  return items
    .filter((i) => i.blocker_id !== "B99")
    .map((i) => recommendationFor(i, i.blocker_id, LAST_RUN.run_id))
    .sort((a, b) => b.priority_score - a.priority_score);
}

const phaseOfWindow = (w: Win): "before" | "after" => (w.to < CHANGE_DAY ? "before" : "after");
const lastSeen = (day: string) => `${day}T18:42:00Z`;

// ---------------------------------------------------------------- endpoints
function meta(): Meta {
  return {
    version: "0.1.0",
    demo_mode: false,
    store_name: "Demo Store (synthetic)",
    currency: "INR",
    operators: OPERATORS,
    agent_classes: AGENT_CLASSES,
    segments: SEGMENTS,
    date_bounds: BOUNDS,
    default_window: { from: FIRST_DAY, to: LAST_DAY },
    last_run: currentRun(st().runs[st().runs.length - 1]) ?? LAST_RUN,
  };
}

function overview(f: Filters): Overview {
  const w = resolveWindow(f);
  const impact = impactFor(w, f);
  const kpis = kpisFor(w, f, impact);
  const prev = previousWindow(w);
  const deltas: Overview["kpi_deltas"] = {};
  if (prev.from >= FIRST_DAY) {
    const pw = { ...prev, days: w.days };
    const pk = kpisFor(pw, f, impactFor(pw, f));
    for (const key of Object.keys(kpis) as (keyof OverviewKpis)[]) {
      const a = kpis[key];
      const b = pk[key];
      if (typeof a === "number" && typeof b === "number") deltas[key] = b ? a / b - 1 : null;
      else if (key === "risk_inr") deltas[key] = pk.risk_inr.base ? kpis.risk_inr.base / pk.risk_inr.base - 1 : null;
    }
  } else {
    for (const key of Object.keys(kpis) as (keyof OverviewKpis)[]) deltas[key] = null;
  }

  const agg = aggregateAgents(w, f);
  const timeseries = dailyStats(w, f).map((d) => ({
    date: d.date,
    human: d.human,
    verified: d.verified,
    declared: d.declared,
    suspected: d.suspected,
    agent_conversion: d.agentSessions ? d.agentConverted / d.agentSessions : 0,
    human_conversion: d.human ? d.humanConverted / d.human : 0,
  }));

  const byOp = new Map<string, { sessions: number; tiers: TierMix }>();
  const byClass = new Map<AgentClass, number>();
  for (const [uid, u] of Object.entries(agg.byUnit)) {
    const def = UNITS.find((x) => x.id === uid)!;
    const o = byOp.get(def.operator) ?? { sessions: 0, tiers: { verified: 0, declared: 0, suspected: 0 } };
    o.sessions += u.sessions;
    o.tiers[def.tier] += u.sessions;
    byOp.set(def.operator, o);
    byClass.set(def.agent_class, (byClass.get(def.agent_class) ?? 0) + u.sessions);
  }
  const total = agg.sessions || 1;
  const mix = (n: number, t: TierMix): TierMix => ({ verified: t.verified / (n || 1), declared: t.declared / (n || 1), suspected: t.suspected / (n || 1) });
  const operator_mix: OperatorMixItem[] = [...byOp.entries()]
    .map(([operator, o]) => ({ operator, sessions: o.sessions, share: o.sessions / total, tier_mix: mix(o.sessions, o.tiers) }))
    .sort((a, b) => b.sessions - a.sessions);
  const class_mix: ClassMixItem[] = [...byClass.entries()]
    .map(([agent_class, sessions]) => ({ agent_class, sessions, share: sessions / total }))
    .sort((a, b) => b.sessions - a.sessions);

  const top_fixes = recommendations(w, f)
    .slice(0, 3)
    .map((r) => ({
      rec_id: r.rec_id, blocker_id: r.blocker_id, blocker_name: r.blocker_name, title: r.title,
      risk_inr_base: r.risk_inr_base, effort: r.effort, priority_score: r.priority_score, owner: r.owner, status: r.status,
    }));

  return {
    window: w, kpis, kpi_deltas: deltas, timeseries,
    annotations: st().annotations.filter((a) => a.ts.slice(0, 10) >= w.from && a.ts.slice(0, 10) <= w.to),
    operator_mix, class_mix, top_fixes,
  };
}

const SIG_MIX: Record<string, Record<SignatureStatus, number>> = {
  verified: { valid: 0.93, invalid_sig: 0, expired: 0.03, unknown_key: 0.02, fetch_failed: 0.02, none: 0 },
  declared: { valid: 0, invalid_sig: 0.03, expired: 0.04, unknown_key: 0, fetch_failed: 0, none: 0.93 },
  suspected: { valid: 0, invalid_sig: 0.08, expired: 0, unknown_key: 0, fetch_failed: 0, none: 0.92 },
};

function agentRows(w: Win & { days: number }, f: Filters): AgentRow[] {
  const agg = aggregateAgents(w, f);
  const groups = new Map<string, { operator: string; name: string; cls: AgentClass; units: string[] }>();
  for (const uid of Object.keys(agg.byUnit)) {
    const u = UNITS.find((x) => x.id === uid)!;
    const key = `${u.operator}/${u.agent_name}`;
    const g = groups.get(key) ?? { operator: u.operator, name: u.agent_name, cls: u.agent_class, units: [] };
    g.units.push(uid);
    groups.set(key, g);
  }
  const rows: AgentRow[] = [];
  for (const g of groups.values()) {
    const sum: UnitAgg = { sessions: 0, converted: 0, revenue: 0, pages: 0, blocked: {} };
    const tiers = { verified: 0, declared: 0, suspected: 0 };
    const sig: Record<SignatureStatus, number> = { valid: 0, invalid_sig: 0, expired: 0, unknown_key: 0, fetch_failed: 0, none: 0 };
    for (const uid of g.units) {
      const u = agg.byUnit[uid];
      const def = UNITS.find((x) => x.id === uid)!;
      sum.sessions += u.sessions; sum.converted += u.converted; sum.pages += u.pages;
      for (const [b, n] of Object.entries(u.blocked)) sum.blocked[b as BlockerId] = (sum.blocked[b as BlockerId] ?? 0) + (n ?? 0);
      tiers[def.tier] += u.sessions;
      const mixKeys = Object.keys(sig) as SignatureStatus[];
      distribute(u.sessions, mixKeys.map((k) => SIG_MIX[def.tier][k])).forEach((n, i) => (sig[mixKeys[i]] += n));
    }
    const failed = failedSessions(sum);
    const top = (Object.entries(sum.blocked) as [BlockerId, number][]).sort((a, b) => b[1] - a[1])[0];
    rows.push({
      operator: g.operator,
      agent_name: g.name,
      agent_class: g.cls,
      sessions: sum.sessions,
      share_of_agent_sessions: agg.sessions ? sum.sessions / agg.sessions : 0,
      pages_per_session: sum.sessions ? sum.pages / sum.sessions : 0,
      conversion: sum.sessions ? sum.converted / sum.sessions : 0,
      tier_mix: { verified: tiers.verified / sum.sessions, declared: tiers.declared / sum.sessions, suspected: tiers.suspected / sum.sessions },
      top_blocker: top && failed ? { blocker_id: top[0], name: BLOCKER_BY_ID[top[0]].name, share_of_failed: top[1] / failed } : null,
      signature_status_counts: sig,
      last_seen: lastSeen(w.to),
    });
  }
  return rows.sort((a, b) => b.sessions - a.sessions);
}

function crawlers(w: Win & { days: number }, f: Filters): CrawlerRow[] {
  if (f.segment && f.segment !== "all_agents") return [];
  if (f.agent_class && f.agent_class !== "search_crawler" && f.agent_class !== "training_crawler") return [];
  return CRAWLERS.filter((c) => (!f.operator || c.operator === f.operator) && (!f.agent_class || c.agent_class === f.agent_class))
    .map((c) => {
      const requests = Math.round((c.requests * w.days) / DAYS.length);
      return {
        operator: c.operator, agent_name: c.agent_name, agent_class: c.agent_class, requests,
        pages: Math.round(requests * c.pagesPerReq), robots_txt_fetched: c.robots, last_seen: lastSeen(w.to),
      };
    });
}

function agents(f: Filters): AgentList {
  const w = resolveWindow(f);
  return { window: w, items: agentRows(w, f), crawlers: crawlers(w, f) };
}

function agentDetail(operator: string, name: string, f: Filters): MockResponse {
  const w = resolveWindow(f);
  const row = agentRows(w, f).find((r) => slug(r.operator) === slug(operator) && slug(r.agent_name) === slug(name));
  const units = UNITS.filter((u) => slug(u.operator) === slug(operator) && slug(u.agent_name) === slug(name));
  if (!units.length) return fail(404, "not_found", `Agent ${operator}/${name} not found`);
  const first = units[0];
  const agg = aggregateAgents(w, { ...f, operator: first.operator });
  const mine = units.filter((u) => agg.byUnit[u.id]);
  const failed = mine.reduce((a, u) => a + failedSessions(agg.byUnit[u.id]), 0);
  const blocked: Partial<Record<BlockerId, number>> = {};
  for (const u of mine) for (const [b, n] of Object.entries(agg.byUnit[u.id].blocked)) blocked[b as BlockerId] = (blocked[b as BlockerId] ?? 0) + (n ?? 0);
  const trend = dailyStats(w, { ...f, operator: first.operator, segment: "all_agents" }).map((d) => ({ date: d.date, sessions: d.agentSessions, conversion: d.agentSessions ? d.agentConverted / d.agentSessions : 0 }));
  const empty: AgentRow = row ?? {
    operator: first.operator, agent_name: first.agent_name, agent_class: first.agent_class, sessions: 0, share_of_agent_sessions: 0,
    pages_per_session: 0, conversion: 0, tier_mix: { verified: 0, declared: 0, suspected: 0 }, top_blocker: null,
    signature_status_counts: { valid: 0, invalid_sig: 0, expired: 0, unknown_key: 0, fetch_failed: 0, none: 0 }, last_seen: lastSeen(w.to),
  };
  const detail: AgentDetail = {
    window: w,
    agent: empty,
    identity: {
      user_agent_example: first.ua,
      signature_agent: first.signatureAgent,
      ip_match_rate: first.tier === "verified" ? 1 : first.tier === "declared" ? 0.55 : null,
      avg_identity_confidence: first.tier === "verified" ? 0.98 : first.tier === "declared" ? 0.82 : 0.58,
    },
    trend,
    blockers: (Object.entries(blocked) as [BlockerId, number][])
      .sort((a, b) => b[1] - a[1])
      .map(([id, n]) => ({ blocker_id: id, name: BLOCKER_BY_ID[id].name, sessions: n, share_of_failed: failed ? n / failed : 0 })),
    recent_sessions: SESSIONS.filter((s) => slug(s.operator) === slug(operator) && slug(s.agent_name) === slug(name) && s.start_ts.slice(0, 10) >= w.from && s.start_ts.slice(0, 10) <= w.to).slice(0, 8),
  };
  return ok(detail);
}

function funnel(f: Filters, compare: Segment | undefined): Funnel {
  const w = resolveWindow(f);
  const segment = f.segment ?? "all_agents";
  const primary = funnelSeries(segment, w, f);
  const cmp = funnelSeries(compare ?? "humans", w, { ...f, segment: compare ?? "humans" });
  const stage_blockers = stageBlockers(segment === "humans" ? [] : impactFor(w, f).items);
  return { window: w, stages: STAGES, primary, compare: cmp, stage_blockers };
}

function blockers(f: Filters): BlockerList {
  const w = resolveWindow(f);
  const impact = impactFor(w, f);
  const s = st().settings.impact;
  return {
    window: w,
    total_risk_base_inr: impact.totalRiskBase,
    total_failed_agent_sessions: impact.totalFailed,
    diagnosis_coverage: impact.diagnosisCoverage,
    assumptions: {
      recoverable_rate: s.recoverable_rate, p_stage_band: s.p_stage_band, default_aov_inr: s.default_aov_inr,
      window_days: w.days, k: impact.k, min_sample: s.min_sample,
    },
    items: impact.items,
  };
}

const CHECKS_FOR: Partial<Record<BlockerId, string[]>> = {
  B03: ["pdp_ssr_price", "pdp_ssr_stock", "jsonld_product"],
  B04: ["jsonld_product"],
  B09: ["size_guide_format"],
  B14: ["robots_txt"],
};

function blockerDetail(id: string, f: Filters): MockResponse {
  const def = BLOCKER_BY_ID[id as BlockerId];
  if (!def) return fail(404, "not_found", `Unknown blocker ${id}`);
  const w = resolveWindow(f);
  const impact = impactFor(w, f);
  const item: BlockerItem = impact.items.find((i) => i.blocker_id === def.id) ?? {
    blocker_id: def.id, name: def.name, stage: def.stage, sessions_blocked: 0, share_of_failed: 0,
    risk_inr: { low: 0, base: 0, high: 0 }, replay_status: replayStatusFor(def.id), effort: def.effort, priority_score: 0, low_confidence: true,
  };
  const L = item.sessions_blocked;
  const codeCounts = distribute(L, def.errorCodes.map((c) => c[1]));
  const exCounts = distribute(L, def.examples.map(() => 1));
  const s = st().settings.impact;
  const checks: SiteCheck[] = (CHECKS_FOR[def.id] ?? []).length
    ? siteChecks(phaseOfWindow(w)).filter((c) => CHECKS_FOR[def.id]!.includes(c.check_name))
    : [];
  const detail: BlockerDetail = {
    window: w,
    blocker: item,
    description: def.description,
    detection: def.detection,
    evidence: {
      top_error_codes: def.errorCodes.map(([code, share], i) => ({ code, count: codeCounts[i], share })),
      example_requests: def.examples.map((summary, i) => ({ request_id: `req_${def.id}_${i + 1}`, summary, count: exCounts[i] })),
      site_checks: checks,
    },
    risk_breakdown: {
      sessions_blocked: L, recoverable_rate: s.recoverable_rate.base, p_stage: item.risk_inr.base && L ? item.risk_inr.base / (L * s.recoverable_rate.base * impact.aov * impact.k) : 0,
      aov_inr: Math.round(impact.aov), k: impact.k,
    },
    trend: blockerTrend(def.id, w, f),
    sample_sessions: sampleSessionsFor(def.id, w.from, w.to, 6),
    replays: REPLAY_ROWS.filter((r) => r.blocker_id === def.id),
    recommendation: def.id === "B99" ? null : recommendationFor(item, def.id, LAST_RUN.run_id),
  };
  return ok(detail);
}

function sessions(f: Filters, q: Query): MockResponse {
  const w = resolveWindow(f);
  const query: SessionQuery = {
    page: Number(q.page) || 1,
    page_size: Math.min(100, Number(q.page_size) || 25),
    q: q.q,
    identity_tier: q.identity_tier as SessionQuery["identity_tier"],
    blocker_id: q.blocker_id as BlockerId | undefined,
    max_stage: q.max_stage as SessionQuery["max_stage"],
    converted: q.converted === undefined ? undefined : q.converted === "true",
    sort: q.sort as SessionQuery["sort"],
    order: q.order as SessionQuery["order"],
  };
  const res = filterSessions(SESSIONS, { ...f, from: w.from, to: w.to }, query);
  return ok({ window: w, ...res });
}

function compare(q: Query): MockResponse {
  const f = parseFilters((k) => q[k]);
  const segment = f.segment ?? "all_agents";
  const need = ["a_from", "a_to", "b_from", "b_to"];
  const missing = need.filter((k) => !q[k]);
  if (missing.length) return fail(422, "validation_error", "Missing window parameters", Object.fromEntries(missing.map((k) => [k, "required"])));
  const summarize = (from: string, to: string): WindowSummary => {
    const w = resolveWindow({ from, to });
    const ff: Filters = { ...f, from: undefined, to: undefined, segment };
    if (segment === "humans") {
      const h = humanAgg(w);
      return {
        window: w, sessions: h.sessions, converted: h.converted, conversion: h.sessions ? h.converted / h.sessions : 0,
        agent_revenue_inr: 0, risk_inr: { low: 0, base: 0, high: 0 }, funnel: funnelSeries("humans", w, ff), blocker_shares: [],
      };
    }
    const agg = aggregateAgents(w, ff);
    const impact = impactFor(w, ff);
    const risk = impact.items.reduce((a, i) => ({ low: a.low + i.risk_inr.low, base: a.base + i.risk_inr.base, high: a.high + i.risk_inr.high }), { low: 0, base: 0, high: 0 });
    return {
      window: w, sessions: agg.sessions, converted: agg.converted, conversion: agg.sessions ? agg.converted / agg.sessions : 0,
      agent_revenue_inr: agg.revenue, risk_inr: risk, funnel: funnelSeries(segment, w, ff),
      blocker_shares: impact.items.map((i) => ({ blocker_id: i.blocker_id, name: i.name, sessions_blocked: i.sessions_blocked, share_of_failed: i.share_of_failed, risk_base_inr: i.risk_inr.base })),
    };
  };
  const a = summarize(q.a_from!, q.a_to!);
  const b = summarize(q.b_from!, q.b_to!);
  const out: Compare = {
    segment, a, b,
    delta: {
      sessions: b.sessions - a.sessions,
      conversion_pp: (b.conversion - a.conversion) * 100,
      conversion_relative: a.conversion ? b.conversion / a.conversion - 1 : null,
      agent_revenue_inr: b.agent_revenue_inr - a.agent_revenue_inr,
      risk_base_inr: b.risk_inr.base - a.risk_inr.base,
    },
    significance: twoProportionZTest(a.converted, a.sessions, b.converted, b.sessions, st().settings.thresholds.significance_min_sessions),
    suggested_windows: suggestedWindows(),
  };
  return ok(out);
}

export function suggestedWindows(annotations: Pick<Annotation, "annotation_id" | "ts" | "type" | "label">[] = st().annotations): SuggestedWindow[] {
  return annotations
    .filter((a) => a.type !== "note")
    .map((a) => {
      const day = a.ts.slice(0, 10);
      const span = Math.min(7, daysBetween(BOUNDS.min, addDays(day, -1)), daysBetween(day, BOUNDS.max));
      return span >= 1
        ? { label: `Around "${a.label}"`, annotation_id: a.annotation_id, a: { from: addDays(day, -span), to: addDays(day, -1) }, b: { from: day, to: addDays(day, span - 1) } }
        : null;
    })
    .filter((x): x is SuggestedWindow => x !== null);
}

// ---------------------------------------------------------------- runs
const PIPELINE_STEPS = ["ingest", "identify", "sessionize", "funnel", "diagnose", "impact", "recommend"];
const REPLAY_STEPS = ["select_blockers", "launch_agent", "replay_sessions", "verdicts"];

function currentRun(rec: RunRecord | undefined): Run | null {
  if (!rec) return null;
  const names = rec.kind === "pipeline" ? PIPELINE_STEPS : REPLAY_STEPS;
  const elapsed = Date.now() - rec.startedMs;
  const per = RUN_MS / names.length;
  const done = elapsed >= RUN_MS;
  const iso = (ms: number) => new Date(ms).toISOString();
  return {
    run_id: rec.run_id,
    kind: rec.kind,
    status: done ? "succeeded" : "running",
    started_at: iso(rec.startedMs),
    finished_at: done ? iso(rec.startedMs + RUN_MS) : null,
    steps: names.map((name, i) => {
      const s = rec.startedMs + i * per;
      const status = elapsed >= (i + 1) * per ? "succeeded" : elapsed >= i * per ? "running" : "pending";
      return { name, status, started_at: status === "pending" ? null : iso(s), finished_at: status === "succeeded" ? iso(s + per) : null, message: null };
    }),
    counts: done ? { ...LAST_RUN.counts } : {},
    error: null,
  };
}

function startRun(kind: "pipeline" | "replay"): MockResponse {
  const s = st();
  const running = s.runs.map(currentRun).find((r) => r?.status === "running");
  if (running) return fail(409, "run_in_progress", `A ${running.kind} run is already in progress`);
  const run_id = `run_mock_${String(s.seq++).padStart(3, "0")}`;
  s.runs.push({ run_id, kind, startedMs: Date.now() });
  persist();
  return ok({ run_id, status: "running" }, 202);
}

// ---------------------------------------------------------------- router
export function mockRequest(method: string, rawPath: string, q: Query = {}, body?: unknown): MockResponse {
  const path = rawPath.replace(/^\/api/, "").replace(/\/+$/, "") || "/";
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const f = parseFilters((k) => q[k]);
  const m = method.toUpperCase();
  const s = st();

  switch (parts[0]) {
    case "health": {
      const h: Health = { status: "ok", version: "0.1.0", time: new Date().toISOString(), db: "ok", demo_mode: false };
      return ok(h);
    }
    case "meta": return ok(meta());
    case "overview": return ok(overview(f));
    case "agents":
      return parts.length === 3 ? agentDetail(parts[1], parts[2], f) : ok(agents(f));
    case "funnel": return ok(funnel(f, q.compare as Segment | undefined));
    case "blockers": return parts[1] ? blockerDetail(parts[1], f) : ok(blockers(f));
    case "sessions":
      if (parts[1]) {
        const d = sessionDetail(parts[1]);
        return d ? ok(d) : fail(404, "not_found", `Session ${parts[1]} not found`);
      }
      return sessions(f, q);
    case "replays":
      if (parts[1] === "run" && m === "POST") return startRun("replay");
      if (parts[1]) {
        const d = replayDetail(parts[1]);
        return d ? ok(d) : fail(404, "not_found", `Replay ${parts[1]} not found`);
      }
      return ok({ items: REPLAY_ROWS });
    case "compare": return compare(q);
    case "annotations": {
      if (m === "POST") {
        const b = (body ?? {}) as Partial<Annotation>;
        if (!b.label || !b.type) return fail(422, "validation_error", "label and type are required", { label: "required" });
        const a: Annotation = {
          annotation_id: `ann_${String(s.annotations.length + 1).padStart(4, "0")}`,
          ts: b.ts ?? `${LAST_DAY}T12:00:00Z`, type: b.type, label: b.label, details: b.details ?? {},
        };
        s.annotations.push(a);
        persist();
        return ok(a, 201);
      }
      return ok({ items: [...s.annotations].sort((a, b) => a.ts.localeCompare(b.ts)) });
    }
    case "recommendations": {
      const w = resolveWindow(f);
      if (m === "PATCH" && parts[1]) {
        const id = parts[1].replace(/^rec_/, "") as BlockerId;
        if (!BLOCKER_BY_ID[id] || id === "B99") return fail(404, "not_found", `Recommendation ${parts[1]} not found`);
        if ((body as { status?: string } | undefined)?.status !== "fixed") return fail(422, "validation_error", "status must be 'fixed'", { status: "must be 'fixed'" });
        if (!s.fixed[id]) {
          const ann: Annotation = {
            annotation_id: `ann_${String(s.annotations.length + 1).padStart(4, "0")}`,
            ts: `${LAST_DAY}T12:00:00Z`, type: "marked_fixed",
            label: `Marked fixed: ${BLOCKER_BY_ID[id].rec.title}`, details: { blocker_id: id, rec_id: `rec_${id}` },
          };
          s.annotations.push(ann);
          s.fixed[id] = ann.annotation_id;
          persist();
        }
        const item = impactFor(w, f).items.find((i) => i.blocker_id === id);
        return ok({
          recommendation: recommendationFor(item, id, LAST_RUN.run_id),
          annotation: s.annotations.find((a) => a.annotation_id === s.fixed[id]),
        });
      }
      return ok({ items: recommendations(w, f) });
    }
    case "settings": {
      if (m === "PUT") {
        const next = body as Settings;
        const fields = validateSettings(next);
        if (Object.keys(fields).length) return fail(422, "validation_error", "Some settings are invalid", fields);
        s.settings = structuredClone(next);
        persist();
      }
      return ok(s.settings);
    }
    case "report":
      return { status: 200, data: reportMarkdown(overview(f), blockers(f)) };
    case "eval": return ok(EVAL_RESULT);
    case "site-checks": return ok({ items: siteChecks(f.to ? phaseOfWindow({ from: f.from ?? FIRST_DAY, to: f.to }) : "after") });
    case "pipeline":
      return m === "POST" ? startRun("pipeline") : fail(405, "method_not_allowed", "Use POST /pipeline/run");
    case "runs": {
      const rec = s.runs.find((r) => r.run_id === parts[1]);
      if (rec) return ok(currentRun(rec));
      return parts[1] === LAST_RUN.run_id ? ok(LAST_RUN) : fail(404, "not_found", `Run ${parts[1]} not found`);
    }
    default:
      return fail(404, "not_found", `No such endpoint: ${rawPath}`);
  }
}
