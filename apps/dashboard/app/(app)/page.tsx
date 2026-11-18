"use client";

import Link from "next/link";
import { Suspense } from "react";
import { api } from "@/lib/api";
import { formatCount, formatInr, formatPercent } from "@/lib/format";
import { useApi, useFilters, useUi } from "@/lib/hooks";
import type { Overview } from "@/lib/types";
import { ClassBar, OperatorDonut, TimeSeriesChart } from "@/components/charts";
import { EffortBadge } from "@/components/domain";
import { Async, Card, EmptyState, Eyebrow, InfoTip, Kpi, PageHeader, SectionTitle, Skeleton, linkButtonClass } from "@/components/ui";

function OverviewSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading overview">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-32" />)}</div>
      <Skeleton className="h-96" />
    </div>
  );
}

function Hero({ o }: { o: Overview }) {
  const k = o.kpis;
  return (
    <Card data-testid="story-hero" className="blueprint-grid mb-8 p-8 md:p-12">
      <Eyebrow className="mb-4">The story in three numbers</Eyebrow>
      <div className="grid gap-8 md:grid-cols-3">
        <div>
          <p className="font-mono text-5xl font-medium tracking-tight text-agent">{formatPercent(k.agent_conversion)}</p>
          <p className="mt-2 text-muted-foreground">of AI agent sessions end in a purchase, against {formatPercent(k.human_conversion)} for human shoppers.</p>
        </div>
        <div>
          <p className="font-mono text-5xl font-medium tracking-tight text-destructive">{formatInr(k.risk_inr.base)}</p>
          <p className="mt-2 text-muted-foreground">of monthly revenue is blocked by fixable store problems (range {formatInr(k.risk_inr.low)} to {formatInr(k.risk_inr.high)}).</p>
        </div>
        <div>
          <p className="font-mono text-5xl font-medium tracking-tight">{formatPercent(k.agent_share)}</p>
          <p className="mt-2 text-muted-foreground">of all store sessions now come from AI agents.</p>
        </div>
      </div>
    </Card>
  );
}

function TopFixes({ o }: { o: Overview }) {
  const { href } = useFilters();
  return (
    <Card className="p-5" data-testid="top-fixes">
      <SectionTitle eyebrow="Do this first" title="Top 3 fixes" info="Ranked by priority: revenue at risk divided by effort. Each fix links to the evidence and a replay that reproduces it." />
      {o.top_fixes.length === 0 ? (
        <p className="text-sm text-muted-foreground">No blockers found in this window.</p>
      ) : (
        <ol className="space-y-3">
          {o.top_fixes.map((f, i) => (
            <li key={f.rec_id}>
              <Link href={href("/blockers", { id: f.blocker_id })} className="flex items-start gap-4 rounded-lg border border-border p-4 transition hover:bg-accent">
                <span className="font-mono text-2xl font-medium text-primary">{i + 1}</span>
                <span className="min-w-0 flex-1">
                  <span className="block font-medium">{f.title}</span>
                  <span className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-mono">{f.blocker_id}</span>·<span>{f.blocker_name}</span>·<EffortBadge effort={f.effort} />
                    {f.status === "fixed" && <span className="font-medium text-success">Fixed</span>}
                  </span>
                </span>
                <span className="text-right">
                  <span className="block font-mono text-lg font-medium text-destructive">{formatInr(f.risk_inr_base)}</span>
                  <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">per month</span>
                </span>
              </Link>
            </li>
          ))}
        </ol>
      )}
      <Link href={href("/blockers")} className={`${linkButtonClass("secondary")} mt-4`}>
        See all blockers
      </Link>
    </Card>
  );
}

function OverviewBody() {
  const { filters, key } = useFilters();
  const { story } = useUi();
  const state = useApi(`overview:${key}`, () => api.overview(filters));
  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="How AI agents shop your store"
        description="Who is visiting, whether they can buy, and what it costs when they cannot."
        actions={<Link href="/blockers" className={linkButtonClass("primary")}>View blockers</Link>}
      />
      <Async
        state={state}
        skeleton={<OverviewSkeleton />}
        isEmpty={(o) => o.kpis.total_sessions === 0}
        empty={<EmptyState title="No data yet" hint="Run agentlens synth or visit the store, then run the pipeline from Settings & Report." action={<Link href="/settings" className={linkButtonClass("primary")}>Go to pipeline</Link>} />}
      >
        {(o) => {
          const k = o.kpis;
          const d = o.kpi_deltas;
          return (
            <div className="space-y-8">
              {story && <Hero o={o} />}
              <section aria-label="Key numbers" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                <Kpi testId="kpi-agent-sessions" label="Agent sessions" value={formatCount(k.agent_sessions)} delta={d.agent_sessions} info="A session is one visit by one visitor. Agent sessions are visits by AI shopping agents, identified from signatures, user agents and behaviour." hint={`${formatPercent(k.agent_share)} of ${formatCount(k.total_sessions)} total sessions`} />
                <Kpi testId="kpi-agent-conversion" label="Agent conversion" tone="agent" value={formatPercent(k.agent_conversion)} delta={d.agent_conversion} info="Share of agent sessions that ended in a paid order. This is the number to move." hint={<>vs <span className="font-mono text-human">{formatPercent(k.human_conversion)}</span> for humans</>} />
                <Kpi testId="kpi-risk" label="Revenue at risk / month" tone="destructive" value={formatInr(k.risk_inr.base)} delta={d.risk_inr} goodWhen="down" info="Estimated monthly revenue lost because agents were stopped by fixable blockers. Base case shown; the range uses the low and high assumptions from Settings. It is an estimate, not an accounting figure." hint={`Range ${formatInr(k.risk_inr.low)} to ${formatInr(k.risk_inr.high)} · ${formatPercent(k.risk_pct_of_agent_revenue, 0)}                 of monthly agent revenue`} />
                <Kpi testId="kpi-revenue" label="Agent revenue" value={formatInr(k.agent_revenue_inr)} delta={d.agent_revenue_inr} info="Order value from sessions identified as agents that converted, in the selected window." hint={`${formatCount(k.agent_converted)} orders`} />
                <Kpi testId="kpi-identity" label="Identity coverage" value={formatPercent(k.identity_coverage, 0)} delta={d.identity_coverage} info="Share of agent sessions whose operator we could attribute (Verified or Declared). The rest are Suspected from behaviour only. Agents that hide their identity are not fully visible to any analytics tool." hint={`${formatPercent(k.verified_share, 0)} cryptographically verified`} />
                <Kpi testId="kpi-diagnosis" label="Diagnosis coverage" value={formatPercent(k.diagnosis_coverage, 0)} delta={d.diagnosis_coverage} info="Share of failed agent sessions where a specific blocker was identified. The remainder is grouped as Unknown (B99)." hint="of failed agent sessions explained" />
              </section>
              <TimeSeriesChart points={o.timeseries} annotations={o.annotations} />
              <section className="grid gap-6 lg:grid-cols-2">
                <OperatorDonut items={o.operator_mix} />
                <ClassBar items={o.class_mix} />
              </section>
              <TopFixes o={o} />
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                Numbers are estimates from observed traffic. <InfoTip text="Identity and revenue-at-risk figures depend on assumptions you can edit under Settings & Report." />
              </p>
            </div>
          );
        }}
      </Async>
    </>
  );
}

export default function OverviewPage() {
  return (
    <Suspense fallback={<OverviewSkeleton />}>
      <OverviewBody />
    </Suspense>
  );
}
