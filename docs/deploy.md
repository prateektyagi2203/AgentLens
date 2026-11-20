# Deploy and demo video

Three ways to run AgentLens, from most to least public. Free-tier limits and terms change; check Vercel's current Hobby terms
before you deploy.

## 1. Public static demo on Vercel (read-only, synthetic)

The dashboard built with `DEMO_MODE=1` is a static Next.js export (`output: "export"`) that reads
`apps/dashboard/public/demo/*.json` (layout: [api-contract.md](api-contract.md) section 4). No backend, database or
Python is needed on Vercel. The snapshot is **synthetic data only** and the dashboard shows a "Demo data (synthetic)" badge.

Refresh the snapshot (optional; the committed one is already usable):

```powershell
./tasks.ps1 demo          # synth -> run-all -> replays -> eval -> export-snapshot -> static build in apps/dashboard/out
./tasks.ps1 preview-demo  # serve apps/dashboard/out on http://localhost:3101 to check it
```

Commit the changed `apps/dashboard/public/demo/**`, push, then in Vercel:

1. **Add New Project**, import the GitHub repo.
2. **Root Directory:** `apps/dashboard` (enable "Include source files outside of the Root Directory" so pnpm can see the workspace).
3. **Framework preset:** Next.js. **Install command:** `pnpm install --frozen-lockfile`. **Build command:** `pnpm build`.
4. **Environment variable:** `DEMO_MODE=1` (Production and Preview). Without it the build targets the live API and every page
   shows an error state.
5. **Output directory:** leave the Next.js default (Vercel serves the `out` export for you). If your project settings force
   one, use `out`.
6. Deploy, open the URL and click through the eight pages. Check there is no error banner and the badge says
   "Demo data (synthetic)". The Compare page and the Story mode work from the snapshot; edits (annotations, settings)
   are disabled in demo mode.

The Vercel build has not been run by the author (no deployment yet). The same build runs locally and in CI:
`pnpm --filter @agentlens/dashboard build:demo`, followed by `test:e2e:demo`.

Optional: also host the demo store. The store needs a writable data dir and a Node server, which Vercel's static hosting
does not give you; keep the store local and tunnelled (below).

## 2. Local full product

`./tasks.ps1 dev` starts store 3100, API 8100 and dashboard 3101. Generate data with `./tasks.ps1 synth-scenario` and
`./tasks.ps1 pipeline`. This is what you record for the video.

## 3. Store through a tunnel (real-agent runs, live demo)

Follow [real-agent-runs.md](real-agent-runs.md): `cloudflared tunnel --url http://localhost:3100` (or `ngrok http 3100`),
put the host in `PUBLIC_STORE_HOST`, set a real `AGENTLENS_ADMIN_PASSWORD`, and stop the tunnel afterwards.

## Docker (untested)

`docker-compose.yml` and `docker/*.Dockerfile` mirror the native ports and commands (3100, 8100, 3101). Docker is not
installed on the author's machine, so they have **not been run**. Expect to fix small things.

```bash
cp .env.example .env
docker compose build
docker compose run --rm api agentlens synth scenario before-after
docker compose run --rm api agentlens run-all
docker compose up
```

## 4. Full public stack on your own domain (VPS + Caddy)

`docker-compose.prod.yml` runs the store, the API and the dashboard behind Caddy, which gets HTTPS certificates
automatically. The public API is **read-only** (`DEMO_MODE=1`: every non-GET request returns 403) and the store has
`/admin` disabled, so visitors cannot trigger pipeline or LLM runs. The server does not need an OpenAI key: you generate
the data on your machine and upload it.

| URL | Service |
|---|---|
| `https://<domain>` | dashboard |
| `https://api.<domain>` | API |
| `https://store.<domain>` | Desi Threads store (a visitor's session is logged to its own volume, not to the demo data) |

**1. Generate the data locally** (optionally with the real LLM classifier: put `AGENTLENS_LLM_PROVIDER=openai` and
`OPENAI_API_KEY=...` in your local `.env` first; the key never leaves your machine):

```powershell
./tasks.ps1 demo          # writes data/demo/agentlens.duckdb (about 8 minutes)
```

**2. Server.** A VPS with 2 vCPU / 4 GB RAM, Docker and the Compose plugin; ports 80 and 443 open.
Add DNS A records for `<domain>`, `api.<domain>` and `store.<domain>` (or one `*.<domain>` record) pointing at the server.

**3. Deploy.**

```bash
git clone https://github.com/prateektyagi2203/AgentLens.git && cd AgentLens
cp .env.production.example .env      # set AGENTLENS_DOMAIN, AGENTLENS_IP_SALT, AGENTLENS_ADMIN_PASSWORD (openssl rand -hex 24)
mkdir -p data
# from your machine:  scp -r data/demo user@server:~/AgentLens/data/demo
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps        # all services should become "healthy"
```

The dashboard bakes the API URL in at build time. If you change `AGENTLENS_DOMAIN`, rebuild with `--build`.

**4. Check.** Open `https://<domain>` (eight pages, no error banner), `https://api.<domain>/health` (`"demo_mode": true`),
`https://store.<domain>/robots.txt`, and confirm `curl -X POST https://api.<domain>/api/pipeline/run` returns 403.

**To refresh the data:** regenerate locally, `scp` the new `data/demo`, then
`docker compose -f docker-compose.prod.yml restart api`.

**Cost control if you do enable the LLM locally:** set a monthly spend limit on the OpenAI project;
`AGENTLENS_LLM_MAX_SESSIONS` caps sessions classified per run.

## Recording the demo video (60 to 90 seconds)

Use [demo-script.md](demo-script.md) for the flow and wording. Setup checklist:

- Real data: `./tasks.ps1 demo`, then start the live stack on that data
  (`$env:AGENTLENS_DATA_DIR="data/demo"; ./tasks.ps1 dev`) so `/admin` works for the toggle shot.
- Browser at 125% zoom, 1080p, light or dark theme (toggle in the header), dashboard Story mode on.
- Clear notifications; use a private window so extensions do not show.
- Capture the store (an agent getting stuck at the pincode modal, B05) with a replay screenshot or a real agent run.
- Burn in captions; many people watch muted.
- Say that the data is synthetic. State the honest limitation once (agents inside the shopper's own browser look like humans).
