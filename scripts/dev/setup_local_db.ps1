# One-time local database setup for MelanoTrack (Windows, native PostgreSQL).
#
# Creates the `melanotrack` login role (with CREATEDB, needed by the test suite) and the
# `melanotrack` database, using the password already in .env. You are prompted for the
# password of the `postgres` superuser you chose when installing PostgreSQL; it is not stored.
#
# Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts\dev\setup_local_db.ps1

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { throw ".env not found at $envFile" }

$vars = @{}
Get-Content $envFile | Where-Object { $_ -match '^\s*([A-Z_]+)=(.*)$' } | ForEach-Object {
    $vars[$Matches[1]] = $Matches[2].Trim()
}
$dbName = $vars["POSTGRES_DB"]; $dbUser = $vars["POSTGRES_USER"]; $dbPass = $vars["POSTGRES_PASSWORD"]
if (-not $dbName -or -not $dbUser -or -not $dbPass) { throw "POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD missing in .env" }

$psql = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $psql) { throw "psql.exe not found under C:\Program Files\PostgreSQL" }
Write-Host "Using $($psql.FullName)"

$secure = Read-Host "Password for the 'postgres' superuser" -AsSecureString
$env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))

try {
    $sql = @"
DO `$`$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$dbUser') THEN
    CREATE ROLE $dbUser LOGIN CREATEDB PASSWORD '$dbPass';
  ELSE
    ALTER ROLE $dbUser LOGIN CREATEDB PASSWORD '$dbPass';
  END IF;
END
`$`$;
"@
    & $psql.FullName -h localhost -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 -c $sql
    if ($LASTEXITCODE -ne 0) { throw "Creating the role failed" }

    $exists = & $psql.FullName -h localhost -p 5432 -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$dbName'"
    if ($exists -ne "1") {
        & $psql.FullName -h localhost -p 5432 -U postgres -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE $dbName OWNER $dbUser ENCODING 'UTF8';"
        if ($LASTEXITCODE -ne 0) { throw "Creating the database failed" }
    } else {
        Write-Host "Database $dbName already exists"
    }
    Write-Host "`nDone. Role '$dbUser' and database '$dbName' are ready." -ForegroundColor Green
}
finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}
