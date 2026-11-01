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
    $databaseFileName = if ($DataProfile -eq "video") { "bankmate-showcase.db" } else { "bankmate.db" }
    $databasePath = Join-Path $dataDirectory $databaseFileName
    New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null

    $env:BANKMATE_ENVIRONMENT = "development"
    $env:BANKMATE_DATABASE_URL = "sqlite:///" + $databasePath.Replace("\", "/")
    $env:BANKMATE_AGENT_PROVIDER = $Provider
    if ($DataProfile -eq "video") {
        $env:BANKMATE_DEMO_NOW = "2026-10-28T12:00:00+00:00"
    } else {
        Remove-Item Env:BANKMATE_DEMO_NOW -ErrorAction SilentlyContinue
    }

    switch ($Mode) {
        "reset" {
            & uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
            if ($LASTEXITCODE -ne 0) { throw "Database migration failed with exit code $LASTEXITCODE." }
            $resetArguments = @("-m", "bankmate_api.reset", "--confirm")
            if ($Showcase) { $resetArguments += "--showcase" }
            & uv run --project apps/api python @resetArguments
            if ($LASTEXITCODE -ne 0) { throw "Synthetic demo reset failed with exit code $LASTEXITCODE." }
        }
        "api" {
            $env:BANKMATE_SUBSCRIPTION_REMINDER_SCHEDULER_ENABLED = "true"
            & uv run --project apps/api uvicorn --app-dir apps/api/src bankmate_api.main:app --host 127.0.0.1 --port 8000
        }
        "web" {
            & pnpm --filter @bankmate/web exec vite --host 127.0.0.1
        }
        "otp" {
            & uv run --project apps/api python -m bankmate_api.demo_verification --latest
        }
    }
}
finally {
    Pop-Location
}
