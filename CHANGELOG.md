# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow the milestones in the PRD.

## [1.0.0] - 2026-11-18

First complete release (milestones M0 to M6).

### Added
- **Demo store "Desi Threads"** (Next.js, port 3100) with 16 friction toggles, a fake test-mode checkout and a capture layer
  that writes JSONL (and optional nginx-combined) access logs with hashed IPs and no request bodies (M1).
- **Pipeline** (`agentlens` CLI): ingest, identify, sessionize, funnel, diagnose (rules B01-B16, optional LLM for B99),
  impact (₹ at risk), recommend, `run-all` (M2, M3).
- **Agent identification** in three tiers: Verified (Web Bot Auth / RFC 9421 signatures), Declared (UA registry), Suspected
  (behaviour), plus Human; identity coverage metric.
- **Synthetic traffic generator** with ground truth (offline, live and a before/after scenario) and the evaluation harness
  (`eval`, `eval-identification`, `eval-diagnosis`) for SC1-SC4.
- **FastAPI** (port 8100) and **dashboard** (port 3101, 8 pages, light/dark theme, Story mode) (M4).
- **Replay agent** (fetch and Playwright browser modes, host allow-list), **Before/After** comparison, and the
  **Agent Readiness Report** (Markdown, HTML, PNG one-pager) (M5).
- **`agentlens export-snapshot`**: static public-demo snapshot (`/demo/*.json`) from the real DuckDB, with a privacy scan that
  fails on ground truth, raw IPs or e-mails. Static dashboard build (`DEMO_MODE=1`), static server and Playwright e2e (M6).
- Task runners `tasks.ps1` / `Makefile`: `demo`, `preview-demo`, `bench`, `snapshot` and others.
- Docs: README, ARCHITECTURE, CONTRIBUTING, SECURITY, ADR-001..009, demo script, real-agent runs, deploy,
  success criteria, performance.

### Changed
- Ingest sets DuckDB `checkpoint_threshold` to 1 GB so per-block commits do not checkpoint every ~16 MB of WAL
  (about 25% faster at 1M lines).

### Fixed
- `tasks.ps1` task runner dropped its arguments for CLI tasks (`pipeline`, `replay`, ...).
- Makefile `replay` target called a nonexistent subcommand.
- `docker-compose.yml` / dashboard Dockerfile passed the API URL at runtime, but Next.js inlines `NEXT_PUBLIC_*` at build time
  and the URL lacked `/api`.
- Dashboard hydration mismatch (store name and date presets in the shell) when the API answered before a Suspense boundary
  finished hydrating; `useMeta` now returns the server-render value until hydration is complete.
- ADR-008 carried the title "ADR-005".
