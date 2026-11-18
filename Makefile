# macOS / Linux equivalent of tasks.ps1
PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: setup dev test lint synth-scenario pipeline replay report snapshot demo preview-demo bench clean-data

setup:
	@test -f .env || cp .env.example .env
	python3 -m pip install --quiet uv && python3 -m uv sync
	pnpm install
	$(PY) -m playwright install chromium

dev:
	@trap 'kill 0' INT; pnpm dev:store & $(PY) -m uvicorn agentlens.main:app --port 8100 --reload & pnpm dev:dashboard & wait

test:
	$(PY) -m pytest -q
	pnpm -r test

lint:
	$(PY) -m ruff check .
	$(PY) -m mypy services
	pnpm -r lint
	pnpm -r typecheck

synth-scenario:
	$(PY) -m agentlens.cli synth scenario before-after --before-days 7 --after-days 7

pipeline:
	$(PY) -m agentlens.cli run-all

replay:
	$(PY) -m agentlens.cli replay-all

report:
	$(PY) -m agentlens.cli report --format all

snapshot:
	$(PY) -m agentlens.cli export-snapshot --force

# Synth data -> pipeline -> replays -> eval -> static snapshot -> static dashboard build. Same steps as `tasks.ps1 demo`.
# Site checks are recorded as of the scenario dates (Before state, then After state at the switch). UNTESTED on Linux/macOS.
demo:
	rm -rf data/demo
	AGENTLENS_DATA_DIR=data/demo $(PY) -m agentlens.cli synth scenario before-after --sessions 12000 --start-date 2026-11-01 --before-days 7 --after-days 7
	@mkdir -p data
	@( cd apps/store && AGENTLENS_DATA_DIR=data/demo-store node server.mjs --dev & echo $$! > data/.store.pid ); \
	  for i in $$(seq 1 60); do curl -fs http://127.0.0.1:3100/robots.txt >/dev/null && break; sleep 1; done; \
	  export AGENTLENS_DATA_DIR=data/demo AGENTLENS_SITE_URL=http://localhost:3100; \
	  ( $(PY) scripts/demo_friction.py before \
	  && $(PY) -m agentlens.cli ingest \
	  && $(PY) -m agentlens.cli site-checks --as-of 2026-11-01T00:00:00Z \
	  && $(PY) scripts/demo_friction.py after && sleep 1 \
	  && $(PY) -m agentlens.cli site-checks --as-of 2026-11-08T00:00:00Z \
	  && $(PY) scripts/demo_friction.py before && sleep 1 \
	  && $(PY) -m agentlens.cli run-all \
	  && $(PY) -m agentlens.cli replay-all --pause 0.3 \
	  && $(PY) -m agentlens.cli eval ); \
	  rc=$$?; pkill -P $$(cat data/.store.pid) 2>/dev/null; kill $$(cat data/.store.pid) 2>/dev/null; rm -f data/.store.pid; \
	  git checkout apps/store/config/friction.json; exit $$rc
	AGENTLENS_DATA_DIR=data/demo $(PY) -m agentlens.cli export-snapshot --force
	pnpm --filter @agentlens/dashboard build:demo

preview-demo:
	pnpm --filter @agentlens/dashboard serve:demo

bench:
	rm -rf data/bench
	AGENTLENS_DATA_DIR=data/bench $(PY) -m agentlens.cli synth offline --sessions 53000 --days 14 --seed 7
	time AGENTLENS_DATA_DIR=data/bench $(PY) -m agentlens.cli run-all
	AGENTLENS_PERF_DATA_DIR=data/bench $(PY) -m pytest -m perf tests/python/test_api_perf.py -s -q

clean-data:
	find data -mindepth 1 ! -name .gitkeep -delete
