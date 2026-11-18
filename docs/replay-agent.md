# Replay agent

The replay agent re-runs a shopping task against the store as an AgentLens test agent and answers one question per blocker:
**does the hypothesis reproduce?** Verdicts are `confirmed`, `not_reproduced` (stored and served as `not_confirmed`) and
`inconclusive`. Package: `agentlens.replay` (`services/replay`). ADR: [ADR-009](decisions/ADR-009-replay-approach.md).

```powershell
agentlens replay --blocker B05                                  # one hypothesis, fetch mode, default task
agentlens replay --blocker B07 --mode browser --base-url http://localhost:3100
agentlens replay --task "buy a size-L black kurta under 2000 INR, deliver to pincode 560001"
agentlens replay-all --top 5                                    # one replay per top blocker (by revenue at risk)
```

Default task: `buy a size-M blue shirt under 1500 INR, deliver to pincode 560001`. The store runs with `node server.mjs`
(port 3100, see `apps/store/README.md`); toggle frictions in the store admin UI or `POST /api/admin/friction`.

## Modes

| | Fetch (default) | Browser |
|---|---|---|
| Client | `httpx`, no JavaScript | Playwright Chromium, headless |
| Reads | HTML, JSON-LD, forms, `/api/*` JSON, headers, timings | The rendered DOM, overlays, network, screenshots |
| Best for | B01-B06, B08-B16 (server-visible blockers) | B07 (client-side overlays), screenshots as evidence |
| Evidence | Step log + network log | Same, plus `step_<n>.png` in the evidence directory |

Pick with `--mode` or `default_mode` in `config/replay.yaml`. Hypotheses that need a real DOM (B07) run in browser mode
automatically when Chromium is installed (`auto_browser`); otherwise the replay is `inconclusive` and says why. A browser
launch failure falls back to fetch mode and is noted on the replay.

Planner: `AGENTLENS_LLM_PROVIDER=mock` (or no key) uses the deterministic planner. With `AGENTLENS_LLM_PROVIDER=openai`
and `OPENAI_API_KEY` the model chooses the next action, but only from the actions the journey currently allows, so it
cannot invent URLs or payloads. Any failure, an invalid answer or the token budget ends LLM use for the rest of that replay
(`notes` records why). `--vision` (browser mode, off by default) sends low-detail screenshots to the model for a second
opinion; it needs a key and is never required for a verdict.

## What a replay does

Search for the task, open candidate products, pick colour and size, check delivery, add to cart, check out with test data,
and place the order, recording a step per action: `action, url, status, observation, blocker_id hypothesis, evidence`.
It tolerates and records blockers rather than stopping at the first one: where a safe workaround exists it uses it
(test pincode `560001`, the store's documented test OTP, a normalised phone number) and lists it under `workarounds`.

Verdict rules:

- Targeted replay (`--blocker B05`): any signal for it present gives `confirmed`; else any signal absent (probed and not
  seen) gives `not_reproduced`; else `inconclusive` with the reason.
- Untargeted replay: `confirmed` if any blocker was observed, `not_reproduced` if the task completed cleanly.

Results land in the `replays` table (`steps_json` is the object the API serves: `verdict, user_agent, signed_requests, steps,
network_log`, plus `task, task_completed, order_id, blockers_observed, workarounds, planner, llm_tokens, notes`). Screenshots and
`evidence.json` are in `data/replays/<replay_id>/`, served at `/api/replays/<id>/screenshots/<file>`.

Verdicts per friction (fetch mode, the friction alone on, targeting its blocker; verified by `pytest -m integration`):

| Friction | Blocker | Verdict | Friction | Blocker | Verdict |
|---|---|---|---|---|---|
| F01 | B01 | confirmed | F09 | B09 | confirmed |
| F02 | B02 | confirmed | F10 | B10 | confirmed |
| F03 | B03 | confirmed | F11 | B15 | confirmed (needs a product hint, below) |
| F04 | B04 | confirmed | F12 | B12 | confirmed (local hosts only) |
| F05 | B05 | confirmed | F13 | B13 | confirmed |
| F06 | B06 | confirmed | F14 | B14 | confirmed |
| F07 / F08 | B07 | inconclusive in fetch mode, confirmed in browser mode | F15 | B11 | confirmed |
| | | | F16 | B08 | confirmed |

With all frictions off the task completes and a targeted replay returns `not_reproduced`.

## Safety and ethics

- **Host allow-list.** Only hosts in `allowed_hosts` (plus `PUBLIC_STORE_HOST` from the environment) are contacted. Entries
  are exact `host:port` (no port means the default ports). Checked on the base URL before any traffic, on every request and
  on every redirect hop; credentials-in-URL, non-http(s) schemes and look-alike hosts are refused. A refusal is raised as
  `HostNotAllowed` (CLI exit code 2) and recorded as a `failed` replay.
- **Rate limit.** `step_pause_s` (default 2 s) between requests, one replay at a time per process, at most
  `max_replays_per_run` (50) replays per run.
- **robots.txt.** Read first and respected for the `AgentLens-Replay` token. A disallow stops that request and is evidence
  for B14, not something to route around.
- **Identity.** User-Agent `AgentLens-Replay/1.0 (+repo url; run=<replay_id>)`. The run id makes every replay a distinct,
  traceable client; the store exempts the `AgentLens-Replay` token from its bot wall (F01), so B01 is checked with a separate
  control-UA probe. `--sign` (or `sign_requests: true`) adds Web Bot Auth signatures from the test-operator key, to show the
  Verified-agent path.
- **No PII, no CAPTCHA solving.** Only the fake `test_profile` is submitted. The OTP bypass uses the demo store's documented
  test code and only on local hosts (`bypass_test_walls`). A CAPTCHA is recorded as the blocker (B02) and never solved.
  Prompts to OpenAI contain the task, test data and redacted page summaries, never log rows or customer data.
- **Load probes.** The B12 burst (25 requests) runs only against local hosts, or when `load_probes: true` (get the site
  owner's consent first).

## Cost controls

Hard caps per replay in `config/replay.yaml`: `max_steps` (30), `max_seconds` (180), `max_tokens` (6000 for the OpenAI planner);
the HTTP client stops at `4 x max_steps` requests. Fetch mode with the deterministic planner costs nothing. Browser mode
costs seconds of CPU; vision costs one low-detail image per screenshot step.

## Adding a blocker hypothesis

1. Add a `Hypothesis` to `services/replay/hypotheses.py`: blocker id, store friction, the modes that can see it, stage,
   a one-line summary and the `inconclusive_hint` shown when it was never probed.
2. In `Journey` (`journey.py`; `BrowserJourney` for DOM-only signals) call
   `self.signal("Bxx", present, detail, step)` where the evidence is observed: `present=True` when the friction showed,
   `present=False` when the probe ran and saw nothing. Guard probes with `self.wants("Bxx")`.
3. If it needs a probe the normal journey does not run, add it to `Journey.allowed`; gate anything intrusive on `cfg`.
4. Add a friction-on and friction-off case to `tests/python/test_replay_integration.py`.

Hypotheses that need a specific product (B15, B08) get product hints from the source sessions' `/p/<slug>` paths.

## Troubleshooting

- `refused: ... not in the replay allow-list`: add the host to `config/replay.yaml` (or set `PUBLIC_STORE_HOST`).
- Repeated replays showing no pincode wall: the store keys per-client state on IP + User-Agent; the per-run `run=` suffix
  exists to prevent that, so do not strip it.
- Browser mode unavailable: `python -m playwright install chromium`.
- Run the real-store tests with `pytest -m integration` (starts `node server.mjs` on a free port, kills only its own PID).
