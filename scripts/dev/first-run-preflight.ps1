[CmdletBinding()]
param(
    [string]$BaseUrl = "http://localhost:8000",
    [int]$LogTail = 250
)

$ErrorActionPreference = "Stop"

function Write-Section {
    param([Parameter(Mandatory = $true)][string]$Title)
    Write-Host "`n=== $Title ===" -ForegroundColor Cyan
}

function Invoke-Endpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [switch]$AllowFailure
    )

    $uri = "$BaseUrl$Path"
    try {
        $response = Invoke-WebRequest -Uri $uri -Method Get -UseBasicParsing -ErrorAction Stop
        $body = $response.Content
        Write-Host "$Path -> HTTP $($response.StatusCode)"
        if ($body) {
            Write-Host $body
        }
        return [pscustomobject]@{
            Path = $Path
            StatusCode = [int]$response.StatusCode
            Body = $body
            Error = $null
        }
    }
    catch {
        $statusCode = $null
        $body = $null
        $response = $_.Exception.Response

        if ($null -ne $response) {
            try {
                $statusCode = [int]$response.StatusCode
            }
            catch {
                $statusCode = $null
            }

            try {
                $stream = $response.GetResponseStream()
                if ($null -ne $stream) {
                    $reader = New-Object System.IO.StreamReader($stream)
                    try {
                        $body = $reader.ReadToEnd()
                    }
                    finally {
                        $reader.Dispose()
                    }
                }
            }
            catch {
                $body = $null
            }
        }

        Write-Host "$Path -> HTTP $statusCode" -ForegroundColor Yellow
        if ($body) {
            Write-Host $body -ForegroundColor Yellow
        }
        else {
            Write-Host $_.Exception.Message -ForegroundColor Yellow
        }

        if (-not $AllowFailure) {
            throw
        }

        return [pscustomobject]@{
            Path = $Path
            StatusCode = $statusCode
            Body = $body
            Error = $_.Exception.Message
        }
    }
}

Write-Section "Repository"
$head = (& git rev-parse HEAD).Trim()
$branch = (& git branch --show-current).Trim()
Write-Host "branch: $branch"
Write-Host "head:   $head"

Write-Section "Canonical first-run assets"
$requiredPaths = @(
    "src/ai_karen_engine/api_routes/auth/auth.py",
    "src/ai_karen_engine/services/auth/auth_service.py",
    "docs/architecture/FIRST_RUN_SYSTEM.md",
    "scripts/ci/production-first-boot-smoke.sh",
    "supabase/migrations"
)

foreach ($path in $requiredPaths) {
    if (-not (Test-Path $path)) {
        throw "Required first-run asset is missing: $path"
    }
    Write-Host "OK $path"
}

$migrations = @(Get-ChildItem -Path "supabase/migrations" -Filter "*.sql" -File | Sort-Object Name)
if ($migrations.Count -eq 0) {
    throw "No canonical SQL migrations were found under supabase/migrations."
}
Write-Host "canonical migrations: $($migrations.Count)"

Write-Section "Docker Compose"
$dockerAvailable = $null -ne (Get-Command docker -ErrorAction SilentlyContinue)
if ($dockerAvailable) {
    try {
        & docker compose config --quiet
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose config failed with exit code $LASTEXITCODE"
        }
        Write-Host "docker compose config: valid"
        & docker compose ps
    }
    catch {
        Write-Host "Docker Compose readiness check failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}
else {
    Write-Host "docker executable not found; skipping Compose inspection" -ForegroundColor Yellow
}

Write-Section "HTTP readiness"
$liveness = Invoke-Endpoint -Path "/health/live" -AllowFailure
$authHealth = Invoke-Endpoint -Path "/api/auth/health" -AllowFailure
$firstRun = Invoke-Endpoint -Path "/api/auth/first-run" -AllowFailure

$firstRunUnavailable = ($firstRun.StatusCode -eq 503) -or ($firstRun.Body -match "First-run state unavailable")

if ($firstRunUnavailable) {
    Write-Section "First-run unavailable diagnosis"
    Write-Host "The API is reachable, but canonical AuthService could not establish durable bootstrap state." -ForegroundColor Yellow
    Write-Host "Required auth tables: tenants, auth_users, auth_sessions, auth_refresh_token_history"
    Write-Host "Runtime schema creation is intentionally forbidden. Apply the canonical migrations to the same database configured for the API, then restart the API."

    if ($dockerAvailable) {
        Write-Section "Recent Compose logs"
        try {
            $logs = & docker compose logs --tail $LogTail 2>&1
            $interesting = $logs | Select-String -Pattern "Auth schema preflight|Missing migration-owned auth tables|AuthService database preflight|First-run state unavailable|database|postgres|asyncpg" -CaseSensitive:$false
            if ($interesting) {
                $interesting | ForEach-Object { Write-Host $_.Line }
            }
            else {
                Write-Host "No matching auth/database failure markers found in the last $LogTail Compose log lines."
            }
        }
        catch {
            Write-Host "Unable to read Compose logs: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }

    exit 2
}

if ($firstRun.StatusCode -eq 200) {
    Write-Section "Result"
    Write-Host "First-run state is available." -ForegroundColor Green
    exit 0
}

Write-Section "Result"
Write-Host "First-run endpoint returned an unexpected result. Inspect the HTTP output and backend logs above." -ForegroundColor Yellow
exit 1
