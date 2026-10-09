#!/usr/bin/env bash
# Start the canonical pgvector database after optional registry authentication.
set -euo pipefail

if [[ -n "${KAREN_CI_DOCKERHUB_USERNAME:-}" || -n "${KAREN_CI_DOCKERHUB_TOKEN:-}" ]]; then
  if [[ -z "${KAREN_CI_DOCKERHUB_USERNAME:-}" || -z "${KAREN_CI_DOCKERHUB_TOKEN:-}" ]]; then
    echo "Docker Hub CI credentials must both be configured" >&2
    exit 1
  fi
  printf '%s' "$KAREN_CI_DOCKERHUB_TOKEN" |
    docker login --username "$KAREN_CI_DOCKERHUB_USERNAME" --password-stdin >/dev/null
fi

image="${KAREN_CI_POSTGRES_IMAGE:-pgvector/pgvector:pg16}"
container="ai-karen-postgres-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
docker rm -f "$container" >/dev/null 2>&1 || true
docker run -d --name "$container" \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=ai_karen \
  -p 127.0.0.1:5432:5432 \
  --health-cmd="pg_isready -U postgres -d ai_karen" \
  --health-interval=5s --health-timeout=5s --health-retries=12 \
  "$image" >/dev/null
for _ in $(seq 1 60); do
  health="$(docker inspect -f '{{.State.Health.Status}}' "$container")"
  if [[ "$health" == "healthy" ]]; then
    echo "Canonical PostgreSQL service healthy"
    exit 0
  fi
  if [[ "$health" == "unhealthy" ]]; then
    docker logs "$container" >&2
    exit 1
  fi
  sleep 2
done
docker logs "$container" >&2
echo "PostgreSQL did not become healthy" >&2
exit 1
