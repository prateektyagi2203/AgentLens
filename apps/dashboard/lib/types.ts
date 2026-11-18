/**
 * TypeScript mirror of docs/api-contract.md (1:1, snake_case on the wire).
 * Money is always a number in rupees (INR). Rates/shares are fractions 0..1.
 * Dates are `YYYY-MM-DD` (day buckets, inclusive); timestamps are ISO-8601 UTC strings.
 */

// ---------------------------------------------------------------- enums
export type Segment = "all_agents" | "verified" | "declared" | "suspected" | "humans";
export type IdentityTier = "verified" | "declared" | "suspected" | "human";
export type AgentClass = "user_fetcher" | "browsing_agent" | "search_crawler" | "training_crawler";
export type StageId = "S1" | "S2" | "S3" | "S4" | "S5" | "S6" | "S7" | "S8";
export type BlockerId =
  | "B01" | "B02" | "B03" | "B04" | "B05" | "B06" | "B07" | "B08"
  | "B09" | "B10" | "B11" | "B12" | "B13" | "B14" | "B15" | "B16" | "B99";
export type Effort = "S" | "M" | "L";
export type Owner = "Eng" | "Product" | "Security" | "Content";
export type SignatureStatus = "valid" | "invalid_sig" | "expired" | "unknown_key" | "fetch_failed" | "none";
export type ReplayVerdict = "confirmed" | "not_confirmed" | "inconclusive";
/** `pending` = a replay is queued/running; `not_run` = none exists for the blocker. */
export type ReplayStatus = ReplayVerdict | "pending" | "not_run";
export type AnnotationType = "config_change" | "marked_fixed" | "note";
export type DiagnosisMethod = "rule" | "llm" | "none";
export type RunStatus = "queued" | "running" | "succeeded" | "failed";

// ---------------------------------------------------------------- filters
/** Query params accepted by every data endpoint (all optional). */
export interface Filters {
  from?: string;
  to?: string;
  segment?: Segment;
  operator?: string;
  agent_class?: AgentClass;
}

export interface DateWindow {
  from: string;
  to: string;
  days: number;
}

export interface RiskRange {
  low: number;
  base: number;
  high: number;
}

export interface ApiErrorBody {
  error: { code: string; message: string; fields?: Record<string, string> };
}

// ---------------------------------------------------------------- /meta, /health, runs
export interface RunStep {
  name: string;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  started_at: string | null;
  finished_at: string | null;
  message: string | null;
}

export interface Run {
  run_id: string;
  kind: "pipeline" | "replay";
  status: RunStatus;
  started_at: string | null;
  finished_at: string | null;
  steps: RunStep[];
  counts: Record<string, number>;
  error: string | null;
}

export interface RunAccepted {
  run_id: string;
  status: RunStatus;
}

export interface Meta {
  version: string;
  demo_mode: boolean;
  store_name: string;
  currency: "INR";
  operators: string[];
  agent_classes: AgentClass[];
  segments: Segment[];
  date_bounds: { min: string; max: string } | null;
  /** Window the dashboard should open with when the URL has no from/to. */
  default_window: { from: string; to: string } | null;
  last_run: Run | null;
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  time: string;
  db: "ok" | "missing" | "error";
  demo_mode: boolean;
}

// ---------------------------------------------------------------- annotations
export interface Annotation {
  annotation_id: string;
  ts: string;
  type: AnnotationType;
  label: string;
  details: Record<string, unknown>;
}

export interface AnnotationList {
  items: Annotation[];
}

export interface AnnotationCreate {
  ts?: string;
  type: AnnotationType;
  label: string;
  details?: Record<string, unknown>;
}

// ---------------------------------------------------------------- recommendations
export interface Recommendation {
  rec_id: string;
  run_id: string;
  blocker_id: BlockerId;
  blocker_name: string;
  title: string;
  body: string;
  why_it_helps: string;
  how_to_verify: string;
  verify_metric: string;
  effort: Effort;
  owner: Owner;
  priority_score: number;
  risk_inr_base: number;
  status: "open" | "fixed";
  fixed_annotation_id: string | null;
  llm_explanation: string | null;
}

export interface RecommendationList {
  items: Recommendation[];
}

export interface RecommendationPatch {
  status: "fixed";
}

export interface RecommendationPatchResult {
  recommendation: Recommendation;
  annotation: Annotation;
}

// ---------------------------------------------------------------- overview
export interface OverviewKpis {
  agent_sessions: number;
  total_sessions: number;
  agent_share: number;
  agent_converted: number;
  agent_conversion: number;
  human_sessions: number;
  human_conversion: number;
  agent_revenue_inr: number;
  risk_inr: RiskRange;
  risk_pct_of_agent_revenue: number;
  identity_coverage: number;
  verified_share: number;
  diagnosis_coverage: number;
}

export interface TimeSeriesPoint {
  date: string;
  human: number;
  verified: number;
  declared: number;
  suspected: number;
  agent_conversion: number;
  human_conversion: number;
}

export interface TierMix {
  verified: number;
  declared: number;
  suspected: number;
}

export interface OperatorMixItem {
  operator: string;
  sessions: number;
  share: number;
  tier_mix: TierMix;
}

export interface ClassMixItem {
  agent_class: AgentClass;
  sessions: number;
  share: number;
}

export interface TopFix {
  rec_id: string;
  blocker_id: BlockerId;
  blocker_name: string;
  title: string;
  risk_inr_base: number;
  effort: Effort;
  priority_score: number;
  owner: Owner;
  status: "open" | "fixed";
}

export interface Overview {
  window: DateWindow;
  kpis: OverviewKpis;
  /** Relative change vs the preceding window of equal length; null when it has no data. */
  kpi_deltas: Partial<Record<keyof OverviewKpis, number | null>>;
  timeseries: TimeSeriesPoint[];
  annotations: Annotation[];
  operator_mix: OperatorMixItem[];
  class_mix: ClassMixItem[];
  top_fixes: TopFix[];
}

// ---------------------------------------------------------------- agents
export interface TopBlockerRef {
  blocker_id: BlockerId;
  name: string;
  share_of_failed: number;
}

export interface AgentRow {
  operator: string;
  agent_name: string;
  agent_class: AgentClass;
  sessions: number;
  share_of_agent_sessions: number;
  pages_per_session: number;
  conversion: number;
  tier_mix: TierMix;
  top_blocker: TopBlockerRef | null;
  signature_status_counts: Record<SignatureStatus, number>;
  last_seen: string;
}

export interface CrawlerRow {
  operator: string;
  agent_name: string;
  agent_class: "search_crawler" | "training_crawler";
  requests: number;
  pages: number;
  robots_txt_fetched: boolean;
  last_seen: string;
}

export interface AgentList {
  window: DateWindow;
  items: AgentRow[];
  crawlers: CrawlerRow[];
}

export interface AgentDetail {
  window: DateWindow;
  agent: AgentRow;
  identity: {
    user_agent_example: string | null;
    signature_agent: string | null;
    ip_match_rate: number | null;
    avg_identity_confidence: number;
  };
  trend: { date: string; sessions: number; conversion: number }[];
  blockers: { blocker_id: BlockerId; name: string; sessions: number; share_of_failed: number }[];
  recent_sessions: SessionRow[];
}

// ---------------------------------------------------------------- funnel
export interface FunnelStageDef {
  id: StageId;
  name: string;
}

export interface FunnelStep {
  stage_id: StageId;
  name: string;
  sessions: number;
  /** sessions(n) / sessions(n-1); 1 for S1. */
  step_conversion: number;
  /** 1 - step_conversion; 0 for S1. */
  drop_off: number;
  /** sessions(n) / sessions(S1). */
  overall_conversion: number;
}

export interface FunnelSeries {
  segment: Segment;
  sessions: number;
  conversion: number;
  steps: FunnelStep[];
}

export interface StageBlocker {
  blocker_id: BlockerId;
  name: string;
  sessions_blocked: number;
  share_of_failed: number;
  risk_inr_base: number;
}

export interface Funnel {
  window: DateWindow;
  stages: FunnelStageDef[];
  primary: FunnelSeries;
  compare: FunnelSeries;
  /** Blockers (of the `primary` segment) that end sessions at each stage; empty array if none. */
  stage_blockers: Record<StageId, StageBlocker[]>;
}

// ---------------------------------------------------------------- blockers
export interface BlockerAssumptions {
  recoverable_rate: RiskRange;
  p_stage_band: number;
  default_aov_inr: number;
  window_days: number;
  /** 30 / window_days */
  k: number;
  min_sample: number;
}

export interface BlockerItem {
  blocker_id: BlockerId;
  name: string;
  stage: StageId;
  sessions_blocked: number;
  share_of_failed: number;
  risk_inr: RiskRange;
  replay_status: ReplayStatus;
  effort: Effort;
  /** Risk_base / effort weight (S=1, M=2, L=4). */
  priority_score: number;
  low_confidence: boolean;
}

export interface BlockerList {
  window: DateWindow;
  total_risk_base_inr: number;
  total_failed_agent_sessions: number;
  diagnosis_coverage: number;
  assumptions: BlockerAssumptions;
  items: BlockerItem[];
}

export type EvidenceItem =
  | { type: "request"; request_id: string; summary: string }
  | { type: "site_check"; check: string; result: "pass" | "fail" | "warn" | "missing" };

export interface BlockerDetail {
  window: DateWindow;
  blocker: BlockerItem;
  description: string;
  detection: string;
  evidence: {
    top_error_codes: { code: string; count: number; share: number }[];
    example_requests: { request_id: string; summary: string; count: number }[];
    site_checks: SiteCheck[];
  };
  risk_breakdown: {
    sessions_blocked: number;
    recoverable_rate: number;
    p_stage: number;
    aov_inr: number;
    k: number;
  };
  trend: { date: string; sessions_blocked: number }[];
  sample_sessions: SessionRow[];
  replays: ReplayRow[];
  recommendation: Recommendation | null;
}

// ---------------------------------------------------------------- sessions
export interface SessionRow {
  session_id: string;
  start_ts: string;
  duration_s: number;
  request_count: number;
  page_count: number;
  identity_tier: IdentityTier;
  operator: string;
  agent_name: string;
  agent_class: AgentClass | "human";
  identity_confidence: number;
  entry_page: string;
  exit_page: string;
  max_stage: StageId | null;
  converted: boolean;
  order_value_inr: number | null;
  terminal_blocker_id: BlockerId | null;
  terminal_blocker_name: string | null;
  blocker_confidence: number | null;
  diagnosis_method: DiagnosisMethod;
}

export interface SessionQuery {
  page?: number;
  page_size?: number;
  q?: string;
  identity_tier?: IdentityTier;
  blocker_id?: BlockerId;
  max_stage?: StageId;
  converted?: boolean;
  sort?: "start_ts" | "duration_s" | "request_count" | "order_value_inr";
  order?: "asc" | "desc";
}

export interface SessionList {
  window: DateWindow;
  page: number;
  page_size: number;
  total: number;
  items: SessionRow[];
}

export interface SessionRequest {
  request_id: string;
  ts: string;
  offset_ms: number;
  method: string;
  path: string;
  status: number;
  duration_ms: number;
  page_type: string | null;
  error_code: string | null;
  stage_id: StageId | null;
  is_asset: boolean;
}

export interface FiredRule {
  blocker_id: BlockerId;
  name: string;
  stage: StageId;
  confidence: number;
  is_terminal: boolean;
  evidence: EvidenceItem[];
}

export interface SessionDetail {
  session: SessionRow;
  identity: {
    signature_status: SignatureStatus;
    signature_agent: string | null;
    suspicion_score: number | null;
    user_agent: string;
    ip_match: boolean | null;
  };
  requests: SessionRequest[];
  stage_events: { stage_id: StageId; first_reached_ts: string }[];
  fired_rules: FiredRule[];
  replay_ids: string[];
}

// ---------------------------------------------------------------- replays
export interface ReplayRow {
  replay_id: string;
  blocker_id: BlockerId;
  blocker_name: string;
  source_session_id: string;
  mode: "fetch" | "browser";
  status: "queued" | "running" | "completed" | "failed";
  verdict: ReplayVerdict | null;
  started_at: string;
  finished_at: string | null;
  steps_count: number;
  verdict_explanation: string;
}

export interface ReplayStep {
  n: number;
  action: string;
  method: string | null;
  url: string;
  status: number | null;
  duration_ms: number;
  note: string;
  /** Absolute URL, or a root-relative path (`/api/...` is prefixed with the API origin by the client). */
  screenshot_url: string | null;
}

export interface NetworkLogEntry {
  ts: string;
  method: string;
  url: string;
  status: number;
  duration_ms: number;
  error_code: string | null;
}

export interface ReplayList {
  items: ReplayRow[];
}

export interface ReplayDetail {
  replay: ReplayRow;
  user_agent: string;
  signed_requests: boolean;
  steps: ReplayStep[];
  network_log: NetworkLogEntry[];
  explanation: string;
}

export interface ReplayRunRequest {
  blocker_id?: BlockerId;
  top_n?: number;
}

// ---------------------------------------------------------------- compare
export interface WindowSummary {
  window: DateWindow;
  sessions: number;
  converted: number;
  conversion: number;
  agent_revenue_inr: number;
  risk_inr: RiskRange;
  funnel: FunnelSeries;
  blocker_shares: {
    blocker_id: BlockerId;
    name: string;
    sessions_blocked: number;
    share_of_failed: number;
    risk_base_inr: number;
  }[];
}

export interface Significance {
  test: "two_proportion_z";
  enough_data: boolean;
  min_sessions: number;
  z: number | null;
  p_value: number | null;
  significant: boolean;
  note: string;
}

export interface SuggestedWindow {
  label: string;
  annotation_id: string;
  a: { from: string; to: string };
  b: { from: string; to: string };
}

export interface CompareQuery {
  a_from: string;
  a_to: string;
  b_from: string;
  b_to: string;
  segment?: Segment;
  operator?: string;
  agent_class?: AgentClass;
}

export interface Compare {
  segment: Segment;
  a: WindowSummary;
  b: WindowSummary;
  delta: {
    sessions: number;
    conversion_pp: number;
    conversion_relative: number | null;
    agent_revenue_inr: number;
    risk_base_inr: number;
  };
  significance: Significance;
  suggested_windows: SuggestedWindow[];
}

// ---------------------------------------------------------------- settings
export interface Settings {
  impact: {
    recoverable_rate: RiskRange;
    p_stage_band: number;
    default_aov_inr: number;
    agent_vs_human_factor: number;
    min_sample: number;
    effort_weights: { S: number; M: number; L: number };
  };
  identification: {
    signature: { clock_skew_s: number; key_cache_ttl_s: number; offline_mode: boolean };
    suspicion: {
      threshold: number;
      page_velocity_per_min: number;
      weights: {
        no_beacon_with_browser_ua: number;
        no_assets: number;
        headless_hint: number;
        missing_sec_fetch: number;
        regular_timing: number;
        high_velocity: number;
        deep_link_cart_rush: number;
        atypical_accept: number;
        invalid_signature: number;
      };
    };
    sessions: { timeout_min_human: number; timeout_min_agent: number };
  };
  thresholds: {
    slow_response_ms: number;
    significance_min_sessions: number;
  };
}

// ---------------------------------------------------------------- eval + site checks
export interface EvalBlockerMetric {
  blocker_id: BlockerId;
  precision: number;
  recall: number;
  f1: number;
  support: number;
}

export interface EvalResult {
  run_id: string;
  ts: string;
  dataset: string;
  identification: {
    tier_accuracy: number;
    verified_precision: number;
    verified_recall: number;
    declared_precision: number;
    declared_recall: number;
    suspected_precision: number;
    suspected_recall: number;
    /** rows = expected tier, cols = predicted tier, order [verified, declared, suspected, human] */
    confusion: number[][];
  };
  diagnosis: {
    top1_accuracy: number;
    coverage: number;
    per_blocker: EvalBlockerMetric[];
  };
  impact: { mean_abs_pct_error: number | null };
  replay: { confirmation_rate: number; completed: number };
  notes: string[];
}

export interface SiteCheck {
  check_id: string;
  run_ts: string;
  check_name: string;
  target: string;
  result: "pass" | "fail" | "warn";
  details: Record<string, unknown>;
}

export interface SiteCheckList {
  items: SiteCheck[];
}
