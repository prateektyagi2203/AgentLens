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

## Recording the demo video (60 to 90 seconds)

Use [demo-script.md](demo-script.md) for the flow and wording. Setup checklist:

- Real data: `./tasks.ps1 demo`, then start the live stack on that data
  (`$env:AGENTLENS_DATA_DIR="data/demo"; ./tasks.ps1 dev`) so `/admin` works for the toggle shot.
- Browser at 125% zoom, 1080p, light or dark theme (toggle in the header), dashboard Story mode on.
- Clear notifications; use a private window so extensions do not show.
- Capture the store (an agent getting stuck at the pincode modal, B05) with a replay screenshot or a real agent run.
- Burn in captions; many people watch muted.
- Say that the data is synthetic. State the honest limitation once (agents inside the shopper's own browser look like humans).
