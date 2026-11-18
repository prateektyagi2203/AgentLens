"use client";

import { cn } from "@/lib/cn";
import { AGENT, HUMAN } from "@/lib/colors";
import { formatCount, formatPercent } from "@/lib/format";
import type { FunnelSeries, StageId } from "@/lib/types";
import { SEGMENT_LABEL } from "./domain";

/** Side-by-side horizontal funnel: each stage is a button, so it is keyboard and screen-reader friendly. */
export function FunnelBars({ primary, compare, selected, onSelect, primaryLabel, compareLabel }: { primary: FunnelSeries; compare: FunnelSeries; selected: StageId | null; onSelect: (s: StageId) => void; primaryLabel?: string; compareLabel?: string }) {
  const pl = primaryLabel ?? SEGMENT_LABEL[primary.segment];
  const cl = compareLabel ?? SEGMENT_LABEL[compare.segment];
  return (
    <div data-testid="funnel-bars" className="space-y-1">
      <div className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-2"><i aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: HUMAN }} />{cl} ({formatCount(compare.sessions)} sessions)</span>
        <span className="flex items-center gap-2"><i aria-hidden className="h-2.5 w-2.5 rounded-sm" style={{ background: AGENT }} />{pl} ({formatCount(primary.sessions)} sessions)</span>
      </div>
      {primary.steps.map((step, i) => {
        const cmp = compare.steps[i];
        const active = selected === step.stage_id;
        return (
          <button
            key={step.stage_id}
            type="button"
            data-testid={`funnel-stage-${step.stage_id}`}
            aria-pressed={active}
            onClick={() => onSelect(step.stage_id)}
            className={cn("grid w-full grid-cols-[7.5rem_1fr] items-center gap-4 rounded-lg border px-3 py-3 text-left transition hover:bg-accent md:grid-cols-[11rem_1fr_9rem]", active ? "border-primary bg-accent" : "border-transparent")}
          >
            <span>
              <span className="font-mono text-xs text-primary">{step.stage_id}</span>
              <span className="block text-sm font-medium">{step.name}</span>
            </span>
            <span className="space-y-1.5">
              <Bar value={cmp.overall_conversion} color={HUMAN} label={`${cl} ${formatPercent(cmp.overall_conversion)} of sessions reach this stage`} />
              <Bar value={step.overall_conversion} color={AGENT} label={`${pl} ${formatPercent(step.overall_conversion)} of sessions reach this stage`} />
            </span>
            <span className="hidden text-right font-mono text-xs md:block">
              <span className="block" style={{ color: HUMAN }}>{formatPercent(cmp.overall_conversion)} · {i ? `-${formatPercent(cmp.drop_off, 0)}` : "start"}</span>
              <span className="block" style={{ color: AGENT }}>{formatPercent(step.overall_conversion)} · {i ? `-${formatPercent(step.drop_off, 0)}` : "start"}</span>
              <span className="block text-muted-foreground">{formatCount(step.sessions)} sessions</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function Bar({ value, color, label }: { value: number; color: string; label: string }) {
  return (
    <span className="block h-3.5 w-full rounded-sm bg-muted" role="img" aria-label={label}>
      <span className="block h-full rounded-sm" style={{ width: `${Math.max(value * 100, value > 0 ? 0.8 : 0)}%`, background: color }} />
    </span>
  );
}
