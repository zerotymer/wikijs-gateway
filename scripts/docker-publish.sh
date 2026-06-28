#!/usr/bin/env bash
# Build the gateway image once and publish it to both registries:
#   - Docker Hub : zerotymer/wikijs-gateway
#   - Nexus      : nexus.zerotymer.net/docker/wikijs-gateway
# Each gets two tags: the given <version> and `latest`.
#
# Server-side deploy (run/pull on a host) is intentionally out of scope —
# this script only builds and pushes images.
#
# Usage:
#   scripts/docker-publish.sh <version>          # e.g. 1.0.3
#   DOCKERHUB_IMAGE=... NEXUS_IMAGE=... scripts/docker-publish.sh 1.0.3
#
# Assumes `docker login` is already done for both registries.
set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "usage: $0 <version>   (e.g. $0 1.0.3)" >&2
  exit 1
fi

# Image paths — override via env if a registry path changes.
DOCKERHUB_IMAGE="${DOCKERHUB_IMAGE:-zerotymer/wikijs-gateway}"
NEXUS_IMAGE="${NEXUS_IMAGE:-nexus.zerotymer.net/docker/wikijs-gateway}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Build the full ref list: each registry x {version, latest}.
REFS=()
for img in "$DOCKERHUB_IMAGE" "$NEXUS_IMAGE"; do
  REFS+=("$img:$VERSION" "$img:latest")
done

# Build once, applying every tag to the same image.
build_args=()
for ref in "${REFS[@]}"; do
  build_args+=(-t "$ref")
done
echo ">> building: ${REFS[*]}"
docker build "${build_args[@]}" .

# Push every tag to both registries.
for ref in "${REFS[@]}"; do
  echo ">> pushing: $ref"
  docker push "$ref"
done

echo ">> done: published $VERSION + latest to Docker Hub and Nexus"
