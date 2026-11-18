"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Suspense, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { api, ApiError } from "@/lib/api";
import { CAN_WRITE } from "@/lib/data-source";
import { formatCount, formatDateTime, formatDuration, formatInr, formatInrFull, formatPercent } from "@/lib/format";
import { useApi, useFilters, useMeta, useUi, useUrlState } from "@/lib/hooks";
import type { BlockerDetail, BlockerId, BlockerItem, BlockerList, SessionRow } from "@/lib/types";
import { MiniTrend } from "@/components/charts";
import { DataTable } from "@/components/data-table";
import { BlockerBadge, EffortBadge, ReplayBadge, StageChip, TierBadge } from "@/components/domain";
import { ReplayCarousel } from "@/components/replay-carousel";
import { Async, Badge, Button, Card, EmptyState, Eyebrow, InfoTip, Kpi, PageHeader, SectionTitle, Skeleton, linkButtonClass } from "@/components/ui";

// ------------------------------------------------------------------ list
function RiskCell({ b }: { b: BlockerItem }) {
  return (
    <div className="font-mono">
      <span className="block text-base font-medium text-destructive">{formatInr(b.risk_inr.base)}</span>
      <span className="block text-xs text-muted-foreground">{formatInr(b.risk_inr.low)} – {formatInr(b.risk_inr.high)}</span>
    </div>
  );
}

function BlockerListView() {
  const { filters, key, href } = useFilters();
  const router = useRouter();
  const { story } = useUi();
  const state = useApi(`blockers:${key}`, () => api.blockers(filters));

  const columns: ColumnDef<BlockerItem>[] = [
    { id: "rank", header: "#", enableSorting: false, cell: ({ row }) => <span className="font-mono text-muted-foreground">{row.index + 1}</span> },
    {
      id: "blocker",
      header: "Blocker",
      accessorFn: (b) => b.name,
      cell: ({ row }) => (
        <div className="flex items-center gap-3">
          <BlockerBadge id={row.original.blocker_id} />
          <div>
            <p className="font-medium">{row.original.name}</p>
            {row.original.low_confidence && <p className="text-xs text-warning">Low sample size: treat as indicative</p>}
          </div>
        </div>
      ),
    },
    { id: "stage", header: "Stage", accessorFn: (b) => b.stage, cell: ({ row }) => <StageChip stage={row.original.stage} /> },
    { id: "sessions", header: "Sessions", accessorFn: (b) => b.sessions_blocked, cell: ({ row }) => <span className="font-mono">{formatCount(row.original.sessions_blocked)}</span> },
    { id: "share", header: "% of failed", accessorFn: (b) => b.share_of_failed, cell: ({ row }) => <span className="font-mono">{formatPercent(row.original.share_of_failed)}</span> },
    { id: "risk", header: "INR at risk / mo", accessorFn: (b) => b.risk_inr.base, cell: ({ row }) => <RiskCell b={row.original} /> },
    { id: "replay", header: "Replay", accessorFn: (b) => b.replay_status, cell: ({ row }) => <ReplayBadge status={row.original.replay_status} /> },
    { id: "effort", header: "Effort", accessorFn: (b) => b.effort, cell: ({ row }) => <EffortBadge effort={row.original.effort} /> },
    { id: "priority", header: "Priority (₹ / effort)", accessorFn: (b) => b.priority_score, cell: ({ row }) => <span className="font-mono">{formatInr(row.original.priority_score)}</span> },
  ];

  const open = (id: BlockerId) => router.push(href("/blockers", { id }));

  return (
    <>
      <PageHeader eyebrow="Blockers" title="What is costing you agent sales" description="Every problem that ended an agent's shopping session, ranked by revenue at risk. Start at the top." />
      <Async
        state={state}
        skeleton={<Skeleton className="h-96" />}
        isEmpty={(l: BlockerList) => l.items.length === 0}
        empty={<EmptyState title="No blockers found" hint="No failed agent sessions in this window, or no data yet. Run agentlens synth or visit the store." />}
      >
        {(l) => (
          <div className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-3">
              <Kpi testId="blockers-total-risk" label="Total at risk / month" tone="destructive" value={formatInr(l.total_risk_base_inr)} info="Sum of the base-case monthly revenue at risk across all blockers below. The ranges per blocker come from the assumptions in Settings." />
              <Kpi label="Failed agent sessions" value={formatCount(l.total_failed_agent_sessions)} info="Agent sessions that did not end in an order." />
              <Kpi label="Diagnosis coverage" value={formatPercent(l.diagnosis_coverage, 0)} info="Share of failed agent sessions where we could name the blocker. The rest are grouped as Unknown (B99)." />
            </div>
            {story && (
              <div className="grid gap-4 md:grid-cols-3" data-testid="story-blockers">
                {l.items.filter((b) => b.risk_inr.base > 0).slice(0, 3).map((b) => (
                  <Link key={b.blocker_id} href={href("/blockers", { id: b.blocker_id })} className="block">
                    <Card className="blueprint-grid p-8 transition hover:border-primary">
                      <Eyebrow className="mb-3">{b.blocker_id} · {b.stage}</Eyebrow>
                      <p className="font-display text-xl font-bold tracking-tight">{b.name}</p>
                      <p className="mt-4 font-mono text-4xl font-medium text-destructive">{formatInr(b.risk_inr.base)}</p>
                      <p className="mt-1 text-sm text-muted-foreground">{formatPercent(b.share_of_failed, 0)} of failed agent sessions</p>
                    </Card>
                  </Link>
                ))}
              </div>
            )}
            <div className="hide-in-story space-y-3">
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                Ranked by revenue at risk (base case, low to high range underneath). Open a row for evidence and the fix.
                <InfoTip text={`Risk = blocked sessions × recoverable rate × stage probability × average order value, scaled to 30 days. Low, base and high use the assumption range (recoverable ${formatPercent(l.assumptions.recoverable_rate.low, 0)} to ${formatPercent(l.assumptions.recoverable_rate.high, 0)}, average order ${formatInrFull(l.assumptions.default_aov_inr)} when no orders exist). Blockers with fewer than ${l.assumptions.min_sample} sessions are greyed out.`} />
              </p>
              <div data-testid="blockers-table">
                <DataTable
                  caption="Blockers ranked by revenue at risk"
                  data={l.items}
                  columns={columns}
                  getRowId={(b) => b.blocker_id}
                  onRowClick={(b) => open(b.blocker_id)}
                  rowClassName={(b) => (b.low_confidence || b.risk_inr.base === 0 ? "opacity-55" : undefined)}
                />
              </div>
            </div>
          </div>
        )}
      </Async>
    </>
  );
}

// ------------------------------------------------------------------ detail
const sessionColumns: ColumnDef<SessionRow>[] = [
  { id: "id", header: "Session", accessorFn: (s) => s.session_id, cell: ({ row }) => <span className="font-mono text-xs">{row.original.session_id}</span> },
  { id: "agent", header: "Agent", accessorFn: (s) => s.agent_name, cell: ({ row }) => <span>{row.original.agent_name}</span> },
  { id: "tier", header: "Identity", accessorFn: (s) => s.identity_tier, cell: ({ row }) => <TierBadge tier={row.original.identity_tier} /> },
  { id: "when", header: "Started", accessorFn: (s) => s.start_ts, cell: ({ row }) => <span className="font-mono text-xs">{formatDateTime(row.original.start_ts)}</span> },
  { id: "dur", header: "Duration", accessorFn: (s) => s.duration_s, cell: ({ row }) => <span className="font-mono text-xs">{formatDuration(row.original.duration_s)}</span> },
];

function ReplayShots({ d }: { d: BlockerDetail }) {
  const best = d.replays.find((r) => r.mode === "browser") ?? d.replays[0];
  const state = useApi(`replay:${best?.replay_id ?? "none"}`, () => (best ? api.replay(best.replay_id) : Promise.reject(new Error("none"))));
  if (!best) return <p className="text-sm text-muted-foreground">No replay has been run for this blocker yet. Start one from Settings &amp; Report.</p>;
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
        <ReplayBadge status={best.verdict ?? "pending"} />
        <span className="text-muted-foreground">{best.verdict_explanation}</span>
      </div>
      <Async state={state} skeleton={<Skeleton className="h-64" />}>{(r) => <ReplayCarousel steps={r.steps} title={`Replay of ${d.blocker.name}`} />}</Async>
      <Link href={`/replays?id=${best.replay_id}`} className="mt-3 inline-block text-sm text-primary hover:underline">Open full replay →</Link>
    </div>
  );
}

function BlockerDetailView({ id }: { id: BlockerId }) {
  const { filters, key, href } = useFilters();
  const router = useRouter();
  const { reload: reloadMeta } = useMeta();
  const state = useApi(`blocker:${id}:${key}`, () => api.blocker(id, filters));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "success" | "destructive"; text: string } | null>(null);

  const markFixed = async (recId: string) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.markFixed(recId);
      setMsg({ tone: "success", text: `Marked as fixed. Annotation "${r.annotation.label}" added to the timeline; compare before and after on the Before / After page.` });
      state.reload();
      reloadMeta();
    } catch (e) {
      setMsg({ tone: "destructive", text: e instanceof ApiError || e instanceof Error ? e.message : "Could not mark as fixed" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Link href={href("/blockers")} className="mb-6 inline-block text-sm text-primary hover:underline" data-testid="back-to-blockers">← All blockers</Link>
      <Async state={state} skeleton={<Skeleton className="h-[40rem]" />}>
        {(d) => {
          const b = d.blocker;
          const rec = d.recommendation;
          const rb = d.risk_breakdown;
          return (
            <div className="space-y-6" data-testid="blocker-detail">
              <PageHeader
                eyebrow={`${b.blocker_id} · Stage ${b.stage}`}
                title={b.name}
                description={d.description}
                actions={<><ReplayBadge status={b.replay_status} /><EffortBadge effort={b.effort} /></>}
              />
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <Kpi label="Revenue at risk / month" tone="destructive" value={formatInr(b.risk_inr.base)} hint={`Range ${formatInr(b.risk_inr.low)} – ${formatInr(b.risk_inr.high)}`} info="Estimated monthly revenue lost to this blocker. Base case with the low–high range from the assumptions in Settings." />
                <Kpi label="Sessions blocked" value={formatCount(b.sessions_blocked)} info="Agent sessions whose diagnosed terminal blocker is this one." />
                <Kpi label="Share of failed sessions" value={formatPercent(b.share_of_failed)} info="Share of all failed agent sessions in this window that ended here." />
                <Kpi label="Priority score" value={formatInr(b.priority_score)} info="Revenue at risk divided by effort weight (S=1, M=2, L=4). Higher means fix sooner." />
              </div>

              <div className="grid gap-6 lg:grid-cols-5">
                <Card className="p-5 lg:col-span-3">
                  <SectionTitle eyebrow="Evidence" title="How we know" />
                  <p className="mb-4 text-sm text-muted-foreground">{d.detection}</p>
                  {d.evidence.top_error_codes.length > 0 && (
                    <div className="mb-4 flex flex-wrap gap-2">
                      {d.evidence.top_error_codes.map((e) => <Badge key={e.code} tone="destructive">{e.code} · {formatCount(e.count)}</Badge>)}
                    </div>
                  )}
                  <h3 className="mb-2 font-mono text-xs uppercase tracking-widest text-muted-foreground">Example requests</h3>
                  {d.evidence.example_requests.length === 0 ? <p className="text-sm text-muted-foreground">No example requests recorded.</p> : (
                    <ul className="space-y-1.5 rounded-md bg-muted p-3 font-mono text-xs">
                      {d.evidence.example_requests.map((r) => <li key={r.request_id} className="flex justify-between gap-3"><span className="min-w-0 break-all">{r.summary}</span><span className="text-muted-foreground">×{formatCount(r.count)}</span></li>)}
                    </ul>
                  )}
                  {d.evidence.site_checks.length > 0 && (
                    <>
                      <h3 className="mb-2 mt-4 font-mono text-xs uppercase tracking-widest text-muted-foreground">Site checks</h3>
                      <ul className="space-y-1 text-sm">
                        {d.evidence.site_checks.map((c) => (
                          <li key={c.check_id} className="flex items-center gap-2"><Badge tone={c.result === "pass" ? "success" : c.result === "warn" ? "warning" : "destructive"}>{c.result}</Badge>{c.check_name} <span className="font-mono text-xs text-muted-foreground">{c.target}</span></li>
                        ))}
                      </ul>
                    </>
                  )}
                </Card>
                <Card className="p-5 lg:col-span-2">
                  <SectionTitle eyebrow="Impact maths" title="How the number is built" info="All inputs are visible so you can disagree with them. Edit the assumptions under Settings & Report." />
                  <dl className="space-y-2 font-mono text-sm">
                    {[
                      ["Sessions blocked", formatCount(rb.sessions_blocked)],
                      ["× Recoverable rate", formatPercent(rb.recoverable_rate, 0)],
                      ["× Stage probability", formatPercent(rb.p_stage, 0)],
                      ["× Avg order value", formatInrFull(rb.aov_inr)],
                      ["× Monthly scale", `${rb.k.toFixed(2)}`],
                    ].map(([k, v]) => <div key={k} className="flex justify-between border-b border-border pb-2"><dt className="text-muted-foreground">{k}</dt><dd>{v}</dd></div>)}
                    <div className="flex justify-between pt-1 text-base"><dt>= Base risk</dt><dd className="font-medium text-destructive">{formatInrFull(b.risk_inr.base)}</dd></div>
                  </dl>
                  <div className="mt-4"><MiniTrend data={d.trend} dataKey="sessions_blocked" /></div>
                </Card>
              </div>

              <Card className="p-5">
                <SectionTitle eyebrow="Proof" title="Replay screenshots" info="A test agent re-ran the failing journey against the store. Step through what it saw." />
                <ReplayShots d={d} />
              </Card>

              <Card className="hide-in-story p-5">
                <SectionTitle eyebrow="Sample sessions" title="Open an example in Session Explorer" />
                {d.sample_sessions.length === 0 ? <p className="text-sm text-muted-foreground">No sample sessions in this window.</p> : (
                  <DataTable caption="Sample sessions hit by this blocker" data={d.sample_sessions} columns={sessionColumns} getRowId={(s) => s.session_id} onRowClick={(s) => router.push(href("/sessions", { id: s.session_id }))} />
                )}
              </Card>

              {rec && (
                <Card className="border-primary/40 p-6" data-testid="recommendation">
                  <Eyebrow className="mb-2">Recommended fix</Eyebrow>
                  <h2 className="font-display text-2xl font-bold tracking-tight">{rec.title}</h2>
                  <p className="mt-3 max-w-3xl">{rec.body}</p>
                  <div className="mt-5 grid gap-4 md:grid-cols-2">
                    <div><h3 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Why it helps</h3><p className="mt-1 text-sm">{rec.why_it_helps}</p></div>
                    <div><h3 className="font-mono text-xs uppercase tracking-widest text-muted-foreground">How to verify</h3><p className="mt-1 text-sm">{rec.how_to_verify}</p><p className="mt-2 text-sm">Verify metric: <span className="font-mono text-primary">{rec.verify_metric}</span></p></div>
                  </div>
                  {rec.llm_explanation && <p className="mt-4 rounded-md bg-muted p-3 text-sm text-muted-foreground"><span className="font-mono text-xs uppercase tracking-widest">AI explanation · </span>{rec.llm_explanation}</p>}
                  <div className="mt-6 flex flex-wrap items-center gap-3">
                    {rec.status === "fixed" ? (
                      <Badge tone="success" className="px-3 py-1.5 text-sm" data-testid="fixed-badge">✓ Marked as fixed</Badge>
                    ) : (
                      <Button data-testid="mark-fixed" disabled={busy || !CAN_WRITE} onClick={() => void markFixed(rec.rec_id)}>{busy ? "Saving…" : "Mark as fixed"}</Button>
                    )}
                    <Link href={href("/compare")} className={linkButtonClass("secondary")}>Compare before / after</Link>
                    {!CAN_WRITE && <span className="text-xs text-muted-foreground">Read-only demo snapshot: marking fixed is disabled.</span>}
                  </div>
                  {msg && <p role="status" data-testid="mark-fixed-msg" className={`mt-3 text-sm ${msg.tone === "success" ? "text-success" : "text-destructive"}`}>{msg.text}</p>}
                </Card>
              )}
            </div>
          );
        }}
      </Async>
    </>
  );
}

function BlockersGate() {
  const { get } = useUrlState();
  const id = get("id");
  return id ? <BlockerDetailView id={id as BlockerId} /> : <BlockerListView />;
}

export default function BlockersPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <BlockersGate />
    </Suspense>
  );
}
