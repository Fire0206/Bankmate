param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("reset", "api", "web", "otp")]
    [string]$Mode,
    [ValidateSet("fake", "openai-compatible")]
    [string]$Provider = "fake",
    [ValidateSet("default", "video")]
    [string]$DataProfile = "default",
    [switch]$Showcase
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repositoryRoot
try {
    if ($Showcase -and ($Mode -ne "reset" -or $DataProfile -ne "video")) {
        throw "-Showcase requires -Mode reset -DataProfile video so it cannot replace the regular local database."
    }
    if ($Mode -eq "otp" -and $DataProfile -ne "video") {
        throw "-Mode otp requires -DataProfile video."
    }

    $dataDirectory = Join-Path $repositoryRoot ".data"
    $databaseFileName = if ($DataProfile -eq "video") { "finorch-showcase.db" } else { "finorch.db" }
    $databasePath = Join-Path $dataDirectory $databaseFileName
    New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null

    $env:FINORCH_ENVIRONMENT = "development"
    $env:FINORCH_DATABASE_URL = "sqlite:///" + $databasePath.Replace("\", "/")
    $env:FINORCH_AGENT_PROVIDER = $Provider

    switch ($Mode) {
        "reset" {
            & uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
            if ($LASTEXITCODE -ne 0) { throw "Database migration failed with exit code $LASTEXITCODE." }
            $resetArguments = @("-m", "finorch_api.reset", "--confirm")
            if ($Showcase) { $resetArguments += "--showcase" }
            & uv run --project apps/api python @resetArguments
            if ($LASTEXITCODE -ne 0) { throw "Synthetic demo reset failed with exit code $LASTEXITCODE." }
        }
        "api" {
            $env:FINORCH_SUBSCRIPTION_REMINDER_SCHEDULER_ENABLED = "true"
            & uv run --project apps/api uvicorn --app-dir apps/api/src finorch_api.main:app --host 127.0.0.1 --port 8000
        }
        "web" {
            & pnpm --filter @finorch/web exec vite --host 127.0.0.1
        }
        "otp" {
            & uv run --project apps/api python -m finorch_api.demo_verification --latest
        }
    }
}
finally {
    Pop-Location
}
