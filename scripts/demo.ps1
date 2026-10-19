param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("reset", "api", "web")]
    [string]$Mode,
    [ValidateSet("fake", "openai-compatible")]
    [string]$Provider = "fake"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repositoryRoot
try {
    $dataDirectory = Join-Path $repositoryRoot ".data"
    $databasePath = Join-Path $dataDirectory "finorch.db"
    New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null

    $env:FINORCH_ENVIRONMENT = "development"
    $env:FINORCH_DATABASE_URL = "sqlite:///" + $databasePath.Replace("\", "/")
    $env:FINORCH_AGENT_PROVIDER = $Provider

    switch ($Mode) {
        "reset" {
            & uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
            if ($LASTEXITCODE -ne 0) { throw "Database migration failed with exit code $LASTEXITCODE." }
            & uv run --project apps/api python -m finorch_api.reset --confirm
            if ($LASTEXITCODE -ne 0) { throw "Synthetic demo reset failed with exit code $LASTEXITCODE." }
        }
        "api" {
            & uv run --project apps/api uvicorn --app-dir apps/api/src finorch_api.main:app --host 127.0.0.1 --port 8000
        }
        "web" {
            & pnpm --filter @finorch/web exec vite --host 127.0.0.1
        }
    }
}
finally {
    Pop-Location
}
