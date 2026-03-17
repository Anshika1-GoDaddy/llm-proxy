#!/usr/bin/env bash
# Build llm-proxy as a single executable (for EC2 a0 cluster, same pattern as Agent Zero binary).
# Run from repo root: ./scripts/build_binary.sh
# Output: dist/llm-proxy (Linux) or dist/llm-proxy.exe (Windows).
# For EC2 (Linux), build on Linux or use scripts/build_binary_linux.sh (Docker).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

BUILD_VENV="${BUILD_VENV:-$REPO_ROOT/.venv-build}"
if [ ! -d "$BUILD_VENV" ]; then
  echo "Creating build venv at $BUILD_VENV ..."
  python3 -m venv "$BUILD_VENV"
fi
# shellcheck source=/dev/null
source "$BUILD_VENV/bin/activate"

echo "Installing dependencies ..."
pip install -q -r requirements.txt
if ls wheels/*.whl 1>/dev/null 2>&1; then
  echo "Installing wheels (e.g. gd_auth) ..."
  pip install -q wheels/*.whl
fi
pip install -q pyinstaller

echo "Building binary with PyInstaller ..."
pyinstaller --clean --noconfirm \
  --onefile \
  --name llm-proxy \
  --hidden-import=main \
  --collect-submodules=uvicorn \
  --collect-submodules=fastapi \
  --collect-submodules=httpx \
  --collect-submodules=gd_auth \
  run.py

echo "Done. Binary: $REPO_ROOT/dist/llm-proxy"
ls -la "$REPO_ROOT/dist/llm-proxy" 2>/dev/null || ls -la "$REPO_ROOT/dist/"
