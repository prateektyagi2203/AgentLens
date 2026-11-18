# macOS / Linux equivalent of tasks.ps1
PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: setup dev test lint synth-scenario pipeline replay snapshot clean-data

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
	$(PY) -m agentlens.cli replay run

snapshot:
	$(PY) -m agentlens.cli export-snapshot

clean-data:
	find data -mindepth 1 ! -name .gitkeep -delete
