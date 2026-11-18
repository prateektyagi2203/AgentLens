# AgentLens task runner (Windows PowerShell). Usage: ./tasks.ps1 <task>
# Tasks: setup | dev | test | lint | synth-scenario | pipeline | replay | report | snapshot | demo | preview-demo | bench | clean-data
param([Parameter(Position = 0)][string]$Task = "help")

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

function Get-Py {
  $venv = Join-Path $Root ".venv\Scripts\python.exe"
  if (Test-Path $venv) { return $venv }
  return "python"
}
function Invoke-Native([scriptblock]$Block) {
  & $Block
  if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
}
function Invoke-AgentLens {
  $py = Get-Py
  $cliArgs = $args
  Invoke-Native { & $py -m agentlens.cli @cliArgs }
}

function Wait-Http([string]$Url, [int]$TimeoutSec = 90) {
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try { if ((Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3).StatusCode -eq 200) { return } } catch { Start-Sleep -Milliseconds 700 }
  }
  throw "Timed out waiting for $Url"
}

# Synth data -> pipeline -> replays -> eval -> static snapshot -> static dashboard build (DEMO_MODE=1).
# Site checks are recorded "as of" the scenario dates: the store is probed in its Before state at the start and in its
# After state (F03/F05/F06 off) at the switch, so diagnosis judges each window against the store as it was then.
function Invoke-Demo {
  $env:AGENTLENS_DATA_DIR = "data/demo"
  $env:AGENTLENS_SITE_URL = "http://localhost:3100"
  $start = "2026-11-01"; $beforeDays = 7
  $switchAt = ([datetime]$start).AddDays($beforeDays).ToString("yyyy-MM-dd") + "T00:00:00Z"
  $frictionFile = Join-Path $Root "apps\store\config\friction.json"
  $frictionOrig = [IO.File]::ReadAllBytes($frictionFile)
  if (Test-Path "data\demo") { Remove-Item "data\demo" -Recurse -Force }
  Invoke-AgentLens synth scenario before-after --sessions 12000 --start-date $start --before-days $beforeDays --after-days 7
  # The store logs its own traffic (probes, replays) to a separate dir so it does not end up in the synthetic dataset.
  $env:AGENTLENS_DATA_DIR = "data/demo-store"
  if (Test-Path "data\demo-store") { Remove-Item "data\demo-store" -Recurse -Force }
  $store = Start-Process -PassThru -WindowStyle Hidden -WorkingDirectory (Join-Path $Root "apps\store") node -ArgumentList "server.mjs", "--dev"
  $env:AGENTLENS_DATA_DIR = "data/demo"
  try {
    Wait-Http "http://127.0.0.1:3100/robots.txt"
    $py = Get-Py
    Invoke-Native { & $py scripts/demo_friction.py before }
    Invoke-AgentLens ingest
    Invoke-AgentLens site-checks --as-of "${start}T00:00:00Z"
    Invoke-Native { & $py scripts/demo_friction.py after }
    Start-Sleep -Seconds 1
    Invoke-AgentLens site-checks --as-of $switchAt
    Invoke-Native { & $py scripts/demo_friction.py before }
    Start-Sleep -Seconds 1
    Invoke-AgentLens run-all
    Invoke-AgentLens replay-all --pause 0.3
    try { Invoke-AgentLens replay --blocker B07 --mode browser --pause 0.3 } catch { Write-Warning "browser replay skipped: $_" }
    Invoke-AgentLens eval
  } finally {
    taskkill /T /F /PID $store.Id | Out-Null
    [IO.File]::WriteAllBytes($frictionFile, $frictionOrig)
  }
  Invoke-AgentLens export-snapshot --force
  Invoke-Native { pnpm.cmd --filter "@agentlens/dashboard" build:demo }
  Write-Host "Static demo built in apps\dashboard\out (preview: ./tasks.ps1 preview-demo)"
}

switch ($Task) {
  "setup" {
    if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env from .env.example" }
    Invoke-Native { python -m pip install --quiet uv }
    Invoke-Native { python -m uv sync }
    Invoke-Native { pnpm install }
    Invoke-Native { & (Get-Py) -m playwright install chromium }
  }
  "dev" {
    $py = Get-Py
    Write-Host "Starting store :3100, API :8100, dashboard :3101 (Ctrl+C stops all)"
    $jobs = @(
      Start-Process -PassThru -NoNewWindow pnpm.cmd -ArgumentList "dev:store"
      Start-Process -PassThru -NoNewWindow $py -ArgumentList "-m", "uvicorn", "agentlens.main:app", "--port", "8100", "--reload"
      Start-Process -PassThru -NoNewWindow pnpm.cmd -ArgumentList "dev:dashboard"
    )
    try { $jobs | Wait-Process } finally { $jobs | ForEach-Object { if (-not $_.HasExited) { Stop-Process -Id $_.Id -Force } } }
  }
  "test" {
    Invoke-Native { & (Get-Py) -m pytest -q }
    Invoke-Native { pnpm -r test }
  }
  "lint" {
    $py = Get-Py
    Invoke-Native { & $py -m ruff check . }
    Invoke-Native { & $py -m mypy services }
    Invoke-Native { pnpm -r lint }
    Invoke-Native { pnpm -r typecheck }
  }
  "synth-scenario" { Invoke-AgentLens synth scenario before-after --before-days 7 --after-days 7 }
  "pipeline" { Invoke-AgentLens run-all }
  "replay" { Invoke-AgentLens replay-all }
  "report" { Invoke-AgentLens report --format all }
  "snapshot" { Invoke-AgentLens export-snapshot --force }
  "demo" { Invoke-Demo }
  "preview-demo" { Invoke-Native { pnpm.cmd --filter "@agentlens/dashboard" serve:demo } }
  "bench" {
    $env:AGENTLENS_DATA_DIR = "data/bench"
    if (Test-Path "data\bench") { Remove-Item "data\bench" -Recurse -Force }
    Invoke-AgentLens synth offline --sessions 53000 --days 14 --seed 7
    Measure-Command { Invoke-AgentLens run-all } | ForEach-Object { Write-Host ("run-all: {0:N0} s" -f $_.TotalSeconds) }
    $env:AGENTLENS_PERF_DATA_DIR = "data/bench"
    Invoke-Native { & (Get-Py) -m pytest -m perf tests/python/test_api_perf.py -s -q }
  }
  "clean-data" { Get-ChildItem data -Exclude ".gitkeep" | Remove-Item -Recurse -Force }
  default {
    Write-Host "Tasks: setup | dev | test | lint | synth-scenario | pipeline | replay | report | snapshot | demo | preview-demo | bench | clean-data"
  }
}
