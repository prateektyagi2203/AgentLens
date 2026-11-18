# AgentLens task runner (Windows PowerShell). Usage: ./tasks.ps1 <task>
# Tasks: setup | dev | test | lint | synth-scenario | pipeline | replay | snapshot | clean-data
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
  Invoke-Native { & $py -m agentlens.cli @args }
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
  "replay" { Invoke-AgentLens replay run }
  "snapshot" { Invoke-AgentLens export-snapshot }
  "clean-data" { Get-ChildItem data -Exclude ".gitkeep" | Remove-Item -Recurse -Force }
  default {
    Write-Host "Tasks: setup | dev | test | lint | synth-scenario | pipeline | replay | snapshot | clean-data"
  }
}
