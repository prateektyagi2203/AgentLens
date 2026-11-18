"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Suspense } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { api } from "@/lib/api";
import { formatDateTime, formatMs } from "@/lib/format";
import { useApi, useFilters, useUrlState } from "@/lib/hooks";
import type { ReplayRow } from "@/lib/types";
import { DataTable } from "@/components/data-table";
import { BlockerBadge, ReplayBadge } from "@/components/domain";
import { ReplayCarousel } from "@/components/replay-carousel";
import { Async, Badge, Card, EmptyState, PageHeader, SectionTitle, Skeleton } from "@/components/ui";

// ------------------------------------------------------------------ list
function ReplayListView() {
  const router = useRouter();
  const { href } = useFilters();
  const state = useApi("replays", () => api.replays());
  const columns: ColumnDef<ReplayRow>[] = [
    { id: "id", header: "Replay", accessorFn: (r) => r.replay_id, cell: ({ row }) => <span className="font-mono text-xs">{row.original.replay_id}</span> },
    { id: "blocker", header: "Blocker", accessorFn: (r) => r.blocker_id, cell: ({ row }) => <span className="flex items-center gap-2"><BlockerBadge id={row.original.blocker_id} />{row.original.blocker_name}</span> },
    { id: "mode", header: "Mode", accessorFn: (r) => r.mode, cell: ({ row }) => <Badge tone="muted">{row.original.mode}</Badge> },
    { id: "verdict", header: "Verdict", accessorFn: (r) => r.verdict ?? r.status, cell: ({ row }) => <ReplayBadge status={row.original.verdict ?? "pending"} /> },
    { id: "steps", header: "Steps", accessorFn: (r) => r.steps_count, cell: ({ row }) => <span className="font-mono">{row.original.steps_count}</span> },
    { id: "when", header: "Ran", accessorFn: (r) => r.started_at, cell: ({ row }) => <span className="font-mono text-xs">{formatDateTime(row.original.started_at)}</span> },
  ];
  return (
    <>
      <PageHeader eyebrow="Replays" title="Proof, not guesses" description="A test agent re-runs the journeys that failed, so each blocker is confirmed on your real store." />
      <Async state={state} skeleton={<Skeleton className="h-80" />} isEmpty={(l) => l.items.length === 0} empty={<EmptyState title="No replays yet" hint="Start replays from Settings & Report once the pipeline has found blockers. No data yet? Run agentlens synth or visit the store." action={<Link href={href("/settings")} className="text-primary hover:underline">Go to Settings & Report</Link>} />}>
        {(l) => <div data-testid="replays-table"><DataTable caption="Replays" data={l.items} columns={columns} getRowId={(r) => r.replay_id} onRowClick={(r) => router.push(`/replays?id=${r.replay_id}`)} initialSort={[{ id: "when", desc: true }]} /></div>}
      </Async>
    </>
  );
}

// ------------------------------------------------------------------ detail
function ReplayDetailView({ id }: { id: string }) {
  const { href } = useFilters();
  const state = useApi(`replay:${id}`, () => api.replay(id));
  return (
    <>
      <Link href="/replays" className="mb-6 inline-block text-sm text-primary hover:underline" data-testid="back-to-replays">← All replays</Link>
      <Async state={state} skeleton={<Skeleton className="h-[34rem]" />}>
        {(d) => {
          const r = d.replay;
          return (
            <div className="space-y-6" data-testid="replay-detail">
              <PageHeader eyebrow={`Replay · ${r.mode} mode`} title={r.blocker_name} description={<span className="font-mono text-sm">{r.replay_id} · from session {r.source_session_id}</span>} actions={<ReplayBadge status={r.verdict ?? "pending"} />} />
              <Card className="p-5">
                <SectionTitle eyebrow="Verdict" title="What the test agent found" />
                <p>{d.explanation}</p>
                <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <Link href={href("/blockers", { id: r.blocker_id })} className="text-primary hover:underline">View blocker {r.blocker_id}</Link>·
                  <Link href={href("/sessions", { id: r.source_session_id })} className="text-primary hover:underline">Source session</Link>·
                  <Badge tone={d.signed_requests ? "success" : "muted"}>{d.signed_requests ? "signed requests" : "unsigned requests"}</Badge>
                </p>
                <p className="mt-3 break-all rounded-md bg-muted p-2 font-mono text-xs">{d.user_agent}</p>
              </Card>
              <Card className="p-5">
                <SectionTitle eyebrow="Steps" title="Step-by-step" />
                <ReplayCarousel steps={d.steps} title={`Replay ${r.replay_id}`} />
              </Card>
              <Card className="hide-in-story p-5">
                <SectionTitle eyebrow="Network" title="Network log" />
                <div className="overflow-x-auto rounded-md bg-muted p-3">
                  <table className="w-full font-mono text-xs" data-testid="network-log">
                    <caption className="sr-only">Network requests made during the replay</caption>
                    <thead><tr className="text-left text-muted-foreground"><th className="pr-4 pb-2">Time</th><th className="pr-4 pb-2">Method</th><th className="pr-4 pb-2">URL</th><th className="pr-4 pb-2">Status</th><th className="pb-2">Took</th></tr></thead>
                    <tbody>
                      {d.network_log.map((n, i) => (
                        <tr key={i}><td className="pr-4 py-0.5 text-muted-foreground">{formatDateTime(n.ts)}</td><td className="pr-4">{n.method}</td><td className="pr-4 break-all">{n.url}</td><td className={`pr-4 ${n.status >= 400 ? "text-destructive" : "text-success"}`}>{n.status}{n.error_code ? ` ${n.error_code}` : ""}</td><td>{formatMs(n.duration_ms)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            </div>
          );
        }}
      </Async>
    </>
  );
}

function ReplaysGate() {
  const { get } = useUrlState();
  const id = get("id");
  return id ? <ReplayDetailView id={id} /> : <ReplayListView />;
}

export default function ReplaysPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <ReplaysGate />
    </Suspense>
  );
}
