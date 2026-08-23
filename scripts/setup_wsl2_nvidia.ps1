# WSL2 NVIDIA Docker Setup Script for AI-Karen
# Run this from Windows PowerShell as Administrator, then restart WSL2.
#
# Prerequisites:
# - NVIDIA GPU with latest Windows driver installed (https://www.nvidia.com/Download/index.aspx)
# - WSL2 installed with a Linux distro (Ubuntu recommended)
# - Docker Desktop installed with WSL2 integration enabled

param(
    [switch]$Force,
    [switch]$SkipReboot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step { param([string]$Msg) Write-Host "[+] $Msg" -ForegroundColor Cyan }
function Write-Info { param([string]$Msg) Write-Host "    $Msg" -ForegroundColor Gray }
function Write-Ok   { param([string]$Msg) Write-Host "[OK] $Msg" -ForegroundColor Green }
function Write-Warn { param([string]$Msg) Write-Host "[!] $Msg" -ForegroundColor Yellow }

# 1. Detect WSL distro
$wslDistro = wsl -l -q 2>$null | Select-Object -First 1
if (-not $wslDistro) {
    throw "No WSL distro detected. Install WSL2 first."
}
Write-Step "Detected WSL distro: $wslDistro"

# 2. Detect NVIDIA driver on Windows
$nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if (-not $nvidiaSmi) {
    Write-Warn "nvidia-smi not found on Windows PATH."
    Write-Info "Install the latest NVIDIA driver from https://www.nvidia.com/Download/index.aspx"
    if (-not $Force) {
        $continue = Read-Host "Continue anyway? (y/N)"
        if ($continue -ne 'y') { exit 1 }
    }
} else {
    $driverVersion = & nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>$null | Select-Object -First 1
    Write-Ok "NVIDIA driver version: $driverVersion"
}

# 3. Install NVIDIA Container Toolkit inside WSL
Write-Step "Installing NVIDIA Container Toolkit inside WSL..."
$installScript = @'
set -e
echo "Adding NVIDIA package repositories..."
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
echo "Installing packages..."
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit nvidia-container-toolkit-base libnvidia-container-tools
echo "Configuring Docker runtime..."
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
echo "NVIDIA setup complete."
'@

wsl -d $wslDistro -e bash -lc $installScript

Write-Ok "NVIDIA Container Toolkit installed in WSL."

# 4. Configure Docker Desktop to use WSL2 backend
Write-Step "Configuring Docker Desktop..."
$dockerSettingsPath = "$env:APPDATA\Docker\settings-store.json"
if (Test-Path $dockerSettingsPath) {
    try {
        $settings = Get-Content $dockerSettingsPath -Raw | ConvertFrom-Json
        if ($settings.wslEngineEnabled -ne $true) {
            $settings.wslEngineEnabled = $true
            $settings | ConvertTo-Json -Depth 10 | Set-Content $dockerSettingsPath
            Write-Ok "Docker Desktop WSL engine enabled."
        } else {
            Write-Info "Docker Desktop WSL engine already enabled."
        }
    } catch {
        Write-Warn "Could not update Docker settings automatically: $_"
        Write-Info "Open Docker Desktop -> Settings -> General -> Use WSL 2 based engine"
    }
} else {
    Write-Warn "Docker Desktop settings not found at $dockerSettingsPath"
    Write-Info "Open Docker Desktop -> Settings -> General -> Use WSL 2 based engine"
}

# 5. Verify inside WSL
Write-Step "Verifying NVIDIA runtime in WSL..."
$verifyScript = @'
set -e
if command -v nvidia-smi >/dev/null 2>&1; then
    echo "nvidia-smi detected in WSL."
    nvidia-smi -L || true
else
    echo "nvidia-smi not found in WSL. Install NVIDIA drivers in WSL first."
fi
if [ -f /etc/docker/daemon.json ]; then
    echo "Docker daemon.json:"
    cat /etc/docker/daemon.json || true
fi
docker info --format '{{.Runtimes}}' 2>/dev/null || echo "docker not available in WSL"
'@

wsl -d $wslDistro -e bash -lc $verifyScript

Write-Ok "WSL2 NVIDIA setup script completed."

if (-not $SkipReboot) {
    Write-Warn "Restart WSL2 for all changes to take effect:"
    Write-Info "  wsl --shutdown"
    Write-Info "Then restart Docker Desktop."
}
