#!/bin/sh
# Build Macaw OpenVoice Docker images (CPU and GPU).
#
# Usage:
#   ./scripts/build_docker.sh          # Build locally (--load)
#   PUSH=1 ./scripts/build_docker.sh   # Build and push to registry (--push)
#
# Environment variables (via env.sh):
#   VERSION        Image tag (default: git describe)
#   PLATFORM       Target platforms (default: linux/arm64,linux/amd64)
#   DOCKER_ORG     Docker Hub org (default: useMacaw)
#   DOCKER_REPO    Full repo name (default: useMacaw/Macaw-openvoice)

set -eu

. "$(dirname "$0")/env.sh"

PUSH=${PUSH:-""}

if [ -z "${PUSH}" ]; then
    echo "Building ${DOCKER_REPO}:${VERSION} locally. Set PUSH=1 to push."
    LOAD_OR_PUSH="--load"
else
    echo "Building and pushing ${DOCKER_REPO}:${VERSION}"
    LOAD_OR_PUSH="--push"
fi

# ── CPU image ──────────────────────────────────────────────────────
echo ""
echo "=== Building CPU image: ${DOCKER_REPO}:${VERSION} ==="
docker buildx build \
    ${LOAD_OR_PUSH} \
    --platform="${PLATFORM}" \
    ${Macaw_COMMON_BUILD_ARGS} \
    -f Dockerfile \
    -t "${DOCKER_REPO}:${VERSION}" \
    .

# ── GPU image (amd64 only — CUDA) ─────────────────────────────────
# GPU image only built for amd64 (NVIDIA CUDA runtime requires x86_64)
if echo "${PLATFORM}" | grep -q "amd64"; then
    echo ""
    echo "=== Building GPU image: ${DOCKER_REPO}:${VERSION}-gpu ==="
    docker buildx build \
        ${LOAD_OR_PUSH} \
        --platform=linux/amd64 \
        ${Macaw_COMMON_BUILD_ARGS} \
        -f Dockerfile.gpu \
        -t "${DOCKER_REPO}:${VERSION}-gpu" \
        .
fi

echo ""
echo "Done."
echo "  CPU: ${DOCKER_REPO}:${VERSION}"
if echo "${PLATFORM}" | grep -q "amd64"; then
    echo "  GPU: ${DOCKER_REPO}:${VERSION}-gpu"
fi
