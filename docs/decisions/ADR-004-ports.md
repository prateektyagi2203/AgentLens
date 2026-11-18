# ADR-004: Default ports 3100 / 3101 / 8100
Date: 2026-11-18
Status: Accepted
## Context
The PRD uses 3000 (store), 3001 (dashboard) and 8000 (API). These are the most common dev-server ports and collided with other local projects on the build machine.
## Decision
Defaults are store 3100, dashboard 3101, API 8100. Every URL comes from `.env` (`STORE_URL`, `API_URL`, `DASHBOARD_URL`), so changing them is a config edit plus the `-p` flag in each app's `package.json`.
## Consequences
No clashes with typical dev servers; docs and tests use the new ports.
