# 5-minute demo walkthrough

A live or recorded walkthrough of AgentLens on the bundled demo store, **Desi Threads**. It uses dashboard **Story mode** and
the replay agent. The numbers below come from the committed demo snapshot (12,000 synthetic sessions, seed 7). If you
regenerate the data (`./tasks.ps1 demo`) the numbers shift by a few percent, so check them before you speak them.

The synthetic story: the shop starts in its **Before** state (login/OTP wall, pincode wall, JS-only content, image-only size
guide, interstitial, strict checkout validation). On 8 Nov three of those fixes go live (F03, F05, F06 off). Week 1 is
1-7 Nov, week 2 is 8-14 Nov.

## Set-up (2 minutes, before you start)

Pick one:

- **Static demo, no servers except a file server** (safest for a screen recording):
  `./tasks.ps1 preview-demo` and open the URL it prints. Replays are pre-recorded in the snapshot.
- **Live stack** (needed for the live replay and the `/admin` toggle):
  1. `./tasks.ps1 demo` once (about 8 minutes). It leaves the data in `data/demo`.
  2. In two terminals: `$env:AGENTLENS_DATA_DIR="data/demo"; .\.venv\Scripts\python.exe -m agentlens.cli serve`
     and `pnpm dev:dashboard`; a third for the store: `pnpm dev:store`.
  3. Open <http://localhost:3101>, set the date filter to the **Before fix** preset, switch on **Story mode**, browser zoom 125%.

## Script

| Time | Page | What to do | What to say |
|---|---|---|---|
| 0:00 | Overview, all 14 days | Point at the four KPI cards: **2,909 agent sessions, 25.6% of 11,381**. Agent conversion **2.5%** vs humans **3.6%**. | "A quarter of this store's traffic is AI agents, and your analytics barely sees them. They convert worse than humans. Why?" |
| 0:40 | Overview, Identity coverage card | Hover the info icon. **Identity coverage 78%, 25% cryptographically verified.** | "AgentLens reads server logs, not JavaScript tags. It puts every visitor in a tier: Verified, Declared, Suspected or Human. Verified means a valid Web Bot Auth signature." |
| 1:10 | Overview, operator donut and trend chart | Show the config-change marker on 8 Nov. | "That dotted line is the day I shipped fixes. Hold on to it." |
| 1:30 | Funnel, preset **Before fix** | Agents vs humans, the S5 "Added to cart" bar. **Agents: 1,489 sessions, 0.0% conversion**, S5 drop-off 100%. | "Agents get to the product page and the delivery check. At Add to cart they all die." |
| 2:10 | Blockers | Read the table top-down. **Total at risk ₹19.3 L a month. B06 Login / OTP wall: 417 sessions, 28% of failures, ₹12.2 L.** Then B09 size guide ₹3.3 L, B05 pincode wall ₹2.6 L. | "Each row is a reason an agent session ended, ranked by revenue at risk, with a low-to-high range, because it is an estimate." |
| 2:50 | Blocker detail: **B06** | Show "How the number is built" (sessions x recoverable rate x stage probability x AOV x scale), the evidence request `POST /api/cart -> 401 AUTH_REQUIRED`, the green **Replay confirmed** pill and the recommended fix. | "The proof: I replayed the journey with a real client and it hit the same wall. The fix: allow a guest cart. Effort: medium." |
| 3:20 | Replays page | Open a replay: step list and, for the browser-mode B07 replay, the screenshot of the interstitial. For a live replay, run `agentlens replay --blocker B05` first and refresh (live stack only). | "The replay agent only visits hosts on an allow-list and respects robots.txt. It is a test client for my own store, not a scraper." |
| 3:50 | Store `/admin` (live only) | Password is `AGENTLENS_ADMIN_PASSWORD` from `.env`. Turn off **OTP before cart** (F06). | "One toggle. In the demo data this fix went live on 8 Nov." |
| 4:10 | Before / After | **Week 1 vs week 2**: agent conversion **0.0% to 5.1%**, **73 orders, about ₹1.6 L** of agent revenue, risk down by about **₹15.2 L**. The panel says the change is significant (two-proportion z-test, p < 0.001). | "Agent conversion goes from zero to five percent, and the fixed blockers are gone. The next fixes are checkout validation and the size guide." |
| 4:40 | Settings & Report (live API) | Click **Download Markdown** (PDF and PNG summary also available). | "And the one-pager is what I would send the head of ecommerce." |
| 4:50 | Overview, Story mode off | Close with the honesty line (see below). | "It is a synthetic store, so these numbers are a demo, not a benchmark. Agents that run inside a shopper's own browser look like humans in logs; the coverage card shows how much I can actually see." |

## Tips

- The Before/After conversion numbers are from synthetic traffic; say so out loud (the dashboard shows a "Demo data
  (synthetic)" badge). The evaluation against ground truth is in [success-criteria.md](success-criteria.md).
- If the live replay is slow, use the pre-recorded replay from the snapshot instead (`./tasks.ps1 preview-demo`).
- Do not open the Sessions page on camera unless you want to show "Verified" sessions: the session ids and IP hashes are
  synthetic, but the table is dense.
- For a real-agent segment (ChatGPT agent, Claude computer use, Gemini) follow [real-agent-runs.md](real-agent-runs.md) and
  [deploy.md](deploy.md) first.
