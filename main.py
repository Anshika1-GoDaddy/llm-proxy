"""
LLM Proxy — OpenAI-compatible API that forwards chat requests to an upstream
CaaS (Chat as a Service) endpoint. Validates clients via PROXY_API_KEY and
authenticates to the upstream with JWT. JWT can be supplied manually (JWT_TOKEN)
or auto-refreshed using the GoCaaS service account (CaaS_JWT_ENV + gd_auth).
"""

import asyncio
import logging
import os
import time
import json
import httpx

# Load .env so JWT_TOKEN, CaaS_JWT_ENV, etc. are set from file when running locally
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # optional; env vars can be set by shell/container

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse


# -----------------------------------------------------------------------------
# Configuration (env vars)
# -----------------------------------------------------------------------------

# caas-dp accepts sso-jwt; caas.open-webui.godaddy.com (Web UI) may return 500 for API + JWT (different auth).
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://caas-dp.open-webui.dev-godaddy.com/api/chat/completions")
PROXY_API_KEY = os.environ.get("PROXY_API_KEY", "sk-my-proxy-key")

# JWT: either manual (JWT_TOKEN) or auto-refresh via gd_auth (CaaS_JWT_ENV = dev|test|prod)
JWT_TOKEN_MANUAL = os.environ.get("JWT_TOKEN")
CaaS_JWT_ENV = os.environ.get("CaaS_JWT_ENV", "").strip().lower()  # dev, test, prod
JWT_REFRESH_INTERVAL_SEC = int(os.environ.get("JWT_REFRESH_INTERVAL_SEC", "1800"))  # 30 min default

# When using CaaS_JWT_ENV, we store the current token and refresh it in the background.
_jwt_token_refreshed: str | None = None
_jwt_last_refresh_at: float | None = None  # epoch sec, for status endpoint
_jwt_last_refresh_error: str | None = None  # last exception message when refresh failed (for /jwt-status)


def _get_jwt_via_gd_auth(env: str) -> str:
    """Fetch JWT using gd_auth (GoCaaS service account). Requires gd_auth and AWS creds in env."""
    try:
        from gd_auth.client import AwsIamAuthTokenClient
    except ImportError as e:
        raise RuntimeError(
            "CaaS_JWT_ENV is set but gd_auth is not installed. "
            "Install the GoDaddy auth package (e.g. from internal repo)."
        ) from e

    SSO_HOSTS = {
        "dev": "sso.dev-godaddy.com",
        "test": "sso.test-godaddy.com",
        "prod": "sso.godaddy.com",
    }
    if env not in SSO_HOSTS:
        raise ValueError(f"CaaS_JWT_ENV must be one of: {list(SSO_HOSTS.keys())}, got: {env!r}")

    client = AwsIamAuthTokenClient(
        SSO_HOSTS[env],
        refresh_min=60,
        primary_region="us-west-2",
    )
    return client.token


def _refresh_jwt_sync() -> None:
    """Update _jwt_token_refreshed with a new token from gd_auth. Called from background task."""
    global _jwt_token_refreshed, _jwt_last_refresh_at, _jwt_last_refresh_error
    if not CaaS_JWT_ENV:
        return
    try:
        _jwt_last_refresh_error = None
        token = _get_jwt_via_gd_auth(CaaS_JWT_ENV)
        _jwt_token_refreshed = token
        _jwt_last_refresh_at = time.time()
        logger.info("CaaS JWT refreshed successfully")
    except Exception as e:
        _jwt_last_refresh_error = str(e)
        logger.error("CaaS JWT refresh failed: %s", e)
        # Keep using previous token if refresh fails (may still be valid)


def get_llm_jwt() -> str:
    """Return the current JWT to use for upstream CaaS calls (manual or auto-refreshed)."""
    if CaaS_JWT_ENV:
        if _jwt_token_refreshed:
            return _jwt_token_refreshed
        # First run: refresh once synchronously so we have a token at startup
        _refresh_jwt_sync()
        if _jwt_token_refreshed:
            return _jwt_token_refreshed
        raise RuntimeError("CaaS JWT auto-refresh failed at startup. Check AWS credentials and CaaS_JWT_ENV.")
    if JWT_TOKEN_MANUAL:
        return JWT_TOKEN_MANUAL
    raise ValueError(
        "No JWT configured. Set JWT_TOKEN (manual) or CaaS_JWT_ENV (dev|test|prod) with gd_auth and AWS credentials."
    )


async def _jwt_refresh_loop() -> None:
    """Background task: refresh CaaS JWT periodically when using CaaS_JWT_ENV."""
    while CaaS_JWT_ENV:
        await asyncio.sleep(JWT_REFRESH_INTERVAL_SEC)
        # Run blocking gd_auth call in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _refresh_jwt_sync)


# Ensure at least one JWT source is configured
if not JWT_TOKEN_MANUAL and not CaaS_JWT_ENV:
    raise ValueError(
        "Set JWT_TOKEN (manual token) or CaaS_JWT_ENV (dev|test|prod for auto-refresh with gd_auth)."
    )


# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("llm-proxy")


# -----------------------------------------------------------------------------
# FastAPI app & health check
# -----------------------------------------------------------------------------

app = FastAPI(title="LLM Proxy")


@app.on_event("startup")
async def startup_jwt_refresh():
    """When using CaaS_JWT_ENV, refresh JWT once at startup and start background refresh loop."""
    if CaaS_JWT_ENV:
        # Initial refresh so first request has a token
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _refresh_jwt_sync)
        asyncio.create_task(_jwt_refresh_loop())
        logger.info("CaaS JWT auto-refresh enabled (env=%s, interval=%ss)", CaaS_JWT_ENV, JWT_REFRESH_INTERVAL_SEC)


@app.get("/health")
async def health():
    """Liveness/readiness check; returns status and current timestamp."""
    return {"status": "ok", "timestamp": int(time.time())}


@app.get("/jwt-status")
async def jwt_status():
    """
    Safe status for JWT config (no token value). Use to verify auto-refresh:
    - jwt_mode: manual | auto
    - token_ready: true if a token is available for upstream calls
    - last_refresh_sec_ago: (auto only) seconds since last refresh
    """
    now = time.time()
    if CaaS_JWT_ENV:
        return {
            "jwt_mode": "auto",
            "caas_env": CaaS_JWT_ENV,
            "token_ready": _jwt_token_refreshed is not None and len(_jwt_token_refreshed) > 0,
            "last_refresh_sec_ago": round(now - _jwt_last_refresh_at, 1) if _jwt_last_refresh_at else None,
            "refresh_interval_sec": JWT_REFRESH_INTERVAL_SEC,
            "last_refresh_error": _jwt_last_refresh_error,
        }
    return {
        "jwt_mode": "manual",
        "token_ready": bool(JWT_TOKEN_MANUAL),
        "last_refresh_sec_ago": None,
        "refresh_interval_sec": None,
    }


# -----------------------------------------------------------------------------
# Upstream LLM client
# -----------------------------------------------------------------------------

async def call_upstream(payload: dict):
    """
    POST the given chat payload to the upstream CaaS endpoint.

    Uses JWT from get_llm_jwt() in Authorization header. On 401, refreshes JWT once (if
    using CaaS_JWT_ENV) and retries. Returns (result_dict, status_code, error_text).
    """
    # Upstream is always called in non-streaming mode so we can parse and reshape the response.
    if payload.get("stream"):
        logger.info("STREAM REQUEST DETECTED → DISABLING STREAM")
        payload["stream"] = False

    logger.info("========== CALLING UPSTREAM ==========")
    logger.info("URL: %s", LLM_BASE_URL)
    logger.info(json.dumps(payload, indent=2)[:2000])

    def do_request(token: str):
        return {
            "Content-Type": "application/json",
            "Authorization": f"sso-jwt {token}",
        }

    token = get_llm_jwt()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                LLM_BASE_URL,
                json=payload,
                headers=do_request(token),
            )

            logger.info("========== UPSTREAM RESPONSE STATUS ==========")
            logger.info(response.status_code)

            if response.status_code == 401 and CaaS_JWT_ENV:
                logger.warning("Upstream returned 401 → refreshing JWT and retrying once")
                _refresh_jwt_sync()
                token = get_llm_jwt()
                response = await client.post(
                    LLM_BASE_URL,
                    json=payload,
                    headers=do_request(token),
                )
                logger.info("========== UPSTREAM RESPONSE STATUS (after retry) ==========")
                logger.info(response.status_code)

            if response.status_code != 200:
                logger.error("========== UPSTREAM ERROR ==========")
                logger.error(response.text[:2000] if response.text else "(empty)")
                return None, response.status_code, response.text

            try:
                result = response.json()
            except json.JSONDecodeError as e:
                logger.error("========== UPSTREAM RETURNED NON-JSON (e.g. 502 HTML) ==========")
                logger.error("Body preview: %s", (response.text or "")[:500])
                return None, 502, "Upstream returned invalid JSON (gateway error?). " + str(e)

            logger.info("========== UPSTREAM RESPONSE BODY ==========")
            logger.info(json.dumps(result, indent=2)[:2000] if result is not None else "(null)")

            # CaaS sometimes returns 200 with body "null" (no completion); treat as upstream error
            if result is None:
                logger.error("========== UPSTREAM RETURNED NULL BODY ==========")
                return None, 502, "Upstream returned null (no completion). Check CaaS model, budget, or quota."
            if not isinstance(result, dict) or "choices" not in result:
                logger.error("========== UPSTREAM RETURNED INVALID SHAPE ==========")
                return None, 502, "Upstream response missing 'choices'. Check CaaS."

            return result, 200, None

    except Exception as e:
        logger.error("========== UPSTREAM EXCEPTION ==========")
        logger.error("%s: %s", type(e).__name__, str(e))
        return None, 500, str(e)


# -----------------------------------------------------------------------------
# Chat completions (OpenAI-style; used by Agent Zero UI)
# -----------------------------------------------------------------------------

def _normalize_content(content: str) -> str:
    """Extract display text from upstream content (tool_args.text when present). Used for /v1/responses only; Agent Zero needs raw JSON."""
    if not (content or "").strip():
        return content or ""
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict) and "tool_args" in parsed:
            out = (parsed["tool_args"].get("text") or "").strip() or content
            if not (parsed["tool_args"].get("text") or "").strip():
                logger.info("tool_args.text missing or empty → using raw content for UI")
            return out
        return content
    except Exception:
        return content


async def _stream_completion_chunks(chunk_id: str, created: int, model: str, content: str):
    """Yield OpenAI-style SSE chunks for a single completion (simulated stream)."""
    # First chunk: role assistant (some clients expect it)
    yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"
    # Content chunk(s): send full content in one delta so client gets it all (we already have it)
    if content:
        yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {'content': content}, 'finish_reason': None}]})}\n\n"
    # Final chunk
    yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """
    OpenAI-style chat completions endpoint. Requires Bearer token matching
    PROXY_API_KEY. When client sends stream=true, returns SSE stream so Agent Zero
    UI can display the reply; otherwise returns a single JSON object.
    """
    logger.info("========== INCOMING /v1/chat/completions ==========")

    auth = request.headers.get("authorization", "")
    logger.info(f"Auth header: {auth}")

    if auth.replace("Bearer ", "").strip() != PROXY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    body = await request.json()

    logger.info("========== RAW REQUEST BODY ==========")
    logger.info(json.dumps(body, indent=2)[:2000])

    client_wants_stream = body.get("stream") is True
    # Upstream is always called non-streaming so we can normalize the response.
    body["stream"] = False

    result, status, error = await call_upstream(body)

    if status != 200 or not result:
        return JSONResponse(status_code=status, content={"error": error})

    content = result["choices"][0]["message"]["content"]

    logger.info("========== RAW MODEL CONTENT ==========")
    logger.info((content or "")[:1000])

    # Agent Zero expects the full JSON (thoughts, headline, tool_name, tool_args) to parse
    # as a valid tool request. Do not extract only tool_args.text — pass through raw content.
    output_text = content if content is not None else ""

    logger.info("========== FINAL OUTPUT (raw for Agent Zero) ==========")
    logger.info((output_text or "")[:1000])

    chunk_id = result.get("id") or f"chatcmpl-{int(time.time())}"
    created = result.get("created") or int(time.time())
    model = body.get("model") or "gpt-4o"

    if client_wants_stream:
        # Return SSE so Agent Zero UI receives a stream and displays the message.
        logger.info("Returning SSE stream to client")
        return StreamingResponse(
            _stream_completion_chunks(chunk_id, created, model, output_text),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    # Non-streaming: return single JSON object.
    response = {
        "id": chunk_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": output_text},
            }
        ],
    }
    logger.info("========== FINAL RESPONSE JSON ==========")
    logger.info(json.dumps(response, indent=2))
    return JSONResponse(status_code=200, content=response)


# -----------------------------------------------------------------------------
# Chat completions (no /v1 prefix) — alias for clients that omit the version
# -----------------------------------------------------------------------------

@app.post("/chat/completions")
async def chat_completions_no_v1(request: Request):
    """Same as /v1/chat/completions; forwards the request to the main handler."""
    logger.info("========== INCOMING /chat/completions ==========")
    return await chat_completions(request)


# -----------------------------------------------------------------------------
# Responses API (LiteLLM-style; useful for curl / simple integration tests)
# -----------------------------------------------------------------------------

@app.post("/v1/responses")
async def responses(request: Request):
    """
    LiteLLM-style responses endpoint: accepts { model, input } and returns
    { output_text, output: [...] }. Internally builds a single user message
    and calls the same upstream chat completions flow.
    """
    logger.info("========== INCOMING /v1/responses ==========")

    auth = request.headers.get("authorization", "")
    if auth.replace("Bearer ", "").strip() != PROXY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    body = await request.json()

    logger.info("========== RAW REQUEST BODY ==========")
    logger.info(json.dumps(body, indent=2)[:2000])

    model = body.get("model")
    input_data = body.get("input")

    # Single user message from the request input.
    messages = [
        {"role": "user", "content": str(input_data)}
    ]

    chat_payload = {
        "model": model,
        "messages": messages,
        "stream": False
    }

    result, status, error = await call_upstream(chat_payload)

    if status != 200 or not result:
        return JSONResponse(status_code=status, content={"error": error})

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, TypeError) as e:
        logger.error("========== UPSTREAM RESPONSE UNEXPECTED SHAPE ==========")
        logger.error("result keys: %s", list(result.keys()) if isinstance(result, dict) else type(result))
        return JSONResponse(
            status_code=502,
            content={"error": f"Upstream response missing choices/message/content. {e!s}"},
        )

    # For /v1/responses we want human-readable text (e.g. for curl); extract tool_args.text when present.
    output_text = _normalize_content(content or "")

    # If upstream returned only {"error": null} as content, surface a clearer message
    if (output_text or "").strip() in ("{\"error\": null}", '{"error": null}', "{\n  \"error\": null\n}"):
        logger.warning("Upstream CaaS returned content {\"error\": null} — check CaaS/model or budget")
        output_text = "Upstream returned no content (CaaS may have an error or budget limit). Check docker logs and CaaS status."

    # LiteLLM-style response shape: output_text + structured output array.
    litellm_response = {
        "id": result.get("id", f"resp-{int(time.time())}"),
        "object": "response",
        "type": "response",
        "created_at": int(time.time()),
        "model": body.get("model", "gpt-4o"),
        "output_text": output_text,
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "text",
                        "text": output_text
                    }
                ]
            }
        ]
    }

    logger.info("========== FINAL RESPONSE JSON ==========")
    logger.info(json.dumps(litellm_response, indent=2))

    return JSONResponse(status_code=200, content=litellm_response)
