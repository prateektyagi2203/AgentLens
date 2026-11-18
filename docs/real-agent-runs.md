# Real-agent runs

Goal: show genuine agents (ChatGPT agent, Claude, Perplexity Comet, Gemini, ...) visiting the demo store, for credibility in
the demo video and to check real Web Bot Auth signatures. These runs are **manual**: AgentLens cannot start them for you,
and the numbers in the public snapshot come from synthetic traffic only.

## Rules

- Only point agents at **your own demo store**. Never at third-party sites. Never enter real payment details or real
  personal data; use the store's test checkout (OTP `123456`, pincode `560001`).
- The store shows "TEST STORE: no real orders" on every page and logs no raw IPs, phone numbers or request bodies.
- The tunnel makes your local store reachable from the internet while it runs. Stop it when you are done, and set your own
  `AGENTLENS_ADMIN_PASSWORD` first (the `/admin` page is reachable through the tunnel unless `DEMO_MODE=1`).

## Steps

1. **Configure.** Copy `.env.example` to `.env`; set `AGENTLENS_ADMIN_PASSWORD`, `AGENTLENS_IP_SALT`. Use a clean data dir for
   the run, for example `AGENTLENS_DATA_DIR=data/real`, so synthetic and real traffic do not mix.
2. **Start the store.** `pnpm dev:store` (port 3100). Check `http://localhost:3100/robots.txt`.
3. **Open a tunnel** to port 3100, one of:
   - `cloudflared tunnel --url http://localhost:3100` (prints `https://<random>.trycloudflare.com`)
   - `ngrok http 3100`
4. **Record the host** in `.env`: `PUBLIC_STORE_HOST=<random>.trycloudflare.com` (host only, no scheme). This adds the tunnel to
   the replay agent's allow-list; restart nothing else. The URL changes every time you restart a quick tunnel.
5. **Set the friction toggles** you want at `http://localhost:3100/admin` (or `POST /api/admin/friction`) and write the
   state into the CSV row. Each change logs a `config_change` annotation, so Before/After works later.
6. **Run a task** from the table below in the agent's own UI, with your tunnel URL in place of `<URL>`. Note start and
   end time (UTC), screen-record if you want footage, and judge the outcome: `completed`, `partial` or `failed`.
7. **Log the run** by copying `docs/real-agent-runs.template.csv` to `docs/real-agent-runs.csv` and adding one row per
   run. Columns: `date, agent, task_id, task_prompt, store_url, toggles_state, outcome, blocker_observed, notes,
   recording_file, window_start, window_end`.
8. **Ingest and look.** Stop the store (or leave it running), then, with the same `AGENTLENS_DATA_DIR`:

   ```powershell
   .\.venv\Scripts\python.exe -m agentlens.cli run-all
   .\.venv\Scripts\python.exe -m agentlens.cli serve      # API on 8100 (stop it before running other CLI commands)
   pnpm dev:dashboard                                      # http://localhost:3101
   ```

   In the dashboard, open Sessions and filter to your `window_start` to `window_end`. Real agents appear as Declared
   (their documented User-Agent token) or Verified (valid Web Bot Auth signature, when the vendor signs), or as Suspected
   or Human if they do neither. Agents running inside your own browser look like humans (see the honest limitation in the README).
9. **Optional.** `agentlens replay-all` replays the top blockers against the tunnel host (allowed through `PUBLIC_STORE_HOST`).

## Standard tasks

| ID | Task prompt given to the agent |
|---|---|
| T1 | "On <URL>, find white sneakers under ₹4,000 in UK size 9." |
| T2 | "Which size should I buy if I'm usually UK 9 in Nike? Use the site's size guide." |
| T3 | "Can this be delivered to pincode 201301 by Friday? Is COD available?" |
| T4 | "Add the cheapest kurta in size M to the cart." |
| T5 | "Go to checkout and fill in a test address. Stop before payment." (Or complete in test mode.) |
| T6 | "What is the return window, and are returns free?" |

The store catalogue is Indian D2C fashion, so adjust product words (for example "sneakers") to what exists in
`apps/store/data/catalog.json` if an agent finds nothing, and note the change in the CSV.

## What to expect

- Real agents often fetch with plain HTTP and no JavaScript, so JS-only content (B03), missing structured data (B04) and
  the pincode wall (B05) matter most. Some vendors send signed requests; others send only a UA token.
- Providers change their agents and policies often. Record the date and agent version you used; results are a snapshot,
  not a benchmark.
