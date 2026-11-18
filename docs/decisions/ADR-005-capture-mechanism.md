# ADR-005: Capture mechanism for the demo store (C2)
Date: 2026-11-18
Status: Accepted
## Context
C2 must log every request the store serves (pages, APIs, `_next` assets, blocked and aborted requests) with the final status, `bytes_out` and `duration_ms`, without ever recording bodies or PII. Next.js middleware cannot see the final status or response size and does not run for assets. Route handlers only see API calls. The store also needs server-level friction (F01 bot wall, F12 rate limit, F13 latency) that must apply before Next renders anything.
## Decision
- `apps/store/server.mjs` is a custom Node server that wraps `next({ dev })`. Every request goes through `capture()` (`lib/capture.ts`) before `handle(req, res)`.
- `capture()` assigns a request id, identifies the client, counts bytes by wrapping `res.write/end`, applies the server-level gate (`decideGate`), and writes exactly one JSON line on `res` `close` (status 499 if the client aborted). Run with `pnpm dev:store` (dev) or `pnpm --filter @agentlens/store start` after `build` (port 3100, `HOST` defaults to 127.0.0.1; containers need `HOST=0.0.0.0`).
- `server.mjs` loads `lib/capture.ts` through `tsx` (`tsImport`) so the capture code stays TypeScript and is unit-tested directly. Next bundles its own copy of `lib/*`, so shared state (cart/pincode/OTP state, per-request meta, friction cache) lives on `globalThis` (`lib/state.ts`).
- Route handlers pass `meta` (for example `error_code`) to the logger through a registry keyed by request id, not through an `x-agentlens-meta` response header. This avoids a header that could leak if stripping failed. Extra events (`order`, `config_change`) are written as separate lines with their own request id.
- Output: `<data>/logs/access-YYYY-MM-DD.jsonl` with the PRD 9.2 schema, where `<data>` is `AGENTLENS_DATA_DIR` (relative values resolve against the repo root, not the cwd) or `<repo>/data`. With `AGENTLENS_NGINX_LOG=1` the same record is also appended to `<data>/logs/access.nginx.log` in nginx combined format plus three quoted fields (Signature, Signature-Input, Signature-Agent). The address column holds the /24 (v4) or /48 (v6) base address, never the raw IP.
- Privacy: only the `dt_sid` cookie is read (logged as `sha256(salt + sid)`); the IP is stored as `sha256(AGENTLENS_IP_SALT + ip)` plus the /24 or /48 prefix; query strings are scrubbed by `lib/scrub.ts` (phone, email, OTP-like and address values become `REDACTED`); bodies are never read by the logger; the referer is reduced to domain and path. Which friction toggles are on is never logged. `meta.synth_session_id` is taken from `X-Synth-Session` only when `AGENTLENS_SYNTH_MODE=1`.
- Absent optional headers are logged as `null`.
- `next.config.mjs` sets `compress: false` so `bytes_out` is the exact body size.
- Environment: `server.mjs` loads the repo-root `.env` with `dotenv` (values already in the process environment win). `AGENTLENS_IP_SALT` and `AGENTLENS_ADMIN_PASSWORD` default to `change-me` for local development only; production mode prints a warning.
## Alternatives considered
- Next.js middleware: no final status or byte count, skips assets.
- Reverse proxy (nginx) logs: needs extra infrastructure and cannot see friction meta. The nginx export above keeps the ingester testable on standard logs.
- Wrapping each route handler: misses pages and assets.
## Consequences
- One capture point for all traffic, with exact status, bytes and duration.
- The store must be started through `server.mjs`; `next start` alone would not log.
- Server state is in memory, so restarting the store clears carts and OTP/pincode flags (the friction file persists).
