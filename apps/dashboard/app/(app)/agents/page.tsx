"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { api } from "@/lib/api";
import { formatCount, formatDate, formatPercent } from "@/lib/format";
import { useApi, useFilters } from "@/lib/hooks";
import type { AgentList, AgentRow, CrawlerRow } from "@/lib/types";
import { MiniTrend } from "@/components/charts";
import { DataTable } from "@/components/data-table";
import { BlockerBadge, CLASS_LABEL, SIGNATURE_LABEL, TierBadge } from "@/components/domain";
import { Async, Badge, Card, Drawer, EmptyState, InfoTip, PageHeader, SectionTitle, Skeleton } from "@/components/ui";
import { SessionTable } from "@/components/session-table";

function TierBar({ mix }: { mix: AgentRow["tier_mix"] }) {
  const parts = [
    { k: "Verified", v: mix.verified, c: "var(--chart-1)" },
    { k: "Declared", v: mix.declared, c: "var(--chart-5)" },
    { k: "Suspected", v: mix.suspected, c: "var(--chart-4)" },
  ];
  return (
    <div className="w-36" role="img" aria-label={parts.map((p) => `${p.k} ${formatPercent(p.v, 0)}`).join(", ")}>
      <div className="flex h-2 overflow-hidden rounded-full bg-muted">
        {parts.map((p) => <span key={p.k} style={{ width: `${p.v * 100}%`, background: p.c }} />)}
      </div>
    </div>
  );
}

const columns: ColumnDef<AgentRow>[] = [
  { id: "agent", header: "Agent", accessorFn: (a) => a.agent_name, cell: ({ row }) => <div><p className="font-medium">{row.original.agent_name}</p><p className="text-xs text-muted-foreground">{row.original.operator === "unknown" ? "Unidentified" : row.original.operator}</p></div> },
  { id: "class", header: "Class", accessorFn: (a) => a.agent_class, cell: ({ row }) => <Badge tone="agent">{CLASS_LABEL[row.original.agent_class]}</Badge> },
  { id: "sessions", header: "Sessions", accessorFn: (a) => a.sessions, cell: ({ row }) => <span className="font-mono">{formatCount(row.original.sessions)}</span> },
  { id: "share", header: "Share", accessorFn: (a) => a.share_of_agent_sessions, cell: ({ row }) => <span className="font-mono">{formatPercent(row.original.share_of_agent_sessions)}</span> },
  { id: "pages", header: "Pages / session", accessorFn: (a) => a.pages_per_session, cell: ({ row }) => <span className="font-mono">{row.original.pages_per_session.toFixed(1)}</span> },
  { id: "conv", header: "Conversion", accessorFn: (a) => a.conversion, cell: ({ row }) => <span className="font-mono">{formatPercent(row.original.conversion)}</span> },
  { id: "identity", header: "Identity mix", enableSorting: false, cell: ({ row }) => <TierBar mix={row.original.tier_mix} /> },
  { id: "blocker", header: "Top blocker", accessorFn: (a) => a.top_blocker?.share_of_failed ?? 0, cell: ({ row }) => row.original.top_blocker ? <span className="flex items-center gap-2"><BlockerBadge id={row.original.top_blocker.blocker_id} /><span className="font-mono text-xs text-muted-foreground">{formatPercent(row.original.top_blocker.share_of_failed, 0)}</span></span> : <span className="text-muted-foreground">-</span> },
];

const crawlerColumns: ColumnDef<CrawlerRow>[] = [
  { id: "agent", header: "Crawler", accessorFn: (c) => c.agent_name, cell: ({ row }) => <div><p className="font-medium">{row.original.agent_name}</p><p className="text-xs text-muted-foreground">{row.original.operator}</p></div> },
  { id: "class", header: "Type", accessorFn: (c) => c.agent_class, cell: ({ row }) => <Badge tone="muted">{CLASS_LABEL[row.original.agent_class]}</Badge> },
  { id: "req", header: "Requests", accessorFn: (c) => c.requests, cell: ({ row }) => <span className="font-mono">{formatCount(row.original.requests)}</span> },
  { id: "pages", header: "Pages", accessorFn: (c) => c.pages, cell: ({ row }) => <span className="font-mono">{formatCount(row.original.pages)}</span> },
  { id: "robots", header: "robots.txt", accessorFn: (c) => c.robots_txt_fetched, cell: ({ row }) => <Badge tone={row.original.robots_txt_fetched ? "success" : "warning"}>{row.original.robots_txt_fetched ? "fetched" : "not fetched"}</Badge> },
  { id: "seen", header: "Last seen", accessorFn: (c) => c.last_seen, cell: ({ row }) => <span className="font-mono text-xs">{formatDate(row.original.last_seen.slice(0, 10))}</span> },
];

function AgentDrawerBody({ agent }: { agent: AgentRow }) {
  const { filters, key, href } = useFilters();
  const state = useApi(`agent:${agent.operator}:${agent.agent_name}:${key}`, () => api.agent(agent.operator, agent.agent_name, filters));
  return (
    <Async state={state} skeleton={<Skeleton className="h-80" />}>
      {(d) => (
        <div className="space-y-6" data-testid="agent-detail">
          <div className="flex flex-wrap gap-2"><Badge tone="agent">{CLASS_LABEL[d.agent.agent_class]}</Badge><Badge tone="muted">{d.agent.operator === "unknown" ? "Unidentified operator" : d.agent.operator}</Badge></div>
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div><dt className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Sessions</dt><dd className="font-mono text-xl">{formatCount(d.agent.sessions)}</dd></div>
            <div><dt className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Conversion</dt><dd className="font-mono text-xl text-agent">{formatPercent(d.agent.conversion)}</dd></div>
            <div><dt className="font-mono text-xs uppercase tracking-widest text-muted-foreground">ID confidence</dt><dd className="font-mono text-xl">{formatPercent(d.identity.avg_identity_confidence, 0)}</dd></div>
            <div><dt className="font-mono text-xs uppercase tracking-widest text-muted-foreground">IP match rate</dt><dd className="font-mono text-xl">{d.identity.ip_match_rate === null ? "n/a" : formatPercent(d.identity.ip_match_rate, 0)}</dd></div>
          </dl>
          {d.identity.user_agent_example && <p className="break-all rounded-md bg-muted p-3 font-mono text-xs">{d.identity.user_agent_example}</p>}
          <div>
            <h3 className="mb-2 font-mono text-xs uppercase tracking-widest text-muted-foreground">Signature status</h3>
            <ul className="flex flex-wrap gap-2">{(Object.entries(d.agent.signature_status_counts) as [keyof typeof SIGNATURE_LABEL, number][]).filter(([, n]) => n > 0).map(([s, n]) => <li key={s}><Badge tone={s === "valid" ? "success" : s === "none" ? "muted" : "warning"}>{SIGNATURE_LABEL[s]} · {formatCount(n)}</Badge></li>)}</ul>
          </div>
          <div><h3 className="mb-1 font-mono text-xs uppercase tracking-widest text-muted-foreground">Sessions per day</h3><MiniTrend data={d.trend} dataKey="sessions" /></div>
          <div>
            <h3 className="mb-2 font-mono text-xs uppercase tracking-widest text-muted-foreground">Where this agent gets stuck</h3>
            {d.blockers.length === 0 ? <p className="text-sm text-muted-foreground">No diagnosed blockers.</p> : (
              <ul className="space-y-2">{d.blockers.map((b) => <li key={b.blocker_id}><Link href={href("/blockers", { id: b.blocker_id })} className="flex items-center justify-between rounded-md border border-border p-2 text-sm hover:bg-accent"><span className="flex items-center gap-2"><BlockerBadge id={b.blocker_id} />{b.name}</span><span className="font-mono text-xs text-muted-foreground">{formatCount(b.sessions)} · {formatPercent(b.share_of_failed, 0)}</span></Link></li>)}</ul>
            )}
          </div>
          <div>
            <h3 className="mb-2 font-mono text-xs uppercase tracking-widest text-muted-foreground">Recent sessions</h3>
            <SessionTable rows={d.recent_sessions} compact />
          </div>
        </div>
      )}
    </Async>
  );
}

function AgentsBody() {
  const { filters, key } = useFilters();
  const state = useApi(`agents:${key}`, () => api.agents(filters));
  const [open, setOpen] = useState<AgentRow | null>(null);
  return (
    <>
      <PageHeader eyebrow="Agents" title="Which agents visit" description="Every AI agent identified in the window, how confidently we identified it, and where it gets stuck." />
      <Async state={state} skeleton={<Skeleton className="h-96" />} isEmpty={(l: AgentList) => l.items.length === 0 && l.crawlers.length === 0} empty={<EmptyState />}>
        {(l) => (
          <div className="space-y-10">
            <section>
              <SectionTitle eyebrow="Shopping agents" title="Agents that browse and buy" info="Identity tiers: Verified (cryptographically signed by the operator), Declared (names itself in the user agent), Suspected (inferred from behaviour). Click a row for details." />
              {l.items.length === 0 ? <p className="text-sm text-muted-foreground">No sessionised agents match these filters.</p> : (
                <div data-testid="agents-table">
                  <DataTable caption="AI agents" data={l.items} columns={columns} getRowId={(a) => `${a.operator}/${a.agent_name}`} onRowClick={setOpen} initialSort={[{ id: "sessions", desc: true }]} selectedId={open ? `${open.operator}/${open.agent_name}` : null} />
                </div>
              )}
              <ul className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
                <li className="flex items-center gap-1.5"><TierBadge tier="verified" /> signed</li>
                <li className="flex items-center gap-1.5"><TierBadge tier="declared" /> self-declared</li>
                <li className="flex items-center gap-1.5"><TierBadge tier="suspected" /> behavioural guess</li>
              </ul>
            </section>
            <section data-testid="crawlers-section">
              <SectionTitle eyebrow="Crawlers" title="Search and training crawlers" info="Crawlers read pages to index them or to train models. They do not shop, so they are excluded from funnel and conversion numbers." />
              {l.crawlers.length === 0 ? <p className="text-sm text-muted-foreground">No crawler traffic in this window.</p> : (
                <DataTable caption="Crawler traffic" data={l.crawlers} columns={crawlerColumns} getRowId={(c) => `${c.operator}/${c.agent_name}`} initialSort={[{ id: "req", desc: true }]} />
              )}
            </section>
            <Card className="p-5 text-sm text-muted-foreground">
              <p className="flex items-center gap-2 font-medium text-foreground">Identity coverage is partial <InfoTip text="Agents can hide behind browser-like user agents. Verified and Declared are lower bounds; Suspected agents may include humans." /></p>
              <p className="mt-1">Only agents that sign requests or declare themselves can be attributed to an operator. Everything else is inferred from behaviour and may be wrong.</p>
            </Card>
          </div>
        )}
      </Async>
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open?.agent_name ?? "Agent"}>
        {open && <AgentDrawerBody agent={open} />}
      </Drawer>
    </>
  );
}

export default function AgentsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <AgentsBody />
    </Suspense>
  );
}
