#!/usr/bin/env bash
# Build gd_auth wheel on the host (where pip install git+ssh works), then Docker can install from it.
# Run from repo root: ./scripts/build_gd_auth_wheel.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WHEELS_DIR="$REPO_ROOT/wheels"
URL="${GD_AUTH_GIT_URL:-git+ssh://git@github.com/gdcorp-identity/python-gd-auth}"

mkdir -p "$WHEELS_DIR"
echo "Building gd_auth wheel from $URL into $WHEELS_DIR ..."
pip wheel --no-deps "$URL" -w "$WHEELS_DIR"
echo "Done. Wheel(s) in $WHEELS_DIR - run: docker-compose build"
ls -la "$WHEELS_DIR"/*.whl 2>/dev/null || true
