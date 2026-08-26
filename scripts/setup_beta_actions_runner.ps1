[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RegistrationToken,

    [string]$RepositoryUrl = "https://github.com/agustealo/AI-Karen",
    [string]$RunnerRoot = "C:\actions-runner\ai-karen-beta",
    [string]$RunnerName = "$env:COMPUTERNAME-karen-beta",
    [string]$ModelBaseUrl = "http://127.0.0.1:1234/v1",
    [string]$ModelName = "",
    [switch]$RunAsService
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-Command {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' is not available in PATH."
    }
}

function Invoke-JsonRequest {
    param([Parameter(Mandatory = $true)][string]$Uri)

    try {
        return Invoke-RestMethod -Uri $Uri -Method Get -TimeoutSec 15
    }
    catch {
        throw "Request failed for $Uri. $($_.Exception.Message)"
    }
}

function Test-LocalModelEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [string]$ExpectedModel
    )

    $normalized = $BaseUrl.TrimEnd('/')
    $modelsUri = "$normalized/models"
    Write-Host "Checking local model endpoint: $modelsUri"

    $payload = Invoke-JsonRequest -Uri $modelsUri
    $models = @(
        $payload.data |
            Where-Object { $_ -and $_.id } |
            ForEach-Object { [string]$_.id }
    )

    if ($models.Count -eq 0) {
        throw "The local OpenAI-compatible endpoint is reachable but exposes no loaded models. Load a model in LM Studio before registering the beta runner."
    }

    if ($ExpectedModel -and ($models -notcontains $ExpectedModel)) {
        throw "Configured model '$ExpectedModel' is not exposed by the endpoint. Available models: $($models -join ', ')"
    }

    $selected = if ($ExpectedModel) { $ExpectedModel } else { $models[0] }
    Write-Host "Local model endpoint is healthy. Selected beta model: $selected"
    return $selected
}

function Get-LatestRunnerRelease {
    $release = Invoke-JsonRequest -Uri "https://api.github.com/repos/actions/runner/releases/latest"
    if (-not $release.tag_name) {
        throw "Unable to determine latest GitHub Actions runner version."
    }

    $version = ([string]$release.tag_name).TrimStart('v')
    $assetName = "actions-runner-win-x64-$version.zip"
    $asset = $release.assets | Where-Object { $_.name -eq $assetName } | Select-Object -First 1
    if (-not $asset) {
        throw "GitHub Actions runner release $version does not expose expected Windows x64 asset '$assetName'."
    }

    return [pscustomobject]@{
        Version = $version
        AssetName = $assetName
        DownloadUrl = [string]$asset.browser_download_url
    }
}

function Install-RunnerFiles {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null

    $configPath = Join-Path $Destination ".runner"
    if (Test-Path $configPath) {
        Write-Host "Runner is already configured at $Destination. Existing registration will be replaced."
    }

    $archive = Join-Path $env:TEMP $Release.AssetName
    Write-Host "Downloading GitHub Actions runner $($Release.Version)..."
    Invoke-WebRequest -Uri $Release.DownloadUrl -OutFile $archive -UseBasicParsing

    Write-Host "Extracting runner to $Destination..."
    Expand-Archive -Path $archive -DestinationPath $Destination -Force
    Remove-Item $archive -Force -ErrorAction SilentlyContinue
}

function Register-Runner {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$RepoUrl,
        [Parameter(Mandatory = $true)][string]$Token,
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$AsService
    )

    Push-Location $Destination
    try {
        $configArgs = @(
            "--url", $RepoUrl,
            "--token", $Token,
            "--name", $Name,
            "--labels", "karen-beta-model,lmstudio,local-ai",
            "--work", "_work",
            "--unattended",
            "--replace"
        )

        if ($AsService) {
            $configArgs += "--runasservice"
        }

        Write-Host "Registering runner '$Name' for $RepoUrl..."
        & .\config.cmd @configArgs
        if ($LASTEXITCODE -ne 0) {
            throw "GitHub Actions runner configuration failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}

Assert-Command -Name "git"
Assert-Command -Name "python"

$pythonVersion = & python --version 2>&1
Write-Host "Python: $pythonVersion"
Write-Host "Git: $(& git --version)"

$selectedModel = Test-LocalModelEndpoint -BaseUrl $ModelBaseUrl -ExpectedModel $ModelName
$release = Get-LatestRunnerRelease
Install-RunnerFiles -Release $release -Destination $RunnerRoot
Register-Runner \
    -Destination $RunnerRoot \
    -RepoUrl $RepositoryUrl \
    -Token $RegistrationToken \
    -Name $RunnerName \
    -AsService:$RunAsService

Write-Host ""
Write-Host "AI KAREN beta runner registration complete."
Write-Host "Runner labels: self-hosted, Windows, X64, karen-beta-model, lmstudio, local-ai"
Write-Host "Local endpoint: $ModelBaseUrl"
Write-Host "Selected model: $selectedModel"
Write-Host ""

if ($RunAsService) {
    Write-Host "The runner was configured as a Windows service. Confirm it appears Online in GitHub before dispatching the beta gate."
}
else {
    Write-Host "Start the runner now with:"
    Write-Host "  cd $RunnerRoot"
    Write-Host "  .\run.cmd"
    Write-Host "Keep that process running while the beta workflow executes."
}

Write-Host ""
Write-Host "Recommended beta-release environment variables:"
Write-Host "  BETA_MODEL_BASE_URL=$ModelBaseUrl"
Write-Host "  BETA_MODEL_NAME=$selectedModel"
