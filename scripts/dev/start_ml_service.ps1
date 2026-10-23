# Start the ml-service locally on :8100 (reuses the backend virtualenv; its deps are a subset).
#   powershell -ExecutionPolicy Bypass -File scripts\dev\start_ml_service.ps1
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run scripts\dev\start_backend.ps1 once first (it creates the virtualenv)." }
if (-not $env:MODEL_ADAPTER) { $env:MODEL_ADAPTER = "mock" }
& $py -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8100 --app-dir (Join-Path $root "ml_service")
