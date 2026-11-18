import type { Annotation, EvalResult, SiteCheck, Run } from "../types";

export const SEED_ANNOTATIONS: Annotation[] = [
  {
    annotation_id: "ann_0001",
    ts: "2026-11-08T09:00:00Z",
    type: "note",
    label: "Perplexity-User traffic ramps up",
    details: { source: "synthetic traffic mix v2" },
  },
  {
    annotation_id: "ann_0002",
    ts: "2026-11-12T06:30:00Z",
    type: "config_change",
    label: "Switched off pincode wall, OTP-before-cart and JS-only price",
    details: { toggles_off: ["F03", "F05", "F06"], source: "store /admin" },
  },
];

const checkTs = "2026-11-18T06:08:00Z";
const beforeTs = "2026-11-11T16:55:00Z";

export function siteChecks(phase: "before" | "after"): SiteCheck[] {
  const ts = phase === "before" ? beforeTs : checkTs;
  const ssr = phase === "after";
  return [
    {
      check_id: "chk_pdp_ssr_price", run_ts: ts, check_name: "pdp_ssr_price", target: "5 random product pages",
      result: ssr ? "pass" : "fail",
      details: { sampled: 5, found: ssr ? 5 : 0, message: ssr ? "Price found in server HTML on 5/5 sampled PDPs" : "Price not found in server HTML or JSON-LD on 5/5 sampled PDPs" },
    },
    {
      check_id: "chk_pdp_ssr_stock", run_ts: ts, check_name: "pdp_ssr_stock", target: "5 random product pages",
      result: ssr ? "pass" : "fail",
      details: { sampled: 5, found: ssr ? 5 : 0, message: ssr ? "Availability found in server HTML on 5/5 sampled PDPs" : "Availability missing from server HTML on 5/5 sampled PDPs" },
    },
    {
      check_id: "chk_jsonld_product", run_ts: ts, check_name: "jsonld_product", target: "5 random product pages",
      result: "warn", details: { sampled: 5, complete: 3, message: "JSON-LD Product present but availability missing on 2/5 sampled PDPs" },
    },
    {
      check_id: "chk_size_guide_format", run_ts: ts, check_name: "size_guide_format", target: "/size-guide/*",
      result: "fail", details: { sampled: 5, html_table: 0, message: "Size guide is image-only (image/png) on 5/5 sampled pages" },
    },
    {
      check_id: "chk_robots_txt", run_ts: ts, check_name: "robots_txt", target: "/robots.txt",
      result: "warn", details: { allowed: ["ChatGPT-User", "Claude-User", "Perplexity-User", "Googlebot"], disallowed: ["PerplexityBot"], message: "User-triggered agents allowed. PerplexityBot (search crawler) is disallowed." },
    },
  ];
}

export const EVAL_RESULT: EvalResult = {
  run_id: "eval_2026-11-18",
  ts: "2026-11-18T06:20:00Z",
  dataset: "tests/golden (2,000 sessions, seed 42)",
  identification: {
    tier_accuracy: 0.962,
    verified_precision: 1,
    verified_recall: 0.994,
    declared_precision: 0.981,
    declared_recall: 0.972,
    suspected_precision: 0.874,
    suspected_recall: 0.861,
    confusion: [
      [348, 2, 0, 0],
      [0, 801, 9, 14],
      [0, 6, 231, 31],
      [0, 5, 21, 532],
    ],
  },
  diagnosis: {
    top1_accuracy: 0.908,
    coverage: 0.887,
    per_blocker: [
      { blocker_id: "B05", precision: 0.97, recall: 0.95, f1: 0.96, support: 240 },
      { blocker_id: "B03", precision: 0.94, recall: 0.93, f1: 0.935, support: 160 },
      { blocker_id: "B06", precision: 0.92, recall: 0.9, f1: 0.91, support: 120 },
      { blocker_id: "B07", precision: 0.83, recall: 0.79, f1: 0.81, support: 100 },
      { blocker_id: "B09", precision: 0.95, recall: 0.92, f1: 0.935, support: 90 },
      { blocker_id: "B10", precision: 0.96, recall: 0.94, f1: 0.95, support: 90 },
      { blocker_id: "B08", precision: 0.88, recall: 0.86, f1: 0.87, support: 60 },
      { blocker_id: "B12", precision: 1, recall: 0.98, f1: 0.99, support: 50 },
    ],
  },
  impact: { mean_abs_pct_error: 0.11 },
  replay: { confirmation_rate: 0.875, completed: 8 },
  notes: [
    "Scores are measured on the labelled synthetic golden dataset, not on real shopper traffic.",
    "Suspected-tier precision is lower because behaviour is a weaker signal than a signature or a declared user agent.",
  ],
};

export const LAST_RUN: Run = {
  run_id: "run_20261118_0610",
  kind: "pipeline",
  status: "succeeded",
  started_at: "2026-11-18T06:08:00Z",
  finished_at: "2026-11-18T06:10:21Z",
  steps: ["ingest", "identify", "sessionize", "funnel", "diagnose", "impact", "recommend"].map((name, i) => ({
    name,
    status: "succeeded" as const,
    started_at: new Date(Date.parse("2026-11-18T06:08:00Z") + i * 20000).toISOString(),
    finished_at: new Date(Date.parse("2026-11-18T06:08:00Z") + i * 20000 + 19000).toISOString(),
    message: null,
  })),
  counts: { requests: 1_204_330, sessions: 52_944, agent_sessions: 8_460, blocker_hits: 7_990 },
  error: null,
};
