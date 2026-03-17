# Production: JWT auto-refresh in Docker

For production, the proxy should use **JWT auto-refresh** (no manual `JWT_TOKEN`) so tokens are renewed before they expire.

## 1. Build the image with gd_auth

`gd_auth` is not on public PyPI. Use one of these:

**Option A – Local wheel (recommended; no SSH in Docker)**

On your machine (where `pip install git+ssh://...` already works):

```bash
./scripts/build_gd_auth_wheel.sh
```

This creates a `.whl` in `wheels/`. Then build the image; the Dockerfile will install any wheel in `wheels/`:

```bash
docker-compose build
docker-compose up -d
```

**Option B – Internal PyPI**

If you have `gd_auth` on an internal PyPI:

```bash
export PIP_EXTRA_INDEX_URL=https://your-internal-pypi.example.com/simple/
docker-compose up -d --build
```

If you use neither, the image builds without `gd_auth` (manual JWT only).

## 2. Run the container with AWS credentials and CaaS env

Auto-refresh needs:

- **CaaS_JWT_ENV** – `dev`, `test`, or `prod`
- **AWS credentials** – from env vars (local/CI) or from the **EC2 instance IAM role** (recommended on a0-dev)

**Option A – EC2 instance with IAM role (e.g. a0-dev)**

When the proxy runs on an EC2 instance that has the right IAM role attached (e.g. `gdasmv2-custom-a0-ec2-instance-role`), the container can use the instance credentials automatically. **Do not** set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN`; leave them unset so the SDK uses the instance profile.

On the EC2 instance (e.g. after SSH or via your deploy):

```bash
cd /path/to/llm-proxy
export CaaS_JWT_ENV=dev
# No JWT_TOKEN, no AWS_* — instance role is used automatically
docker-compose up -d --build
```

Ensure the instance role is allowed to get the GoCaaS SSO JWT (whitelisted for your account/role). Then check:

```bash
curl -s http://localhost:8000/jwt-status | jq
```

You should see `token_ready: true`.

**Option B – Env vars from host (e.g. aws-okta-processor)**

Export credentials on the host, then start the stack so the container receives them:

```bash
export CaaS_JWT_ENV=prod
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_SESSION_TOKEN=...
# Leave JWT_TOKEN unset
docker-compose up -d
```

**Option B – ECS / EKS**

Attach an IAM role to the task/pod so the process gets AWS credentials without env vars. Set only:

- `CaaS_JWT_ENV=prod` (or `dev`/`test`)

in the task definition. The proxy will use the role credentials to refresh the JWT.

## 3. Verify in production

```bash
curl -s https://your-proxy-url/jwt-status | jq
```

Expect:

- `jwt_mode`: `"auto"`
- `token_ready`: `true`
- `last_refresh_sec_ago`: number (seconds since last refresh)
- `last_refresh_error`: `null`

If `token_ready` is `false`, check `last_refresh_error` and ensure the image has `gd_auth` and the container has AWS credentials and `CaaS_JWT_ENV`. If the error is **Forbidden / not authorized to perform: execute-api:Invoke**, either have the instance role whitelisted with CaaS, or set **`CaaS_ASSUME_ROLE_ARN`** to a role that can invoke the token API (e.g. `arn:aws:iam::661303382885:role/GD-AWS-USA-GD-GDASMv2-Dev-Private-PowerUser`). That role’s **trust policy** must allow the EC2 instance role to assume it, and the instance role needs **sts:AssumeRole** on that role.

## 4. Optional: refresh interval

Default refresh is every 30 minutes. Override if needed:

```yaml
environment:
  - JWT_REFRESH_INTERVAL_SEC=1200
```

(Example: 1200 = 20 minutes.)

---

# Run proxy as a binary on EC2 (a0 cluster)

For **gdsec 360** you run Agent Zero and the proxy as **binaries** on an EC2 cluster (a0). Traffic flow:

```
GDSEC360
   │
   ▼
ALB
   │
   ▼
Agent Zero  (port 50010)
   │
   ▼
LLM Proxy   (port 8000)
   │
   ▼
CaaS
```

**Ports on EC2:** Agent Zero → **50010** · LLM Proxy → **8000**

---

## Step-by-step: push binary to repo, pull on EC2

Use this flow to build the binary on your laptop, push it to the proxy repo, then clone and run on EC2. Replace `sk-your-proxy-key` with your real key.

### Step 0 — Create the Git repo (do this once if you don’t have a repo yet)

**On GitHub:** Create a new repository (e.g. `Anshika1-GoDaddy/llm-proxy`). Do **not** add a README, .gitignore, or license (you already have a project).

**On your laptop**, in the proxy project:

```bash
cd /Users/anshika1/Desktop/llm-proxy
git init
git remote add origin https://github.com/Anshika1-GoDaddy/llm-proxy.git
```

Add and commit the project (no binary yet):

```bash
git add .
git commit -m "initial llm-proxy project"
git branch -M main
git push -u origin main
```

*(If you use a different GitHub org or repo name, change the `origin` URL and the clone URL in Step 2.)*

### Step 1 — Push the binary to your proxy repo (on your laptop)

In your proxy project:

```bash
cd /Users/anshika1/Desktop/llm-proxy
```

Build the Linux binary (if you haven’t already). You need the gd_auth wheel for JWT auto-refresh:

```bash
./scripts/build_gd_auth_wheel.sh   # if needed
./scripts/build_binary_linux.sh
```

Move binary into repo root and commit:

```bash
cp dist/llm-proxy .
git add llm-proxy
git commit -m "add proxy binary for ec2 deployment"
git push
```

*(If your repo has a `.gitignore` that ignores `llm-proxy` or `dist/`, use `git add -f llm-proxy`.)*

### Step 2 — Pull on EC2

In your EC2 terminal:

```bash
cd ~
git clone https://github.com/Anshika1-GoDaddy/llm-proxy.git
cd llm-proxy
chmod +x llm-proxy
```

### Step 3 — Run proxy

Set env. Do not set `JWT_TOKEN`; the proxy uses the EC2 instance role (or an assumed role). Optional: **CaaS_SERVICE_NAME** if the token API expects it; **CaaS_ASSUME_ROLE_ARN** to assume another role (e.g. PowerUser) before calling the token API if the instance role can’t invoke it:

```bash
export CaaS_JWT_ENV=dev
export PROXY_API_KEY=sk-my-proxy-key
# Optional: service name for CaaS whitelist
export CaaS_SERVICE_NAME=a0-proxy-ec2
# Optional: assume this role for token API (role must trust the instance role; instance role needs sts:AssumeRole)
export CaaS_ASSUME_ROLE_ARN=arn:aws:iam::661303382885:role/GD-AWS-USA-GD-GDASMv2-Dev-Private-PowerUser
```

Start it in the background (use `dist/llm-proxy` if you cloned the repo; redirect stdin so the process doesn’t exit under nohup):

```bash
nohup ./dist/llm-proxy </dev/null >> proxy.log 2>&1 &
```

If the process exits right away (e.g. `Done(1)`), see **Troubleshooting: proxy exits with nohup** below.

### Step 4 — Verify

Check process:

```bash
ps aux | grep llm-proxy
```

Check health:

```bash
curl http://localhost:8000/health
```

Optional — JWT status:

```bash
curl -s http://localhost:8000/jwt-status | jq
```

Your EC2 will now be running **Agent Zero → 50010**, **LLM Proxy → 8000**. Point Agent Zero at the proxy (e.g. `http://192.168.11.216:8000` when on the same host, or the instance’s private IP) with the same `PROXY_API_KEY`.

### Troubleshooting: proxy exits with nohup

If `nohup ./dist/llm-proxy > proxy.log 2>&1 &` exits immediately (e.g. `[1] + Done(1)`):

1. **See the real error** — run in foreground and watch the output:
   ```bash
   cd ~/llm-proxy
   export CaaS_JWT_ENV=dev
   export PROXY_API_KEY=sk-your-proxy-key
   ./dist/llm-proxy 2>&1 | tee proxy.log
   ```
   If it stays up, press Ctrl+C and try background again with **stdin closed**:
   ```bash
   nohup ./dist/llm-proxy </dev/null >> proxy.log 2>&1 &
   ```

2. **Check the log** after a failed run:
   ```bash
   cat proxy.log
   ```
   If you see `gd_auth is not installed`, the binary was built without the gd_auth wheel — rebuild on your laptop with `./scripts/build_gd_auth_wheel.sh` then `./scripts/build_binary_linux.sh` and push again.

3. **Confirm the binary** — on EC2 run `file ./dist/llm-proxy`. It must show **`x86-64`** (your EC2 is amd64). If it shows **`ARM aarch64`**, the binary was built for the wrong architecture (e.g. from Apple Silicon without `--platform linux/amd64`). Rebuild on your laptop with `./scripts/build_binary_linux.sh` (it now forces amd64) and push again. If it shows `ASCII` or `data`, Git corrupted it; ensure `.gitattributes` has `dist/llm-proxy binary` and re-push.

---

## Alternative: copy binary via scp (no git)

Do this on your **Mac** (or a machine with Docker), then on **EC2**. Replace `YOUR_KEY.pem`, `EC2_IP`, and `sk-your-proxy-key` with your values.

**Example:** If your a0 instance has **private IP 192.168.11.216**, use that when configuring Agent Zero: `http://192.168.11.216:8000`. For `ssh`/`scp` use the instance’s **public IP** (or bastion) unless you’re on the same VPC/VPN.

### On your Mac (or build machine)

**Step 1 – Go to the project**
```bash
cd /Users/anshika1/Desktop/llm-proxy
```

**Step 2 – Build gd_auth wheel (needed for JWT auto-refresh on EC2)**  
*(Skip if you already have `wheels/gd_auth-*.whl`.)*
```bash
./scripts/build_gd_auth_wheel.sh
```

**Step 3 – Build the Linux binary**
```bash
./scripts/build_binary_linux.sh
```

**Step 4 – Copy the binary to EC2**  
*(Replace `YOUR_KEY.pem` and `EC2_IP` with your key path and a0 instance public IP.)*
```bash
ssh -i YOUR_KEY.pem ec2-user@EC2_IP "mkdir -p ~/bin"
scp -i YOUR_KEY.pem dist/llm-proxy ec2-user@EC2_IP:~/bin/llm-proxy
ssh -i YOUR_KEY.pem ec2-user@EC2_IP "chmod +x ~/bin/llm-proxy"
```

### On EC2 (SSH in, then run the proxy)

**Step 5 – SSH into the instance**
```bash
ssh -i YOUR_KEY.pem ec2-user@EC2_IP
```

**Step 6 – Run the proxy**
```bash
export CaaS_JWT_ENV=dev
export PROXY_API_KEY=sk-your-proxy-key
nohup ~/bin/llm-proxy > ~/llm-proxy.log 2>&1 &
```

**Step 7 – Check it’s running**
```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/jwt-status | jq
```

---

## How it works after deploy (JWT refresh and full flow)

Once the binary is running on EC2 with `CaaS_JWT_ENV=dev` (or `test`/`prod`), here’s how everything works. No Docker, no manual token — the proxy gets and refreshes the JWT by itself.

### 1. Where the proxy gets AWS credentials (EC2)

- On EC2, **do not** set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, or `AWS_SESSION_TOKEN`.
- The binary uses the **EC2 instance IAM role** (e.g. `gdasmv2-custom-a0-ec2-instance-role`). The AWS SDK (used inside `gd_auth`) reads credentials from the instance metadata service automatically.
- So: same binary, same env vars; only the machine’s role matters for JWT.

### 2. What happens when the binary starts

1. **Startup**  
   - Reads env: `CaaS_JWT_ENV`, `PROXY_API_KEY`, optional `PORT`, `LLM_BASE_URL`, etc.  
   - **First JWT refresh** (synchronous): calls `gd_auth` → `gd_auth` uses the instance role → gets a JWT from GoDaddy SSO for that env (`dev`/`test`/`prod`).  
   - Stores that token in memory and starts the HTTP server (port 8000 by default).  
   - Starts a **background task** that will refresh the JWT on a timer.

2. **Background refresh**  
   - Every **30 minutes** by default (`JWT_REFRESH_INTERVAL_SEC=1800`).  
   - The background task calls `gd_auth` again, gets a new JWT, and replaces the in-memory token.  
   - So the token is renewed before it expires; no manual action needed.

3. **If a refresh fails**  
   - The proxy keeps using the **previous** token (it may still be valid).  
   - Errors are stored and exposed in `/jwt-status` as `last_refresh_error`.  
   - You can monitor with: `curl -s http://localhost:8000/jwt-status | jq`

### 3. What happens when Agent Zero (or any client) sends a request

1. **Client** (e.g. Agent Zero) sends a chat request to the proxy:  
   `POST http://192.168.11.216:8000/v1/chat/completions` (or `/v1/responses`, etc.) with header `Authorization: Bearer <PROXY_API_KEY>` — use your proxy host’s private IP if different.

2. **Proxy**  
   - Validates the request using `PROXY_API_KEY`.  
   - Gets the **current JWT** from memory (the one refreshed at startup and by the background task).  
   - Forwards the request to **CaaS** (e.g. `caas-dp.open-webui.dev-godaddy.com`) with header `Authorization: sso-jwt <JWT>`.

3. **If CaaS returns 401**  
   - The proxy **refreshes the JWT once** (calls `gd_auth` again), then **retries** the same request with the new token.  
   - So a single 401 (e.g. token just expired) is handled automatically.

4. **Proxy** then returns CaaS’s response (or a reshaped one) back to the client.

### 4. Summary

| You set on EC2 | What it’s for |
|----------------|----------------|
| `CaaS_JWT_ENV=dev` (or `test`/`prod`) | Tells the proxy to get/refresh JWT via `gd_auth` for that environment. |
| `PROXY_API_KEY=sk-...` | Key that clients (Agent Zero) must send; proxy rejects requests without it. |
| No `JWT_TOKEN`, no `AWS_*` | Proxy uses the instance role for `gd_auth`; JWT is fully automatic. |

**JWT refresh:**  
- At startup (one sync refresh).  
- Every 30 min in the background.  
- Once more on any 401 from CaaS, then retry.  

**End-to-end:**  
Agent Zero → proxy (with `PROXY_API_KEY`) → proxy adds CaaS JWT (from `gd_auth` + instance role) → CaaS → response back to Agent Zero.

---

## 1. Build the binary (reference)

**On a Linux machine (or from macOS/Windows for a Linux binary):**

- **Option A – Build on Linux (e.g. an EC2 build box or your Linux laptop)**  
  From repo root:
  ```bash
  ./scripts/build_gd_auth_wheel.sh   # if you need JWT auto-refresh
  ./scripts/build_binary.sh
  ```
  Binary: `dist/llm-proxy`

- **Option B – Build a Linux binary from macOS/Windows (for EC2)**  
  From repo root. **Use this so the binary is x86_64 (amd64)** — your a0 EC2 is x86_64; the script forces `--platform linux/amd64` so it works even on Apple Silicon:
  ```bash
  ./scripts/build_gd_auth_wheel.sh   # if you need JWT auto-refresh
  ./scripts/build_binary_linux.sh    # Docker build → dist/llm-proxy (Linux amd64)
  ```
  After build, run `file dist/llm-proxy` — it must show **x86-64**, not aarch64. Then commit and push `dist/llm-proxy`.

- **Option C – GitHub Actions (same idea as building Agent Zero from GitHub)**  
  Push to `main`/`master` or run the workflow manually. The [build-binary](.github/workflows/build-binary.yml) workflow produces a Linux binary and uploads it as artifact `llm-proxy-linux`. Download from the Actions run and use that for EC2.  
  If you use a different pipeline (e.g. Vercel, internal “vy cling”, or another CI), run the same build steps (or call `scripts/build_binary_linux.sh`) and take the artifact `dist/llm-proxy`.

## 2. Copy binary to EC2 (a0 cluster)

Copy the single file to each node where you run the proxy (same way you deploy the Agent Zero binary):

```bash
scp -i your-key.pem dist/llm-proxy ec2-user@<a0-instance-ip>:~/bin/llm-proxy
# or use your existing deploy (Ansible, rsync, etc.)
```

## 3. Run the proxy on EC2

On the a0 instance, run the binary with env vars. **No Docker, no Python install.** Use the instance IAM role for JWT (do not set `AWS_*`):

```bash
# Optional: put in a systemd unit or your process manager
export CaaS_JWT_ENV=dev
export PROXY_API_KEY=sk-your-proxy-key
# Optional: PORT=8000 (default), LLM_BASE_URL=...
# Do not set JWT_TOKEN or AWS_* — instance role is used for gd_auth

./bin/llm-proxy
```

Or in one line:

```bash
CaaS_JWT_ENV=dev PROXY_API_KEY=sk-your-proxy-key ./bin/llm-proxy
```

## 4. Point Agent Zero at the proxy

Configure Agent Zero (on the same cluster or elsewhere) to use this proxy URL, e.g. `http://192.168.11.216:8000` (private IP of the a0 instance running the proxy), and set the proxy API key where Agent Zero sends it (e.g. `PROXY_API_KEY` or the key in the request header).

## 5. Verify

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/jwt-status | jq
```
