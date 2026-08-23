#!/usr/bin/env bash
# WSL2 NVIDIA Docker Setup Script
# Run this from inside your WSL2 distro (Ubuntu/Debian).
# Usage: sudo bash scripts/setup_wsl2_nvidia.sh
set -euo pipefail

echo "[+] Detecting distribution..."
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
echo "    Distribution: $distribution"

echo "[+] Adding NVIDIA package repositories..."
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -fsSL https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

echo "[+] Installing NVIDIA Container Toolkit..."
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit nvidia-container-toolkit-base libnvidia-container-tools

echo "[+] Configuring Docker runtime..."
sudo nvidia-ctk runtime configure --runtime=docker

echo "[+] Restarting Docker..."
sudo systemctl restart docker || true

echo "[+] Verifying..."
if command -v nvidia-smi >/dev/null 2>&1; then
    echo "    nvidia-smi detected."
    nvidia-smi -L || true
else
    echo "    WARNING: nvidia-smi not found in WSL."
    echo "    Install NVIDIA drivers in WSL:"
    echo "      sudo apt install -y nvidia-driver-525"
fi

echo "[+] Docker runtimes:"
docker info --format '{{.Runtimes}}' 2>/dev/null || echo "    docker not available"

echo "[OK] WSL2 NVIDIA setup complete."
echo "    Restart WSL2: wsl --shutdown"
echo "    Then restart Docker Desktop on Windows."
