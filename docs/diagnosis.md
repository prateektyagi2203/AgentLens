# Diagnosis, impact and recommendations (M3)

How AgentLens explains why an AI agent session did not convert, prices it in rupees and turns it into a ranked fix list.
Code: `services/api/funnel.py`, `diagnosis/`, `impact.py`, `recommend.py`, `eval/`. Config: `config/funnel.yaml`,
`config/blockers.yaml`, `config/diagnosis.yaml`, `config/impact.yaml`. Decision record: `decisions/ADR-007-diagnosis-impact-methodology.md`.

Pipeline order: `ingest, identify, sessionize, funnel, diagnose, impact, recommend` (`agentlens run-all`). Every step is
set-based SQL, transactional and idempotent (re-running recomputes the same rows).

## 1. Funnel (`agentlens funnel`)

`config/funnel.yaml` maps `(method, path regex)` to stage S1..S8 and to a page type. A request reaches a stage only with a
success status (`success_status`). Outputs:

| Table | Content |
| --- | --- |
| `session_stages(session_id, stage_id, first_reached_ts)` | every stage a session reached; S8 is added for converted sessions (order linked) |
| `sessions.max_stage` | deepest stage reached (NULL = none) |
| `funnel_stats(segment_type, segment, day, stage_id, sessions_reached, sessions_total, step_conv, overall_conv, dropped)` | `day IS NULL` = all days. Segments: `group` (all/agents/human), `tier`, `agent_class`, `agent`, `operator` |

`sessions_reached` counts sessions whose `max_stage` rank is at least the stage (cumulative). `step_conv` = reached /
previous stage reached, `overall_conv` = reached / total, `dropped` = previous reached - reached.

## 2. Diagnosis (`agentlens diagnose [--site-url URL] [--llm mock|openai|off]`)

**Scope.** Sessions with identity tier verified / declared / suspected that did not convert. Crawler classes
(`search_crawler`, `training_crawler`) only get the infrastructure rules (B01, B12, B13, B16); `robots_token_only` and humans
are never diagnosed.

**Rules** (`diagnosis/rules.py`, one SQL function per blocker). Code-driven rules fire on an error that was never followed by
a success on the same endpoint (the agent did not get past it).

| Blocker | Signal | Confidence |
| --- | --- | --- |
| B01 bot wall | last request 403/503 with `BOT_CHALLENGE` or no code | .95 / .7 |
| B02 captcha | `POST /api/checkout` 403 `CAPTCHA_REQUIRED`, never solved | .92 / .97 |
| B03 JS-only content | `user_fetcher` without a beacon ending on a PDP; `pdp_ssr_price` check | fail .85, unknown .4, pass .1 |
| B04 missing JSON-LD | same shape with `pdp_jsonld_product` check | fail .8, warn .6, unknown .4, pass .1 |
| B05 pincode wall | `POST /api/cart` 409 `PINCODE_REQUIRED` | .95 |
| B06 login wall | `POST /api/cart` 401 (`AUTH_REQUIRED`, login seen) | .97 / .95 / .7 without a code |
| B07 overlay | `browsing_agent` stops on a loaded page (needs a replay to confirm) | .6 / .5 |
| B08 out of stock | variant 409 `OUT_OF_STOCK` (.95), cart 409 (.9), variant 200 but catalog stock 0 (.8) | .95 / .9 / .8 |
| B09 image-only size guide | session ends on a size-guide/PDP page; `size_guide_table` check | fail .85, unknown .45, pass .2 |
| B10 checkout validation | `POST /api/checkout` 400/422 (`PHONE_FORMAT` .95) | .95 / .65 |
| B11 payment step | `POST /api/checkout` 409 `COD_OTP_REQUIRED` | .95 |
| B12 rate limit | last request 429 | .95 / .85 |
| B13 slow | last request slower than `slow_ms` (5000) | .9 |
| B14 robots | session stops right after `robots.txt`; check `robots_txt.blocked_agents` names the agent | .9 / .7 / .3 |
| B15 price mismatch | cart `unit_price` differs from the catalog price for `product_id`, cart is the last action | .85 |
| B16 broken link | last request 404 on a page path | .95 |

**Terminal blocker.** A session may have several hits. Hits with confidence >= `min_terminal_confidence` (0.5) compete; the
winner is the deepest stage, then the latest evidence, then the highest confidence. It is stored in
`sessions.terminal_blocker_id`, `blocker_confidence` and `diagnosis_method` (`rules` | `llm`). Hits at confidence >=
`min_hit_confidence` (0.3) are kept in `blocker_hits` (`is_terminal` marks the winner).

**B99 (unknown).** A shopping session with no terminal hit that ended on an error, or a browsing agent stalled in S2-S7.
Stored at 0.3 with `diagnosis_method = 'rules'`. These, and only these, go to the optional LLM pass.

**Evidence model.** `blocker_hits.evidence_json` is an array:

```json
[{"type": "request", "request_id": "req-...", "summary": "POST /api/cart -> 409 PINCODE_REQUIRED"},
 {"type": "site_check", "check": "pdp_ssr_price", "result": "fail"},
 {"type": "llm_note", "summary": "one-sentence rationale (redacted input)"}]
```

**Site checks** (`agentlens site-checks --site-url URL`, or `--site-url` / `AGENTLENS_SITE_URL` on `diagnose`). Run against the live
store and appended to `site_checks(check_id, run_ts, check_name, target, result, details_json)`: `robots_txt` (details
`blocked_agents`), `llms_txt`, `sitemap`, `pdp_ssr_price`, `pdp_jsonld_product`, `size_guide_table`, `captcha_presence`
(fail = present). Results: `pass | fail | warn | missing`. With no URL or an unreachable store one `site_probe` row with
result `skipped` is recorded and diagnosis carries on with logs only (B03/B04/B09 then stay under the terminal threshold and
abstain). Each check is valid from its run until the next run, so a session is judged against the store as it was when it
started.

**LLM-assisted classifier** (ADR-001). Only sees B99 candidates, capped at 200 sessions per run
(`AGENTLENS_LLM_MAX_SESSIONS`). Provider `mock` (default, deterministic, no network) or `openai` (`OPENAI_API_KEY`, model
`AGENTLENS_LLM_MODEL`, default `gpt-4o-mini`; falls back to mock without a key). Prompts hold only method, path without query
string, status, error code and timing, with emails, phone numbers and long ids masked. A verdict under `llm_min_confidence`
(0.6) leaves the session as B99. Real-provider answers are cached in `data/llm_cache.jsonl`. Rules-only mode (`--llm off`)
needs no key and no network. Ground truth is never read outside `agentlens.eval` (`tests/python/test_isolation.py`).

## 3. Impact (`agentlens impact`)

Per blocker b (PRD 14.1), scaled to 30 days:

```
Risk_b = L_b x r x p_s x AOV x k           k = 30 / window_days
```

- `L_b`: agent sessions (not crawlers) whose terminal blocker is b. B99 is not priced.
- `r`: recoverable rate, low / base / high = 0.4 / 0.6 / 0.8 (`impact.yaml`).
- `p_s`: conversion probability of agent sessions that reached the blocker's stage (the most common stage of its terminal
  hits). Low / high use p_s -20% / +20%, capped at 1.
- `AOV`: average order value of agent orders, else all orders, else `default_aov_inr` (2200).
- `window_days`: calendar days between the first and last session start.

If fewer than `min_sample` (30) agent sessions reached the stage, or fewer than `min_conversions` (5) converted, p_s falls
back to the human conversion at that stage times `agent_vs_human_factor` (recorded in `impact_assumptions.p_source`).
`low_confidence` is true when `L_b < 30`.

**Overlapping blockers.** Each failed session carries exactly one terminal blocker, so it is counted in one `L_b` and rupees
are never double counted. Secondary hits stay visible in `blocker_hits` but carry no rupees.

Worked example (PRD 14.3, test `test_prd_14_3_worked_example`): 1,240 x 0.6 x 0.18 x 2,200 x 30/7 = Rs 12,62,674 (about
Rs 12.6 lakh). Values are stored as plain rupee numbers; the UI formats lakh / crore.

Tables: `impact(run_id, window_start, window_end, blocker_id, stage_id, sessions_blocked, p_stage, recoverable_low/base/high,
aov, risk_low/base/high, low_confidence)` and `impact_assumptions(run_id, blocker_id, p_source, window_days, k, aov_source,
r_low, r_base, r_high)`.

## 4. Recommendations (`agentlens recommend`)

One row per priced blocker in `recommendations`, ranked by `priority_score = risk_base / effort_weight` (S=1, M=2, L=4).
`rec_id = rec-<blocker>` is stable, so re-runs keep `status` and `fixed_annotation_id`. Fix text, effort, owner and the
verification recipe come from `config/blockers.yaml`. `body` JSON: `what, why_it_helps, how_to_verify, verify_metric,
evidence_summary, llm_explanation, risk_inr_base/low/high, sessions_blocked, stage`.

## 5. Evaluation (`agentlens eval-diagnosis [--golden]`)

Only `agentlens.eval` reads synthetic ground truth. `eval/golden.py` generates the 2,000-session golden set (eight segments,
seeds 4101-4108, each with its own friction toggles and persona mix; cached in `<data>/golden`), probes an in-process fake
store (`eval/fakestore.py`, driven by the same toggles) for the site checks, runs diagnosis rules-only and scores it. Sessions
are scored when their identity tier is non-human and they are in diagnosis scope; B99/none abstentions are never false
positives. Report: `<data>/eval/diagnosis-eval-*.md`. SC4 (PRD 18): precision >= 0.85, recall >= 0.80.
`tests/python/test_eval_diagnosis.py` regenerates the set and asserts SC4.

## 6. Adding a blocker

1. Add `B17` to `config/blockers.yaml` (name, stage, description, fix, effort, owner, how_to_verify).
2. Write `@rule("B17", "title")` in `diagnosis/rules.py` returning the documented SELECT (`session_id, blocker_id, stage_id,
   confidence, evidence_ts, ev_ids, site_ev, note`) from `_dsess` / `_dreq` / `_dsite` / `_dcat`. Never read ground truth.
3. Add positive and negative cases to `tests/python/test_diagnosis_rules.py`, and a synth scenario if it should be evaluable.
4. Impact and recommendations pick it up automatically.
