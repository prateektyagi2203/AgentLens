"use client";

import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { ApiState } from "@/lib/hooks";

// ------------------------------------------------------------------ layout primitives
export function Card({ className, children, as: Tag = "div", ...rest }: { className?: string; children: ReactNode; as?: "div" | "section" | "article" } & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag className={cn("bg-card border border-border rounded-lg", className)} {...rest}>
      {children}
    </Tag>
  );
}

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("font-mono text-xs uppercase tracking-widest text-primary", className)}>{children}</p>;
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        <Eyebrow className="mb-3">{eyebrow}</Eyebrow>
        <h1 className="font-display text-4xl md:text-5xl font-bold tracking-tight">{title}</h1>
        {description && <p className="mt-3 text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}

export function SectionTitle({ eyebrow, title, info, right }: { eyebrow?: string; title: string; info?: string; right?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        {eyebrow && <Eyebrow className="mb-1">{eyebrow}</Eyebrow>}
        <h2 className="font-display text-xl font-bold tracking-tight flex items-center gap-2">
          {title}
          {info && <InfoTip text={info} />}
        </h2>
      </div>
      {right}
    </div>
  );
}

// ------------------------------------------------------------------ tooltip
export function InfoTip({ text, className }: { text: string; className?: string }) {
  const id = useId();
  return (
    <span className={cn("group relative inline-flex align-middle", className)}>
      <button
        type="button"
        aria-label="More information"
        aria-describedby={id}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-border font-mono text-[10px] leading-none text-muted-foreground hover:text-foreground focus-visible:text-foreground"
      >
        i
      </button>
      <span
        id={id}
        role="tooltip"
        className="pointer-events-none invisible absolute left-1/2 top-full z-30 mt-2 w-64 -translate-x-1/2 rounded-md border border-border bg-popover p-3 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-popover-foreground opacity-0 shadow-lg transition-opacity group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100"
      >
        {text}
      </span>
    </span>
  );
}

// ------------------------------------------------------------------ badges and buttons
const TONES = {
  muted: "bg-muted text-muted-foreground",
  primary: "bg-primary/10 text-primary",
  success: "bg-success/15 text-success",
  destructive: "bg-destructive/10 text-destructive",
  warning: "bg-warning/15 text-warning",
  agent: "bg-agent/10 text-agent",
  human: "bg-human/15 text-human",
} as const;
export type Tone = keyof typeof TONES;

export function Badge({ tone = "muted", children, className, title, ...rest }: { tone?: Tone; children: ReactNode; className?: string; title?: string } & React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span title={title} {...rest} className={cn("inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-xs font-medium whitespace-nowrap", TONES[tone], className)}>
      {children}
    </span>
  );
}

type ButtonVariant = "primary" | "secondary" | "ghost";
const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-primary text-primary-foreground hover:opacity-90",
  secondary: "border border-border bg-card text-foreground hover:bg-accent",
  ghost: "text-muted-foreground hover:bg-accent hover:text-foreground",
};

export function Button({ variant = "primary", className, ...rest }: { variant?: ButtonVariant } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={cn("inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50", BUTTON_VARIANTS[variant], className)}
      {...rest}
    />
  );
}

export const linkButtonClass = (variant: ButtonVariant = "secondary") =>
  cn("inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition", BUTTON_VARIANTS[variant]);

export const inputClass =
  "h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground disabled:opacity-60";

export function Segmented<T extends string>({ options, value, onChange, label, size = "md" }: { options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; label: string; size?: "sm" | "md" }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-md border border-border bg-muted p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded-[5px] font-medium transition",
            size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm",
            o.value === value ? "bg-card text-foreground shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ KPI
export function Delta({ value, goodWhen = "up", suffix = "vs previous period" }: { value: number | null | undefined; goodWhen?: "up" | "down"; suffix?: string }) {
  if (value === null || value === undefined || !Number.isFinite(value)) return <span className="font-mono text-xs text-muted-foreground">no prior period</span>;
  const up = value >= 0;
  const good = goodWhen === "up" ? up : !up;
  const flat = Math.abs(value) < 0.005;
  return (
    <span className={cn("font-mono text-xs", flat ? "text-muted-foreground" : good ? "text-success" : "text-destructive")}>
      {up ? "▲" : "▼"} {(Math.abs(value) * 100).toFixed(1)}% <span className="text-muted-foreground">{suffix}</span>
    </span>
  );
}

export function Kpi({ label, value, info, delta, goodWhen, hint, tone, className, testId }: { label: string; value: ReactNode; info: string; delta?: number | null; goodWhen?: "up" | "down"; hint?: ReactNode; tone?: "destructive" | "success" | "agent" | "human"; className?: string; testId?: string }) {
  return (
    <Card className={cn("p-5", className)} data-testid={testId}>
      <div className="flex items-center gap-2">
        <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">{label}</p>
        <InfoTip text={info} />
      </div>
      <p className={cn("mt-3 font-mono text-3xl font-medium tracking-tight", tone === "destructive" && "text-destructive", tone === "success" && "text-success", tone === "agent" && "text-agent", tone === "human" && "text-human")}>{value}</p>
      <div className="mt-2 min-h-4 text-xs text-muted-foreground">
        {delta !== undefined && <Delta value={delta} goodWhen={goodWhen} />}
        {hint && <div>{hint}</div>}
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ states
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-md bg-muted", className)} />;
}

export function SkeletonBlock({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-3">
      <span className="sr-only">{label}...</span>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({ title = "No data yet", hint = "Run agentlens synth or visit the store.", action, className }: { title?: string; hint?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div data-testid="empty-state" className={cn("blueprint-grid flex flex-col items-center justify-center rounded-lg border border-dashed border-border px-6 py-14 text-center", className)}>
      <Eyebrow className="mb-3">Empty</Eyebrow>
      <p className="font-display text-xl font-bold tracking-tight">{title}</p>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">{hint}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div role="alert" data-testid="error-state" className="rounded-lg border border-destructive/40 bg-destructive/5 p-6">
      <Eyebrow className="mb-2 text-destructive">Error</Eyebrow>
      <p className="font-display text-lg font-bold tracking-tight">Could not load this view</p>
      <p className="mt-2 text-sm text-muted-foreground">{error.message}</p>
      {onRetry && (
        <Button variant="secondary" className="mt-4" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

/** One wrapper for the loading / error / empty / ready states every page needs (DX2). */
export function Async<T>({ state, children, isEmpty, empty, skeleton }: { state: ApiState<T>; children: (data: T) => ReactNode; isEmpty?: (data: T) => boolean; empty?: ReactNode; skeleton?: ReactNode }) {
  if (state.error && !state.data) return <ErrorState error={state.error} onRetry={state.reload} />;
  if (!state.data) return <>{skeleton ?? <SkeletonBlock rows={5} />}</>;
  if (isEmpty?.(state.data)) return <>{empty ?? <EmptyState />}</>;
  return (
    <div className={cn(state.loading && "opacity-60 transition-opacity")} aria-busy={state.loading}>
      {state.error && <ErrorState error={state.error} onRetry={state.reload} />}
      {children(state.data)}
    </div>
  );
}

// ------------------------------------------------------------------ chart frame
export function ChartFrame({ title, info, eyebrow, legend, children, className, right }: { title: string; info?: string; eyebrow?: string; legend?: { label: string; color: string }[]; children: ReactNode; className?: string; right?: ReactNode }) {
  return (
    <Card className={cn("p-5", className)}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          {eyebrow && <Eyebrow className="mb-1">{eyebrow}</Eyebrow>}
          <h3 className="font-display text-base font-bold tracking-tight flex items-center gap-2">
            {title}
            {info && <InfoTip text={info} />}
          </h3>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          {legend && (
            <ul className="flex flex-wrap gap-x-4 gap-y-1">
              {legend.map((l) => (
                <li key={l.label} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: l.color }} />
                  {l.label}
                </li>
              ))}
            </ul>
          )}
          {right}
        </div>
      </div>
      {children}
    </Card>
  );
}

// ------------------------------------------------------------------ drawer
export function Drawer({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-foreground/30" onClick={onClose} aria-hidden />
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className="relative h-full w-full max-w-xl overflow-y-auto border-l border-border bg-background p-6 shadow-xl outline-none">
        <div className="mb-6 flex items-start justify-between gap-4">
          <h2 className="font-display text-2xl font-bold tracking-tight">{title}</h2>
          <Button variant="ghost" onClick={onClose} aria-label="Close panel">
            Close
          </Button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ small helpers
export function Field({ label, error, hint, children }: { label: string; error?: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted-foreground">{label}</span>
      {children}
      {error ? <span role="alert" className="mt-1 block text-xs text-destructive">{error}</span> : hint ? <span className="mt-1 block text-xs text-muted-foreground">{hint}</span> : null}
    </label>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono", className)}>{children}</span>;
}
