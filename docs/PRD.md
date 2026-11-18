# AgentLens - Product Requirements Document (PRD)

**Product:** AgentLens - Agent Analytics for Ecommerce ("Google Analytics for AI shoppers")
**Owner:** Prateek Tyagi (Product Manager and builder)
**Doc version:** 1.0
**Date:** 16 Nov 2026
**Status:** Ready for build
**Type:** Portfolio prototype (open source), built to be demoed via screen recording on LinkedIn, with a free-tier public link

---

## 0. How to use this document (read first, Claude)

This PRD is written so it can be handed to Claude (chat or Claude Code) to build the product end to end.

**Instructions for the building assistant:**

1. Build **one milestone at a time** (Section 22). Do not jump ahead.
2. For every milestone, output **complete files** (not diffs or fragments), with the full file path as a heading above each file.
3. After each milestone, give **exact run commands for Windows 11 (PowerShell)** and note any macOS differences.
4. Each milestone must end with its **Definition of Done checklist** passing (Section 22) and its tests (Section 20) green.
5. When this PRD is silent on something, choose the **simplest option that keeps the demo working** and log the decision in `docs/decisions/ADR-XXX.md` (Section 24 has the template).
6. Never use real customer data. All data is synthetic or produced by test agents visiting the demo store.
7. The diagnosis engine must **never read ground-truth labels** (Section 12.6). Ground truth is only for evaluation.
8. Everything must run **with no LLM API key** (rules-only mode). The LLM layer is an optional upgrade.
9. Keep the code readable and commented. The repo is a public portfolio piece, and the README is part of the product.

**Section map:** A to Z is covered in this order:
Problem → Users → Goals → Scope → Concepts → Architecture → Components (store, capture, ingestion, identification, sessions, funnel, diagnosis, replay, impact, recommendations, dashboard, synthetic traffic, real-agent harness, reports) → Data model → APIs → Config → Metrics → Product decisions → Privacy and security → Non-functional requirements → Tech stack and repo → Setup → Deployment → Testing → Milestones with prompts → Demo script → Content plan → Risks → Open questions → Appendices.

---

## 1. Executive summary

AI agents (ChatGPT agent, Claude, Perplexity Comet, Gemini, and others) now browse ecommerce sites, compare products, and complete purchases for shoppers. Retailers' analytics stacks were built for humans who run JavaScript tags. They miss agents that fetch pages without running JavaScript, they mix agent and human sessions together, and they say nothing about **why** an agent failed to buy.

The big analytics vendors (Microsoft Clarity, Contentsquare, Snowplow and others) have started to add agent visibility. They mostly answer **"which agents came and what did they do"**.

**AgentLens goes one step further:**

> AgentLens diagnoses **why** AI agents fail on an ecommerce site, **proves** the cause by replaying the journey with a test agent, and **puts a ₹ value** on each fix so teams know what to fix first.

**Three differentiators:**

1. **Built on server logs, not a JavaScript tag.** It sees every request, including agents that never run JS.
2. **Auto-replay.** A test agent re-runs the failed journey and confirms the blocker with screenshot evidence.
3. **India-first blocker catalog.** Pincode serviceability walls, OTP login before the cart, COD and UPI flows, app-download interstitials, +91 phone validation.

**Hero demo:** a dashboard shows "31% of agent sessions died at the pincode check, costing about ₹4.2 lakh a month". The pincode wall is switched off, traffic is re-run, and the agent conversion rate jumps.

---

## 2. Background and problem

### 2.1 Context
- AI-referred traffic to retail sites has grown very fast through 2025 and 2026, and it converts better than average traffic in several industry panels.
- Agents increasingly complete tasks on their own: search, pick a variant, check delivery, add to cart, check out.
- Retailers are split. Some block agents, others build gateways and rules for them. Either way, they first need to **see** what agents are doing.
- New standards help identify agents. **Web Bot Auth** (an IETF draft built on RFC 9421 HTTP Message Signatures) lets an agent operator sign requests so a site can verify who sent them.

### 2.2 The problem (for a retailer)
| # | Pain | Today |
|---|------|-------|
| P1 | "How much of my traffic is AI agents?" | Unknown or guessed. Tag-based tools miss agents that don't run JS. |
| P2 | "Which agents, and can I trust that they are who they claim?" | User-agent strings are easy to fake. Few teams verify signatures. |
| P3 | "Where do agents drop off in my funnel?" | Agent sessions are mixed into human funnels, which distorts both. |
| P4 | "Why did they fail?" | No tool explains the cause (bot wall, JS-only price, pincode modal, OTP wall...). |
| P5 | "Is it worth fixing?" | No ₹ estimate, so agent-readiness loses every prioritisation fight. |
| P6 | "Did my fix work?" | No before/after comparison for agent traffic. |

### 2.3 Why now
- Agent traffic is now big enough to matter and still small enough that early movers win.
- Signed-agent standards make reliable identification possible for the first time.
- LLMs make it practical to classify messy failure evidence (HTML, status codes, screenshots) at scale.

---

## 3. Users and personas

### 3.1 Product personas (who would use AgentLens in a company)
| Persona | Role | Job to be done | What they need from AgentLens |
|---|---|---|---|
| **Neha, Head of Ecommerce** | Owns online P&L | "Tell me if agents are a real channel and what it's worth." | Overview KPIs, ₹ at risk, trend |
| **Arjun, Growth/CRO PM** | Owns funnel conversion | "Show me exactly where agents drop and what to fix first." | Funnel, blockers ranked by ₹, before/after |
| **Kavya, Platform/Web Engineer** | Owns site, CDN, WAF | "Prove the cause so I don't chase ghosts." | Session explorer, replay evidence, raw requests |
| **Rohit, D2C Founder** | Runs a small brand | "Is my site agent-ready? What are the 3 fixes?" | One-page Agent Readiness Report |
| **Security/Trust lead** | Owns bot policy | "Which agents are real? Should we allow or block?" | Identity tiers, verified operators, policy view |

### 3.2 Portfolio audience (who the LinkedIn demo must impress)
- Hiring managers at big tech and retail: product thinking plus the ability to build.
- Retail and ecom leaders: a commercial problem with a ₹ answer.
- Founders and investors: an original, timely wedge.
- PM and builder community: clean architecture, honest trade-offs, an open repo.

---

## 4. Goals, non-goals and success criteria

### 4.1 Product goals (v1)
- G1: Identify agent traffic from server logs with **three confidence tiers** (Verified, Declared, Suspected).
- G2: Rebuild agent sessions and show an **agent funnel** next to the human funnel.
- G3: **Diagnose** the blocker that ended each failed agent session, using a catalog of at least 15 blocker types.
- G4: **Confirm** top blockers with an automated **replay agent** (screenshot plus verdict).
- G5: Estimate **₹ at risk per month** per blocker, with low/base/high scenarios.
- G6: Recommend **fixes ranked by ₹ impact and effort**.
- G7: Compare **before/after** windows around a site change.
- G8: Export a one-page **Agent Readiness Report** (Markdown and PDF).

### 4.2 Portfolio goals
- PG1: A 60 to 90 second demo video with a clear before/after moment.
- PG2: A public free-tier link where anyone can click through a read-only demo.
- PG3: A GitHub repo whose README doubles as a crisp PRD summary, with one-command setup.
- PG4: Honest evaluation numbers (identification accuracy, diagnosis precision/recall) on a labelled synthetic dataset.

### 4.3 Non-goals (v1)
- Not a production bot-management or WAF product. AgentLens **observes and recommends**. It does not block traffic.
- No real customer data, no multi-tenant SaaS, no billing, no user accounts beyond a simple local admin.
- No support for agent commerce protocols (ACP, UCP, MCP checkout) in v1. Listed under future scope.
- No real payments. The demo store uses a fake test-mode checkout.
- No mobile app.

### 4.4 Success criteria (measurable)
| ID | Metric | Target |
|---|---|---|
| SC1 | Verified-tier precision (valid signatures marked Verified) | 100% on test set, **0 false Verified** on tampered signatures |
| SC2 | Declared-tier identification accuracy on synthetic set | ≥ 98% |
| SC3 | Suspected-tier recall on synthetic undeclared agents | ≥ 75% at ≤ 5% false positive rate on human sessions |
| SC4 | Diagnosis precision / recall on golden set (terminal blocker) | ≥ 0.85 / ≥ 0.80 |
| SC5 | Replay confirmation rate for top 5 blockers | ≥ 80% confirmed with evidence |
| SC6 | Pipeline speed: 1M log lines end to end on a laptop | ≤ 3 minutes |
| SC7 | Dashboard page load (100k sessions) | ≤ 2 seconds |
| SC8 | Setup: fresh clone to running demo | ≤ 15 minutes using the README |

---

## 5. Scope and phasing

### 5.1 MVP (v1.0, this build)
Demo store with friction toggles · log capture · ingestion (JSONL plus nginx combined format) · agent identification (3 tiers, including Web Bot Auth verification) · sessionization · funnel · rule-based diagnosis (15+ rules) · optional LLM classifier for unknown failures · replay agent (Playwright) · ₹ impact model · recommendations · dashboard (8 pages) · synthetic traffic generator with ground truth · evaluation harness · before/after compare · report export · public read-only demo snapshot.

### 5.2 v1.1 (nice to have, only if time permits)
- Cloudflare Logpush and AWS CloudFront log formats.
- Alerting (email or Slack webhook) when a new blocker spikes.
- "Agent policy simulator": what changes if you allow or block a given operator.

### 5.3 Future (documented, not built)
- Agent commerce protocol analytics (ACP, UCP, MCP-based checkout).
- Real-time streaming ingestion.
- Multi-site, multi-tenant SaaS with auth and billing.
- Benchmarks across sites (anonymised).

---

## 6. Key concepts and glossary

| Term | Definition |
|---|---|
| **Agent** | Any automated client acting on the web. AgentLens focuses on agents acting **for a shopper**. |
| **Agent class** | `training_crawler` (collects data for model training), `search_crawler` (indexes for search or answers), `user_fetcher` (fetches a page because a user asked, usually no JS), `browsing_agent` (drives a real browser for a user, runs JS, clicks, fills forms), `api_agent` (protocol-based, future). |
| **Shopping agent traffic** | `user_fetcher` plus `browsing_agent`. These go into the funnel. Crawlers are reported separately. |
| **Operator** | The company running the agent (OpenAI, Anthropic, Perplexity, Google...). |
| **Identity tier** | **Verified**: valid Web Bot Auth signature. **Declared**: user-agent matches a known agent token but no valid signature. **Suspected**: behaviour looks automated but nothing is declared. **Human**: none of the above. |
| **Session** | A sequence of requests from one client, split by an inactivity timeout. |
| **Funnel stage** | A step on the path to purchase (Landing → PDP → Variant → Serviceability → Cart → Checkout start → Checkout submit → Order). |
| **Blocker** | A site behaviour that stops an agent from progressing (for example, a pincode modal). |
| **Terminal blocker** | The blocker attributed as the reason a session ended without an order. Exactly one per failed session (or `unknown`). |
| **Replay** | An automated re-run of a failed journey by AgentLens's own test agent, to confirm the blocker. |
| **₹ at risk** | Estimated monthly revenue lost because of a blocker. |
| **Friction toggle** | A switch in the demo store that turns a blocker on or off. |
| **Ground truth** | The true label of a synthetic session (agent type, intended path, blocker hit). Used only for evaluation. |
| **AOV** | Average order value. |
| **PDP / PLP** | Product detail page / product listing page. |

---

## 7. System overview

### 7.1 High-level flow
```
 ┌──────────────────────┐        ┌──────────────────────────┐
 │  Traffic sources     │        │  Demo Store (Next.js)    │
 │  - Real agents       │──HTTP─▶│  "Desi Threads"          │
 │  - Synthetic agents  │        │  + friction toggles      │
 │  - Synthetic humans  │        │  + capture middleware    │
 └──────────────────────┘        └────────────┬─────────────┘
                                              │ JSONL access logs
                                              ▼
                         ┌────────────────────────────────────────┐
                         │  AgentLens API (FastAPI + DuckDB)       │
                         │  1. Ingest & normalise                  │
                         │  2. Identify (Verified/Declared/Susp.)  │
                         │  3. Sessionize                          │
                         │  4. Funnel mapping                      │
                         │  5. Diagnose (rules → LLM fallback)     │
                         │  6. Impact (₹ at risk)                  │
                         │  7. Recommend fixes                     │
                         └───────┬─────────────────────┬──────────┘
                                 │ jobs                │ REST/JSON
                                 ▼                     ▼
                  ┌───────────────────────┐   ┌──────────────────────┐
                  │ Replay Agent           │   │ Dashboard (Next.js)  │
                  │ (Playwright + LLM)     │   │ 8 pages + report     │
                  │ screenshots, verdicts  │   │ export               │
                  └───────────────────────┘   └──────────────────────┘
```

### 7.2 Components
| ID | Component | Tech | Section |
|---|---|---|---|
| C1 | Demo store "Desi Threads" | Next.js (App Router) | 8 |
| C2 | Capture layer | Next.js middleware + route handlers → JSONL | 9 |
| C3 | Ingestion and normalisation | Python, DuckDB | 10 |
| C4 | Agent identification | Python (`cryptography`, `http-message-signatures` or own verifier) | 11 |
| C5 | Sessionization | Python / SQL | 12.1 |
| C6 | Funnel mapping | YAML config + SQL | 12.2 |
| C7 | Diagnosis engine | Python rules + optional Claude API | 12.3 to 12.6 |
| C8 | Replay agent | Python Playwright + optional Claude API | 13 |
| C9 | Impact model | Python | 14 |
| C10 | Recommendation engine | YAML catalog + Python | 15 |
| C11 | Dashboard | Next.js + Recharts + TanStack Table | 16 |
| C12 | Synthetic traffic generator | Python (httpx, Playwright) | 17 |
| C13 | Real-agent test harness | Markdown runbook + CSV | 18 |
| C14 | Report export | Markdown → PDF (WeasyPrint or Playwright print) | 19 |

---

## 8. C1 - Demo store "Desi Threads"

A realistic Indian D2C fashion and footwear store, built only to be visited by agents and humans and to produce logs.

### 8.1 Catalogue
- 60 products across 4 categories: Men's sneakers, Women's kurtas, Men's shirts, Accessories.
- Each product: id, slug, name, brand ("Desi Threads"), category, price (₹), MRP, discount %, images (placeholder or generated, no copyrighted images), description, attributes (material, fit, colour), variants (size × colour), stock per variant, size chart (both HTML table and image version), return policy, rating (synthetic).
- Seed data lives in `apps/store/data/catalog.json`, generated by a script with a fixed seed.
- 10% of variants are out of stock. Two products have a price mismatch between PDP and cart when toggle F11 is on.

### 8.2 Pages and endpoints
| Route | Type | Funnel stage |
|---|---|---|
| `/` | Home | S1 Landing |
| `/search?q=` | Search results | S1 Landing |
| `/c/[category]` | PLP | S1 Landing |
| `/p/[slug]` | PDP (SSR by default) | S2 PDP |
| `/api/products/[id]/variants` | Variant availability (JSON) | S3 Variant |
| `/api/serviceability?pincode=` | Delivery check (JSON) | S4 Serviceability |
| `POST /api/cart` | Add to cart | S5 Cart |
| `/cart` | Cart page | S5 Cart |
| `/login`, `POST /api/otp/send`, `POST /api/otp/verify` | Login/OTP | (blocker surface) |
| `/checkout` | Checkout form (address, phone, payment method) | S6 Checkout start |
| `POST /api/checkout` | Submit order (test mode) | S7 Checkout submit |
| `/order/confirmed/[orderId]` | Confirmation | S8 Order |
| `/policies/returns` | Returns policy | (info) |
| `/size-guide/[category]` | Size guide | (info) |
| `/robots.txt` | Robots, switchable | (policy) |
| `/.well-known/http-message-signatures-directory` | Test operator key directory (for synthetic signed agents only) | n/a |
| `/admin` | Friction toggles + annotations (password from env) | n/a |

**Checkout:** payment methods are COD, UPI (simulated) and Card (simulated). No real payment ever happens. Orders are written to `data/orders.jsonl` with `order_id`, `session_cookie_id`, `cart_value`, `ts`.

**Structured data:** PDP includes schema.org `Product` JSON-LD with `offers.price`, `priceCurrency=INR`, `availability`, and size variants, unless toggle F04 removes it.

### 8.3 Friction toggles (the heart of the demo)
Stored in `apps/store/config/friction.json`, editable at `/admin`. Every change writes an **annotation event** to the log (`event_type=config_change`) so before/after windows can be detected automatically.

| ID | Toggle | Behaviour when ON | Expected blocker ID |
|---|---|---|---|
| F01 | Bot wall | Requests with non-browser or known agent UAs get 403 with a challenge page | B01 |
| F02 | Captcha at checkout | `/checkout` shows a captcha that must be solved before submit | B02 |
| F03 | JS-only price | PDP price and stock rendered client-side only (not in HTML or JSON-LD) | B03 |
| F04 | No structured data | Removes JSON-LD from PDP | B04 |
| F05 | Pincode wall | Modal blocks PDP interaction until a pincode is entered. Add to cart is rejected (409 `PINCODE_REQUIRED`) until `/api/serviceability` succeeds in the session | B05 |
| F06 | OTP before cart | `POST /api/cart` returns 401 and redirects to `/login` unless OTP-verified. OTP is sent "by SMS" (logged only) and cannot be read by agents | B06 |
| F07 | App-download interstitial | Full-screen "Get the app for 10% off" overlay on first PDP view, close button hidden for 3 s | B07 |
| F08 | Spin-the-wheel popup | Email-capture popup on landing that covers the page | B07 |
| F09 | Size chart image-only | Size guide served only as an image, no HTML table | B09 |
| F10 | Strict phone validation | Checkout rejects phone unless format is exactly `+91 XXXXX XXXXX` with a space | B10 |
| F11 | Price mismatch | Cart price differs from PDP price for 2 products | B15 |
| F12 | Rate limit | More than 20 requests/minute per client returns 429 | B12 |
| F13 | Slow pages | PDP adds 6 to 9 s latency | B13 |
| F14 | robots.txt disallow | Disallows `/p/` and `/checkout` for listed agent tokens | B14 |
| F15 | COD OTP confirm | COD orders need an OTP confirmation step | B11 |
| F16 | Out-of-stock dead end | Selecting an OOS variant returns 409 with no alternative suggested | B08 |

**Default demo state ("Before"):** F01 off, F03 on, F05 on, F06 on, F07 on, F09 on, F10 on. Everything else off.
**"After" state:** F05 off, F06 off, F03 off (keep others) to show the jump.

### 8.4 Store requirements
- SR1: Every request (page, API, asset) passes through the capture layer (C2).
- SR2: The store sets a first-party cookie `dt_sid` (random UUID) on first response. Agents that drop cookies will not keep it, and this is expected.
- SR3: A tiny JS beacon (`/api/beacon`) fires on page load, so humans and JS-running agents produce a beacon event while non-JS fetchers do not.
- SR4: Pages are fast (< 300 ms server time) unless F13 is on.
- SR5: Must work behind a tunnel (Cloudflare Tunnel or ngrok) so real external agents can visit the local store.
- SR6: No external trackers, no third-party scripts.

---

## 9. C2 - Capture layer

### 9.1 Mechanism
- Next.js `middleware.ts` assigns `request_id` and start time, reads headers, and passes them on.
- A server-side logger writes one JSON line per request to `data/logs/access-YYYY-MM-DD.jsonl` once the response is known (route handlers and a custom server wrapper, or a Node server around Next.js; Claude should pick the most reliable approach and document it in an ADR).
- An optional **nginx combined format** export exists so the ingestion layer is proven on standard logs too.

### 9.2 Log record schema (JSONL)
| Field | Type | Notes |
|---|---|---|
| `ts` | ISO-8601 string (ms, UTC) | Request start |
| `request_id` | string (uuid) | |
| `method` | string | |
| `host` | string | |
| `path` | string | Without query |
| `query` | string | Raw query string, PII-scrubbed (no phone/email values) |
| `status` | int | |
| `bytes_out` | int | |
| `duration_ms` | int | |
| `ip_hash` | string | SHA-256(salt + IP), salt from env. **Raw IP never stored.** |
| `ip_prefix` | string | /24 for IPv4 or /48 for IPv6, for range matching. Optional, can be disabled |
| `user_agent` | string | |
| `referer` | string | Domain plus path only |
| `accept` | string | |
| `accept_language` | string | |
| `sec_ch_ua` | string | Client hints if present |
| `sec_fetch_site`, `sec_fetch_mode`, `sec_fetch_dest` | string | |
| `signature` | string | `Signature` header (raw) |
| `signature_input` | string | `Signature-Input` header (raw) |
| `signature_agent` | string | `Signature-Agent` header (raw) |
| `cookie_sid_hash` | string | Hash of `dt_sid` if present |
| `is_asset` | bool | Static asset request |
| `event_type` | string | `request` (default), `beacon`, `config_change`, `order` |
| `meta` | object | e.g. `{ "order_id": "...", "cart_value": 2499 }` for orders, `{ "toggles": {...} }` for config changes |

**Not logged by design:** request bodies, OTP values, phone numbers, addresses, emails, cookies other than `dt_sid` hash.

**Important:** the store must **not** log which friction blocked a request (for example "pincode modal shown"). Real sites don't have that label. Diagnosis must infer it from generic signals. (Synthetic ground truth is stored separately, Section 17.)

### 9.3 Sample log line
```json
{"ts":"2026-11-20T10:15:02.331Z","request_id":"6f1c...","method":"POST","host":"desithreads.local","path":"/api/cart","query":"","status":409,"bytes_out":88,"duration_ms":41,"ip_hash":"a91e...","ip_prefix":"203.0.113.0/24","user_agent":"Mozilla/5.0 ... Chrome/131.0 Safari/537.36","referer":"desithreads.local/p/white-court-sneaker","accept":"application/json","accept_language":"en-IN","sec_ch_ua":"\"Chromium\";v=\"131\"","sec_fetch_site":"same-origin","sec_fetch_mode":"cors","sec_fetch_dest":"empty","signature":"sig1=:MEUCIQ...:","signature_input":"sig1=(\"@authority\" \"signature-agent\");created=1795600000;expires=1795600300;keyid=\"abc\";alg=\"ed25519\";tag=\"web-bot-auth\"","signature_agent":"\"https://chatgpt.com\"","cookie_sid_hash":"7d2c...","is_asset":false,"event_type":"request","meta":{"error_code":"PINCODE_REQUIRED"}}
```
Note: `meta.error_code` is allowed because real APIs return error codes in their responses. It is generic API behaviour, not a friction label.

---

## 10. C3 - Ingestion and normalisation

### 10.1 Inputs
- `jsonl` (native schema above).
- `nginx_combined` (with optional extra fields for signature headers if configured).
- v1.1: Cloudflare Logpush, CloudFront.

### 10.2 Requirements
- IN1: CLI `agentlens ingest --source data/logs --format jsonl` and API `POST /api/ingest`.
- IN2: Incremental: tracks file offsets in an `ingest_state` table and does not re-ingest lines.
- IN3: Validates each line. Bad lines go to `ingest_errors` with the reason, and do not stop ingestion.
- IN4: Normalises into the `requests` table (Section 21).
- IN5: Classifies `page_type` from path using `config/funnel.yaml` patterns (home, search, plp, pdp, variant_api, serviceability_api, cart_api, cart, login, otp_api, checkout, checkout_api, order_confirm, policy, size_guide, robots, asset, beacon, admin, other).
- IN6: Throughput target: ≥ 10k lines/second on a laptop (DuckDB bulk insert from Arrow or Parquet batches).
- IN7: Pipeline command `agentlens run-all` runs ingest → identify → sessionize → funnel → diagnose → impact → recommend in order, and is idempotent.

---

## 11. C4 - Agent identification

Every request gets an `identity_tier`, `operator`, `agent_name`, `agent_class` and `identity_confidence` (0 to 1). Sessions inherit the strongest identity seen in the session.

### 11.1 Tier 1: Verified (Web Bot Auth)
**Logic (follow the current IETF draft; verify the latest spec at build time and record the version in an ADR):**
1. Request has `Signature`, `Signature-Input` and (usually) `Signature-Agent` headers, with `tag="web-bot-auth"`.
2. Parse `Signature-Input` per RFC 9421: covered components, `created`, `expires`, `keyid`, `alg`.
3. Check `created ≤ now(ts) ≤ expires` (allow 60 s clock skew, configurable).
4. Fetch the key directory from the `Signature-Agent` origin at `/.well-known/http-message-signatures-directory` (JWKS-style). Cache results for 1 hour in `key_cache`. In **offline mode**, use cached or bundled keys only.
5. Find the key by `keyid` (JWK thumbprint) and verify the signature over the signature base built from the covered components (at least `@authority`, plus `signature-agent` if present).
6. Valid → `tier=verified`, `operator` = mapped from the `Signature-Agent` domain via `config/agents.yaml`, confidence 1.0.
7. Present but invalid (bad signature, expired, unknown key) → **not** verified. Record `signature_status` (`invalid_sig`, `expired`, `unknown_key`, `fetch_failed`) and fall through to Tier 2/3. A forged signature is a **risk signal** (+30 to suspicion score).

**Testing approach:** the synthetic generator acts as a fake operator `https://agents.desithreads.test` with its own Ed25519 keypair, served from the store's well-known directory. Tests cover valid, expired, tampered body/authority, wrong key and missing headers. Real signatures from ChatGPT agent are verified when it visits through the tunnel.

### 11.2 Tier 2: Declared (user-agent)
- Match `user_agent` against the registry in `config/agents.yaml` (starter list in Appendix A) using case-insensitive token matching.
- Optional strengthening: if the operator publishes IP ranges and `ip_prefix` matches, set `ip_match=true` and confidence 0.9, otherwise 0.7.
- Map to `agent_class` from the registry.
- Note: `Google-Extended` and `Applebot-Extended` are robots.txt tokens, not user-agents. Keep them in the registry only for the robots.txt analysis (B14).

### 11.3 Tier 3: Suspected (behaviour)
For sessions with no Verified or Declared identity, compute a **suspicion score 0 to 100** from weighted signals (weights in `config/identification.yaml`):

| Signal | Default weight |
|---|---|
| HTML pages fetched but **no beacon** while UA claims a full browser | 25 |
| No static assets loaded for HTML pages | 15 |
| `HeadlessChrome` or automation hints in UA or client hints | 30 |
| Missing `sec-fetch-*` headers with a modern browser UA | 10 |
| Very regular inter-request timing (low coefficient of variation) | 10 |
| Page velocity > N pages/minute (default 15) | 10 |
| Deep-link entry with no referer and immediate cart attempt | 5 |
| `accept` header atypical for claimed browser | 5 |
| Invalid Web Bot Auth signature present | 30 |

- Score ≥ 60 → `tier=suspected`, `agent_class=browsing_agent` (if beacons present) or `user_fetcher` (if not), operator `unknown`, confidence = score/100.
- Score < 60 → `tier=human`.
- Known search and training crawlers (Googlebot, GPTBot, CCBot...) are tagged as Declared crawlers and **excluded from the shopping funnel**, but shown on the Agents page.

### 11.4 Honest limitation (must appear in README and dashboard tooltip)
Agents that run inside the shopper's own browser (for example, browser extensions) look like humans at the server. AgentLens can only flag them as Suspected through behaviour, if at all. The **identity coverage** metric (Section 23) shows how much traffic is confidently identified.

### 11.5 Outputs
- `requests.identity_tier`, `operator`, `agent_name`, `agent_class`, `identity_confidence`, `signature_status`, `suspicion_score`.

---

## 12. C5 to C7 - Sessions, funnel and diagnosis

### 12.1 C5 Sessionization
- Session key, in priority order:
  1. Verified/Declared agents: `operator + agent_name + ip_hash + ua_hash` (agents often drop cookies).
  2. Clients with `cookie_sid_hash`: that hash.
  3. Fallback: `ip_hash + ua_hash`.
- Inactivity timeout: 30 min for humans, 10 min for agents (configurable).
- Session record: id, key, start, end, duration, request count, page count, identity (strongest), entry page, exit page, max funnel stage reached, converted (bool), order value, terminal blocker (filled by C7), blocker confidence.
- Beacons and assets are attached to sessions but don't count as pages.
- `config_change` events are stored as annotations, not sessions.

### 12.2 C6 Funnel mapping
- Stages from `config/funnel.yaml` (Section 22.3 example). Each stage = list of `{method, path_regex, status_ok}` rules.
- A session "reaches" a stage when it makes at least one request matching that stage with a success status.
- `max_stage` = highest stage reached. `converted` = reached S8 (or an order event is linked to the session).
- Funnel output per segment (human, all agents, per operator, per tier, per class): sessions reaching each stage, step conversion %, overall conversion %.
- Order linkage: orders link via `cookie_sid_hash`, or via `request_id` of the `POST /api/checkout` that returned the order id.

### 12.3 C7 Diagnosis engine: overview
For each **failed agent session** (agent tier, did not convert, reached at least S1), find the **terminal blocker**:
1. Run all rules in the blocker catalog (12.4) against the session's requests plus site-level checks.
2. Each rule that fires returns `{blocker_id, stage, confidence, evidence[]}`.
3. Pick the terminal blocker: the firing rule at the **highest stage reached**, nearest in time to the session's last request. Ties go to higher confidence.
4. If no rule fires: `blocker_id=B99 unknown`. If the LLM is enabled, send compact evidence to the LLM classifier (12.5).
5. Also store **all** fired rules (secondary blockers) for reporting, but attribute ₹ only to the terminal blocker (prevents double counting).

**Site-level checks** (run once per pipeline, not per session): robots.txt fetch and parse, PDP HTML sample (5 random PDPs fetched with a plain HTTP client) to check for SSR price and JSON-LD, size-guide format check. Results stored in `site_checks`.

### 12.4 Blocker catalog (v1)
Defined in `config/blockers.yaml`. Each rule has detection logic in `services/api/diagnosis/rules/*.py`.

| ID | Blocker | Stage | Detection signals (no ground truth) | Fix (summary) | Effort |
|---|---|---|---|---|---|
| B01 | Bot wall / WAF block | Any | Status 403/503 with challenge markers in response metadata, or 403 as last request; agent identity present | Allow-list verified agents (Web Bot Auth), challenge only suspicious traffic | M |
| B02 | Captcha | S6/S7 | Session reaches checkout, captcha endpoint/page requested, no successful submit | Remove captcha for verified agents, use risk-based challenges | M |
| B03 | JS-only content | S2 | `user_fetcher` session fetched PDP and ended; site check shows price/stock missing from server HTML and JSON-LD | Server-render price and stock, include in JSON-LD | M |
| B04 | Missing structured data | S2 | Site check: JSON-LD Product missing or incomplete (price, availability, variants) | Add complete schema.org Product markup | S |
| B05 | Pincode/serviceability wall | S4/S5 | Add-to-cart returned 409 `PINCODE_REQUIRED`, or repeated serviceability calls failing, or session ended within 2 requests after PDP with serviceability required | Make pincode optional before cart, accept pincode via URL/API, show delivery promise without a modal | S |
| B06 | Login/OTP wall before cart | S5 | Cart POST 401 → redirect to `/login`, OTP send without verify, session ends | Allow guest cart, defer login to checkout or offer guest checkout | M |
| B07 | Interstitial/popup | S1/S2 | Browsing agent with beacons but no further interaction after PDP/landing within threshold; replay confirms overlay | Delay or remove overlays, never block content, provide accessible close button | S |
| B08 | Out-of-stock dead end | S3 | Variant API 409 OOS as last meaningful request, no alternative variant request | Suggest in-stock alternatives, expose availability per variant in HTML/JSON-LD | S |
| B09 | Size guide image-only | S3 | Size guide requested, served as image, session ended before cart | Provide HTML table size guide | S |
| B10 | Checkout validation failure | S7 | Repeated 400/422 on checkout submit with field error codes (e.g. `PHONE_FORMAT`) | Relax/normalise validation (accept +91 variants), clear error messages | S |
| B11 | Unsupported payment step | S7 | COD OTP step or UPI intent step reached, no completion | Offer agent-compatible payment (card token, prepaid link), skip COD OTP for verified agents | L |
| B12 | Rate limited | Any | 429 responses, session ends after | Higher limits for verified agents, `Retry-After` header | S |
| B13 | Slow response / timeout | Any | Last request duration > threshold (default 5 s) or abandoned in-flight | Performance fixes, caching | M |
| B14 | robots.txt disallow | S1/S2 | Agent fetched robots.txt, path disallowed for its token, agent left | Review robots policy for user-triggered agents | S |
| B15 | Price mismatch PDP vs cart | S5/S6 | Cart value ≠ sum of PDP prices seen in session (from catalog snapshot), session ends | Fix pricing consistency, show same price everywhere | M |
| B16 | Broken link / 404 | Any | 404 as last request on a product/checkout path | Fix links, redirects for old URLs | S |
| B99 | Unknown | Any | Nothing fired | LLM classifier / manual review | n/a |

Each fired rule writes evidence items like `{type: "request", request_id, summary: "POST /api/cart → 409 PINCODE_REQUIRED"}` or `{type: "site_check", check: "pdp_ssr_price", result: "missing"}`.

### 12.5 LLM classifier (optional)
- Used only for B99 sessions, and to write plain-English explanations for the top blockers.
- Input: compact session summary (max 40 requests: method, path, status, error code, duration, page type), identity, site check results, and the blocker catalog descriptions.
- Output (strict JSON, validated with Pydantic):
```json
{"blocker_id": "B05", "confidence": 0.72, "explanation": "The agent viewed the product, then the add-to-cart call failed twice asking for a pincode, and it left.", "suggested_new_blocker": null}
```
- If the LLM proposes something outside the catalog, store it in `suggested_new_blocker` and keep `B99`.
- Provider: Claude API via `ANTHROPIC_API_KEY`, model name from env `AGENTLENS_LLM_MODEL`. Wrapped in an interface so a mock provider is used in tests.
- Cost guardrails: max sessions per run (default 200), max tokens per call, response cache keyed on session-summary hash, daily spend cap estimate printed after each run.

### 12.6 Ground-truth isolation (hard rule)
- Synthetic ground truth lives only in `data/ground_truth/*.jsonl` and the `ground_truth` table.
- Diagnosis, identification and impact code **must not import or query** it. A unit test scans the diagnosis package for references to `ground_truth` and fails if found.
- The `eval` module is the only consumer.

---

## 13. C8 - Replay agent

### 13.1 Purpose
Confirm the top blockers with evidence a human can trust: "We re-ran the journey and here is the screenshot where it got stuck."

### 13.2 Behaviour
- Triggered per blocker (not per session): pick up to 3 representative failed sessions for each of the top N blockers (default N=5), or on demand from the dashboard.
- Two replay modes, matched to the original agent class:
  - **Fetch mode** (for `user_fetcher`): plain HTTP client, JS off, replays the URL sequence, checks whether price/stock/serviceability info is present in the response.
  - **Browser mode** (for `browsing_agent`): Playwright Chromium, replays the path step by step (open landing → PDP → select variant → serviceability → add to cart → checkout) up to the stage where the session ended.
- At each step: capture screenshot (browser mode), DOM text snapshot (trimmed), network log of key calls, timing.
- Verdict:
  - Rules first: for example, if `POST /api/cart` returns 409 `PINCODE_REQUIRED` → confirmed B05.
  - Optional LLM vision check: screenshot + step goal → "Is there an overlay blocking interaction? yes/no + reason".
- Output: `replays` record with `status` (`confirmed`, `not_reproduced`, `error`), evidence paths, steps log, duration.

### 13.3 Requirements
- RP1: Replays only target the demo store host(s) in `config/replay.yaml` (allow-list). Refuse any other host.
- RP2: Max 1 concurrent replay, max 50 replays per run, 2 s pause between steps.
- RP3: Screenshots stored under `data/replays/<replay_id>/step_<n>.png`.
- RP4: Replay uses a declared UA `AgentLens-Replay/1.0 (+https://github.com/<user>/agentlens)` and can optionally sign requests with the test operator key, to show the "verified agent allowed through the bot wall" scenario.
- RP5: Works headless by default, with `--headed` for recording the demo video.

---

## 14. C9 - Impact model (₹ at risk)

### 14.1 Definitions (per analysis window, scaled to 30 days)
For each terminal blocker *b* at stage *s*:

- `L_b` = failed agent sessions whose terminal blocker is *b*
- `p_s` = probability an agent session converts **given it passed stage s**, computed from agent sessions in the same window that passed *s* (fallback: human conversion from stage *s* × `agent_vs_human_factor`, default 1.0, if fewer than 30 agent sessions passed *s*)
- `r` = recoverable rate, the share of blocked sessions that would continue if the blocker were removed (default 0.6; low 0.4, high 0.8)
- `AOV_a` = average agent order value (fallback: overall AOV, then config default ₹2,200)
- `k` = 30 / window_days

**₹ at risk per month:**
```
Risk_b = L_b × r × p_s × AOV_a × k
```
Low/base/high scenarios use low/base/high `r` and a ±20% band on `p_s`.

### 14.2 Rules
- IM1: Only terminal blockers carry ₹ (no double counting).
- IM2: Show assumptions next to every number (tooltip and report appendix).
- IM3: If sample size < 30 sessions for a blocker, show "low confidence" and grey out.
- IM4: Total ₹ at risk = sum of blockers. Also show it as a % of current agent revenue.
- IM5: All assumption values editable in Settings and saved to `config/impact.yaml`.

### 14.3 Example
Pincode wall: `L=1,240` sessions/window (7 days), `r=0.6`, `p_s=0.18`, `AOV=₹2,200`, `k=30/7=4.29` → Risk ≈ 1,240 × 0.6 × 0.18 × 2,200 × 4.29 ≈ **₹12.6 lakh/month** (base).

---

## 15. C10 - Recommendation engine

- For each blocker with ₹ > 0, produce a recommendation from `config/blockers.yaml`: title, what to change, why it helps agents, how to verify (which metric should move), effort (S/M/L), owner (Eng / Product / Security / Content).
- **Priority score** = `Risk_b_base / effort_weight` (S=1, M=2, L=4). Sort descending.
- If the LLM is enabled, generate a 2-sentence tailored explanation citing the evidence (for example "92% of failures were 409 PINCODE_REQUIRED on add-to-cart").
- Each recommendation links to: blocker detail page, sample sessions, replay evidence.
- "Mark as fixed" action creates an annotation, which seeds a before/after comparison.

---

## 16. C11 - Dashboard

### 16.1 Global
- Next.js app at `apps/dashboard`, talks to the FastAPI backend.
- Global filters (top bar): date range, segment (All agents / Verified / Declared / Suspected / Humans), operator, agent class.
- Light and dark theme. INR formatting with lakh/crore (₹12.6 L, ₹1.2 Cr).
- Every number has a tooltip explaining the definition.
- Annotations (config changes, "marked fixed") appear as vertical markers on time charts.
- **Demo mode** flag: read-only, data loaded from a static JSON snapshot (for the public link).

### 16.2 Pages
**P1 Overview**
- KPI cards: Agent sessions (and % of all sessions), Agent conversion rate vs Human conversion rate, Agent revenue, **₹ at risk / month**, Identity coverage %, Verified share of agent traffic.
- Time series: sessions by segment per day.
- Agent mix donut: by operator. Bar: by class.
- "Top 3 fixes" card with ₹ and effort.

**P2 Agents**
- Table: operator, agent name, class, tier mix, sessions, pages/session, conversion, top blocker, signature status counts.
- Drawer: agent detail, recent sessions, trend.
- Crawler section (training/search crawlers), separate from shopping agents.

**P3 Funnel**
- Side-by-side funnel bars: Humans vs Agents (selectable second segment).
- Step conversion % and drop-off % at each stage.
- Click a stage → list of blockers ending sessions at that stage.

**P4 Blockers** (hero page)
- Ranked list: blocker, stage, sessions blocked, % of failed agent sessions, ₹ at risk (low/base/high), replay status badge, effort, priority.
- Detail view: description, evidence summary (top error codes, example requests), sample sessions, replay screenshots, recommendation, "Mark as fixed".

**P5 Session Explorer**
- Search/filter sessions. Timeline view of one session: each request with time, method, path, status, duration, stage chips, identity info, signature status, fired rules, terminal blocker highlight.

**P6 Replays**
- List of replays with status. Detail: step-by-step screenshots carousel, network log, verdict, explanation.

**P7 Before / After**
- Pick two windows (auto-suggested around annotations). Compare agent conversion, funnel, blocker shares, ₹ at risk. Show delta with a simple significance note (two-proportion z-test on conversion; show "not enough data" if < 100 sessions per window).

**P8 Settings and Report**
- Edit impact assumptions, thresholds, identification weights (writes YAML via API).
- Trigger pipeline run, replay run.
- Export Agent Readiness Report (Section 19).

### 16.3 UX requirements
- DX1: First meaningful paint < 2 s on 100k sessions (API pre-aggregates).
- DX2: Empty states explain what to do ("No data yet. Run `agentlens synth` or visit the store.").
- DX3: Accessible colours, keyboard navigation for tables.
- DX4: Charts use one consistent palette: agents vs humans always the same two colours.
- DX5: A "Story mode" toggle for the demo video: big fonts, hides dense tables, shows the hero numbers.

---

## 17. C12 - Synthetic traffic generator

### 17.1 Purpose
Produce realistic volume (humans plus many agent types) through the **real store and capture path**, with ground truth, so the pipeline can be tested and evaluated.

### 17.2 Modes
- **Live mode:** sends real HTTP traffic to the running store (httpx for fetchers and humans, Playwright for a sample of browsing agents). Default 5,000 sessions per run, configurable rate.
- **Offline mode:** writes log lines directly in the native schema (no store needed), for scale tests (1M+ lines) and CI. Must produce statistically similar data.

### 17.3 Personas (configurable in `config/synth.yaml`)
| Persona | Share (default) | Identity | Behaviour |
|---|---|---|---|
| Human shopper | 70% | Human | Realistic browser headers, beacons, assets, random think time, varied paths, ~3% conversion |
| Signed browsing agent (test operator) | 6% | Verified | Valid Web Bot Auth signatures, full browser behaviour, goal-directed |
| Declared ChatGPT-style user fetcher | 6% | Declared | `ChatGPT-User` UA token, no JS, fetches PDP and policies |
| Declared Claude-style user fetcher | 4% | Declared | `Claude-User` UA token, no JS |
| Declared Perplexity-style fetcher | 3% | Declared | `Perplexity-User` UA token |
| Undeclared headless agent | 5% | Suspected expected | Chrome UA, HeadlessChrome hints, no assets, regular timing |
| Forged-signature bot | 1% | Declared/Suspected, signature invalid | Copies a signature header with wrong key |
| Search/training crawlers | 5% | Declared crawlers | Googlebot/GPTBot/CCBot-like crawling patterns |

Note: user-agent tokens are used only on the generator's own requests to the demo store, to simulate declared agents.

### 17.4 Agent behaviour model
- Each agent session has a **task** (from Section 18 tasks) and a goal stage.
- At each step the generator checks the store response. If it hits active friction, it reacts per persona: retry up to 2 times, try an alternative path, or abandon. This yields realistic failure patterns.
- Agents complete orders when unblocked with a task-dependent probability (default 35% for browsing agents that reach checkout).

### 17.5 Ground truth
For each synthetic session, write to `data/ground_truth/gt-<run_id>.jsonl`:
`{run_id, synthetic_session_id, persona, expected_tier, operator, agent_class, task, toggles_active, blocker_hit (ID or null), stage_of_failure, converted}`.
Link to logs via a header `X-Synth-Session` that the capture layer logs into `meta.synth_session_id` **only** when `AGENTLENS_SYNTH_MODE=1`. Diagnosis code must not read this field (enforced by the isolation test).

### 17.6 CLI
```
agentlens synth live --sessions 5000 --rate 20/s --seed 42
agentlens synth offline --sessions 200000 --days 14 --seed 42 --out data/logs/
agentlens synth scenario before-after --before-days 7 --after-days 7
```
The `before-after` scenario flips the toggles from the "Before" to the "After" state halfway, and writes a `config_change` annotation at the switch.

---

## 18. C13 - Real-agent test harness

### 18.1 Purpose
Show genuine agents (not just synthetic ones) visiting the store, for credibility in the demo and to verify real Web Bot Auth signatures.

### 18.2 Setup
- Expose the local store with a tunnel: Cloudflare Tunnel (`cloudflared tunnel --url http://localhost:3000`) or ngrok. Record the public URL in `.env`.
- Agents to try (whatever is available to the builder): ChatGPT agent, Claude (browser or web fetch), Perplexity Comet, Gemini.

### 18.3 Standard tasks
| ID | Task prompt given to the agent |
|---|---|
| T1 | "On <URL>, find white sneakers under ₹4,000 in UK size 9." |
| T2 | "Which size should I buy if I'm usually UK 9 in Nike? Use the site's size guide." |
| T3 | "Can this be delivered to pincode 201301 by Friday? Is COD available?" |
| T4 | "Add the cheapest kurta in size M to the cart." |
| T5 | "Go to checkout and fill in a test address. Stop before payment." (Or complete in test mode.) |
| T6 | "What is the return window, and are returns free?" |

### 18.4 Run log
`docs/real-agent-runs.csv`: date, agent, task, toggles state, outcome (completed/partial/failed), notes, screen recording file name. Each run's sessions can be tagged in the dashboard via a time window.

### 18.5 Rules
- Only point agents at the demo store. Never at third-party sites.
- Never use real payment details.

---

## 19. C14 - Agent Readiness Report

- One page (two at most), generated from current data. Markdown and PDF.
- Contents: headline (agent share, agent vs human conversion, ₹ at risk), identity coverage, funnel comparison chart, top 5 blockers with ₹ and effort, top 3 fixes with how to verify, before/after result if available, assumptions and method appendix, date and data window.
- Endpoint `GET /api/report?format=md|pdf`. File saved to `data/reports/`.
- Style: clean, brand-neutral, readable on LinkedIn as an image (also export PNG of page 1).

---

## 20. Testing and evaluation

### 20.1 Test layers
| Layer | Tooling | What |
|---|---|---|
| Unit (Python) | pytest | Parsers, signature verification, UA matching, suspicion scoring, sessionization edge cases, each diagnosis rule, impact math |
| Unit (TS) | Vitest | Store friction logic, capture logger, dashboard formatting utils (INR lakh/crore) |
| Integration | pytest + live store | Synthetic live run → pipeline → expected tables populated |
| E2E | Playwright | Dashboard pages render, filters work, report export works |
| Evaluation | `agentlens eval` | Accuracy metrics vs ground truth (SC1 to SC5) |
| Performance | `agentlens synth offline` 1M lines | SC6 timing |
| Isolation | pytest | Diagnosis/identification packages contain no ground-truth references |

### 20.2 Signature test vectors
- Valid signature, valid window → Verified.
- Expired (`expires` < ts) → not verified, `expired`.
- Tampered `@authority` → `invalid_sig`.
- Unknown `keyid` → `unknown_key`.
- Directory unreachable (offline, no cache) → `fetch_failed`, not verified.
- Signature header present but `tag` not `web-bot-auth` → ignored for Tier 1.

### 20.3 Golden dataset
- `tests/golden/`: 2,000 sessions offline-generated with fixed seed covering every blocker at least 50 times plus clean sessions. Expected outputs checked in.
- Eval report: confusion matrix for tiers and blockers, precision/recall/F1 per blocker, written to `data/eval/eval-<date>.md` and shown in the README.

### 20.4 Acceptance criteria per component (summary)
- C1: All 16 toggles demonstrably change behaviour (E2E test per toggle).
- C2: 100% of requests logged, schema-valid, no PII fields (test sends a phone in body and asserts it never appears in logs).
- C3: Ingest 1M lines within SC6 budget, bad lines quarantined.
- C4: SC1 to SC3 met.
- C5/C6: Session counts within ±2% of ground truth. Funnel reach matches ground truth stages ≥ 98%.
- C7: SC4 met.
- C8: SC5 met. Refuses non-allow-listed hosts (test).
- C9: Impact math unit tests with fixed inputs, including the 14.3 example.
- C11: SC7 met. All pages have empty states.
- C14: Report renders with and without before/after data.

---

## 21. Data model (DuckDB)

Database file: `data/agentlens.duckdb`.

**requests**
`request_id PK, ts, method, host, path, query, status, bytes_out, duration_ms, ip_hash, ip_prefix, user_agent, ua_hash, referer, accept, accept_language, sec_ch_ua, sec_fetch_site, sec_fetch_mode, sec_fetch_dest, has_signature, signature_status, signature_agent, cookie_sid_hash, is_asset, event_type, page_type, error_code, identity_tier, operator, agent_name, agent_class, identity_confidence, suspicion_score, session_id, ingested_at, source_file`

**sessions**
`session_id PK, session_key, start_ts, end_ts, duration_s, request_count, page_count, has_beacon, identity_tier, operator, agent_name, agent_class, identity_confidence, entry_page, exit_page, max_stage, converted, order_id, order_value, terminal_blocker_id, blocker_confidence, diagnosis_method (rule|llm|none)`

**session_stages**
`session_id, stage_id, first_reached_ts`

**blocker_hits**
`session_id, blocker_id, stage_id, confidence, is_terminal, evidence_json`

**site_checks**
`check_id PK, run_ts, check_name, target, result (pass|fail|warn), details_json`

**replays**
`replay_id PK, blocker_id, source_session_id, mode (fetch|browser), status, started_at, finished_at, steps_json, evidence_dir, verdict_explanation`

**impact**
`run_id, window_start, window_end, blocker_id, stage_id, sessions_blocked, p_stage, recoverable_low, recoverable_base, recoverable_high, aov, risk_low, risk_base, risk_high, low_confidence`

**recommendations**
`rec_id PK, run_id, blocker_id, title, body, effort, owner, priority_score, status (open|fixed), fixed_annotation_id`

**annotations**
`annotation_id PK, ts, type (config_change|marked_fixed|note), label, details_json`

**orders**
`order_id PK, ts, session_id, cookie_sid_hash, order_value, payment_method`

**key_cache**
`signature_agent, fetched_at, keys_json, status`

**ingest_state** `source_file PK, last_offset, last_ingested_at`
**ingest_errors** `source_file, line_no, error, raw_line, ts`
**ground_truth** (eval only) `run_id, synthetic_session_id, persona, expected_tier, operator, agent_class, task, toggles_json, blocker_hit, stage_of_failure, converted`
**runs** `run_id PK, started_at, finished_at, steps_json, status, counts_json`

---

## 22. Configuration files

### 22.1 `config/agents.yaml` (excerpt, full starter list in Appendix A)
```yaml
operators:
  openai:
    display_name: OpenAI
    signature_agents: ["https://chatgpt.com"]
    agents:
      - name: ChatGPT-User
        ua_tokens: ["ChatGPT-User"]
        class: user_fetcher
      - name: OAI-SearchBot
        ua_tokens: ["OAI-SearchBot"]
        class: search_crawler
      - name: GPTBot
        ua_tokens: ["GPTBot"]
        class: training_crawler
  anthropic:
    display_name: Anthropic
    agents:
      - name: Claude-User
        ua_tokens: ["Claude-User"]
        class: user_fetcher
      - name: Claude-SearchBot
        ua_tokens: ["Claude-SearchBot"]
        class: search_crawler
      - name: ClaudeBot
        ua_tokens: ["ClaudeBot"]
        class: training_crawler
  test_operator:
    display_name: AgentLens Test Operator
    signature_agents: ["https://agents.desithreads.test"]
    agents:
      - name: TestSignedAgent
        ua_tokens: ["TestSignedAgent"]
        class: browsing_agent
```

### 22.2 `config/identification.yaml`
```yaml
signature:
  clock_skew_s: 60
  key_cache_ttl_s: 3600
  offline_mode: false
suspicion:
  threshold: 60
  page_velocity_per_min: 15
  weights:
    no_beacon_with_browser_ua: 25
    no_assets: 15
    headless_hint: 30
    missing_sec_fetch: 10
    regular_timing: 10
    high_velocity: 10
    deep_link_cart_rush: 5
    atypical_accept: 5
    invalid_signature: 30
sessions:
  timeout_min_human: 30
  timeout_min_agent: 10
```

### 22.3 `config/funnel.yaml`
```yaml
stages:
  - id: S1
    name: Landing / Search
    rules:
      - { method: GET, path: "^/$" }
      - { method: GET, path: "^/search" }
      - { method: GET, path: "^/c/" }
  - id: S2
    name: Product page
    rules: [{ method: GET, path: "^/p/[^/]+$" }]
  - id: S3
    name: Variant selected
    rules: [{ method: GET, path: "^/api/products/[^/]+/variants" }]
  - id: S4
    name: Delivery check
    rules: [{ method: GET, path: "^/api/serviceability" }]
  - id: S5
    name: Added to cart
    rules: [{ method: POST, path: "^/api/cart$" }]
  - id: S6
    name: Checkout started
    rules: [{ method: GET, path: "^/checkout$" }]
  - id: S7
    name: Checkout submitted
    rules: [{ method: POST, path: "^/api/checkout$" }]
  - id: S8
    name: Order placed
    rules: [{ method: GET, path: "^/order/confirmed/" }]
success_status: [200, 201, 204, 302]
```

### 22.4 `config/impact.yaml`
```yaml
recoverable_rate: { low: 0.4, base: 0.6, high: 0.8 }
p_stage_band: 0.2
default_aov_inr: 2200
agent_vs_human_factor: 1.0
min_sample: 30
effort_weights: { S: 1, M: 2, L: 4 }
```

### 22.5 `config/replay.yaml`
```yaml
allowed_hosts: ["localhost:3000", "desithreads.local", "${PUBLIC_STORE_HOST}"]
top_n_blockers: 5
sessions_per_blocker: 3
max_replays_per_run: 50
step_pause_s: 2
user_agent: "AgentLens-Replay/1.0 (+https://github.com/<user>/agentlens)"
sign_requests: false
```

### 22.6 `.env.example`
```
AGENTLENS_IP_SALT=change-me
AGENTLENS_ADMIN_PASSWORD=change-me
ANTHROPIC_API_KEY=            # optional; empty = rules-only mode
AGENTLENS_LLM_MODEL=          # e.g. a current Claude model name
AGENTLENS_LLM_MAX_SESSIONS=200
AGENTLENS_SYNTH_MODE=0
PUBLIC_STORE_HOST=            # tunnel host for real-agent runs
STORE_URL=http://localhost:3000
API_URL=http://localhost:8000
DEMO_MODE=0
```

---

## 23. Metrics and definitions

| Metric | Definition |
|---|---|
| Agent sessions | Sessions with tier Verified/Declared/Suspected and class `user_fetcher` or `browsing_agent` |
| Agent share | Agent sessions / all non-crawler sessions |
| Agent conversion rate | Converted agent sessions / agent sessions |
| Human conversion rate | Converted human sessions / human sessions |
| Stage step conversion | Sessions reaching stage n+1 / sessions reaching stage n |
| Agent revenue | Sum of order value for converted agent sessions |
| Blocker incidence | Failed agent sessions with terminal blocker b / all failed agent sessions |
| ₹ at risk | Section 14 |
| Identity coverage | (Verified + Declared agent sessions) / (all agent sessions incl. Suspected). Shows how much agent traffic is confidently identified |
| Verified share | Verified agent sessions / agent sessions |
| Replay confirmation rate | Confirmed replays / completed replays |
| Diagnosis coverage | Failed agent sessions with a non-B99 blocker / failed agent sessions |

---

## 24. Key product decisions and trade-offs

These are the PRD decisions that show product thinking. Each must also exist as an ADR in `docs/decisions/`.

| # | Decision | Chosen | Alternatives considered | Why |
|---|---|---|---|---|
| D1 | Data source | Server logs | JS tag, CDN-only logs | Logs see agents that never run JS. Tags miss them. CDN logs are a v1.1 add-on |
| D2 | Identity model | 3 tiers with confidence | Binary bot/human | Honest about certainty. Lets teams set policy per tier |
| D3 | What counts as an "agent conversion" | Order placed within an agent-identified session | Any AI-referred order; agent-assisted | Clean and measurable. AI-referred and assisted are listed as future segments |
| D4 | Terminal blocker attribution | One per failed session, highest stage | Count all blockers | Avoids double counting ₹ |
| D5 | Rules first, LLM second | Deterministic rules, LLM only for unknowns | LLM for everything | Cheaper, testable, explainable. LLM adds coverage without being a black box |
| D6 | Replay to confirm | Yes, top blockers only | No replay; replay every session | Evidence builds trust. Top-N keeps cost and load low |
| D7 | ₹ with ranges | Low/base/high with visible assumptions | Single number | A single precise number would be false precision |
| D8 | Observe, don't block | AgentLens never blocks traffic | Act as WAF | Keeps scope focused. Blocking is a policy decision for the retailer |
| D9 | Privacy | Hash IPs with salt, no bodies, no PII | Store raw logs | Privacy by design. Still enough for analysis |
| D10 | Demo store friction labels | Not logged; inferred | Log friction directly | Keeps diagnosis honest and realistic |
| D11 | Open vs block agents (customer guidance) | Recommend "allow verified, challenge suspicious" | Block all / allow all | Balances revenue and risk |

**ADR template (`docs/decisions/ADR-000-template.md`):**
```
# ADR-XXX: <title>
Date: YYYY-MM-DD
Status: Accepted | Superseded
## Context
## Decision
## Alternatives considered
## Consequences
```

---

## 25. Privacy, security and ethics

- PS1: No raw IPs, phone numbers, emails, addresses, OTPs or request bodies in logs or database.
- PS2: IP hashing uses a secret salt from `.env`. Rotating the salt breaks linkage (documented).
- PS3: Data retention: logs older than 30 days auto-deleted by `agentlens prune` (configurable).
- PS4: Admin page protected by password from env. Admin never exposed in demo mode.
- PS5: Replay agent restricted to allow-listed hosts (RP1).
- PS6: Real-agent runs only against the demo store. Never test third-party sites without permission.
- PS7: No real payments. Clear "TEST STORE: no real orders" banner on every store page.
- PS8: Public demo is read-only, synthetic data only.
- PS9: Secrets never committed. `.env` in `.gitignore`. A pre-commit check (e.g. `gitleaks` or a simple grep) blocks committing keys.
- PS10: Dependencies pinned. `pip-audit` / `npm audit` run in CI.
- PS11: README states clearly that this is a demo and synthetic dataset, and the limits of identification (11.4).

---

## 26. Non-functional requirements

| Area | Requirement |
|---|---|
| Performance | SC6, SC7. API p95 < 300 ms for dashboard endpoints on 100k sessions |
| Scalability | Single-node DuckDB. Designed for up to ~10M requests on a laptop |
| Reliability | Pipeline idempotent and resumable. Failures in one step don't corrupt previous outputs (write to temp tables, swap) |
| Portability | Windows 11 and macOS. Docker Compose default, native fallback |
| Observability | Structured logs for the pipeline (`logs/agentlens.log`), run summary table `runs` |
| Maintainability | Type hints (mypy clean), ruff lint, ESLint + Prettier, clear module boundaries |
| Cost | Runs fully free. LLM optional, with spend estimate shown per run |
| Accessibility | WCAG AA colour contrast on dashboard |
| Documentation | README, ARCHITECTURE.md, ADRs, CONTRIBUTING.md, eval report |

---

## 27. Tech stack and repo structure

### 27.1 Stack
| Layer | Choice |
|---|---|
| Demo store | Next.js 15 (App Router), TypeScript, Tailwind CSS |
| Dashboard | Next.js 15, TypeScript, Tailwind, Recharts, TanStack Table |
| Backend API | Python 3.12, FastAPI, Pydantic v2, Uvicorn |
| Analytics DB | DuckDB (embedded file) |
| Data processing | DuckDB SQL + Polars or PyArrow |
| Signatures | `cryptography` (Ed25519) + RFC 9421 signature-base builder (own module or a maintained library; document choice in ADR) |
| Replay | Playwright for Python (Chromium) |
| LLM (optional) | Anthropic Python SDK, model from env |
| Synthetic traffic | httpx (async), Playwright, Faker (Indian locale `en_IN`) |
| CLI | Typer |
| Tests | pytest, Vitest, Playwright Test |
| Lint/format | ruff, mypy, ESLint, Prettier |
| Packaging | uv (Python), pnpm (Node) |
| Containers | Docker Compose (store, api, dashboard). Native scripts as fallback |
| PDF | Playwright print-to-PDF (no extra system deps) |

### 27.2 Repo structure
```
agentlens/
├─ README.md
├─ ARCHITECTURE.md
├─ CONTRIBUTING.md
├─ LICENSE (MIT)
├─ .env.example
├─ docker-compose.yml
├─ Makefile / tasks.ps1          # same commands on Windows and macOS
├─ config/
│  ├─ agents.yaml
│  ├─ identification.yaml
│  ├─ funnel.yaml
│  ├─ blockers.yaml
│  ├─ impact.yaml
│  ├─ replay.yaml
│  └─ synth.yaml
├─ apps/
│  ├─ store/                      # Next.js demo store "Desi Threads"
│  │  ├─ app/ (routes from 8.2)
│  │  ├─ lib/friction.ts
│  │  ├─ lib/logger.ts
│  │  ├─ middleware.ts
│  │  ├─ data/catalog.json
│  │  └─ config/friction.json
│  └─ dashboard/                  # Next.js dashboard
│     ├─ app/ (pages P1–P8)
│     ├─ components/
│     └─ lib/api.ts, lib/format.ts
├─ services/
│  ├─ api/                        # FastAPI + pipeline
│  │  ├─ main.py
│  │  ├─ cli.py                   # Typer entrypoint "agentlens"
│  │  ├─ ingest/
│  │  ├─ identify/ (signatures.py, ua_registry.py, suspicion.py)
│  │  ├─ sessions/
│  │  ├─ funnel/
│  │  ├─ diagnosis/ (engine.py, rules/, llm.py, site_checks.py)
│  │  ├─ impact/
│  │  ├─ recommend/
│  │  ├─ report/
│  │  ├─ eval/                    # only module allowed to read ground truth
│  │  └─ db.py, schema.sql
│  ├─ replay/
│  │  ├─ runner.py
│  │  └─ verdicts.py
│  └─ synth/
│     ├─ live.py
│     ├─ offline.py
│     ├─ personas.py
│     └─ signer.py                # test operator Web Bot Auth signer
├─ tests/
│  ├─ python/
│  ├─ golden/
│  └─ e2e/
├─ docs/
│  ├─ PRD.md                      # this document
│  ├─ decisions/ADR-*.md
│  ├─ real-agent-runs.csv
│  └─ demo-script.md
└─ data/                          # gitignored: logs, db, replays, reports, eval
```

---

## 28. Environment setup (Windows 11 with admin rights, macOS also supported)

### 28.1 Prerequisites
- Git, VS Code.
- **Option A (default): Docker Desktop.** Note: Docker Desktop needs a paid subscription for use at larger companies. For a personal open-source project on a personal licence this is usually fine, but check the licence terms for your situation. If in doubt, use Option B.
- **Option B (native):** Python 3.12 (python.org installer, tick "Add to PATH"), `uv` (`pip install uv` or the official installer), Node.js 22 LTS, `pnpm` (`npm i -g pnpm`), then `uv run playwright install chromium`.
- Optional: `cloudflared` or `ngrok` for real-agent runs.

### 28.2 One-command start
```
# Option A
docker compose up --build

# Option B (PowerShell)
./tasks.ps1 setup     # installs Python + Node deps, Playwright browser
./tasks.ps1 dev       # starts store :3000, api :8000, dashboard :3001
```

### 28.3 Typical demo flow
```
./tasks.ps1 synth-scenario     # before-after scenario, ~10k sessions
./tasks.ps1 pipeline           # agentlens run-all
./tasks.ps1 replay             # replay top blockers
# open http://localhost:3001
```

---

## 29. Deployment (free tier + local)

### 29.1 Local (full product)
Everything runs locally: store, API, dashboard, replay. Used for the screen-recorded demo video.

### 29.2 Public free-tier demo (read-only)
- `agentlens export-snapshot` writes all dashboard API responses for the demo dataset to `apps/dashboard/public/demo/*.json` plus replay screenshots.
- Dashboard built with `DEMO_MODE=1` reads the snapshot instead of the API (no backend needed).
- Deploy the dashboard to **Vercel Hobby (free)** as a static/SSG site.
- Optionally deploy the demo store to Vercel too (logging disabled, banner "Demo store: logs not collected in public mode").
- README links: live demo, video, GitHub.
- Free-tier limits and terms change; check the current Vercel Hobby terms before deploying.

### 29.3 Real-agent runs
Done locally through a tunnel (Section 18), not on the public deployment.

---

## 30. Milestones and build plan (with prompts for Claude)

Estimated: 6 to 7 weekends. Each milestone ends with a demoable result.

### M0: Repo skeleton and setup (½ weekend)
**Scope:** repo structure (27.2), Docker Compose, tasks.ps1/Makefile, lint/format configs, `.env.example`, empty FastAPI with `/health`, empty Next.js apps, CI workflow (lint + tests), README skeleton, ADR template.
**DoD:** `docker compose up` (or `tasks.ps1 dev`) shows store, dashboard and `/health` running. CI green.
**Prompt:** "Using the attached AgentLens PRD, build Milestone M0 exactly as specified in Sections 27 and 28. Output every file in full with its path. Then give Windows PowerShell run commands and a checklist to confirm M0's Definition of Done."

### M1: Demo store + friction toggles + capture (1½ weekends)
**Scope:** C1 and C2 in full: catalogue seed script, all routes in 8.2, 16 toggles with `/admin`, beacon, JSON-LD, test checkout, JSONL logging with PII scrubbing, annotations.
**DoD:** all 16 toggles change behaviour (E2E tests), log lines match the schema, PII test passes.
**Prompt:** "Build Milestone M1 (Sections 8 and 9). Include the E2E test per toggle and the PII test."

### M2: Synthetic traffic + ingestion + identification + sessions (1½ weekends)
**Scope:** C12 (live and offline, personas, ground truth, test operator signer), C3, C4 (all tiers incl. Web Bot Auth verification and test vectors), C5.
**DoD:** `agentlens synth live` + `agentlens run-all` (up to sessionization) produce correct tables. Signature test vectors pass. SC1 to SC3 measured.
**Prompt:** "Build Milestone M2 (Sections 10, 11, 12.1, 17). Follow the ground-truth isolation rule in 12.6."

### M3: Funnel + diagnosis + impact + recommendations (1 weekend)
**Scope:** C6, C7 rules B01 to B16 + site checks + LLM classifier (mockable), C9, C10, eval module and golden dataset.
**DoD:** SC4 met on golden set, impact example 14.3 reproduces, eval report generated.
**Prompt:** "Build Milestone M3 (Sections 12.2 to 12.6, 14, 15, 20.3). Rules-only mode must work with no API key."

### M4: Dashboard (1½ weekends)
**Scope:** C11 pages P1 to P8, global filters, annotations on charts, INR formatting, story mode, API endpoints needed (Section 31).
**DoD:** all pages render with demo data, SC7 met, E2E tests pass.
**Prompt:** "Build Milestone M4 (Sections 16 and 31). Prioritise P1 Overview, P3 Funnel and P4 Blockers polish for the demo video."

### M5: Replay agent + before/after + report (1 weekend)
**Scope:** C8 (fetch and browser modes, verdicts, allow-list), P7 before/after, C14 report (MD, PDF, PNG).
**DoD:** SC5 met on top 5 blockers, before/after scenario shows the conversion jump, report exports.
**Prompt:** "Build Milestone M5 (Sections 13, 16.2 P7, 19)."

### M6: Polish, public demo, launch assets (1 weekend)
**Scope:** export-snapshot + DEMO_MODE, Vercel deploy guide, README (problem, demo GIF, architecture diagram, decisions, eval results, limitations, setup), ARCHITECTURE.md, demo script, real-agent runs (Section 18).
**DoD:** public link works, README setup verified on a fresh clone (SC8), demo video recorded.
**Prompt:** "Build Milestone M6 (Sections 29, 32, and the README requirements in Section 26)."

### Working tips for building with Claude chat
- Attach this PRD every time (or paste the relevant sections plus Sections 0, 21, 22).
- One milestone per conversation if the chat gets long. Start the next chat with: the PRD, the current repo tree (`tree /F` output) and any errors.
- Keep a `CHANGELOG.md` updated at the end of each milestone.
- When something fails, paste the full error plus the file involved and ask for the complete corrected file.

---

## 31. API specification (FastAPI)

Base URL `http://localhost:8000/api`. All responses JSON. Filters as query params: `from`, `to`, `segment`, `operator`, `agent_class`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/ingest` | Ingest logs from configured source |
| POST | `/pipeline/run` | Run full pipeline (async job), returns `run_id` |
| GET | `/runs/{run_id}` | Run status and counts |
| GET | `/overview` | KPI cards + time series + mix |
| GET | `/agents` | Agent table |
| GET | `/agents/{operator}/{agent_name}` | Agent detail |
| GET | `/funnel` | Funnel per segment (`compare=humans`) |
| GET | `/blockers` | Ranked blockers with ₹ and status |
| GET | `/blockers/{blocker_id}` | Detail: evidence, sample sessions, replays, recommendation |
| GET | `/sessions` | Paginated session search |
| GET | `/sessions/{session_id}` | Session timeline |
| POST | `/replays/run` | Run replays for top blockers or a given `blocker_id` |
| GET | `/replays` / `/replays/{replay_id}` | Replay list / detail |
| GET | `/compare` | Before/after metrics for two windows |
| GET | `/annotations` / POST `/annotations` | List / create annotations |
| GET | `/recommendations` / PATCH `/recommendations/{id}` | List / mark fixed |
| GET | `/settings` / PUT `/settings` | Read / update config values |
| GET | `/report?format=md\|pdf\|png` | Agent Readiness Report |
| GET | `/eval/latest` | Latest evaluation results |
| GET | `/site-checks` | Site-level check results |

Example `GET /blockers` response:
```json
{
  "window": {"from": "2026-11-13", "to": "2026-11-19"},
  "total_risk_base_inr": 2140000,
  "items": [
    {"blocker_id": "B05", "name": "Pincode wall", "stage": "S5", "sessions_blocked": 1240,
     "share_of_failed": 0.31, "risk_inr": {"low": 840000, "base": 1260000, "high": 1680000},
     "replay_status": "confirmed", "effort": "S", "priority_score": 1260000, "low_confidence": false}
  ]
}
```

---

## 32. Demo script (60 to 90 second video)

| Time | Screen | Voice-over (first person, casual) |
|---|---|---|
| 0–8 s | Agent (ChatGPT agent or synthetic browser) trying to buy sneakers on Desi Threads, getting stuck at a pincode modal | "This is an AI agent trying to buy sneakers for me. Watch where it gets stuck." |
| 8–20 s | AgentLens Overview: agent share, agent vs human conversion, ₹ at risk | "My analytics would never show this. So I built AgentLens. It reads server logs and spots AI agents, even the ones that don't run JavaScript." |
| 20–35 s | Funnel page: agents vs humans, big drop at Delivery check / Cart | "Humans get through fine. Agents drop off hard at the cart." |
| 35–50 s | Blockers page: "Pincode wall: 31% of failed agent sessions, ₹12.6 L/month", replay screenshot | "AgentLens finds the reason, replays the journey to prove it, and puts a rupee value on it." |
| 50–65 s | `/admin`: toggle pincode wall off. Before/After page shows agent conversion jump | "One fix. Switched off the pincode wall, re-ran the traffic, and agent conversion went from X% to Y%." |
| 65–80 s | GitHub README + architecture diagram | "It's open source. PRD, code and evaluation numbers are all on GitHub. Link in comments." |

Record with dashboard Story mode on, browser zoom 125%, 1080p, captions burned in.

---

## 33. LinkedIn content plan (tie-in)

1. **Problem post:** "Your analytics can't see your fastest-growing customer." No product yet, just the insight.
2. **Build decision post:** why logs and not tags, and how agent identity works (Web Bot Auth explained simply).
3. **Hero demo video:** Section 32.
4. **PRD trade-off post:** "What counts as an agent conversion?" Invite debate (D3).
5. **What broke post:** honest lessons, evaluation numbers, GitHub link, call for contributors.

Writing style: human-sounding Indian professional English, casual first person, no Unicode bold, no em-dashes, no consulting jargon.

---

## 34. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Big vendors already offer agent analytics | "Me-too" perception | Lead with the differentiators: diagnosis + replay proof + ₹ + India blockers + open source |
| Web Bot Auth spec changes | Verification breaks | Isolate in `identify/signatures.py`, record spec version in ADR, test vectors |
| Real agents fail to reach the local store (tunnel, blocks) | No real-agent footage | Synthetic signed agents cover the story. Record whichever real agent works |
| Agents in the user's browser look human | Under-counting | Suspected tier + clear limitation note + identity coverage metric |
| Synthetic data looks "too clean" | Credibility | Add noise, retries, partial failures, human-like variance. Show eval numbers honestly |
| LLM cost overrun | Money | Rules-first, caps, cache, spend estimate per run, mock mode |
| Scope creep | Never ships | Strict milestones. v1.1/future list. Demo-first priorities (P1, P3, P4) |
| Building on a company laptop | Possible IT policy or IP ownership questions with the current employer | Keep the repo on a personal GitHub account, build in personal time, and check company policy (or use a personal machine) |
| Docker Desktop licensing at a large company | Licence issue | Use native setup (Option B) if unsure |
| Free-tier terms change | Public demo goes down | Static snapshot is portable (Vercel, Netlify, GitHub Pages, Cloudflare Pages) |

---

## 35. Open questions (defaults assumed, change if needed)

| # | Question | Default assumed |
|---|---|---|
| Q1 | Product name | AgentLens (check name availability on GitHub before launch) |
| Q2 | Demo store category and name | Indian fashion/footwear, "Desi Threads" |
| Q3 | Currency and locale | INR, en-IN, lakh/crore formatting |
| Q4 | LLM provider | Claude API, optional |
| Q5 | Licence | MIT |
| Q6 | Public demo host | Vercel Hobby (free), static snapshot |
| Q7 | Which real agents to use in the video | Whatever is available at recording time; ChatGPT agent preferred for verified signatures |
| Q8 | Repo visibility during build | Private until M6, then public |

---

## Appendix A - Starter agent registry (verify at build time)

Agent names and tokens change often. Claude must check each operator's current official documentation when building and update `config/agents.yaml`. Starter list:

| Operator | Token / name | Class | Notes |
|---|---|---|---|
| OpenAI | ChatGPT-User | user_fetcher | User-triggered fetches |
| OpenAI | OAI-SearchBot | search_crawler | Search indexing |
| OpenAI | GPTBot | training_crawler | Training |
| OpenAI | ChatGPT agent (browser) | browsing_agent | Identify via Web Bot Auth `Signature-Agent: https://chatgpt.com` |
| Anthropic | Claude-User | user_fetcher | User-triggered fetches |
| Anthropic | Claude-SearchBot | search_crawler | Search |
| Anthropic | ClaudeBot | training_crawler | Training |
| Perplexity | Perplexity-User | user_fetcher | User-triggered |
| Perplexity | PerplexityBot | search_crawler | Indexing |
| Google | Googlebot | search_crawler | Exclude from shopping funnel |
| Google | Google-Extended | robots token only | Not a user-agent; robots.txt analysis only |
| Google | Google agent (browsing) | browsing_agent | Some requests signed via Web Bot Auth; check current docs for the signature agent domain |
| Apple | Applebot | search_crawler | |
| Apple | Applebot-Extended | robots token only | robots.txt only |
| Amazon | Amazonbot | search_crawler | |
| Meta | Meta-ExternalAgent | training_crawler | |
| Meta | Meta-ExternalFetcher | user_fetcher | |
| Common Crawl | CCBot | training_crawler | |
| ByteDance | Bytespider | training_crawler | |
| DuckDuckGo | DuckAssistBot | user_fetcher | |
| Mistral | MistralAI-User | user_fetcher | |
| AgentLens | AgentLens-Replay | internal | Exclude from all metrics |
| AgentLens | TestSignedAgent | browsing_agent | Synthetic test operator |

---

## Appendix B - Blocker evidence examples

| Blocker | Example evidence line shown in UI |
|---|---|
| B01 | `GET /p/white-court-sneaker → 403 (challenge page) · agent: ChatGPT-User (Declared)` |
| B03 | `Site check: price not found in server HTML or JSON-LD on 5/5 sampled PDPs` |
| B05 | `POST /api/cart → 409 PINCODE_REQUIRED (×2) · session ended 4 s later` |
| B06 | `POST /api/cart → 401 → GET /login → POST /api/otp/send · no verify · ended` |
| B10 | `POST /api/checkout → 422 PHONE_FORMAT (×3)` |
| B12 | `GET /p/... → 429 Retry-After: 60 · ended` |

---

## Appendix C - Definition of the "Before" and "After" demo states

| Toggle | Before | After |
|---|---|---|
| F03 JS-only price | ON | OFF |
| F05 Pincode wall | ON | OFF |
| F06 OTP before cart | ON | OFF |
| F07 App interstitial | ON | ON |
| F09 Size chart image-only | ON | ON |
| F10 Strict phone validation | ON | ON |
| All others | OFF | OFF |

Expected story: agent conversion rises clearly after the change, the pincode wall disappears from the blockers list, and the remaining blockers (interstitial, size chart, phone validation) become the new "next fixes".

---

## Appendix D - README outline (part of the product)

1. One-line pitch + demo GIF
2. The problem (3 bullets)
3. What AgentLens does (diagnose → prove → put a ₹ value on it)
4. Live demo link + video link
5. Architecture diagram
6. Quick start (Docker / native)
7. How identification works (3 tiers, Web Bot Auth) + limitations
8. Blocker catalog
9. Evaluation results (table)
10. Key product decisions (link to ADRs)
11. Roadmap
12. Contributing, licence
13. About the author (PM who builds)

---

*End of PRD.*
