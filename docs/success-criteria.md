# Success criteria (SC1 to SC8)

Targets are from [PRD section 4.4](PRD.md). Measured on the author's laptop (Windows, Intel i5-1345U with 10 cores and 12
threads, 15.4 GB RAM, SSD) on **synthetic data with ground truth**, 18 Nov 2026. Real traffic will score lower, especially
the Suspected tier (see [README limitations](../README.md#known-limitations)).

| ID | Target | Measured | Status |
|---|---|---|---|
| SC1 | Verified precision 100%, 0 false Verified on tampered signatures | Precision 100%, recall 100%, 0 false Verified, 0 forged signatures marked Verified (12,000 sessions) | Met |
| SC2 | Declared accuracy at least 98% | 100.0% over 2,150 sessions | Met |
| SC3 | Suspected recall at least 75% at no more than 5% human false positives | Recall 86.5% over 749 sessions; human false-positive rate 0.0% over 8,371 sessions | Met |
| SC4 | Diagnosis precision / recall at least 85% / 80% | Golden set (2,000 sessions): **95.0% / 100.0%**. Demo data (3,528 agent sessions, with site probes): 91.8% / 100.0% | Met |
| SC5 | Replay confirms at least 80% of the top blockers | 6 of 6 replays confirmed with evidence (demo data) | Met |
| SC6 | 1M log lines end to end in at most 3 minutes | 1,009,669 lines in **198 s** (3 min 18 s); 206 s before the ingest fix | **Not met** (about 10% over) |
| SC7 | Dashboard page load (100k sessions) at most 2 s | Browser page load 0.19 to 0.62 s on the 12k-session demo; API cold p95 at most 282 ms on the 1M-line database (53k sessions); on 100k sessions two of 16 endpoints are 5 to 15% over the 300 ms internal cold budget on a loaded laptop | Met for page load; see caveat |
| SC8 | Fresh clone to running demo in at most 15 minutes | About 3 minutes of commands with warm package caches (setup 80 s, synth 18 s, pipeline 19 s, start about 45 s); cold caches add the downloads | Met (caches warm) |

Caveats:

- The synthetic generator and the identification rules were written by the same author. Ground-truth scores show that the
  pipeline recovers what the generator planted, not how it performs on unseen real traffic.
- SC4 on the demo data is lower than on the golden set because two blockers (B03 JS-only content, B09 image-only size
  guide) are only visible through live site probes, and the demo's probes are taken "as of" the scenario dates.
  Without any probes, demo precision is 98.6% and recall 47.7%.
- SC6 details and the investigation are in [performance.md](performance.md). Parallel parsing and a bulk load would likely
  bring it under 3 minutes.
- SC7 is measured against 12k sessions in a real browser and 100k sessions at the API level; the 100k browser number was not
  measured.
- SC8 does not include running the full test suite (about 6 minutes with the default pytest markers).

## Reproduce

Run from the repository root after `./tasks.ps1 setup`. Use `.\.venv\Scripts\python.exe` (Windows) or `.venv/bin/python`
(Linux) for `python`.

| ID | Command |
|---|---|
| SC1 to SC3 | `./tasks.ps1 demo` (or `synth scenario` + `run-all`), then `python -m agentlens.cli eval-identification` (stop `serve` first). The tampered-signature cases are also in `pytest tests/python/test_signatures.py` and `tests/python/test_integration.py` (`test_sc1_*`, `test_sc2_*`, `test_sc3_*`) |
| SC4 (golden) | `python -m agentlens.cli eval-diagnosis --golden`, or `pytest tests/python/test_eval_diagnosis.py` |
| SC4, SC5 (demo) | `./tasks.ps1 demo`. It ends with `agentlens eval`, which writes `data/demo/eval/latest.json` (shown on the Settings page and in the snapshot) |
| SC6 | `./tasks.ps1 bench` (or `make bench`): 1M-line synth, `run-all` timing, API p95 check |
| SC7 (API) | `AGENTLENS_PERF_DATA_DIR=data/bench pytest -m perf tests/python/test_api_perf.py -s` (the default dataset is `data/perf100k`, built as the test docstring describes) |
| SC7 (browser) | Build the dashboard (`pnpm --filter @agentlens/dashboard build`), serve it with the API on `data/demo`, and time the navigation until `kpi-risk`, `funnel-bars` or `blockers-table` is visible (method in [performance.md](performance.md)) |
| SC8 | Fresh clone, then the README quick start: `./tasks.ps1 setup; ./tasks.ps1 synth-scenario; ./tasks.ps1 pipeline; ./tasks.ps1 dev` |

Everything else (all default tests, linters and builds): `./tasks.ps1 lint; ./tasks.ps1 test`. CI runs the same commands
plus the static-demo build and the Playwright suites ([.github/workflows/ci.yml](../.github/workflows/ci.yml)).
