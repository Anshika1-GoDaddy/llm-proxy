#!/usr/bin/env bash
# Test that JWT auto-refresh works (no JWT_TOKEN; CaaS_JWT_ENV only).
# Run with: ./scripts/test_jwt_auto_refresh.sh [BASE_URL]
# Requires: proxy already running with CaaS_JWT_ENV=dev (and AWS creds), PROXY_API_KEY set.

set -euo pipefail

BASE_URL="${1:-http://localhost:8000}"
API_KEY="${PROXY_API_KEY:-sk-my-proxy-key}"

echo "=== Testing JWT auto-refresh at $BASE_URL ==="
echo ""

# 1. Health
echo "1. GET /health"
health=$(curl -s "$BASE_URL/health")
echo "   $health"
if ! echo "$health" | jq -e '.status == "ok"' >/dev/null 2>&1; then
  echo "   FAIL: health check"
  exit 1
fi
echo "   OK"
echo ""

# 2. JWT status (must be auto and token_ready)
echo "2. GET /jwt-status"
jwt_status=$(curl -s "$BASE_URL/jwt-status")
echo "   $jwt_status"
mode=$(echo "$jwt_status" | jq -r '.jwt_mode')
ready=$(echo "$jwt_status" | jq -r '.token_ready')
if [[ "$mode" != "auto" ]]; then
  echo "   FAIL: expected jwt_mode=auto (proxy may be running with JWT_TOKEN set)"
  exit 1
fi
if [[ "$ready" != "true" ]]; then
  echo "   FAIL: token_ready should be true"
  exit 1
fi
echo "   OK (mode=$mode, token_ready=$ready)"
echo ""

# 3. Real call to CaaS via proxy (no manual JWT)
echo "3. POST /v1/responses (proxy uses auto-refreshed JWT to call CaaS)"
resp=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/v1/responses" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","input":"Say hello in one word."}')

body=$(echo "$resp" | sed '$d')
code=$(echo "$resp" | tail -n 1)
if [[ "$code" != "200" ]]; then
  echo "   Response code: $code"
  echo "   Body: $body"
  echo "   FAIL: expected 200"
  exit 1
fi
echo "   HTTP $code"
echo "   output_text: $(echo "$body" | jq -r '.output_text // .error // .')"
echo "   OK"
echo ""

echo "=== All checks passed: JWT auto-refresh is working ==="
