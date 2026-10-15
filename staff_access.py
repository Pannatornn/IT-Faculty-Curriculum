"""Server-side, fail-closed access to the optional staff tools.

The ThaiLLM key is an upstream credential, never an authorization credential.
Sessions contain an expiry and nonce signed with the independently configured
STAFF_ACCESS_TOKEN. No token is sent back to the browser or written to disk.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import OrderedDict
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse


COOKIE_NAME = "curriculum_staff_session"
SESSION_SECONDS = 8 * 60 * 60
MAX_BODY_BYTES = 8192
MAX_TOKEN_BYTES = 4096
LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 10 * 60
MAX_RATE_LIMIT_ENTRIES = 1024
_attempts: OrderedDict[str, tuple[float, int]] = OrderedDict()
_attempts_lock = threading.Lock()


def _secret() -> str:
    token = os.getenv("STAFF_ACCESS_TOKEN", "").strip()
    return token if len(token.encode("utf-8")) <= MAX_TOKEN_BYTES else ""


def _response(configured: bool, authorized: bool = False, *, status: int = 200,
              error: str | None = None, retry_after: int | None = None) -> JSONResponse:
    payload: dict[str, object] = {
        "configured": configured,
        "authorized": authorized,
        "mode": "staff" if configured else "disabled",
    }
    if error:
        payload["error"] = error
    headers = {"Cache-Control": "no-store", "Vary": "Cookie", "X-Content-Type-Options": "nosniff"}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(payload, status_code=status, headers=headers)


def _same_origin(req: Request) -> bool:
    """Reject cross-site and missing-Origin mutations, including form posts."""
    origin = req.headers.get("origin", "")
    if not origin or origin == "null":
        return False
    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return False
        if parsed.path or parsed.query or parsed.fragment:
            return False
        expected = urlsplit(str(req.url))
        # Vercel may terminate TLS before the ASGI runtime. The Host must still
        # match; forwarded host headers are intentionally not accepted here.
        expected_scheme = "https" if os.getenv("VERCEL") else expected.scheme
        default = lambda scheme: 443 if scheme == "https" else 80
        return (
            parsed.scheme == expected_scheme
            and parsed.hostname == expected.hostname
            and (parsed.port or default(parsed.scheme)) == (expected.port or default(expected_scheme))
        )
    except ValueError:
        return False


def _secure_cookie(req: Request) -> bool:
    return bool(os.getenv("VERCEL")) or req.url.scheme == "https"


def _signature(value: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), ("staff-session:" + value).encode("ascii"), hashlib.sha256).hexdigest()


def _session_valid(req: Request, secret: str) -> bool:
    cookie = req.cookies.get(COOKIE_NAME, "")
    if len(cookie) > 256:
        return False
    try:
        version, expires, nonce, signature = cookie.split(".")
        if version != "v1" or not expires.isascii() or not expires.isdigit():
            return False
        expiry = int(expires)
        now = int(time.time())
        if expiry <= now or expiry > now + SESSION_SECONDS:
            return False
        if len(nonce) != 32 or not all(c in "0123456789abcdef" for c in nonce):
            return False
        if len(signature) != 64 or not all(c in "0123456789abcdef" for c in signature):
            return False
        value = f"{version}.{expires}.{nonce}"
        return hmac.compare_digest(signature, _signature(value, secret))
    except (ValueError, UnicodeError):
        return False


def _login_retry_after(req: Request) -> int | None:
    """Bounded process-local throttle, independent of the supplied token."""
    key = req.client.host if req.client else "unknown"
    now = time.monotonic()
    with _attempts_lock:
        for old_key, (started, _) in list(_attempts.items()):
            if now - started >= LOGIN_WINDOW_SECONDS:
                _attempts.pop(old_key, None)
        started, count = _attempts.get(key, (now, 0))
        if count >= LOGIN_ATTEMPTS:
            return max(1, int(LOGIN_WINDOW_SECONDS - (now - started)) + 1)
        _attempts[key] = (started, count + 1)
        _attempts.move_to_end(key)
        while len(_attempts) > MAX_RATE_LIMIT_ENTRIES:
            _attempts.popitem(last=False)
    return None


def require_staff(req: Request) -> JSONResponse | None:
    """Return an error response unless a valid staff cookie permits this request."""
    secret = _secret()
    if not secret:
        return _response(False, status=503, error="Staff tools are not configured.")
    if not _session_valid(req, secret):
        return _response(True, status=401, error="Staff sign-in is required.")
    if req.method not in {"GET", "HEAD", "OPTIONS"} and not _same_origin(req):
        return _response(True, status=403, error="A same-origin request is required.")
    return None


async def staff_session(req: Request) -> JSONResponse:
    """Handle GET/POST/DELETE /api/staff/session (register all three methods)."""
    secret = _secret()
    if req.method == "GET":
        if not secret:
            return _response(False, status=503, error="Staff tools are not configured.")
        return _response(True, _session_valid(req, secret))
    if req.method not in {"POST", "DELETE"}:
        return _response(bool(secret), status=405, error="Method not allowed.")
    if not _same_origin(req):
        return _response(bool(secret), status=403, error="A same-origin request is required.")
    if req.method == "DELETE":
        response = _response(bool(secret))
        response.delete_cookie(COOKIE_NAME, path="/api", secure=_secure_cookie(req), httponly=True, samesite="strict")
        return response
    if not secret:
        return _response(False, status=503, error="Staff tools are not configured.")
    if retry_after := _login_retry_after(req):
        return _response(True, status=429, error="Too many sign-in attempts. Try again later.", retry_after=retry_after)
    if req.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _response(True, status=415, error="Use application/json.")
    try:
        if int(req.headers.get("content-length", "0")) > MAX_BODY_BYTES:
            return _response(True, status=413, error="Request is too large.")
        raw = bytearray()
        async for chunk in req.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY_BYTES:
                return _response(True, status=413, error="Request is too large.")
        body = json.loads(raw)
        token = body.get("token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token.strip() or len(token.encode("utf-8")) > MAX_TOKEN_BYTES:
            return _response(True, status=400, error="A valid token string is required.")
    except (ValueError, UnicodeError):
        return _response(True, status=400, error="Invalid JSON request.")
    if not hmac.compare_digest(token.strip().encode("utf-8"), secret.encode("utf-8")):
        return _response(True, status=401, error="The staff token is incorrect.")
    value = f"v1.{int(time.time()) + SESSION_SECONDS}.{secrets.token_hex(16)}"
    response = _response(True, True)
    response.set_cookie(COOKIE_NAME, f"{value}.{_signature(value, secret)}", max_age=SESSION_SECONDS,
                        path="/api", secure=_secure_cookie(req), httponly=True, samesite="strict")
    return response
