#!/bin/sh
# Common environment setup for Macaw OpenVoice build scripts.
#
# Sources version from git tags and sets Docker/Python build variables.
# Used by: build_docker.sh, build_linux.sh

set -eu

export VERSION=${VERSION:-$(git describe --tags --first-parent --abbrev=7 --long --dirty --always 2>/dev/null | sed -e "s/^v//g" || echo "0.0.0-dev")}
export PYTHON_VERSION=${PYTHON_VERSION:-"3.12"}
export PLATFORM=${PLATFORM:-"linux/arm64,linux/amd64"}
export DOCKER_ORG=${DOCKER_ORG:-"useMacaw"}
export DOCKER_REPO=${DOCKER_REPO:-"ghcr.io/${DOCKER_ORG}/Macaw-openvoice"}

Macaw_COMMON_BUILD_ARGS="--build-arg=VERSION \
    --build-arg=PYTHON_VERSION"

echo "Building Macaw OpenVoice"
echo "VERSION=$VERSION"
echo "PYTHON_VERSION=$PYTHON_VERSION"
echo "PLATFORM=$PLATFORM"
