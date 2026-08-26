"""Cross-platform operator CLI for AI KAREN.

The CLI is an adapter around canonical runtime/deployment entrypoints. It must
not own provider routing, prompt construction, memory behavior, authorization,
or application lifecycle policy.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence

APP_TARGET = "ai_karen_engine.app:create_app"


def _run(command: Sequence[str]) -> int:
    completed = subprocess.run(list(command), check=False)
    return int(completed.returncode)


def _serve(*, reload: bool) -> int:
    host = os.getenv("KARI_SERVER_HOST", "127.0.0.1" if reload else "0.0.0.0")
    port = os.getenv("KARI_SERVER_PORT", "8000")
    log_level = os.getenv("KARI_SERVER_LOG_LEVEL", "info").lower()

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        APP_TARGET,
        "--factory",
        "--host",
        host,
        "--port",
        port,
        "--log-level",
        log_level,
    ]
    if reload:
        command.append("--reload")

    return _run(command)


def _doctor() -> int:
    failures: list[str] = []

    try:
        import fastapi  # noqa: F401
    except Exception as exc:  # pragma: no cover - operator diagnostic path
        failures.append(f"FastAPI import failed: {exc}")

    try:
        import uvicorn  # noqa: F401
    except Exception as exc:  # pragma: no cover - operator diagnostic path
        failures.append(f"Uvicorn import failed: {exc}")

    try:
        from ai_karen_engine.app import create_app  # noqa: F401
    except Exception as exc:  # pragma: no cover - operator diagnostic path
        failures.append(f"Canonical application entrypoint failed: {exc}")

    environment = os.getenv("ENVIRONMENT", "development").lower()
    if environment == "production":
        for forbidden, unsafe_values in {
            "KARI_AUTH_BYPASS": {"1", "true", "yes", "on"},
            "AUTH_ALLOW_DEV_LOGIN": {"1", "true", "yes", "on"},
            "DEBUG": {"1", "true", "yes", "on"},
        }.items():
            value = os.getenv(forbidden, "").strip().lower()
            if value in unsafe_values:
                failures.append(f"Unsafe production setting: {forbidden}={value}")

    if failures:
        print("AI KAREN doctor: FAILED")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("AI KAREN doctor: OK")
    print(f" - environment: {environment}")
    print(f" - app target: {APP_TARGET}")
    return 0


def _docker(action: str, extra: Sequence[str]) -> int:
    if action == "up":
        return _run(["docker", "compose", "up", "-d", *extra])
    if action == "down":
        return _run(["docker", "compose", "down", *extra])
    if action == "logs":
        return _run(["docker", "compose", "logs", "-f", *extra])
    if action == "status":
        return _run(["docker", "compose", "ps", *extra])
    raise ValueError(f"Unsupported docker action: {action}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="karen", description="AI KAREN operator CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("dev", help="Run the API with auto-reload")
    subparsers.add_parser("start", help="Run the production-style API process")
    subparsers.add_parser("doctor", help="Validate the local runtime entrypoint and safety flags")

    docker = subparsers.add_parser("docker", help="Operate the Docker Compose deployment adapter")
    docker_subparsers = docker.add_subparsers(dest="docker_action", required=True)
    for action in ("up", "down", "logs", "status"):
        action_parser = docker_subparsers.add_parser(action)
        action_parser.add_argument("extra", nargs=argparse.REMAINDER)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "dev":
        return _serve(reload=True)
    if args.command == "start":
        return _serve(reload=False)
    if args.command == "doctor":
        return _doctor()
    if args.command == "docker":
        return _docker(args.docker_action, args.extra)

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
