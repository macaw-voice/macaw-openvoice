#!/bin/sh
# Build Macaw OpenVoice distribution artifacts for Linux.
#
# Produces:
#   dist/Macaw_openvoice-<VERSION>-py3-none-any.whl   (pip wheel)
#   dist/Macaw_openvoice-<VERSION>.tar.gz              (sdist)
#   Docker images (via build_docker.sh)
#
# Usage:
#   ./scripts/build_linux.sh
#
# Environment variables (via env.sh):
#   VERSION        Package version (default: git describe)
#   PUSH           Set to 1 to also push Docker images

set -eu

. "$(dirname "$0")/env.sh"

# Check for required tools
if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is required but not installed." >&2
    echo "Install with: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

mkdir -p dist

# ── Step 1: Build pip wheel ───────────────────────────────────────
echo ""
echo "=== Building pip wheel ==="
uv build --out-dir dist/
echo "Wheel built:"
ls -la dist/*.whl dist/*.tar.gz 2>/dev/null || true

# ── Step 2: Build Docker images ───────────────────────────────────
echo ""
echo "=== Building Docker images ==="
"$(dirname "$0")/build_docker.sh"

echo ""
echo "=== Build complete ==="
echo "Artifacts in dist/:"
ls -la dist/ 2>/dev/null || true
