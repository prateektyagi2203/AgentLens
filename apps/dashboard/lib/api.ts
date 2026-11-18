import { filterSessions, filtersToQuery, slug, toSearch } from "./filters";
import { API_ORIGIN, API_URL, DEMO_BASE, MODE } from "./data-source";
import type {
  AgentDetail, AgentList, Annotation, AnnotationCreate, AnnotationList, BlockerDetail, BlockerId, BlockerList, Compare,
  CompareQuery, EvalResult, Filters, Funnel, FunnelSeries, FunnelStageDef, Health, Meta, Overview, RecommendationList,
  RecommendationPatchResult, ReplayDetail, ReplayList, ReplayRunRequest, Run, RunAccepted, Segment, SessionDetail,
  SessionList, SessionQuery, SessionRow, Settings, SiteCheckList, StageBlocker, StageId,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public fields?: Record<string, string>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Query = Record<string, string | number | boolean | undefined | null>;
const MOCK_LATENCY_MS = 120;

// ------------------------------------------------------------ transports
async function viaApi<T>(method: string, path: string, query: Query, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}${toSearch(query)}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network_error", `Cannot reach the AgentLens API at ${API_URL}. Start it with "agentlens serve", or run the dashboard with NEXT_PUBLIC_USE_MOCKS=1.`);
  }
  return parse<T>(res);
}

async function parse<T>(res: Response): Promise<T> {
  if (res.ok) return (res.status === 204 ? undefined : await res.json()) as T;
  let code = "http_error";
  let message = `Request failed (${res.status})`;
  let fields: Record<string, string> | undefined;
  try {
    const b = (await res.json()) as { error?: { code: string; message: string; fields?: Record<string, string> } };
    if (b.error) ({ code, message, fields } = b.error);
  } catch {
    /* body was not JSON */
  }
  throw new ApiError(res.status, code, message, fields);
}

async function viaMocks<T>(method: string, path: string, query: Query, body?: unknown): Promise<T> {
  const { mockRequest } = await import("./fixtures/handler");
  await new Promise((r) => setTimeout(r, MOCK_LATENCY_MS));
  const q = Object.fromEntries(
    Object.entries(query)
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => [k, String(v)]),
  );
  const res = mockRequest(method, path, q, body);
  if (res.status >= 400) {
    const e = (res.data as { error: { code: string; message: string; fields?: Record<string, string> } }).error;
    throw new ApiError(res.status, e.code, e.message, e.fields);
  }
  return res.data as T;
}

async function demoJson<T>(file: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${DEMO_BASE}/${file}`);
  } catch {
    throw new ApiError(0, "network_error", `Could not load demo snapshot ${file}.`);
  }
  if (!res.ok) throw new ApiError(res.status, "demo_missing", `Demo snapshot ${DEMO_BASE}/${file} is missing. Run "agentlens export-snapshot" (or pnpm generate:demo).`);
  return (await res.json()) as T;
}

const readonly = (): never => {
  throw new ApiError(405, "demo_readonly", "This is a read-only demo snapshot. Run the dashboard against the API or with mocks to make changes.");
};

// ------------------------------------------------------------ demo adapters
interface DemoFunnel {
  window: Funnel["window"];
  stages: FunnelStageDef[];
  series: Record<Segment, FunnelSeries>;
  stage_blockers: Record<Segment, Record<StageId, StageBlocker[]>>;
}

function demoFunnel(raw: DemoFunnel, f: Filters, compare?: Segment): Funnel {
  const segment = f.segment ?? "all_agents";
  return {
    window: raw.window,
    stages: raw.stages,
    primary: raw.series[segment],
    compare: raw.series[compare ?? "humans"],
    stage_blockers: raw.stage_blockers[segment],
  };
}

function demoOverview(o: Overview, f: Filters): Overview {
  const inWin = (d: string) => (!f.from || d >= f.from) && (!f.to || d <= f.to);
  return {
    ...o,
    timeseries: o.timeseries.filter((p) => inWin(p.date)),
    annotations: o.annotations.filter((a) => inWin(a.ts.slice(0, 10))),
  };
}

// ------------------------------------------------------------ generic dispatchers
async function get<T>(path: string, query: Query, demoFile: string, adapt?: (raw: never) => T): Promise<T> {
  if (MODE === "demo") {
    const raw = await demoJson<unknown>(demoFile);
    return adapt ? adapt(raw as never) : (raw as T);
  }
  return MODE === "mocks" ? viaMocks<T>("GET", path, query) : viaApi<T>("GET", path, query);
}

function write<T>(method: string, path: string, query: Query, body?: unknown): Promise<T> {
  if (MODE === "demo") return Promise.resolve(readonly());
  return MODE === "mocks" ? viaMocks<T>(method, path, query, body) : viaApi<T>(method, path, query, body);
}

const fq = (f: Filters): Query => filtersToQuery(f);
const enc = encodeURIComponent;

// ------------------------------------------------------------ typed API
export const api = {
  meta: () => get<Meta>("/meta", {}, "meta.json", (m: Meta) => ({ ...m, demo_mode: true })),
  health: () => get<Health>("/health", {}, "health.json"),
  overview: (f: Filters) => get<Overview>("/overview", fq(f), "overview.json", (o: Overview) => demoOverview(o, f)),
  agents: (f: Filters) => get<AgentList>("/agents", fq(f), "agents.json"),
  agent: (operator: string, name: string, f: Filters) =>
    get<AgentDetail>(`/agents/${enc(operator)}/${enc(name)}`, fq(f), `agents/${slug(operator)}/${slug(name)}.json`),
  funnel: (f: Filters, compare?: Segment) =>
    get<Funnel>("/funnel", { ...fq(f), compare }, "funnel.json", (raw: DemoFunnel) => demoFunnel(raw, f, compare)),
  blockers: (f: Filters) => get<BlockerList>("/blockers", fq(f), "blockers.json"),
  blocker: (id: BlockerId, f: Filters) => get<BlockerDetail>(`/blockers/${id}`, fq(f), `blockers/${id}.json`),
  sessions: (f: Filters, q: SessionQuery) =>
    get<SessionList>("/sessions", { ...fq(f), ...q }, "sessions.json", (raw: { window: SessionList["window"]; items: SessionRow[] }) => ({
      window: raw.window,
      ...filterSessions(raw.items, f, q),
    })),
  session: (id: string) => get<SessionDetail>(`/sessions/${enc(id)}`, {}, `sessions/${id}.json`),
  replays: () => get<ReplayList>("/replays", {}, "replays.json"),
  replay: (id: string) => get<ReplayDetail>(`/replays/${enc(id)}`, {}, `replays/${id}.json`),
  compare: (q: CompareQuery) => get<Compare>("/compare", { ...q }, "compare.json"),
  annotations: () => get<AnnotationList>("/annotations", {}, "annotations.json"),
  createAnnotation: (a: AnnotationCreate) => write<Annotation>("POST", "/annotations", {}, a),
  recommendations: (f: Filters) => get<RecommendationList>("/recommendations", fq(f), "recommendations.json"),
  markFixed: (recId: string) => write<RecommendationPatchResult>("PATCH", `/recommendations/${enc(recId)}`, {}, { status: "fixed" }),
  settings: () => get<Settings>("/settings", {}, "settings.json"),
  saveSettings: (s: Settings) => write<Settings>("PUT", "/settings", {}, s),
  eval: () => get<EvalResult>("/eval/latest", {}, "eval.json"),
  siteChecks: () => get<SiteCheckList>("/site-checks", {}, "site-checks.json"),
  runPipeline: () => write<RunAccepted>("POST", "/pipeline/run", {}),
  runReplays: (r: ReplayRunRequest = {}) => write<RunAccepted>("POST", "/replays/run", {}, r),
  run: (id: string) => get<Run>(`/runs/${enc(id)}`, {}, `runs/${id}.json`),
};

// ------------------------------------------------------------ helpers
/** Absolute URL for a screenshot/asset returned by the API. */
export function assetUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (/^https?:\/\//.test(url)) return url;
  return MODE === "api" && url.startsWith("/api/") ? `${API_ORIGIN}${url}` : url;
}

export type ReportFormat = "md" | "pdf" | "png";

/** Link to the exportable Agent Readiness Report; null when the format is unavailable in this data mode. */
export function reportUrl(format: ReportFormat, f: Filters): string | null {
  if (MODE === "api") return `${API_URL}/report${toSearch({ format, ...fq(f) })}`;
  return format === "md" ? `${DEMO_BASE}/report.md` : null;
}
