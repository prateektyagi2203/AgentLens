"use client";

import Link from "next/link";
import { Suspense, useMemo } from "react";
import { api } from "@/lib/api";
import { addDays, buildPresets, daysBetween, isDay } from "@/lib/filters";
import { formatCount, formatDateRange, formatInr, formatPercent, formatPp } from "@/lib/format";
import { useApi, useFilters, useMeta, useUi, useUrlState } from "@/lib/hooks";
import type { Compare, CompareQuery, WindowSummary } from "@/lib/types";
import { FunnelBars } from "@/components/funnel-bars";
import { BlockerBadge, SEGMENT_LABEL } from "@/components/domain";
import { Async, Badge, Card, EmptyState, Eyebrow, InfoTip, Kpi, PageHeader, SectionTitle, Skeleton, inputClass } from "@/components/ui";
import { cn } from "@/lib/cn";

function useDefaultWindows() {
  const { meta } = useMeta();
  const ann = useApi("annotations", () => api.annotations());
  const { get } = useUrlState();
  return useMemo(() => {
    const b = meta?.date_bounds;
    const fromUrl = { a_from: get("a_from"), a_to: get("a_to"), b_from: get("b_from"), b_to: get("b_to") };
    if (isDay(fromUrl.a_from) && isDay(fromUrl.a_to) && isDay(fromUrl.b_from) && isDay(fromUrl.b_to)) {
      return { ready: true as const, q: { a_from: fromUrl.a_from, a_to: fromUrl.a_to, b_from: fromUrl.b_from, b_to: fromUrl.b_to } };
    }
    if (!b || (ann.loading && !ann.data)) return { ready: false as const, q: null };
    const presets = buildPresets(b, ann.data?.items ?? []);
    const before = presets.find((p) => p.id === "before");
    const after = presets.find((p) => p.id === "after");
    if (before && after) return { ready: true as const, q: { a_from: before.from, a_to: before.to, b_from: after.from, b_to: after.to } };
    const half = Math.floor(daysBetween(b.min, b.max) / 2);
    return { ready: true as const, q: { a_from: b.min, a_to: addDays(b.min, half - 1), b_from: addDays(b.min, half), b_to: b.max } };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta, ann.data, ann.loading, get("a_from"), get("a_to"), get("b_from"), get("b_to")]);
}

function WindowPicker({ label, tone, from, to, onChange, bounds }: { label: string; tone: "human" | "agent"; from: string; to: string; onChange: (f: string, t: string) => void; bounds: { min: string; max: string } | null }) {
  return (
    <Card className="p-4">
      <p className={cn("mb-2 font-mono text-xs uppercase tracking-widest", tone === "agent" ? "text-agent" : "text-human")}>{label}</p>
      <div className="flex flex-wrap items-center gap-2">
        <input type="date" aria-label={`${label} from`} className={cn(inputClass, "w-36 font-mono")} value={from} min={bounds?.min} max={to} onChange={(e) => e.target.value && onChange(e.target.value, to)} />
        <span aria-hidden className="text-muted-foreground">→</span>
        <input type="date" aria-label={`${label} to`} className={cn(inputClass, "w-36 font-mono")} value={to} min={from} max={bounds?.max} onChange={(e) => e.target.value && onChange(from, e.target.value)} />
      </div>
    </Card>
  );
}

function DeltaCard({ label, info, a, b, fmt, goodWhen = "up", testId }: { label: string; info: string; a: number; b: number; fmt: (n: number) => string; goodWhen?: "up" | "down"; testId?: string }) {
  const diff = b - a;
  const good = goodWhen === "up" ? diff >= 0 : diff <= 0;
  return (
    <Card className="p-5" data-testid={testId}>
      <p className="flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-muted-foreground">{label}<InfoTip text={info} /></p>
      <p className="mt-3 font-mono text-3xl font-medium tracking-tight">{fmt(b)}</p>
      <p className="mt-1 text-xs text-muted-foreground">was <span className="font-mono">{fmt(a)}</span></p>
      <p className={cn("mt-2 font-mono text-sm", Math.abs(diff) < 1e-9 ? "text-muted-foreground" : good ? "text-success" : "text-destructive")}>{diff >= 0 ? "▲" : "▼"} {fmt(Math.abs(diff))}</p>
    </Card>
  );
}

function BlockerShares({ a, b }: { a: WindowSummary; b: WindowSummary }) {
  const ids = Array.from(new Set([...a.blocker_shares, ...b.blocker_shares].map((x) => x.blocker_id))).sort();
  const get = (w: WindowSummary, id: string) => w.blocker_shares.find((x) => x.blocker_id === id);
  return (
    <div className="space-y-3" data-testid="blocker-shares">
      {ids.map((id) => {
        const x = get(a, id);
        const y = get(b, id);
        const name = (x ?? y)?.name ?? id;
        return (
          <div key={id} className="grid grid-cols-[minmax(0,12rem)_1fr_7rem] items-center gap-4">
            <span className="flex items-center gap-2 truncate text-sm"><BlockerBadge id={id} />{name}</span>
            <span className="space-y-1">
              <span className="block h-2.5 rounded-sm bg-muted"><span className="block h-full rounded-sm bg-human" style={{ width: `${(x?.share_of_failed ?? 0) * 100}%` }} /></span>
              <span className="block h-2.5 rounded-sm bg-muted"><span className="block h-full rounded-sm bg-agent" style={{ width: `${(y?.share_of_failed ?? 0) * 100}%` }} /></span>
            </span>
            <span className="text-right font-mono text-xs"><span className="block text-human">{formatPercent(x?.share_of_failed ?? 0, 0)}</span><span className={cn("block", (y?.share_of_failed ?? 0) === 0 ? "text-success" : "text-agent")}>{formatPercent(y?.share_of_failed ?? 0, 0)}</span></span>
          </div>
        );
      })}
      <p className="text-xs text-muted-foreground">Top bar: window A (before). Bottom bar: window B (after). Share of failed agent sessions.</p>
    </div>
  );
}

function CompareResult({ c }: { c: Compare }) {
  const { story } = useUi();
  const s = c.significance;
  return (
    <div className="space-y-6" data-testid="compare-result">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <DeltaCard testId="delta-conversion" label="Agent conversion" info="Share of agent sessions that ended in a purchase in each window." a={c.a.conversion} b={c.b.conversion} fmt={(n) => formatPercent(n)} />
        <DeltaCard label="Agent sessions" info="Agent sessions in each window. Windows can have different lengths." a={c.a.sessions} b={c.b.sessions} fmt={formatCount} />
        <DeltaCard label="Agent revenue" info="Order value from converted agent sessions in each window." a={c.a.agent_revenue_inr} b={c.b.agent_revenue_inr} fmt={formatInr} />
        <DeltaCard testId="delta-risk" label="INR at risk / month" info="Base-case monthly revenue at risk from blockers, scaled to 30 days." a={c.a.risk_inr.base} b={c.b.risk_inr.base} fmt={formatInr} goodWhen="down" />
      </div>
      <Card className={cn("p-5", s.enough_data ? (s.significant ? "border-success/50" : "") : "border-warning/50")} data-testid="significance">
        <Eyebrow className="mb-2">Is the change real?</Eyebrow>
        {s.enough_data ? (
          <p>
            Conversion moved by <span className="font-mono font-medium">{formatPp(c.delta.conversion_pp)}</span>
            {s.p_value !== null && <> (two-proportion z-test: z = <span className="font-mono">{s.z?.toFixed(2)}</span>, p = <span className="font-mono">{s.p_value < 0.001 ? "<0.001" : s.p_value.toFixed(3)}</span>)</>}.{" "}
            <Badge tone={s.significant ? "success" : "warning"}>{s.significant ? "Statistically significant" : "Not significant"}</Badge>
          </p>
        ) : (
          <p><Badge tone="warning">Not enough data</Badge> <span className="ml-2">Each window needs at least {formatCount(s.min_sessions)} agent sessions to say anything reliable.</span></p>
        )}
        <p className="mt-2 text-xs text-muted-foreground">{s.note} Before/after comparisons cannot prove the fix caused the change: other things (traffic mix, seasonality) may have moved too.</p>
      </Card>
      <Card className="p-5">
        <SectionTitle eyebrow="Funnel" title="Funnel before vs after" info="Slate bars show window A (before); blue bars show window B (after), for the same segment." />
        <FunnelBars primary={c.b.funnel} compare={c.a.funnel} primaryLabel="Window B (after)" compareLabel="Window A (before)" selected={null} onSelect={() => undefined} />
      </Card>
      <Card className={cn("hide-in-story p-5")}>
        <SectionTitle eyebrow="Blockers" title="Blocker shares" info="Share of failed agent sessions ended by each blocker. A blocker you fixed should drop to zero." />
        <BlockerShares a={c.a} b={c.b} />
      </Card>
      {story && <Kpi label="Change in conversion" value={formatPp(c.delta.conversion_pp)} info="Percentage-point change in agent conversion between the two windows." tone={c.delta.conversion_pp >= 0 ? "success" : "destructive"} />}
    </div>
  );
}

function CompareBody() {
  const { filters, href } = useFilters();
  const { meta } = useMeta();
  const { set } = useUrlState();
  const win = useDefaultWindows();
  const q: CompareQuery | null = win.q ? { ...win.q, segment: filters.segment, operator: filters.operator, agent_class: filters.agent_class } : null;
  const state = useApi(`compare:${JSON.stringify(q)}`, () => (q ? api.compare(q) : Promise.reject(new Error("Windows not ready"))));
  const suggestions = state.data?.suggested_windows ?? [];
  const setA = (f: string, t: string) => set({ a_from: f, a_to: t, b_from: win.q?.b_from, b_to: win.q?.b_to });
  const setB = (f: string, t: string) => set({ b_from: f, b_to: t, a_from: win.q?.a_from, a_to: win.q?.a_to });

  return (
    <>
      <PageHeader eyebrow="Before / After" title="Did the fix work?" description={`Pick two windows around a change. Showing ${SEGMENT_LABEL[filters.segment ?? "all_agents"].toLowerCase()}; use the segment filter above to switch.`} />
      <div className="mb-6 space-y-3">
        <div className="grid gap-3 md:grid-cols-2">
          {win.q && <WindowPicker label="Window A · before" tone="human" from={win.q.a_from} to={win.q.a_to} onChange={setA} bounds={meta?.date_bounds ?? null} />}
          {win.q && <WindowPicker label="Window B · after" tone="agent" from={win.q.b_from} to={win.q.b_to} onChange={setB} bounds={meta?.date_bounds ?? null} />}
        </div>
        {suggestions.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">Suggested from annotations:</span>
            {suggestions.map((s) => (
              <button key={s.annotation_id} type="button" data-testid="suggested-window" className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-accent" onClick={() => set({ a_from: s.a.from, a_to: s.a.to, b_from: s.b.from, b_to: s.b.to })}>
                {s.label} · <span className="font-mono">{formatDateRange(s.a.from, s.a.to)} vs {formatDateRange(s.b.from, s.b.to)}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {!win.ready ? <Skeleton className="h-96" /> : (
        <Async state={state} skeleton={<Skeleton className="h-[36rem]" />} isEmpty={(c) => c.a.sessions + c.b.sessions === 0} empty={<EmptyState hint="No sessions in either window. Run agentlens synth or visit the store." action={<Link href={href("/settings")} className="text-primary hover:underline">Go to pipeline</Link>} />}>
          {(c) => <CompareResult c={c} />}
        </Async>
      )}
    </>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <CompareBody />
    </Suspense>
  );
}
