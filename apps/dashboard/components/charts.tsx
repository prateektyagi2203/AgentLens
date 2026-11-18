"use client";

import { useState } from "react";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Cell, Legend, Line, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AGENT, AXIS, GRID, HUMAN, OPERATOR_COLORS, SUCCESS, TIER_COLOR, PRIMARY } from "@/lib/colors";
import { formatCount, formatDate, formatPercent } from "@/lib/format";
import type { Annotation, ClassMixItem, OperatorMixItem, TimeSeriesPoint } from "@/lib/types";
import { CLASS_LABEL } from "./domain";
import { ChartFrame, Segmented } from "./ui";

interface TipRow {
  name?: string | number;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
}
function TipBox({ active, payload, label, fmt }: { active?: boolean; payload?: TipRow[]; label?: string | number; fmt: (key: string, v: number) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-popover p-3 text-xs text-popover-foreground shadow-lg">
      <p className="mb-1.5 font-mono text-muted-foreground">{typeof label === "string" ? formatDate(label) : label}</p>
      {payload.map((p) => (
        <p key={String(p.dataKey)} className="flex items-center justify-between gap-6">
          <span className="flex items-center gap-1.5">
            <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: p.color }} />
            {p.name}
          </span>
          <span className="font-mono">{fmt(String(p.dataKey), Number(p.value))}</span>
        </p>
      ))}
    </div>
  );
}

const annTone = (a: Annotation) => (a.type === "marked_fixed" ? SUCCESS : a.type === "config_change" ? PRIMARY : AXIS);
const annShort = (a: Annotation) => (a.type === "config_change" ? "Config change" : a.type === "marked_fixed" ? "Marked fixed" : "Note");

// ------------------------------------------------------------------ time series
export function TimeSeriesChart({ points, annotations }: { points: TimeSeriesPoint[]; annotations: Annotation[] }) {
  const [metric, setMetric] = useState<"sessions" | "conversion">("sessions");
  const days = new Set(points.map((p) => p.date));
  const marks = annotations.filter((a) => days.has(a.ts.slice(0, 10)));

  const legend =
    metric === "sessions"
      ? [
          { label: "Verified agents", color: TIER_COLOR.verified },
          { label: "Declared agents", color: TIER_COLOR.declared },
          { label: "Suspected agents", color: TIER_COLOR.suspected },
          { label: "Humans (right axis)", color: HUMAN },
        ]
      : [
          { label: "Agent conversion", color: AGENT },
          { label: "Human conversion", color: HUMAN },
        ];

  return (
    <ChartFrame
      title="Sessions over time by segment"
      eyebrow="Trend"
      info="Daily sessions split by how confidently each visitor was identified. Vertical markers are annotations: store config changes and fixes you marked as done."
      legend={legend}
      right={<Segmented size="sm" label="Chart metric" value={metric} onChange={setMetric} options={[{ value: "sessions", label: "Sessions" }, { value: "conversion", label: "Conversion" }]} />}
    >
      <div data-testid="timeseries-chart" className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} margin={{ top: 24, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" tickFormatter={formatDate} stroke={AXIS} tick={{ fontSize: 11, fill: AXIS }} tickLine={false} minTickGap={16} />
            <YAxis yAxisId="l" tickFormatter={metric === "sessions" ? undefined : (v: number) => formatPercent(v, 0)} stroke={AXIS} tick={{ fontSize: 11, fill: AXIS }} tickLine={false} axisLine={false} width={44} />
            <YAxis yAxisId="r" orientation="right" hide={metric !== "sessions"} stroke={AXIS} tick={{ fontSize: 11, fill: AXIS }} tickLine={false} axisLine={false} width={48} />
            <Tooltip content={<TipBox fmt={(k, v) => (k.endsWith("conversion") ? formatPercent(v) : formatCount(v))} />} />
            {/* Recharts 2 only discovers direct children (no fragments), hence arrays. */}
            {metric === "sessions"
              ? [
                  <Area key="v" yAxisId="l" stackId="a" type="monotone" dataKey="verified" name="Verified" stroke={TIER_COLOR.verified} fill={TIER_COLOR.verified} fillOpacity={0.85} />,
                  <Area key="d" yAxisId="l" stackId="a" type="monotone" dataKey="declared" name="Declared" stroke={TIER_COLOR.declared} fill={TIER_COLOR.declared} fillOpacity={0.7} />,
                  <Area key="s" yAxisId="l" stackId="a" type="monotone" dataKey="suspected" name="Suspected" stroke={TIER_COLOR.suspected} fill={TIER_COLOR.suspected} fillOpacity={0.6} />,
                  <Line key="h" yAxisId="r" type="monotone" dataKey="human" name="Humans" stroke={HUMAN} strokeWidth={2} strokeDasharray="5 4" dot={false} />,
                ]
              : [
                  <Line key="a" yAxisId="l" type="monotone" dataKey="agent_conversion" name="Agents" stroke={AGENT} strokeWidth={2.5} dot={{ r: 3, fill: AGENT }} />,
                  <Line key="b" yAxisId="l" type="monotone" dataKey="human_conversion" name="Humans" stroke={HUMAN} strokeWidth={2} strokeDasharray="5 4" dot={false} />,
                ]}
            {marks.map((a) => (
              <ReferenceLine key={a.annotation_id} yAxisId="l" x={a.ts.slice(0, 10)} stroke={annTone(a)} strokeWidth={1.5} strokeDasharray="4 3" label={{ value: annShort(a), position: "top", fill: annTone(a), fontSize: 10 }} />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {marks.length > 0 && (
        <ul data-testid="annotation-list" className="mt-3 space-y-1 border-t border-border pt-3">
          {marks.map((a) => (
            <li key={a.annotation_id} className="flex gap-2 text-xs text-muted-foreground">
              <span className="font-mono" style={{ color: annTone(a) }}>
                {formatDate(a.ts.slice(0, 10))}
              </span>
              <span>
                <span className="font-medium text-foreground">{annShort(a)}:</span> {a.label}
              </span>
            </li>
          ))}
        </ul>
      )}
    </ChartFrame>
  );
}

// ------------------------------------------------------------------ operator donut
export function OperatorDonut({ items }: { items: OperatorMixItem[] }) {
  const data = items.map((o, i) => ({ name: o.operator === "unknown" ? "Unidentified" : o.operator, value: o.sessions, share: o.share, fill: OPERATOR_COLORS[i % OPERATOR_COLORS.length] }));
  const total = items.reduce((s, o) => s + o.sessions, 0);
  return (
    <ChartFrame title="Agent sessions by operator" eyebrow="Who" info="Which company runs the agents visiting your store. Verified and Declared identities are attributed to an operator; Suspected agents are shown as Unidentified.">
      <div className="flex flex-col items-center gap-4 sm:flex-row">
        <div className="relative h-48 w-48 shrink-0" data-testid="operator-donut">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} dataKey="value" nameKey="name" innerRadius={58} outerRadius={88} paddingAngle={2} stroke="var(--card)" strokeWidth={2}>
                {data.map((d) => (
                  <Cell key={d.name} fill={d.fill} />
                ))}
              </Pie>
              <Tooltip content={<TipBox fmt={(_k, v) => formatCount(v)} />} />
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="font-mono text-xl font-medium">{formatCount(total)}</span>
            <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">sessions</span>
          </div>
        </div>
        <ul className="w-full space-y-2">
          {data.map((d) => (
            <li key={d.name} className="flex items-center justify-between gap-3 text-sm">
              <span className="flex items-center gap-2">
                <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: d.fill }} />
                {d.name}
              </span>
              <span className="font-mono text-muted-foreground">{formatPercent(d.share)}</span>
            </li>
          ))}
        </ul>
      </div>
    </ChartFrame>
  );
}

// ------------------------------------------------------------------ class bar
export function ClassBar({ items }: { items: ClassMixItem[] }) {
  const data = items.map((c) => ({ name: CLASS_LABEL[c.agent_class], sessions: c.sessions, share: c.share }));
  return (
    <ChartFrame title="Agent sessions by class" eyebrow="What kind" info="User fetchers read a page when a person asks an assistant a question. Browsing agents click through the site like a shopper. Crawlers are listed separately on the Agents page because they are not shoppers.">
      <div data-testid="class-bar" className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" horizontal={false} />
            <XAxis type="number" stroke={AXIS} tick={{ fontSize: 11, fill: AXIS }} tickLine={false} axisLine={false} />
            <YAxis type="category" dataKey="name" stroke={AXIS} tick={{ fontSize: 12, fill: AXIS }} tickLine={false} axisLine={false} width={110} />
            <Tooltip cursor={{ fill: "var(--accent)" }} content={<TipBox fmt={(_k, v) => formatCount(v)} />} />
            <Bar dataKey="sessions" name="Sessions" fill={AGENT} radius={[0, 4, 4, 0]} barSize={22} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartFrame>
  );
}

// ------------------------------------------------------------------ small trend (blocker / agent detail)
export function MiniTrend({ data, dataKey, color = AGENT, format = formatCount }: { data: { date: string }[]; dataKey: string; color?: string; format?: (n: number) => string }) {
  return (
    <div className="h-36 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="date" tickFormatter={formatDate} stroke={AXIS} tick={{ fontSize: 10, fill: AXIS }} tickLine={false} minTickGap={20} />
          <YAxis stroke={AXIS} tick={{ fontSize: 10, fill: AXIS }} tickLine={false} axisLine={false} width={36} tickFormatter={(v: number) => format(v)} />
          <Tooltip content={<TipBox fmt={(_k, v) => format(v)} />} />
          <Area type="monotone" dataKey={dataKey} name="Value" stroke={color} fill={color} fillOpacity={0.18} strokeWidth={2} />
          <Legend wrapperStyle={{ display: "none" }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
