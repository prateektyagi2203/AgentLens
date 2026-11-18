# Contributing

Thanks for looking. Issues and PRs are welcome; this is a small project, so keep changes focused.

## Setup

Follow the Quick start in the [README](README.md) (Python 3.11+, Node 22, pnpm 12, `uv`). Short version:

```powershell
./tasks.ps1 setup        # Windows;  `make setup` on macOS / Linux
```

## Checks that must pass

```powershell
./tasks.ps1 lint         # ruff check, mypy services, pnpm -r lint, pnpm -r typecheck
./tasks.ps1 test         # pytest (default markers), pnpm -r test (vitest)
```

Equivalent commands: `.\.venv\Scripts\python.exe -m ruff check .`, `-m mypy services`, `-m pytest -q`, `pnpm -r lint`,
`pnpm -r typecheck`, `pnpm -r test`. CI runs the same plus the dashboard build and the static demo build.

Slower, opt-in suites:

| Suite | Command |
|---|---|
| Replay integration (starts its own store; needs a built store: `pnpm --filter @agentlens/store build`) | `python -m pytest -m integration` |
| API latency on a large DB | `python -m pytest -m perf tests/python/test_api_perf.py -s` (see docs/performance.md) |
| Store e2e (Playwright) | `pnpm --filter @agentlens/store test:e2e` |
| Dashboard e2e on mocks / on the real API / on the static demo | `pnpm --filter @agentlens/dashboard test:e2e`, `playwright.api.config.ts`, `test:e2e:demo` |

## Conventions

- Python: ruff (line length in `pyproject.toml`) and strict-ish mypy on `services`. Config lives in `config/*.yaml`;
  thresholds and rules are data, not code.
- TypeScript: strict, `pnpm -r lint` has zero warnings allowed. The dashboard follows [docs/theme.md](docs/theme.md);
  all data access goes through `apps/dashboard/lib/data-source.ts` (ADR-008).
- Privacy first: never log or store raw IPs, phone numbers, emails, OTPs or request bodies (PS1 in the PRD).
- Decisions that change behaviour or architecture get an ADR in `docs/decisions/` (copy `ADR-000-template.md`).
- Changes to the API shape update [docs/api-contract.md](docs/api-contract.md) and the dashboard types together.
- Do not commit `.env`, `data/`, keys or tokens. CI greps for API keys.
- Keep the honest limitation honest: do not claim identification of agents that look like humans at the server.
