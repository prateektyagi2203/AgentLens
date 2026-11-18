"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { api } from "@/lib/api";
import { formatCount, formatInr, formatPercent } from "@/lib/format";
import { useApi, useFilters } from "@/lib/hooks";
import type { Segment, StageId } from "@/lib/types";
import { FunnelBars } from "@/components/funnel-bars";
import { BlockerBadge, SEGMENT_LABEL } from "@/components/domain";
import { Async, Card, EmptyState, PageHeader, SectionTitle, Segmented, Skeleton, linkButtonClass } from "@/components/ui";

const SEGMENT_ORDER: Segment[] = ["humans", "all_agents", "verified", "declared", "suspected"];

function FunnelBody() {
  const { filters, key, href } = useFilters();
  const [compare, setCompare] = useState<Segment>("humans");
  const [picked, setPicked] = useState<StageId | null>(null);
  const primary = filters.segment ?? "all_agents";
  const effectiveCompare: Segment = compare !== primary ? compare : primary === "humans" ? "all_agents" : "humans";
  const state = useApi(`funnel:${key}:${effectiveCompare}`, () => api.funnel(filters, effectiveCompare));

  return (
    <>
      <PageHeader
        eyebrow="Funnel"
        title="Where agents drop off"
        description="The same eight shopping stages for humans and for agents. The gap between the two bars is what agents lose."
        actions={
          <Segmented<Segment>
            label="Compare against"
            value={effectiveCompare}
            onChange={setCompare}
            options={SEGMENT_ORDER.filter((s) => s !== primary).map((s) => ({ value: s, label: SEGMENT_LABEL[s] }))}
          />
        }
      />
      <Async state={state} skeleton={<Skeleton className="h-[34rem]" />} isEmpty={(f) => f.primary.sessions === 0 && f.compare.sessions === 0} empty={<EmptyState />}>
        {(f) => {
          const worst = f.primary.steps.slice(1).reduce((a, b) => (b.drop_off > a.drop_off ? b : a), f.primary.steps[1]);
          const stage = picked ?? worst.stage_id;
          const blockers = f.stage_blockers[stage] ?? [];
          const stageName = f.stages.find((s) => s.id === stage)?.name ?? stage;
          return (
            <div className="space-y-6">
              <div className="grid gap-4 sm:grid-cols-3">
                <Card className="p-5">
                  <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">{SEGMENT_LABEL[f.primary.segment]} conversion</p>
                  <p className="mt-2 font-mono text-3xl font-medium text-agent">{formatPercent(f.primary.conversion)}</p>
                </Card>
                <Card className="p-5">
                  <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">{SEGMENT_LABEL[f.compare.segment]} conversion</p>
                  <p className="mt-2 font-mono text-3xl font-medium text-human">{formatPercent(f.compare.conversion)}</p>
                </Card>
                <Card className="p-5">
                  <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">Biggest drop-off ({SEGMENT_LABEL[f.primary.segment]})</p>
                  <p className="mt-2 font-mono text-3xl font-medium text-destructive">{worst.stage_id} · -{formatPercent(worst.drop_off, 0)}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{worst.name}</p>
                </Card>
              </div>
              <Card className="p-5">
                <SectionTitle eyebrow="Side by side" title="Share of sessions reaching each stage" info="Each bar is the share of that segment's sessions that reached the stage. The percentage after the dot is the drop-off from the previous stage. Click a stage to see what ends agent sessions there." />
                <FunnelBars primary={f.primary} compare={f.compare} selected={stage} onSelect={setPicked} />
              </Card>
              <Card className="p-5" data-testid="stage-blockers">
                <SectionTitle eyebrow={`${stage} · ${stageName}`} title="What stops agents at this stage" info="Blockers whose diagnosed terminal point is this stage, for the primary segment." />
                {blockers.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No diagnosed blockers at this stage in this window.</p>
                ) : (
                  <ul className="divide-y divide-border">
                    {blockers.map((b) => (
                      <li key={b.blocker_id}>
                        <Link href={href("/blockers", { id: b.blocker_id })} className="flex flex-wrap items-center justify-between gap-4 py-3 hover:text-primary">
                          <span className="flex items-center gap-3">
                            <BlockerBadge id={b.blocker_id} />
                            <span className="font-medium">{b.name}</span>
                          </span>
                          <span className="flex items-center gap-6 font-mono text-sm">
                            <span className="text-muted-foreground">{formatCount(b.sessions_blocked)} sessions · {formatPercent(b.share_of_failed, 0)} of failures</span>
                            <span className="text-destructive">{formatInr(b.risk_inr_base)}</span>
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
                <Link href={href("/blockers")} className={`${linkButtonClass("secondary")} mt-4`}>
                  All blockers
                </Link>
              </Card>
            </div>
          );
        }}
      </Async>
    </>
  );
}

export default function FunnelPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <FunnelBody />
    </Suspense>
  );
}
