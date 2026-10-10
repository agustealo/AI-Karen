"""Deployment contract for the opt-in governed PEFT worker image."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_peft_dependencies_are_installed_in_dedicated_image():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements/training-peft.txt").read_text(encoding="utf-8")
    assert "FROM runtime AS training-peft" in dockerfile
    assert "COPY requirements/training-peft.txt" in dockerfile
    assert "python -m pip install --no-cache-dir -r /app/requirements/training-peft.txt" in dockerfile
    assert "python -m pip check" in dockerfile
    worker = compose.split("  training-worker:", 1)[1].split("\n\n  #", 1)[0]
    assert "PROFILE: training-peft" in worker
    assert "KAREN_TRAINING_WORKER_TENANT:" in worker
    assert "training.worker_service" in worker
    assert "peft>=" in requirements
    assert "accelerate>=" in requirements
    assert "safetensors>=" in requirements
