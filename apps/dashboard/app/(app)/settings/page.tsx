"use client";

import { Suspense, useEffect, useState } from "react";
import { api, ApiError, reportUrl, type ReportFormat } from "@/lib/api";
import { CAN_WRITE, MODE } from "@/lib/data-source";
import { formatDateTime, formatPercent } from "@/lib/format";
import { useApi, useFilters, useMeta } from "@/lib/hooks";
import { validateSettings } from "@/lib/settings-validation";
import type { EvalResult, Run, Settings } from "@/lib/types";
import { Async, Badge, Button, Card, EmptyState, Eyebrow, Field, InfoTip, PageHeader, SectionTitle, Skeleton, inputClass, linkButtonClass } from "@/components/ui";
import { cn } from "@/lib/cn";

type Errors = Record<string, string>;

function getPath(obj: unknown, path: string): number | boolean {
  return path.split(".").reduce<unknown>((o, k) => (o as Record<string, unknown>)[k], obj) as number | boolean;
}
function setPath<T>(obj: T, path: string, value: number | boolean): T {
  const clone = structuredClone(obj) as Record<string, unknown>;
  const keys = path.split(".");
  let cur = clone;
  for (const k of keys.slice(0, -1)) cur = cur[k] as Record<string, unknown>;
  cur[keys[keys.length - 1]] = value;
  return clone as T;
}

function Num({ s, path, label, hint, errors, step = "any", onChange, disabled }: { s: Settings; path: string; label: string; hint?: string; errors: Errors; step?: string; onChange: (path: string, v: number) => void; disabled: boolean }) {
  return (
    <Field label={label} hint={hint} error={errors[path]}>
      <input type="number" step={step} disabled={disabled} aria-invalid={!!errors[path]} data-testid={`setting-${path}`} className={cn(inputClass, "w-full font-mono", errors[path] && "border-destructive")} value={Number(getPath(s, path))} onChange={(e) => onChange(path, e.target.value === "" ? NaN : Number(e.target.value))} />
    </Field>
  );
}

// ------------------------------------------------------------------ settings form
function SettingsForm({ initial, onSaved }: { initial: Settings; onSaved: () => void }) {
  const [s, setS] = useState<Settings>(initial);
  const [server, setServer] = useState<Errors>({});
  const [status, setStatus] = useState<{ tone: "success" | "destructive"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const local = validateSettings(s);
  const errors = { ...server, ...local };
  const invalid = Object.keys(local).length > 0;
  const edit = (path: string, v: number) => { setS((p) => setPath(p, path, v)); setServer({}); setStatus(null); };
  const ro = !CAN_WRITE;
  const p = { s, errors, onChange: edit, disabled: ro };

  const save = async () => {
    setSaving(true);
    setStatus(null);
    try {
      await api.saveSettings(s);
      setStatus({ tone: "success", text: "Saved. Re-run the pipeline to apply the new assumptions." });
      onSaved();
    } catch (e) {
      if (e instanceof ApiError && e.fields) setServer(e.fields);
      setStatus({ tone: "destructive", text: e instanceof Error ? e.message : "Could not save" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="space-y-6" data-testid="settings-form" onSubmit={(e) => { e.preventDefault(); if (!invalid) void save(); }}>
      <Card className="p-5">
        <SectionTitle eyebrow="Impact" title="Revenue-at-risk assumptions" info="These numbers turn blocked sessions into rupees. They are assumptions, not measurements: change them to match what you know about your store." />
        <div className="grid gap-4 sm:grid-cols-3">
          <Num {...p} path="impact.recoverable_rate.low" label="Recoverable rate · low" hint="0 to 1" step="0.01" />
          <Num {...p} path="impact.recoverable_rate.base" label="Recoverable rate · base" hint="Share of blocked sessions that would buy if unblocked" step="0.01" />
          <Num {...p} path="impact.recoverable_rate.high" label="Recoverable rate · high" step="0.01" />
          <Num {...p} path="impact.p_stage_band" label="Stage probability band" hint="± uncertainty, 0 to 0.9" step="0.05" />
          <Num {...p} path="impact.default_aov_inr" label="Default order value (₹)" hint="Used when there are no orders to average" />
          <Num {...p} path="impact.agent_vs_human_factor" label="Agent vs human factor" hint="0.1 to 5" step="0.1" />
          <Num {...p} path="impact.min_sample" label="Minimum sample" hint="Blockers below this are greyed out" step="1" />
          <Num {...p} path="impact.effort_weights.S" label="Effort weight · S" step="0.5" />
          <Num {...p} path="impact.effort_weights.M" label="Effort weight · M" step="0.5" />
          <Num {...p} path="impact.effort_weights.L" label="Effort weight · L" step="0.5" />
        </div>
      </Card>
      <Card className="p-5">
        <SectionTitle eyebrow="Thresholds" title="Detection and significance" />
        <div className="grid gap-4 sm:grid-cols-3">
          <Num {...p} path="thresholds.slow_response_ms" label="Slow response (ms)" hint="Responses slower than this count as B13" step="100" />
          <Num {...p} path="thresholds.significance_min_sessions" label="Min sessions per window" hint="Before/After shows 'not enough data' below this" step="10" />
        </div>
      </Card>
      <Card className="p-5">
        <SectionTitle eyebrow="Identification" title="How agents are told apart" info="Signature checks give Verified; user agents give Declared; weighted behavioural signals give Suspected when the total reaches the threshold." />
        <div className="grid gap-4 sm:grid-cols-3">
          <Num {...p} path="identification.signature.clock_skew_s" label="Signature clock skew (s)" step="1" />
          <Num {...p} path="identification.signature.key_cache_ttl_s" label="Key cache TTL (s)" step="60" />
          <Num {...p} path="identification.suspicion.threshold" label="Suspicion threshold" hint="1 to 100" step="1" />
          <Num {...p} path="identification.suspicion.page_velocity_per_min" label="Page velocity / min" step="1" />
          <Num {...p} path="identification.sessions.timeout_min_human" label="Human session timeout (min)" step="1" />
          <Num {...p} path="identification.sessions.timeout_min_agent" label="Agent session timeout (min)" step="1" />
        </div>
        <h3 className="mb-3 mt-6 font-mono text-xs uppercase tracking-widest text-muted-foreground">Suspicion weights</h3>
        <div className="grid gap-4 sm:grid-cols-3">
          {Object.keys(s.identification.suspicion.weights).map((k) => (
            <Num key={k} {...p} path={`identification.suspicion.weights.${k}`} label={k.replace(/_/g, " ")} step="1" />
          ))}
        </div>
      </Card>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" data-testid="save-settings" disabled={invalid || saving || ro}>{saving ? "Saving…" : "Save settings"}</Button>
        <Button variant="secondary" onClick={() => { setS(initial); setServer({}); setStatus(null); }} disabled={ro}>Reset</Button>
        {invalid && <span role="alert" className="text-sm text-destructive" data-testid="settings-invalid">Fix {Object.keys(local).length} invalid value(s) to save.</span>}
        {ro && <span className="text-sm text-muted-foreground">Read-only demo snapshot: settings cannot be changed.</span>}
        {status && <span role="status" data-testid="settings-status" className={cn("text-sm", status.tone === "success" ? "text-success" : "text-destructive")}>{status.text}</span>}
      </div>
    </form>
  );
}

// ------------------------------------------------------------------ runs
function RunPanel() {
  const { meta, reload } = useMeta();
  const [run, setRun] = useState<Run | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const activeId = run && (run.status === "running" || run.status === "queued") ? run.run_id : null;

  useEffect(() => {
    if (!activeId) return;
    const t = setInterval(() => {
      api.run(activeId).then((r) => {
        setRun(r);
        if (r.status !== "running" && r.status !== "queued") reload();
      }).catch(() => undefined);
    }, 800);
    return () => clearInterval(t);
  }, [activeId, reload]);

  const start = async (kind: "pipeline" | "replay") => {
    setStarting(true);
    setErr(null);
    try {
      const acc = kind === "pipeline" ? await api.runPipeline() : await api.runReplays({ top_n: 3 });
      setRun(await api.run(acc.run_id));
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not start the run");
    } finally {
      setStarting(false);
    }
  };

  const shown = run ?? meta?.last_run ?? null;
  const busy = starting || !!activeId;
  return (
    <Card className="p-5" data-testid="run-panel">
      <SectionTitle eyebrow="Pipeline" title="Run analysis" info="The pipeline identifies agents, builds sessions, diagnoses blockers and estimates impact. Replays re-run failing journeys with a test agent to confirm blockers." />
      <div className="flex flex-wrap gap-3">
        <Button data-testid="run-pipeline" disabled={busy || !CAN_WRITE} onClick={() => void start("pipeline")}>Run pipeline</Button>
        <Button variant="secondary" data-testid="run-replays" disabled={busy || !CAN_WRITE} onClick={() => void start("replay")}>Run replays (top 3)</Button>
      </div>
      {!CAN_WRITE && <p className="mt-3 text-sm text-muted-foreground">Read-only demo snapshot: runs are disabled.</p>}
      {err && <p role="alert" className="mt-3 text-sm text-destructive">{err}</p>}
      {shown && (
        <div className="mt-4" data-testid="run-status">
          <p className="flex flex-wrap items-center gap-2 text-sm">
            <Badge tone={shown.status === "succeeded" ? "success" : shown.status === "failed" ? "destructive" : "primary"}>{shown.kind} · {shown.status}</Badge>
            <span className="font-mono text-xs text-muted-foreground">{shown.run_id}{shown.finished_at ? ` · finished ${formatDateTime(shown.finished_at)}` : ""}</span>
          </p>
          <ol className="mt-3 space-y-1.5 text-sm">
            {shown.steps.map((st) => (
              <li key={st.name} className="flex items-center gap-2"><span aria-hidden className={cn("h-2 w-2 rounded-full", st.status === "succeeded" ? "bg-success" : st.status === "failed" ? "bg-destructive" : st.status === "running" ? "animate-pulse bg-primary" : "bg-muted-foreground")} />{st.name}<span className="text-xs text-muted-foreground">{st.status}{st.message ? ` · ${st.message}` : ""}</span></li>
            ))}
          </ol>
          {shown.error && <p role="alert" className="mt-2 text-sm text-destructive">{shown.error}</p>}
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ report
function ReportPanel() {
  const { filters } = useFilters();
  const formats: { f: ReportFormat; label: string }[] = [{ f: "md", label: "Markdown" }, { f: "pdf", label: "PDF" }, { f: "png", label: "PNG summary" }];
  return (
    <Card className="p-5" data-testid="report-panel">
      <SectionTitle eyebrow="Export" title="Agent Readiness Report" info="A shareable summary of identity coverage, blockers, revenue at risk and the recommended fixes for the selected filters." />
      <div className="flex flex-wrap gap-3">
        {formats.map(({ f, label }) => {
          const url = reportUrl(f, filters);
          return url ? (
            <a key={f} href={url} download={f === "md" ? "agent-readiness-report.md" : undefined} target="_blank" rel="noreferrer" data-testid={`report-${f}`} className={linkButtonClass(f === "md" ? "primary" : "secondary")}>Download {label}</a>
          ) : (
            <span key={f} data-testid={`report-${f}-disabled`} aria-disabled="true" className={cn(linkButtonClass("secondary"), "cursor-not-allowed opacity-50")} title={`${label} export needs the live API (${MODE} mode)`}>{label} (live API only)</span>
          );
        })}
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ eval
function EvalPanel() {
  const state = useApi("eval", () => api.eval());
  const pct = (n: number) => formatPercent(n, 1);
  return (
    <Card className="p-5" data-testid="eval-panel">
      <SectionTitle eyebrow="Accuracy" title="Evaluation results" info="How well the pipeline does on a labelled synthetic dataset where the right answers are known. Real traffic will be messier." />
      <Async state={state} skeleton={<Skeleton className="h-40" />} empty={<EmptyState title="No evaluation yet" hint="Run agentlens eval to measure identification and diagnosis accuracy." />}>
        {(e: EvalResult) => (
          <div className="space-y-4">
            <p className="text-xs text-muted-foreground">Dataset <span className="font-mono">{e.dataset}</span> · {formatDateTime(e.ts)}</p>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[
                ["Identity accuracy", pct(e.identification.tier_accuracy)],
                ["Verified precision", pct(e.identification.verified_precision)],
                ["Diagnosis top-1", pct(e.diagnosis.top1_accuracy)],
                ["Replay confirmed", pct(e.replay.confirmation_rate)],
              ].map(([k, v]) => <div key={k} className="rounded-md border border-border p-3"><p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">{k}</p><p className="mt-1 font-mono text-2xl font-medium">{v}</p></div>)}
            </div>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">{e.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          </div>
        )}
      </Async>
    </Card>
  );
}

function Limitations() {
  return (
    <Card className="border-warning/50 p-5" data-testid="limitations">
      <Eyebrow className="mb-2 text-warning">Honest limitations</Eyebrow>
      <h2 className="font-display text-xl font-bold tracking-tight">What this dashboard cannot see</h2>
      <ul className="mt-3 list-disc space-y-2 pl-5 text-sm">
        <li>Only agents that sign their requests (Verified) or name themselves (Declared) are attributed with confidence. Agents that look like ordinary browsers can only be Suspected from behaviour, and some will be missed or wrongly flagged.</li>
        <li>Identity coverage is therefore a lower bound. The share of agent traffic we cannot name is shown on the Overview.</li>
        <li>Revenue at risk is an estimate built from the assumptions above, not an accounting figure.</li>
        <li>Before / After shows that metrics moved, not that your change caused it.</li>
        <li>Blockers confirmed by a replay are stronger evidence than blockers inferred from logs alone.</li>
      </ul>
    </Card>
  );
}

function SettingsBody() {
  const state = useApi("settings", () => api.settings());
  return (
    <>
      <PageHeader eyebrow="Settings & Report" title="Tune it and share it" description="Edit the assumptions behind every number, run the analysis, and export the report." />
      <div className="space-y-6">
        <div className="grid gap-6 lg:grid-cols-2"><RunPanel /><ReportPanel /></div>
        <EvalPanel />
        <Async state={state} skeleton={<Skeleton className="h-96" />}>{(s) => <SettingsForm initial={s} onSaved={state.reload} />}</Async>
        <Limitations />
        <p className="flex items-center gap-2 text-xs text-muted-foreground">Data mode: <span className="font-mono">{MODE}</span><InfoTip text="api = live FastAPI backend; mocks = built-in fixtures; demo = read-only static snapshot." /></p>
      </div>
    </>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <SettingsBody />
    </Suspense>
  );
}
