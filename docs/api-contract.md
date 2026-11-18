# AgentLens Dashboard API Contract (v1)

Status: normative for the M4 dashboard. The FastAPI backend (port 8100) **must implement exactly this**.
The dashboard mirrors it 1:1 in `apps/dashboard/lib/types.ts` (the TypeScript interface of every response is the
field-by-field schema; this document gives routes, semantics and examples). A reference implementation of every
endpoint (the "mock backend") lives in `apps/dashboard/lib/fixtures/handler.ts` and is covered by tests, so when this
text is ambiguous, `handler.ts` + `types.ts` are the tie-breaker.

Base URL: `http://localhost:8100/api` (dashboard env `NEXT_PUBLIC_API_URL`). CORS must allow `http://localhost:3101`.

## 1. Conventions

| Topic | Rule |
|---|---|
| Wire format | JSON, **snake_case**, UTF-8. `Content-Type: application/json` on bodies. |
| Money | Always a **number in rupees** (INR), e.g. `1260000` = ₹12.6 L. Never strings, never paise. The dashboard formats (lakh/crore). |
| Rates / shares | Fractions `0..1` (`0.31` = 31%). Percentage points (`conversion_pp`) are in pp (`4.0` = +4 pp). |
| Dates | Day buckets `YYYY-MM-DD`, **inclusive** on both ends. Timestamps ISO-8601 UTC (`2026-11-11T20:45:00Z`). |
| Stages | `S1` Landing/Search, `S2` Product page, `S3` Variant selected, `S4` Delivery check, `S5` Added to cart, `S6` Checkout started, `S7` Checkout submitted, `S8` Order placed. |
| Blockers | `B01` WAF block (S1), `B02` CAPTCHA (S6), `B03` JS-only price/stock (S2), `B04` missing structured data (S2), `B05` pincode wall (S5), `B06` login/OTP wall (S5), `B07` app-download interstitial (S2), `B08` out-of-stock dead end (S3), `B09` image-only size guide (S3), `B10` checkout validation failure (S7), `B11` unsupported payment step (S7), `B12` rate limited (S1), `B13` slow response/timeout (S1), `B14` robots.txt disallow (S1), `B15` price mismatch PDP vs cart (S6), `B16` broken link/404 (S2), `B99` unknown. |
| Identity tiers | `verified` (valid Web Bot Auth signature), `declared` (known agent UA), `suspected` (behavioural score), `human`. |
| Agent classes | `user_fetcher`, `browsing_agent`, `search_crawler`, `training_crawler`. Crawlers never become sessions (see `/agents.crawlers`). |
| Errors | Non-2xx: `{"error":{"code":"...","message":"...","fields":{"dotted.path":"msg"}}}` (`fields` only for 422). Codes: `validation_error` (422), `not_found` (404), `run_in_progress` (409), `bad_request` (400). |
| Empty data | A window with no sessions is **200** with zero counts / empty arrays, never 404. `/eval/latest` before any eval has run: 404 `not_found` (dashboard shows an empty state). |
| Lists | Wrapped objects (`{"items":[...]}`), never bare arrays. |

### 1.1 Global filters (query params on every data endpoint)

| Param | Values | Default |
|---|---|---|
| `from`, `to` | `YYYY-MM-DD` inclusive | the whole data range (`/meta.default_window`) |
| `segment` | `all_agents` \| `verified` \| `declared` \| `suspected` \| `humans` | `all_agents` |
| `operator` | exact operator name from `/meta.operators` (e.g. `OpenAI`) | all |
| `agent_class` | one of the agent classes | all |

Semantics:

* `segment=humans` selects human sessions; on **agent-only endpoints** (`/agents`, `/blockers`, `/recommendations`, `/agents/{..}`) it yields an empty population (zero rows), not an error.
* `operator`/`agent_class` only ever narrow agent sessions; combined with `segment=humans` they yield an empty set.
* Every response that depends on a window echoes it as `window: {from, to, days}` (resolved defaults applied).
* `/replays`, `/annotations`, `/settings`, `/eval/latest`, `/runs/{id}`, `/health`, `/meta` ignore filters.

## 2. Endpoint index

| # | Method + path | Response type (`lib/types.ts`) | Notes |
|---|---|---|---|
| 1 | `GET /meta` | `Meta` | operators, classes, date bounds, `demo_mode`, `last_run` (feeds the "Run pipeline" chip) |
| 2 | `GET /health` | `Health` | liveness; `db` = ok/missing/error |
| 3 | `GET /overview` | `Overview` | P1 |
| 4 | `GET /agents` | `AgentList` | P2 table + `crawlers` |
| 5 | `GET /agents/{operator}/{agent_name}` | `AgentDetail` | URL-encode both segments; 404 if no sessions in window/filters |
| 6 | `GET /funnel?compare=` | `Funnel` | P3; `compare` is a `Segment` (default `humans`) |
| 7 | `GET /blockers` | `BlockerList` | P4 hero, ranked |
| 8 | `GET /blockers/{id}` | `BlockerDetail` | `{id}` = `B01..B16`/`B99`; 404 otherwise |
| 9 | `GET /sessions` | `SessionList` | paginated (see 3.9) |
| 10 | `GET /sessions/{id}` | `SessionDetail` | 404 if unknown |
| 11 | `GET /replays` | `ReplayList` | not window-scoped |
| 12 | `GET /replays/{id}` | `ReplayDetail` | 404 if unknown |
| 13 | `GET /compare` | `Compare` | P7; params `a_from,a_to,b_from,b_to,segment,operator,agent_class` |
| 14 | `GET /annotations` | `AnnotationList` | sorted by `ts` asc |
| 15 | `POST /annotations` | `Annotation` (201) | body `AnnotationCreate` |
| 16 | `GET /recommendations` | `RecommendationList` | sorted by `priority_score` desc |
| 17 | `PATCH /recommendations/{rec_id}` | `RecommendationPatchResult` | body `{"status":"fixed"}` |
| 18 | `GET /settings` | `Settings` | |
| 19 | `PUT /settings` | `Settings` | full replacement; 422 with `fields` on invalid |
| 20 | `GET /report?format=md\|pdf\|png` | file download | `text/markdown`, `application/pdf`, `image/png`; filters apply |
| 21 | `GET /eval/latest` | `EvalResult` | |
| 22 | `GET /site-checks` | `SiteCheckList` | latest result per check; `to` filter selects the as-of date |
| 23 | `POST /pipeline/run` | `RunAccepted` (202) | 409 `run_in_progress` if one is active |
| 24 | `GET /runs/{id}` | `Run` | polled every 1 s by the dashboard while `queued`/`running` |
| 25 | `POST /replays/run` | `RunAccepted` (202) | body `ReplayRunRequest` (`{}` = top 5 blockers) |

## 3. Endpoint semantics

### 3.1 `GET /meta`
```json
{
  "version": "0.1.0", "demo_mode": false, "store_name": "Demo Store (synthetic)", "currency": "INR",
  "operators": ["Anthropic", "Google", "OpenAI", "Perplexity", "TestOperator", "Unidentified"],
  "agent_classes": ["user_fetcher", "browsing_agent", "search_crawler", "training_crawler"],
  "segments": ["all_agents", "verified", "declared", "suspected", "humans"],
  "date_bounds": {"min": "2026-11-05", "max": "2026-11-18"},
  "default_window": {"from": "2026-11-05", "to": "2026-11-18"},
  "last_run": { "run_id": "run_20261118_01", "kind": "pipeline", "status": "succeeded", "started_at": "…", "finished_at": "…", "steps": [], "counts": {}, "error": null }
}
```
`date_bounds`/`default_window`/`last_run` are `null` when there is no data / no run yet (empty-state: "No data yet. Run agentlens synth or visit the store.").

### 3.2 `GET /overview`
`kpis` (all over the filtered window):

* `agent_sessions`, `total_sessions` (**ignores** `segment` and `operator`/`agent_class`, i.e. all sessions in the date window), `agent_share = agent_sessions/total_sessions`.
* `agent_converted`, `agent_conversion = agent_converted/agent_sessions`; `human_sessions`, `human_conversion`.
* `agent_revenue_inr`: sum of `order_value_inr` of converted agent sessions in the window.
* `risk_inr {low,base,high}`: **monthly** revenue at risk (sum over blockers, see 4); `risk_pct_of_agent_revenue = risk_inr.base / (agent_revenue_inr * 30/days)`.
* `identity_coverage = (verified + declared agent sessions) / agent_sessions`; `verified_share = verified / agent_sessions`.
* `diagnosis_coverage`: share of failed agent sessions with a terminal blocker other than `B99`.

`kpi_deltas`: relative change `(now - prev)/prev` vs the preceding window of equal length, `null` when the previous window has no data. Keys are any `kpis` key (scalar keys only; `risk_inr` delta is on `base`).
`timeseries`: one point per day in the window: `human`, `verified`, `declared`, `suspected` (session counts) and `agent_conversion`, `human_conversion` (fractions). `annotations`: annotations whose `ts` day is in the window. `operator_mix` (agent sessions per operator incl. `tier_mix` counts, `share` of agent sessions), `class_mix` (**sessionised classes only**; crawlers are in `/agents.crawlers`), `top_fixes`: top 3 recommendations by `priority_score` (`status` = open|fixed).

### 3.3 `GET /agents`, `GET /agents/{operator}/{agent_name}`
`AgentRow.tier_mix` holds session counts per tier; `signature_status_counts` has **all six** statuses (`valid, invalid_sig, expired, unknown_key, fetch_failed, none`) as keys; `top_blocker` is the most frequent terminal blocker or `null`; `pages_per_session`/`conversion` as numbers/fractions. `crawlers[]` lists crawler agents by request volume (`requests`, `pages`, `robots_txt_fetched`). Detail adds identity facts, a daily `trend`, `blockers` (terminal blockers for that agent) and up to 10 `recent_sessions`.

### 3.4 `GET /funnel?compare=<segment>`
`primary` = the `segment` filter (default `all_agents`), `compare` = the `compare` param (default `humans`). Either may be `humans`. Each `FunnelSeries.steps` has all 8 stages in order. Per step: `sessions` (sessions that **reached at least** this stage; monotonically non-increasing), `step_conversion = sessions(n)/sessions(n-1)` (1 for S1), `drop_off = 1 - step_conversion` (0 for S1), `overall_conversion = sessions(n)/sessions(S1)`. `FunnelSeries.conversion = overall_conversion of S8`. `stage_blockers[S1..S8]` (always all eight keys, `[]` if none): the terminal blockers of the **primary** segment, grouped by the blocker's catalog stage (`BlockerItem.stage`), each with `sessions_blocked`, `share_of_failed` and `risk_inr_base`, sorted by `sessions_blocked` desc. The dashboard uses it for "click a stage → blockers at that stage".

### 3.5 `GET /blockers` and `GET /blockers/{id}`
```json
{
  "window": {"from": "2026-11-05", "to": "2026-11-11", "days": 7},
  "total_risk_base_inr": 2720000, "total_failed_agent_sessions": 4000, "diagnosis_coverage": 0.89,
  "assumptions": {"recoverable_rate": {"low": 0.4, "base": 0.6, "high": 0.8}, "p_stage_band": 0.25, "default_aov_inr": 2200, "window_days": 7, "k": 4.2857, "min_sample": 30},
  "items": [{
    "blocker_id": "B05", "name": "Pincode wall", "stage": "S5", "sessions_blocked": 1240, "share_of_failed": 0.31,
    "risk_inr": {"low": 670000, "base": 1260000, "high": 2020000},
    "replay_status": "confirmed", "effort": "S", "priority_score": 1260000, "low_confidence": false
  }]
}
```
* `share_of_failed = sessions_blocked / total_failed_agent_sessions`; failed = agent sessions that did not convert and have a terminal blocker (incl. `B99`).
* Items sorted by `risk_inr.base` desc (ties by `blocker_id`); `B99` last with zero risk. Blockers with 0 sessions are omitted from the list.
* `low_confidence = sessions_blocked < assumptions.min_sample` (dashboard greys the row and labels it "Low sample size").
* `replay_status`: `confirmed|not_confirmed|inconclusive` (latest replay verdict), `pending` (queued/running), `not_run`.
* `effort` is the catalog default (S/M/L) per blocker; `priority_score = risk_inr.base / effort_weights[effort]` (S=1, M=2, L=4 by default).
* `GET /blockers/{id}` for a blocker with no sessions in the window returns 200 with zeros (so a freshly fixed blocker still has a page). `evidence.top_error_codes` (count, share of that blocker's sessions), `example_requests` (grouped by summary, `count`), `site_checks` (related `SiteCheck`s), `risk_breakdown` (the five inputs of the impact formula for the base case), `trend` (daily `sessions_blocked`), `sample_sessions` (up to 6, newest first), `replays` (all for the blocker), `recommendation` (`null` for B99).

### 3.6 Impact formula (all INR figures)
For blocker *b* in a window of `days` days: `k = 30/days`, `AOV = agent_revenue_inr / agent_converted` (fallback `impact.default_aov_inr` when nobody converted), `L = sessions_blocked`, `p_stage` = estimated probability that a session which reached the blocking stage would have gone on to buy (the mock uses a fixed table per stage; the backend should estimate it from the human funnel: `humans reaching S8 / humans reaching that stage`).

```
risk_base = L × recoverable_rate.base × min(1, p_stage)                    × AOV × k
risk_low  = L × recoverable_rate.low  × min(1, p_stage × (1 − p_stage_band)) × AOV × k
risk_high = L × recoverable_rate.high × min(1, p_stage × (1 + p_stage_band)) × AOV × k
```
Rounded to whole rupees, per 30 days. `B99` risk is always 0. The backend may use its own `p_stage` estimator but **must** return `risk_breakdown` such that `sessions_blocked × recoverable_rate × p_stage × aov_inr × k` equals `blocker.risk_inr.base` (±1 rupee), and the dashboard displays that breakdown ("How the number is built").

### 3.7 `GET /replays`, `GET /replays/{id}`
`ReplayRow.status`: `queued|running|completed|failed`; `verdict` is `null` until completed. `ReplayStep.screenshot_url`: absolute URL or root-relative path; a root-relative `/api/...` path is resolved by the dashboard against the API origin (`http://localhost:8100`). Fetch-mode replays have `screenshot_url: null` for all steps (dashboard shows a text list). `network_log` is the HTTP log (`ts, method, url, status, duration_ms, error_code`). `signed_requests` tells whether the replay agent signed its requests (Web Bot Auth).

### 3.8 `GET /compare`
`a` and `b` are `WindowSummary` computed with the **same** segment/operator/agent_class filters. `delta.sessions = b - a`, `conversion_pp = (b.conversion - a.conversion) × 100`, `conversion_relative = (b - a)/a` or `null` if `a.conversion = 0`, `agent_revenue_inr = b - a`, `risk_base_inr = b.risk_inr.base - a.risk_inr.base`. `significance`: two-proportion z-test on agent conversion (pooled variance, two-sided), `test:"two_proportion_z"`. `enough_data = min(a.sessions, b.sessions) >= min_sessions` where `min_sessions = settings.thresholds.significance_min_sessions` (default 100); if false: `z = p_value = null`, `significant = false`, `note = "Not enough data: ..."`. `significant = p_value < 0.05`. `suggested_windows`: for each **non-note** annotation (`config_change`, `marked_fixed`) a pair of equal-length windows (up to 7 days) immediately before and from the annotation day, clipped to data bounds. `blocker_shares` of each window sorted by `risk_base_inr` desc.

### 3.9 `GET /sessions`
Extra query params: `page` (1-based, default 1), `page_size` (default 25, max 100), `q` (case-insensitive substring over `session_id, operator, agent_name, entry_page, exit_page, terminal_blocker_id, terminal_blocker_name`), `identity_tier`, `blocker_id` (terminal blocker), `max_stage`, `converted` (`true|false`), `sort` (`start_ts|duration_s|request_count|order_value_inr`, default `start_ts`), `order` (`asc|desc`, default `desc`). `segment` applies as in 1.1 and `humans` **is** allowed here (human sessions are listed with `identity_tier:"human"`, `agent_class:"human"`, `operator:"human", agent_name:"Browser (human)"`). `total` = rows matching all filters. `SessionRow.max_stage` = highest stage reached (`null` if none), `terminal_blocker_*`/`blocker_confidence` are `null` for converted sessions, `diagnosis_method` is `rule|llm|none`.

### 3.10 `GET /sessions/{id}`
`requests` ordered by time (`offset_ms` from session start; `is_asset` rows may be hidden by the UI), `stage_events` (first time each stage was reached), `fired_rules` (every blocker rule that matched, with `is_terminal` true for the one chosen; `evidence` items are `{"type":"request","request_id","summary"}` or `{"type":"site_check","check","result"}`), `identity.signature_status`, `replay_ids` (replays whose source is this session).

### 3.11 Annotations and recommendations
* `POST /annotations` body `{ts?, type: "config_change"|"marked_fixed"|"note", label, details?}`; `ts` defaults to now; 422 if `label`/`type` missing. Returns the created `Annotation` (201).
* `PATCH /recommendations/{rec_id}` (`rec_id` = `rec_<BLOCKER>`, e.g. `rec_B05`) with `{"status":"fixed"}`: sets the recommendation `status="fixed"`, **creates a `marked_fixed` annotation** (label `"Marked fixed: <rec.title>"`, `details {blocker_id, rec_id}`) and returns `{recommendation, annotation}`. Idempotent: a second call returns the same annotation. 422 for any other status, 404 for unknown/`B99`.
* `Recommendation`: `title, body, why_it_helps, how_to_verify, verify_metric` (e.g. "Step conversion S4 → S5 for agents"), `effort`, `owner` (`Eng|Product|Security|Content`), `priority_score`, `risk_inr_base`, `fixed_annotation_id`, `llm_explanation` (null unless an LLM ran).

### 3.12 `GET/PUT /settings`
`PUT` replaces the whole document and returns it. Validation (422 `validation_error`, `fields` keyed by dotted path, mirrored client-side in `lib/settings-validation.ts`):

| Path | Rule |
|---|---|
| `impact.recoverable_rate.{low,base,high}` | each `0..1`; `low <= base <= high` |
| `impact.p_stage_band` | `0..0.9` |
| `impact.default_aov_inr` | `1..10,000,000` |
| `impact.agent_vs_human_factor` | `0.1..5` |
| `impact.min_sample` | integer `1..100000` |
| `impact.effort_weights.{S,M,L}` | each `0.5..100`; `S <= M <= L` |
| `identification.signature.clock_skew_s` | `0..600` |
| `identification.signature.key_cache_ttl_s` | `60..86400` |
| `identification.suspicion.threshold` | `1..100` |
| `identification.suspicion.page_velocity_per_min` | `1..600` |
| `identification.suspicion.weights.*` | each `0..100` |
| `identification.sessions.timeout_min_{human,agent}` | integer `1..240` |
| `thresholds.slow_response_ms` | `100..60000` |
| `thresholds.significance_min_sessions` | `10..100000` |

Settings changes take effect on the next `POST /pipeline/run` (the dashboard says so).

### 3.13 Runs
`POST /pipeline/run` and `POST /replays/run` return **202** `{run_id, status}`; a second call while a run is active returns 409 `run_in_progress`. `GET /runs/{id}` returns `Run {run_id, kind: "pipeline"|"replay", status: queued|running|succeeded|failed, started_at, finished_at, steps[{name,status,started_at,finished_at,message}], counts{}, error}`. Pipeline step names (suggested): `ingest, sessionize, identify, diagnose, impact, recommend`; replay: `select, replay, verdict`. `/meta.last_run` is the most recent run of either kind.

### 3.14 `GET /report?format=md|pdf|png`
Agent Readiness Report for the current filters (default window = all data). Returns the file with `Content-Disposition: attachment; filename="agent-readiness-report.<ext>"`. `md` must contain: headline numbers, ranked blockers with INR range, replay evidence, recommendations, methodology, and the honest-limitations paragraph (PRD 11.4: identity coverage is partial; Verified is cryptographic, Declared is self-reported, Suspected is a heuristic). Unsupported format: 400.

### 3.15 `GET /eval/latest`, `GET /site-checks`
`EvalResult`: `identification.confusion` is a 4×4 matrix, rows = expected tier, columns = predicted, order `[verified, declared, suspected, human]`; `diagnosis.per_blocker` precision/recall/F1/support; `impact.mean_abs_pct_error` may be `null`; `notes[]` are human-readable caveats. `SiteCheck.check_name` examples: `robots_txt`, `jsonld_product`, `price_in_html`, `size_guide_alt_text`, `pincode_optional`, `guest_checkout`, `llms_txt`; `result`: `pass|warn|fail`.

## 4. Demo snapshot scheme (`DEMO_MODE=1`)

With `NEXT_PUBLIC_DEMO_MODE=1` (or `DEMO_MODE=1` at build time) the dashboard never calls the API. It fetches static JSON from `/demo/*` (served from `apps/dashboard/public/demo/`), and `next build` produces a static export (`out/`). `agentlens export-snapshot` must write exactly this layout; `pnpm --filter @agentlens/dashboard generate:demo` writes it from the mock backend.

| File | Content |
|---|---|
| `meta.json`, `health.json`, `overview.json`, `agents.json`, `blockers.json`, `replays.json`, `compare.json`, `annotations.json`, `recommendations.json`, `settings.json`, `eval.json`, `site-checks.json` | the response of the same endpoint, full data range (agents/blockers/recommendations for the hero "before" window) |
| `agents/<operator-slug>/<agent-slug>.json` | `GET /agents/{operator}/{agent_name}`; slug = lowercase, runs of non `[a-z0-9]` replaced by `-`, trimmed (`slug()` in `lib/filters.ts`) |
| `blockers/<ID>.json` | `GET /blockers/{id}` for every `B01..B16`, `B99` |
| `funnel.json` | **special shape**: `{window, stages, series: {<segment>: FunnelSeries}, stage_blockers: {<segment>: {S1..S8: StageBlocker[]}}}` with all five segments; the client picks `primary`/`compare` by filter |
| `sessions.json` | `{window, page, page_size, total, items: SessionRow[] (all rows)}`; filtering, search, sorting and paging are done client-side |
| `sessions/<session_id>.json` | `GET /sessions/{id}` |
| `replays/<replay_id>.json`, `replays/<replay_id>/step_<n>.svg\|png` | replay detail + screenshots (`screenshot_url` is a root-relative `/demo/replays/...` path) |
| `runs/<run_id>.json` | `GET /runs/{id}` for `meta.last_run` |
| `report.md` | the Markdown report (PDF/PNG links are disabled in demo mode) |

Filter behaviour in demo mode: date range, segment, operator and agent class are applied client-side **only** to `sessions.json` and to the `overview.json` time series/annotations. All other views show the snapshot as exported; the top bar shows a visible "demo data" note saying so. Write calls (`POST/PUT/PATCH`) fail with `405 demo_readonly` and the UI disables them.

## 5. Dashboard data modes (single module: `lib/data-source.ts`)

Priority: `NEXT_PUBLIC_DEMO_MODE=1` → static snapshots; else `NEXT_PUBLIC_USE_MOCKS=1` → built-in fixtures (`lib/fixtures/*`, with in-browser state for annotations/settings/runs); else the real API at `NEXT_PUBLIC_API_URL` (default `http://localhost:8100/api`). **There is no silent fallback to mocks**: an unreachable API shows an error state with instructions.

## 6. Hero story the real data should be able to tell

Window "before" (store config with the pincode wall, JS-only price, OTP wall, app interstitial, image size guide, strict phone validation) vs "after" (a `config_change` annotation switches off B03/B05/B06): agent conversion rises from ≈3.5% to ≈7.5% (humans ≈4.2% throughout); B05 is ≈31% of failed agent sessions and ≈₹12.6 L/month at risk before the fix and 0 after. See `docs/PRD.md` §1, §32 and Appendix C.
