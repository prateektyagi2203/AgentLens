"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { IS_DEMO, IS_MOCK } from "@/lib/data-source";
import { buildPresets, hasActiveFilters } from "@/lib/filters";
import { MetaProvider, UiProvider, useApi, useFilters, useMeta, useUi } from "@/lib/hooks";
import { formatClock } from "@/lib/format";
import { cn } from "@/lib/cn";
import type { AgentClass, Run, Segment } from "@/lib/types";
import { CLASS_LABEL, SEGMENT_LABEL } from "./domain";
import { Badge, Button, Segmented, inputClass } from "./ui";

const NAV = [
  { href: "/", label: "Overview", id: "overview" },
  { href: "/agents", label: "Agents", id: "agents" },
  { href: "/funnel", label: "Funnel", id: "funnel" },
  { href: "/blockers", label: "Blockers", id: "blockers" },
  { href: "/sessions", label: "Sessions", id: "sessions" },
  { href: "/replays", label: "Replays", id: "replays" },
  { href: "/compare", label: "Before / After", id: "compare" },
  { href: "/settings", label: "Settings & Report", id: "settings" },
];

const normalise = (p: string) => (p.length > 1 ? p.replace(/\/+$/, "") : p);

function Sidebar() {
  const pathname = normalise(usePathname());
  const { href } = useFilters();
  const { meta } = useMeta();
  return (
    <aside className="border-b border-border bg-card md:fixed md:inset-y-0 md:left-0 md:z-30 md:w-60 md:border-b-0 md:border-r">
      <div className="flex items-center gap-3 px-5 py-5 md:py-6">
        <span aria-hidden className="grid h-8 w-8 place-items-center rounded-md bg-primary font-mono text-sm font-medium text-primary-foreground">AL</span>
        <div>
          <p className="font-display text-lg font-bold leading-none tracking-tight">AgentLens</p>
          <p className="mt-1 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{meta?.store_name ?? "Agent readiness"}</p>
        </div>
      </div>
      <nav aria-label="Main" className="flex gap-1 overflow-x-auto px-3 pb-3 md:block md:space-y-1 md:px-3 md:pb-0">
        {NAV.map((n) => {
          const active = pathname === n.href || (n.href !== "/" && pathname.startsWith(n.href));
          return (
            <Link
              key={n.id}
              href={href(n.href)}
              data-testid={`nav-${n.id}`}
              aria-current={active ? "page" : undefined}
              className={cn("block whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium transition", active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground")}
            >
              {n.label}
            </Link>
          );
        })}
      </nav>
      <p className="hidden px-6 pt-8 font-mono text-[10px] uppercase leading-relaxed tracking-widest text-muted-foreground md:block">
        See what AI shopping agents see.
      </p>
    </aside>
  );
}

export function ThemeToggle() {
  const { theme, toggleTheme } = useUi();
  return (
    <Button variant="secondary" data-testid="theme-toggle" onClick={toggleTheme} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} className="h-9 px-3" suppressHydrationWarning>
      <span aria-hidden suppressHydrationWarning>{theme === "dark" ? "☀" : "☾"}</span>
      <span className="hidden lg:inline" suppressHydrationWarning>{theme === "dark" ? "Light" : "Dark"}</span>
    </Button>
  );
}

export function StoryToggle() {
  const { story, toggleStory } = useUi();
  return (
    <Button variant={story ? "primary" : "secondary"} data-testid="story-toggle" aria-pressed={story} onClick={toggleStory} className="h-9 px-3" suppressHydrationWarning title="Story mode: larger type, hero numbers, no dense tables">
      Story mode
    </Button>
  );
}

function RunChip() {
  const { meta, reload } = useMeta();
  const last = meta?.last_run ?? null;
  const [live, setLive] = useState<Run | null>(null);
  const active = last && (last.status === "running" || last.status === "queued") ? last.run_id : null;

  useEffect(() => {
    if (!active) return;
    let stop = false;
    const id = setInterval(() => {
      api.run(active).then((r) => {
        if (stop) return;
        setLive(r);
        if (r.status !== "running" && r.status !== "queued") {
          clearInterval(id);
          reload();
        }
      }).catch(() => undefined);
    }, 1000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [active, reload]);

  const run = active && live?.run_id === active ? live : last;
  if (!run) return <Badge tone="muted" className="h-9 px-3">No pipeline run yet</Badge>;
  const tone = run.status === "succeeded" ? "success" : run.status === "failed" ? "destructive" : "primary";
  const done = run.steps.filter((s) => s.status === "succeeded").length;
  return (
    <Link href="/settings" data-testid="run-chip" className="rounded-md" aria-label={`Latest ${run.kind} run: ${run.status}`}>
      <Badge tone={tone} className="h-9 px-3">
        <span aria-hidden className={cn("h-2 w-2 rounded-full bg-current", run.status === "running" && "animate-pulse")} />
        {run.status === "running" || run.status === "queued" ? `${run.kind} ${done}/${run.steps.length}` : `${run.kind} ${run.status}${run.finished_at ? ` · ${formatClock(run.finished_at)}` : ""}`}
      </Badge>
    </Link>
  );
}

function FilterBar() {
  const { filters, setFilters } = useFilters();
  const { meta } = useMeta();
  const ann = useApi("annotations", () => api.annotations());
  const bounds = meta?.date_bounds ?? null;
  const presets = buildPresets(bounds, ann.data?.items ?? []);
  const from = filters.from ?? bounds?.min ?? "";
  const to = filters.to ?? bounds?.max ?? "";
  const current = presets.find((p) => p.from === from && p.to === to)?.id ?? "custom";

  const setRange = (f: string | undefined, t: string | undefined) => {
    const isAll = bounds && f === bounds.min && t === bounds.max;
    setFilters({ from: isAll ? undefined : f, to: isAll ? undefined : t });
  };

  return (
    <div className="flex flex-wrap items-center gap-2" role="search" aria-label="Global filters">
      <select aria-label="Date range preset" data-testid="filter-preset" className={inputClass} value={current} onChange={(e) => { const p = presets.find((x) => x.id === e.target.value); if (p) setRange(p.from, p.to); }}>
        {presets.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        <option value="custom" disabled>Custom range</option>
      </select>
      <input type="date" aria-label="From date" data-testid="filter-from" className={cn(inputClass, "w-36 font-mono")} value={from} min={bounds?.min} max={to || bounds?.max} onChange={(e) => e.target.value && setRange(e.target.value, to || undefined)} />
      <span aria-hidden className="text-muted-foreground">→</span>
      <input type="date" aria-label="To date" data-testid="filter-to" className={cn(inputClass, "w-36 font-mono")} value={to} min={from || bounds?.min} max={bounds?.max} onChange={(e) => e.target.value && setRange(from || undefined, e.target.value)} />
      <Segmented<Segment>
        label="Segment"
        size="sm"
        value={filters.segment ?? "all_agents"}
        onChange={(v) => setFilters({ segment: v === "all_agents" ? undefined : v })}
        options={(["all_agents", "verified", "declared", "suspected", "humans"] as Segment[]).map((s) => ({ value: s, label: SEGMENT_LABEL[s] }))}
      />
      <select aria-label="Operator" data-testid="filter-operator" className={inputClass} value={filters.operator ?? ""} onChange={(e) => setFilters({ operator: e.target.value || undefined })}>
        <option value="">All operators</option>
        {(meta?.operators ?? []).map((o) => <option key={o} value={o}>{o === "unknown" ? "Unidentified" : o}</option>)}
      </select>
      <select aria-label="Agent class" data-testid="filter-class" className={inputClass} value={filters.agent_class ?? ""} onChange={(e) => setFilters({ agent_class: (e.target.value || undefined) as AgentClass | undefined })}>
        <option value="">All classes</option>
        {(meta?.agent_classes ?? []).map((c) => <option key={c} value={c}>{CLASS_LABEL[c]}</option>)}
      </select>
      {hasActiveFilters(filters) && (
        <Button variant="ghost" className="h-9 px-3" data-testid="filter-reset" onClick={() => setFilters({ from: undefined, to: undefined, segment: undefined, operator: undefined, agent_class: undefined })}>
          Reset
        </Button>
      )}
    </div>
  );
}

function TopBar() {
  const { filters } = useFilters();
  return (
    <div className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur">
      <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-3">
        <FilterBar />
        <div className="flex items-center gap-2">
          {(IS_DEMO || IS_MOCK) && <Badge tone="warning" className="h-9 px-3" data-testid="demo-badge">{IS_DEMO ? "Demo data (synthetic)" : "Mock data"}</Badge>}
          <RunChip />
          <StoryToggle />
          <ThemeToggle />
        </div>
      </div>
      {IS_DEMO && hasActiveFilters(filters) && (
        <p data-testid="demo-note" className="border-t border-border bg-muted px-6 py-2 text-xs text-muted-foreground">
          Demo data: this is a static snapshot. Only the date range (Overview time series) and the Sessions filters are applied; other filters are ignored.
        </p>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <UiProvider>
      <MetaProvider>
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground">
          Skip to content
        </a>
        <Suspense fallback={null}>
          <Sidebar />
          <div className="md:pl-60">
            <TopBar />
            <main id="main" className="mx-auto max-w-[1400px] px-6 py-10">
              {children}
            </main>
          </div>
        </Suspense>
      </MetaProvider>
    </UiProvider>
  );
}
