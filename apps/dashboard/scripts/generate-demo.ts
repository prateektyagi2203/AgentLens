/**
 * Writes the static demo snapshot (public/demo/**) from the mock backend.
 * Run with `pnpm --filter @agentlens/dashboard generate:demo`.
 * `agentlens export-snapshot` will later produce the same file layout from the real backend (docs/api-contract.md, "Demo snapshot").
 */
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { mockRequest, resetMockState } from "../lib/fixtures/handler";
import { REPLAY_ROWS, replayScenes } from "../lib/fixtures/replays";
import { SESSIONS } from "../lib/fixtures/sessions";
import { BLOCKERS } from "../lib/fixtures/catalog";
import { slug } from "../lib/filters";
import type { AgentList, Funnel, Meta, Segment, StageId, StageBlocker } from "../lib/types";
import { renderScene } from "./scene-svg";

const OUT = join(process.cwd(), "public", "demo");
const FULL = { from: "2026-11-05", to: "2026-11-18" };
const BEFORE = { from: "2026-11-05", to: "2026-11-11" };
const AFTER = { from: "2026-11-12", to: "2026-11-18" };

function call<T>(path: string, q: Record<string, string> = {}): T {
  const res = mockRequest("GET", path, q);
  if (res.status !== 200) throw new Error(`${path} -> ${res.status} ${JSON.stringify(res.data)}`);
  return res.data as T;
}

function write(file: string, data: unknown) {
  const p = join(OUT, file);
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, typeof data === "string" ? data : JSON.stringify(data, null, 1));
}

rmSync(OUT, { recursive: true, force: true });
resetMockState();

const meta = call<Meta>("/meta");
write("meta.json", { ...meta, demo_mode: true });
write("health.json", call("/health"));
write("overview.json", call("/overview", FULL));

// Snapshots that are not window-clippable client-side use the hero "before the fix" window.
const agents = call<AgentList>("/agents", BEFORE);
write("agents.json", agents);
for (const a of agents.items) {
  write(`agents/${slug(a.operator)}/${slug(a.agent_name)}.json`, call(`/agents/${encodeURIComponent(a.operator)}/${encodeURIComponent(a.agent_name)}`, BEFORE));
}

const segments: Segment[] = ["all_agents", "verified", "declared", "suspected", "humans"];
const series = {} as Record<Segment, Funnel["primary"]>;
const stageBlockers = {} as Record<Segment, Record<StageId, StageBlocker[]>>;
let base: Funnel | null = null;
for (const seg of segments) {
  const f = call<Funnel>("/funnel", { ...BEFORE, segment: seg, compare: seg === "humans" ? "all_agents" : "humans" });
  series[seg] = f.primary;
  stageBlockers[seg] = f.stage_blockers;
  base ??= f;
}
if (!base) throw new Error("no funnel");
write("funnel.json", { window: base.window, stages: base.stages, series, stage_blockers: stageBlockers });

write("blockers.json", call("/blockers", BEFORE));
for (const b of BLOCKERS) write(`blockers/${b.id}.json`, call(`/blockers/${b.id}`, BEFORE));

write("sessions.json", { window: { ...FULL, days: 14 }, page: 1, page_size: SESSIONS.length, total: SESSIONS.length, items: SESSIONS });
for (const s of SESSIONS) write(`sessions/${s.session_id}.json`, call(`/sessions/${encodeURIComponent(s.session_id)}`));

write("replays.json", call("/replays"));
for (const r of REPLAY_ROWS) write(`replays/${r.replay_id}.json`, call(`/replays/${r.replay_id}`));
for (const sc of replayScenes()) write(`replays/${sc.replay_id}/step_${sc.n}.svg`, renderScene(sc));

write("compare.json", call("/compare", { a_from: BEFORE.from, a_to: BEFORE.to, b_from: AFTER.from, b_to: AFTER.to }));
write("annotations.json", call("/annotations"));
write("recommendations.json", call("/recommendations", BEFORE));
write("settings.json", call("/settings"));
write("eval.json", call("/eval/latest"));
write("site-checks.json", call("/site-checks", { to: BEFORE.to }));
if (meta.last_run) write(`runs/${meta.last_run.run_id}.json`, meta.last_run);
write("report.md", mockRequest("GET", "/report", { format: "md", ...BEFORE }).data as string);

console.log(`demo snapshot written to ${OUT}`);
