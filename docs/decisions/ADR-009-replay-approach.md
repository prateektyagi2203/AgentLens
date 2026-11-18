# ADR-009: Replay agent approach
Date: 2026-11-18
Status: Accepted
## Context
PRD 13 asks for a test agent that re-runs a failed journey, confirms the blocker and keeps evidence. It must be safe (allow-listed hosts only, no CAPTCHA solving, no real PII), cheap, deterministic enough for CI, and able to use an LLM when a key exists (ADR-001).
## Decision
- **Two modes.** Fetch mode uses `httpx` (no JavaScript) and sees what a `user_fetcher` agent sees: HTML, JSON-LD, forms, JSON APIs, headers, timings. Browser mode uses Playwright Chromium and sees overlays and the rendered DOM, with screenshots as evidence. Fetch is the default; only hypotheses that need a DOM (B07) upgrade to browser.
- **Hypothesis-driven journeys, not free-form agents.** One scripted shopping journey (search, product, variant, delivery, cart, checkout) emits signals per blocker hypothesis (`present` / `absent`). Verdicts come from these signals by fixed rules, so a replay is reproducible and unit-testable. The LLM never decides the verdict.
- **LLM as a planner only.** With `AGENTLENS_LLM_PROVIDER=openai` and a key, the model picks the next action from the journey's allowed actions; invalid answers, API errors or the token budget fall back to the deterministic planner for the rest of the replay. `mock`/no key uses the deterministic planner, so CI never needs a key. Vision (screenshots to OpenAI) is optional and off by default.
- **Hard budgets.** `max_steps`, `max_seconds`, `max_tokens` per replay, `max_replays_per_run` per run, one replay at a time, `step_pause_s` between requests.
- **Safety at the client.** The allow-list is enforced inside the HTTP client (base URL, every request, every redirect hop) and the browser's request routing, not only at the CLI. `robots.txt` is respected and a disallow is evidence for B14. CAPTCHAs are recorded, never solved. Only fake test data is submitted; the test-OTP workaround is limited to local hosts.
- **Identity.** `AgentLens-Replay/1.0 (...; run=<replay_id>)`. The store exempts the token from its bot wall (F01), B01 is therefore checked by a control-UA probe. The per-run suffix is needed because the store keys cart/pincode/OTP state on IP + User-Agent for cookie-less clients, so a shared UA leaks state between replays. Optional Web Bot Auth signatures use the test-operator key.
- **Storage.** The existing `replays` table, no schema change: `steps_json` holds `{verdict, user_agent, signed_requests, steps[], network_log[]}` plus extras; `not_reproduced` is stored as `not_confirmed` to match the API contract. Evidence goes to `data/replays/<id>/`.
- **Integration.** `agentlens.replay.runner.run_replays(con, blocker_id=None, top_n=None, on_step=None)` is the entry point for the CLI and the API; `agentlens replay` / `replay-all` are the commands.
## Alternatives considered
- LLM-driven browsing agent (browser-use style): non-deterministic, costly, hard to test, and it could wander off the allow-list. Rejected for the verdict path; kept as an optional planner under rules above.
- Replaying recorded sessions request by request: the logs hold no bodies and sessions carry stale cart state, so it cannot confirm a wall reliably.
- Browser mode only: slower and heavier; most blockers are visible over HTTP.
## Consequences
- 14 of 16 hypotheses are confirmed in fetch mode in CI against the real store (`pytest -m integration`); B07 needs Chromium; B16 has no store friction, so it is only observed if the store has broken links.
- A replay proves a hypothesis on a test store, not that the same blocker hit a particular real session; the report says so.
- Adding a hypothesis is a table entry plus one `signal()` call (docs/replay-agent.md).
- OpenAI planning and vision are untested against the live API without a key; the fallback paths are unit-tested with a mock transport.
