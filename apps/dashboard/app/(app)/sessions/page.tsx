"use client";

import Link from "next/link";
import { Suspense } from "react";
import { api } from "@/lib/api";
import { formatCount, formatDateTime, formatDuration, formatInr, formatMs, formatPercent } from "@/lib/format";
import { useApi, useFilters, useUrlState } from "@/lib/hooks";
import type { BlockerId, IdentityTier, SessionQuery, StageId } from "@/lib/types";
import { BlockerBadge, SIGNATURE_LABEL, StageChip, TierBadge } from "@/components/domain";
import { SessionTable } from "@/components/session-table";
import { Async, Badge, Button, Card, EmptyState, Eyebrow, PageHeader, SectionTitle, Skeleton, inputClass } from "@/components/ui";
import { cn } from "@/lib/cn";

const STAGES: StageId[] = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"];
const BLOCKERS: BlockerId[] = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B09", "B10", "B11", "B12", "B13", "B14", "B15", "B16", "B99"];
const PAGE_SIZE = 25;

// ------------------------------------------------------------------ list
function SessionListView() {
  const { filters, key } = useFilters();
  const { get, set } = useUrlState();
  const page = Math.max(1, Number(get("page") ?? 1) || 1);
  const q: SessionQuery = {
    page,
    page_size: PAGE_SIZE,
    q: get("q"),
    identity_tier: get("tier") as IdentityTier | undefined,
    blocker_id: get("blocker") as BlockerId | undefined,
    max_stage: get("stage") as StageId | undefined,
    converted: get("outcome") === "converted" ? true : get("outcome") === "failed" ? false : undefined,
    sort: "start_ts",
    order: "desc",
  };
  const qKey = JSON.stringify(q);
  const state = useApi(`sessions:${key}:${qKey}`, () => api.sessions(filters, q));
  const pick = (name: string) => (e: { target: { value: string } }) => set({ [name]: e.target.value || undefined, page: undefined });

  return (
    <>
      <PageHeader eyebrow="Sessions" title="Session Explorer" description="Every visit, one row each. Open a session to see the timeline, how the visitor was identified, and which rule explains where it ended." />
      <div className="mb-4 flex flex-wrap items-center gap-2" role="search" aria-label="Session filters">
        <input type="search" aria-label="Search sessions" data-testid="session-search" placeholder="Search id, agent, page…" className={cn(inputClass, "w-64")} defaultValue={get("q") ?? ""} onKeyDown={(e) => { if (e.key === "Enter") set({ q: e.currentTarget.value || undefined, page: undefined }); }} onBlur={(e) => { if ((e.target.value || undefined) !== get("q")) set({ q: e.target.value || undefined, page: undefined }); }} />
        <select aria-label="Identity tier" className={inputClass} value={get("tier") ?? ""} onChange={pick("tier")}>
          <option value="">Any identity</option><option value="verified">Verified</option><option value="declared">Declared</option><option value="suspected">Suspected</option><option value="human">Human</option>
        </select>
        <select aria-label="Outcome" className={inputClass} value={get("outcome") ?? ""} onChange={pick("outcome")}>
          <option value="">Any outcome</option><option value="converted">Purchased</option><option value="failed">Did not purchase</option>
        </select>
        <select aria-label="Furthest stage" className={inputClass} value={get("stage") ?? ""} onChange={pick("stage")}>
          <option value="">Any stage</option>{STAGES.map((s) => <option key={s} value={s}>Reached {s}</option>)}
        </select>
        <select aria-label="Blocker" className={inputClass} value={get("blocker") ?? ""} onChange={pick("blocker")}>
          <option value="">Any blocker</option>{BLOCKERS.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        {["q", "tier", "outcome", "stage", "blocker"].some((k) => get(k)) && <Button variant="ghost" className="h-9" onClick={() => set({ q: undefined, tier: undefined, outcome: undefined, stage: undefined, blocker: undefined, page: undefined })}>Clear</Button>}
      </div>
      <Async state={state} skeleton={<Skeleton className="h-96" />} isEmpty={(l) => l.total === 0} empty={<EmptyState title="No sessions match" hint="Try widening the date range or clearing filters. No data yet? Run agentlens synth or visit the store." />}>
        {(l) => {
          const pages = Math.max(1, Math.ceil(l.total / l.page_size));
          return (
            <div className="space-y-4" data-testid="sessions-list">
              <SessionTable rows={l.items} caption="Sessions" />
              <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span className="font-mono">{formatCount(l.total)} sessions · page {l.page} of {pages}</span>
                <span className="flex gap-2">
                  <Button variant="secondary" disabled={l.page <= 1} onClick={() => set({ page: String(l.page - 1) })}>Previous</Button>
                  <Button variant="secondary" disabled={l.page >= pages} onClick={() => set({ page: String(l.page + 1) })}>Next</Button>
                </span>
              </div>
            </div>
          );
        }}
      </Async>
    </>
  );
}

// ------------------------------------------------------------------ detail (timeline)
function SessionDetailView({ id }: { id: string }) {
  const { href } = useFilters();
  const state = useApi(`session:${id}`, () => api.session(id));
  return (
    <>
      <Link href={href("/sessions")} className="mb-6 inline-block text-sm text-primary hover:underline" data-testid="back-to-sessions">← All sessions</Link>
      <Async state={state} skeleton={<Skeleton className="h-[36rem]" />}>
        {(d) => {
          const s = d.session;
          const reached = new Set(d.stage_events.map((e) => e.stage_id));
          const terminal = d.fired_rules.find((r) => r.is_terminal);
          return (
            <div className="space-y-6" data-testid="session-detail">
              <PageHeader eyebrow={`Session · ${formatDateTime(s.start_ts)}`} title={s.agent_name} description={<span className="font-mono text-sm">{s.session_id}</span>} actions={<TierBadge tier={s.identity_tier} />} />
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {[
                  ["Duration", formatDuration(s.duration_s)],
                  ["Requests", `${formatCount(s.request_count)} (${formatCount(s.page_count)} pages)`],
                  ["Outcome", s.converted ? `Purchased ${formatInr(s.order_value_inr)}` : terminal ? `Blocked: ${terminal.blocker_id}` : "Abandoned"],
                  ["Identity confidence", formatPercent(s.identity_confidence, 0)],
                ].map(([k, v]) => (
                  <Card key={k} className="p-4"><p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">{k}</p><p className={cn("mt-2 font-mono text-lg font-medium", k === "Outcome" && !s.converted && terminal && "text-destructive", k === "Outcome" && s.converted && "text-success")}>{v}</p></Card>
                ))}
              </div>

              <Card className="p-5">
                <SectionTitle eyebrow="Journey" title="Stages reached" />
                <ol className="flex flex-wrap items-center gap-2" aria-label="Funnel stages">
                  {STAGES.map((st) => {
                    const hit = reached.has(st);
                    const stuck = terminal && s.max_stage && STAGES.indexOf(st) === STAGES.indexOf(s.max_stage) + 1;
                    return (
                      <li key={st} className={cn("rounded-md border px-3 py-1.5 font-mono text-xs", hit ? "border-agent bg-agent/10 text-agent" : "border-border text-muted-foreground", stuck && "border-destructive bg-destructive/10 text-destructive")} aria-label={`${st} ${hit ? "reached" : stuck ? "blocked here" : "not reached"}`}>
                        {st} {hit ? "✓" : stuck ? "✕" : ""}
                      </li>
                    );
                  })}
                </ol>
              </Card>

              <div className="grid gap-6 lg:grid-cols-2">
                <Card className="p-5">
                  <SectionTitle eyebrow="Identity" title="How we identified this visitor" />
                  <dl className="space-y-2 text-sm">
                    <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Signature</dt><dd><Badge tone={d.identity.signature_status === "valid" ? "success" : d.identity.signature_status === "none" ? "muted" : "warning"}>{SIGNATURE_LABEL[d.identity.signature_status]}</Badge></dd></div>
                    {d.identity.signature_agent && <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Signature-Agent</dt><dd className="font-mono text-xs">{d.identity.signature_agent}</dd></div>}
                    <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Suspicion score</dt><dd className="font-mono">{d.identity.suspicion_score ?? "n/a"}</dd></div>
                    <div className="flex justify-between gap-4"><dt className="text-muted-foreground">IP matches published range</dt><dd className="font-mono">{d.identity.ip_match === null ? "n/a" : d.identity.ip_match ? "yes" : "no"}</dd></div>
                    <div><dt className="mb-1 text-muted-foreground">User agent</dt><dd className="break-all rounded-md bg-muted p-2 font-mono text-xs">{d.identity.user_agent}</dd></div>
                  </dl>
                </Card>
                <Card className={cn("p-5", terminal && "border-destructive/50")} data-testid="fired-rules">
                  <SectionTitle eyebrow="Diagnosis" title="Rules that fired" />
                  {d.fired_rules.length === 0 ? <p className="text-sm text-muted-foreground">No blocker rule fired for this session.</p> : (
                    <ul className="space-y-3">
                      {d.fired_rules.map((r) => (
                        <li key={r.blocker_id} className={cn("rounded-md border p-3", r.is_terminal ? "border-destructive bg-destructive/5" : "border-border")}>
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <Link href={href("/blockers", { id: r.blocker_id })} className="flex items-center gap-2 font-medium hover:text-primary"><BlockerBadge id={r.blocker_id} />{r.name}</Link>
                            <span className="flex items-center gap-2">{r.is_terminal && <Badge tone="destructive">Terminal blocker</Badge>}<span className="font-mono text-xs text-muted-foreground">{formatPercent(r.confidence, 0)} confidence</span></span>
                          </div>
                          <ul className="mt-2 space-y-1 text-xs text-muted-foreground">{r.evidence.map((e, i) => <li key={i} className="font-mono">{e.type === "request" ? e.summary : `${e.check}: ${e.result}`}</li>)}</ul>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>

              <Card className="p-5">
                <SectionTitle eyebrow="Timeline" title="Requests in order" />
                <ol className="relative space-y-0 border-l border-border pl-6" data-testid="session-timeline">
                  {d.requests.map((r) => {
                    const bad = r.status >= 400 || r.error_code;
                    return (
                      <li key={r.request_id} className={cn("relative py-2", r.is_asset && "opacity-60")}>
                        <span aria-hidden className={cn("absolute -left-[1.85rem] top-3.5 h-2.5 w-2.5 rounded-full border-2 border-card", bad ? "bg-destructive" : r.stage_id ? "bg-agent" : "bg-muted-foreground")} />
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs">
                          <span className="w-14 text-muted-foreground">+{formatMs(r.offset_ms)}</span>
                          <span className="font-medium">{r.method}</span>
                          <span className="break-all">{r.path}</span>
                          <span className={cn(bad ? "text-destructive" : "text-success")}>{r.status}</span>
                          <span className="text-muted-foreground">{formatMs(r.duration_ms)}</span>
                          {r.stage_id && <StageChip stage={r.stage_id} />}
                          {r.error_code && <Badge tone="destructive">{r.error_code}</Badge>}
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </Card>

              {d.replay_ids.length > 0 && (
                <p className="text-sm"><Eyebrow className="mb-1">Replays</Eyebrow>{d.replay_ids.map((r) => <Link key={r} href={`/replays?id=${r}`} className="mr-3 font-mono text-primary hover:underline">{r}</Link>)}</p>
              )}
            </div>
          );
        }}
      </Async>
    </>
  );
}

function SessionsGate() {
  const { get } = useUrlState();
  const id = get("id");
  return id ? <SessionDetailView id={id} /> : <SessionListView />;
}

export default function SessionsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <SessionsGate />
    </Suspense>
  );
}
