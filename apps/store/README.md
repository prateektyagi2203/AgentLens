# Desi Threads (AgentLens demo store)

Synthetic Indian D2C fashion store ("TEST STORE: no real orders") with 16 switchable friction toggles and a request-capture layer that writes the access log the AgentLens pipeline reads.

## Run

From the repo root:

```powershell
pnpm install
pnpm dev:store          # http://127.0.0.1:3100 (custom server, dev mode)
```

Production-style: `pnpm --filter @agentlens/store build` then `pnpm --filter @agentlens/store start`.
Always start through `server.mjs` (the `dev` / `start` scripts do); `next start` alone does not log.

Tests: `pnpm --filter @agentlens/store test` (Vitest), `typecheck`, `lint`, `test:e2e` (Playwright; builds the store and runs it on port 3100 with an isolated data dir under `apps/store/.e2e-tmp`; run `pnpm --filter @agentlens/store exec playwright install chromium` once).

## Environment (repo-root `.env`)

| Variable | Purpose |
| --- | --- |
| `AGENTLENS_IP_SALT` | Salt for `ip_hash` and `cookie_sid_hash` (default `change-me`) |
| `AGENTLENS_ADMIN_PASSWORD` | `/admin` password (default `change-me`) |
| `AGENTLENS_DATA_DIR` | Output dir (default `<repo>/data`; relative paths resolve against the repo root) |
| `AGENTLENS_NGINX_LOG=1` | Also write `<data>/logs/access.nginx.log` |
| `AGENTLENS_SYNTH_MODE=1` | Copy `X-Synth-Session` into `meta.synth_session_id` |
| `DEMO_MODE=1` | Disables `/admin` and `/api/admin/*` |
| `PORT` / `HOST` | Default `3100` / `127.0.0.1` (use `HOST=0.0.0.0` in containers) |
| `AGENTLENS_FRICTION_FILE` | Override the friction file (used by E2E) |

## Files

- Log: `<data>/logs/access-YYYY-MM-DD.jsonl` (PRD 9.2 schema, see `docs/log-contract.md`)
- Orders: `<data>/orders.jsonl`
- Friction state: `apps/store/config/friction.json` (edits apply without restart)
- Catalogue: `apps/store/data/catalog.json` (regenerate with `pnpm --filter @agentlens/store seed`; fixed seed, deterministic)
- Test operator keys (synthetic): `apps/store/config/test-operator-jwks.json` (public, served at `/.well-known/http-message-signatures-directory`) and `apps/store/config/test-operator.private.pem` (PKCS8; regenerate with `gen-test-key`)

## Admin

`/admin` shows the 16 toggles and an annotation note. Scripts can call `GET/POST /api/admin/friction` with header `x-admin-password` and body `{ "toggles": { "F05": false }, "note": "..." }`; each change writes a `config_change` log line.

Fixed dev OTP is `123456`. The OTP is "sent" by doing nothing: neither the code nor the number is logged.

Design notes: `docs/decisions/ADR-005-capture-mechanism.md`.
