#!/usr/bin/env bash
set -euo pipefail

# The operator-controlled Docker runner executes only reviewed main source.
# Browser dependencies and acceptance identity are kept on a hosted runner.
: "${TARGET_SHA:?Reviewed target commit is required}"
: "${KAREN_RELEASE_REPO_ROOT:?Approved release checkout path is required}"
: "${KAREN_RELEASE_REPOSITORY:?Approved GitHub repository is required}"
: "${KAREN_BASE_URL:?Approved HTTPS deployment origin is required}"

[[ "$TARGET_SHA" =~ ^[a-f0-9]{40}$ ]] || {
  echo "::error::Invalid reviewed target SHA" >&2
  exit 1
}
test "$GITHUB_REF" = "refs/heads/main" || {
  echo "::error::Docker acceptance is only available from main" >&2
  exit 1
}
test "$GITHUB_SHA" = "$TARGET_SHA" || {
  echo "::error::Dispatch revision differs from reviewed main" >&2
  exit 1
}
test "$(git rev-parse HEAD)" = "$TARGET_SHA" || {
  echo "::error::Runner checkout differs from reviewed main" >&2
  exit 1
}
test "$KAREN_RELEASE_REPOSITORY" = "$GITHUB_REPOSITORY" || {
  echo "::error::Approved signing repository differs from workflow repository" >&2
  exit 1
}
current="$(gh api "repos/$GITHUB_REPOSITORY/branches/main" --jq '.commit.sha')"
test "$current" = "$TARGET_SHA" || {
  echo "::error::Main moved during protected acceptance" >&2
  exit 1
}

# An absolute, approved host checkout must use exactly the reviewed Compose
# configuration and must retain its separate secret-bearing .env.production.
[[ "$KAREN_RELEASE_REPO_ROOT" = /* ]] && test -d "$KAREN_RELEASE_REPO_ROOT" || {
  echo "::error::Approved production checkout must be an existing absolute path" >&2
  exit 1
}
test -f "$KAREN_RELEASE_REPO_ROOT/.env.production" || {
  echo "::error::Approved production environment configuration is unavailable" >&2
  exit 1
}
test "$(git -C "$KAREN_RELEASE_REPO_ROOT" rev-parse HEAD)" = "$TARGET_SHA" || {
  echo "::error::Release host checkout is not the approved main revision" >&2
  exit 1
}
for file in \
  docker-compose.yml \
  deploy/compose/docker-compose.prod.yml \
  deploy/compose/docker-compose.signed-release.yml; do
  cmp -s "$file" "$KAREN_RELEASE_REPO_ROOT/$file" || {
    echo "::error::Release host has a different canonical Compose definition" >&2
    exit 1
  }
done

# Only the trusted current-main verifier executes. Do not execute scripts
# from the mutable host checkout or modify the deployed containers.
python3 -m scripts.ci.verify_docker_release
echo "SIGNED DOCKER HOST AND PUBLIC INGRESS ACCEPTANCE PASSED"
