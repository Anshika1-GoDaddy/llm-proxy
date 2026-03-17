#!/usr/bin/env bash
# Build a Linux binary of llm-proxy (for EC2). Use this from macOS/Windows so the binary runs on a0 EC2.
# Run from repo root: ./scripts/build_binary_linux.sh
# Output: dist/llm-proxy (Linux x86_64).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "Building Linux binary in Docker (for EC2) ..."
docker run --rm \
  -v "$REPO_ROOT:/app" \
  -w /app \
  python:3.11-slim \
  bash -c '
    set -e
    apt-get update -qq && apt-get install -y -qq gcc libffi-dev > /dev/null
    pip install -q -r requirements.txt
    [ -n "$(ls wheels/*.whl 2>/dev/null)" ] && pip install -q wheels/*.whl || true
    pip install -q pyinstaller
    pyinstaller --clean --noconfirm \
      --onefile --name llm-proxy \
      --hidden-import=main \
      --collect-submodules=uvicorn --collect-submodules=fastapi --collect-submodules=httpx --collect-submodules=gd_auth \
      run.py
  '

echo "Done. Linux binary: $REPO_ROOT/dist/llm-proxy"
ls -la "$REPO_ROOT/dist/llm-proxy"
