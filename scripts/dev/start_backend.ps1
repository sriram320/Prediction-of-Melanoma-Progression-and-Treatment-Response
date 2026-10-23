# Start the FastAPI backend locally (hot reload) against the local PostgreSQL from .env.
# Applies migrations and the idempotent seed first.
#   powershell -ExecutionPolicy Bypass -File scripts\dev\start_backend.ps1
$ErrorActionPreference = "Stop"
$backend = Resolve-Path (Join-Path $PSScriptRoot "..\..\backend")
$py = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating backend virtualenv..."
    py -3.11 -m venv (Join-Path $backend ".venv")
    & $py -m pip install -q --upgrade pip
    & $py -m pip install -q -r (Join-Path $backend "requirements.txt")
}
Push-Location $backend
try {
    & $py -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Migration failed - is PostgreSQL running and has setup_local_db.ps1 been run?" }
    & $py -m app.scripts.seed
    if ($LASTEXITCODE -ne 0) { throw "Seed failed" }
    & $py -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
