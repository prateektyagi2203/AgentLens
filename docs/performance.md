# Performance (SC6, SC7)

Measured on one machine; treat the numbers as indicative.

| | |
|---|---|
| Machine | Windows 11 laptop, Intel Core i5-1345U (10 cores / 12 threads), 15.4 GB RAM, NVMe SSD |
| Software | Python 3.11.2, DuckDB (from `uv.lock`), Node 22.17 |
| Conditions | Other applications running (editor, browsers); no other AgentLens process; no LLM key (mock provider); site checks skipped |

## SC6: 1M log lines end to end (target: at most 3 minutes)

Data: `agentlens synth offline --sessions 53000 --days 14 --seed 7` gives 53,000 sessions, **1,009,669 log lines**
(14 JSONL files, about 267 MB in DuckDB). Generating it took 78-83 s (not part of the target). Then
`agentlens run-all` (see `tasks.ps1 bench` / `make bench`):

| Step | Run 1 | Run 2 (after the checkpoint change) |
|---|---|---|
| ingest | 131.9 s | 109.8 s |
| identify | 30.9 s | 37.0 s |
| sessionize | 27.8 s | 25.1 s |
| funnel | 3.2 s | 5.0 s |
| diagnose | 8.1 s | 8.7 s |
| impact | 0.2 s | 0.3 s |
| recommend | 0.7 s | 1.1 s |
| **Total** | **206 s** | **198 s** |

**Result: not met on this machine.** 198-206 s against a 180 s target (about 10-15% over). Run-to-run variation is
about +-10% because the machine was shared. On a quieter or faster machine the target is plausible but unproven.

What was investigated:

- Ingest is the largest step. The parse (`orjson`, 32 MB blocks) runs at roughly 45-50k lines/s; the rest is the DuckDB
  insert and the commit. Ingest throughput falls from about 19k lines/s on a 113k-line file to about 9k lines/s at 1M lines,
  because the `request_id` primary-key index grows with the table.
- Low-hanging fruit applied: DuckDB checkpointed on nearly every block commit (default `checkpoint_threshold` 16 MB of WAL).
  Raising it to 1 GB for ingest cut the commit time from 17 s to 5 s on a 430k-line sample and ingest by about 15-25 s.
  The final checkpoint costs about 1 s on close. Behaviour is unchanged.
- Not done: parsing blocks in parallel worker processes and bulk-loading with deferred index creation would likely bring
  ingest under 60 s, at the price of more code. identify and sessionize are single SQL passes and were left alone.

Reproduce: `./tasks.ps1 bench` (or `make bench`). It deletes `data/bench`, generates the data, times `run-all` and runs the
API check below.

## SC7: API latency on the 1M-line database (dashboard page load budget: 2 s)

`pytest -m perf tests/python/test_api_perf.py -s` with `AGENTLENS_PERF_DATA_DIR=data/bench`: every endpoint a dashboard page
calls, 10 rounds x 3 batches, in-process FastAPI `TestClient`, cold cache. Budget: p95 under 300 ms.

| Endpoint | Cold p95 (ms) | Warm p95 (ms) |
|---|---|---|
| overview | 235 | 105 |
| overview (segment=verified) | 217 | 88 |
| funnel / funnel (agents) | 149 / 150 | 43 / 26 |
| blockers | 129 | 23 |
| blocker detail | 282 | 137 |
| agents / agent detail | 161 / 191 | 153 / 176 |
| sessions (page 1 / page 50 / filtered / search) | 65 / 103 / 61 / 97 | 66 / 184 / 78 / 105 |
| session detail | 81 | 76 |
| recommendations | 106 | 31 |
| site-checks | 23 | 36 |
| compare | 262 | 50 |

All 16 calls pass the 300 ms budget, so a page that makes 3-5 of these calls in parallel stays well under 2 s of API time.
The measured page-load time in a real browser also includes Next.js rendering; see [success-criteria.md](success-criteria.md)
for how SC7 was checked.

### 100k sessions (the SC7 dataset size)

The 1M-line database has about 53k sessions, half of the "100k sessions" in SC7. The `perf` test defaults to a 100k-session
dataset (`data/perf100k`, see the test docstring). Re-run on it during M6, on a machine that was also running Teams, VS Code
and Chrome (CPU about 85% busy before the test started), two runs gave:

- 14 of 16 endpoints passed the 300 ms cold p95 budget in both runs (most between 40 and 260 ms).
- `compare` cold p95 was 319-347 ms and `overview` 276-304 ms, so the budget was missed by up to about 15% on the noisiest
  batches (warm p95 for them is 43 ms and 118-133 ms). `compare` computes two full windows with no cached aggregates, which is
  the worst case; the test clears the cache before every request.

So the strict internal cold budget is narrowly missed for `compare` at 100k sessions on a loaded laptop. The user-visible
metric, SC7 page load, is measured in a real browser below and is well within 2 s.

### Page load in a real browser (SC7)

Production dashboard build (`next start`, port 3101) against the real API (port 8100) serving the 12k-session demo
dataset. Playwright Chromium, navigation until the main component (`kpi-risk`, `funnel-bars` or `blockers-table`) is
visible, 5 runs each, same loaded laptop:

| Page | Load times (ms) |
|---|---|
| Overview | 474, 371, 490, 267, 287 |
| Funnel | 268, 191, 192, 231, 213 |
| Blockers | 247, 221, 255, 228, 615 |

This is on 12k sessions, not 100k; the API-level numbers above are the 100k evidence. The static demo build needs no API and
is covered by the 12 static-demo end-to-end checks.
