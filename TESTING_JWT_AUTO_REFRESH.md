# Testing JWT auto-refresh (no manual token)

Use this to confirm the proxy works in production with **only** `CaaS_JWT_ENV` (no `JWT_TOKEN`).

---

## 1. Run the proxy in auto-refresh mode (no JWT_TOKEN)

**Unset** `JWT_TOKEN` so the proxy must use gd_auth:

```bash
# Unset manual token
unset JWT_TOKEN

# AWS credentials (same as Confluence Step 2: aws-okta-processor, then export)
export $(printf "AWS_ACCESS_KEY_ID=%s AWS_SECRET_ACCESS_KEY=%s AWS_SESSION_TOKEN=%s" \
  $(aws-okta-processor authenticate ... | jq -r '.AccessKeyId, .SecretAccessKey, .SessionToken'))

# Auto-refresh only
export CaaS_JWT_ENV=dev
# optional: shorter interval for testing refresh loop (e.g. 60 sec)
# export JWT_REFRESH_INTERVAL_SEC=60

python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Check logs for:

- `CaaS JWT auto-refresh enabled (env=dev, interval=1800)`
- `CaaS JWT refreshed successfully`

---

## 2. Call `/jwt-status` (safe, no token exposed)

```bash
curl -s http://localhost:8000/jwt-status | jq
```

**Expected when auto-refresh is working:**

```json
{
  "jwt_mode": "auto",
  "caas_env": "dev",
  "token_ready": true,
  "last_refresh_sec_ago": 0.5,
  "refresh_interval_sec": 1800
}
```

- `token_ready: true` → proxy has a JWT and can call CaaS.
- `last_refresh_sec_ago` → time since last refresh (increases until next refresh).

---

## 3. Call the proxy (proves token is used)

```bash
curl -s -X POST http://localhost:8000/v1/responses \
  -H "Authorization: Bearer sk-my-proxy-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o","input":"Say hello in one word."}' | jq
```

Expect `200` and a body with `output_text`. If you get `401` or upstream errors, JWT may be missing or invalid (check AWS creds and `CaaS_JWT_ENV`).

---

## 4. Run the test script

With the proxy running (auto-refresh, no `JWT_TOKEN`):

```bash
export PROXY_API_KEY=sk-my-proxy-key   # if different
./scripts/test_jwt_auto_refresh.sh
# or against another host:
./scripts/test_jwt_auto_refresh.sh https://your-proxy.example.com
```

The script checks:

1. `GET /health` → ok  
2. `GET /jwt-status` → `jwt_mode=auto`, `token_ready=true`  
3. `POST /v1/responses` → 200 and valid response  

---

## 5. (Optional) Verify the refresh loop

Use a short interval so you see a refresh within a few minutes:

```bash
export JWT_REFRESH_INTERVAL_SEC=60
# start proxy, then:
curl -s http://localhost:8000/jwt-status | jq '.last_refresh_sec_ago'
# wait 70 seconds
curl -s http://localhost:8000/jwt-status | jq '.last_refresh_sec_ago'
```

After the interval, `last_refresh_sec_ago` should drop back to a small value (e.g. &lt; 5) and logs should show another `CaaS JWT refreshed successfully`.

---

## Production checklist

- [ ] Proxy runs **without** `JWT_TOKEN` (only `CaaS_JWT_ENV=dev` or `test`/`prod`).
- [ ] AWS credentials are available (env vars or IAM role for the process).
- [ ] `GET /jwt-status` returns `jwt_mode: "auto"` and `token_ready: true`.
- [ ] `POST /v1/responses` (or chat) returns 200.
- [ ] `JWT_REFRESH_INTERVAL_SEC` is set so the token is refreshed before expiry (e.g. 1800 if token TTL is 1h).
