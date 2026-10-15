import asyncio
import json
import sys
from http.cookies import SimpleCookie
from pathlib import Path

import pytest
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import staff_access as staff


TOKEN = "test-only-staff-token-for-access-tests"


@pytest.fixture(autouse=True)
def configured_staff(monkeypatch):
    monkeypatch.setenv("STAFF_ACCESS_TOKEN", TOKEN)
    monkeypatch.delenv("VERCEL", raising=False)
    staff._attempts.clear()


def request(method="GET", body=None, *, cookie=None, origin="https://example.test", raw=None, extra_headers=None):
    data = json.dumps(body).encode() if raw is None and body is not None else raw or b""
    headers = {"host": "example.test", "content-type": "application/json"}
    if origin is not None:
        headers["origin"] = origin
    if cookie:
        headers["cookie"] = f"{staff.COOKIE_NAME}={cookie}"
    headers.update(extra_headers or {})
    scope = {"type": "http", "method": method, "scheme": "https", "path": "/api/staff/session",
             "raw_path": b"/api/staff/session", "query_string": b"", "server": ("example.test", 443),
             "client": ("127.0.0.1", 12345), "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": data, "more_body": False}

    return Request(scope, receive)


def session(*args, **kwargs):
    return asyncio.run(staff.staff_session(request(*args, **kwargs)))


def payload(response):
    return json.loads(response.body)


def login_cookie():
    response = session("POST", {"token": TOKEN})
    assert response.status_code == 200
    parsed = SimpleCookie()
    parsed.load(response.headers["set-cookie"])
    return parsed[staff.COOKIE_NAME].value


def test_disabled_staff_fails_closed(monkeypatch):
    monkeypatch.delenv("STAFF_ACCESS_TOKEN")
    for response in [session(), session("POST", {"token": TOKEN}), staff.require_staff(request())]:
        assert response.status_code == 503
        assert payload(response)["configured"] is False
        assert payload(response)["authorized"] is False
        assert payload(response)["mode"] == "disabled"


def test_anonymous_and_custom_llm_key_cannot_authorize_tools():
    response = staff.require_staff(request("POST", extra_headers={"x-thaillm-api-key": TOKEN}))
    assert response.status_code == 401
    assert payload(session())["authorized"] is False


def test_incorrect_token_never_sets_a_cookie_or_returns_secret():
    response = session("POST", {"token": "wrong-token"})
    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert TOKEN not in response.body.decode()
    assert "wrong-token" not in response.body.decode()


def test_valid_login_sets_http_only_secure_strict_cookie_and_authorizes():
    response = session("POST", {"token": TOKEN})
    assert payload(response) == {"configured": True, "authorized": True, "mode": "staff"}
    assert TOKEN not in response.body.decode()
    assert TOKEN not in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=/api", f"Max-Age={staff.SESSION_SECONDS}"):
        assert attribute in response.headers["set-cookie"]
    cookie = login_cookie()
    assert payload(session(cookie=cookie))["authorized"] is True
    assert staff.require_staff(request("POST", cookie=cookie)) is None


def test_tampered_expired_and_rotated_sessions_fail(monkeypatch):
    clock = 1_800_000_000
    monkeypatch.setattr(staff.time, "time", lambda: clock)
    cookie = login_cookie()
    assert staff.require_staff(request(cookie=cookie)) is None
    tampered = cookie[:-1] + ("0" if cookie[-1] != "0" else "1")
    assert staff.require_staff(request(cookie=tampered)).status_code == 401
    clock += staff.SESSION_SECONDS
    assert staff.require_staff(request(cookie=cookie)).status_code == 401
    clock -= staff.SESSION_SECONDS
    monkeypatch.setenv("STAFF_ACCESS_TOKEN", "new-token")
    assert staff.require_staff(request(cookie=cookie)).status_code == 401


def test_logout_expires_cookie():
    cookie = login_cookie()
    response = session("DELETE", cookie=cookie)
    assert payload(response)["authorized"] is False
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]


@pytest.mark.parametrize("origin", [None, "null", "https://attacker.test", "http://example.test", "https://example.test/", "https://example.test:444"])
def test_mutations_require_exact_same_origin(origin):
    assert session("POST", {"token": TOKEN}, origin=origin).status_code == 403
    assert session("DELETE", origin=origin).status_code == 403
    cookie = login_cookie()
    assert staff.require_staff(request("POST", cookie=cookie, origin=origin)).status_code == 403


@pytest.mark.parametrize("body", [{}, [], {"token": None}, {"token": 123}, {"token": ""}, {"token": "x" * (staff.MAX_TOKEN_BYTES + 1)}])
def test_invalid_token_shapes_are_rejected(body):
    assert session("POST", body).status_code == 400


def test_json_body_is_bounded_and_invalid_json_has_safe_response():
    assert session("POST", raw=b"x" * (staff.MAX_BODY_BYTES + 1)).status_code == 413
    assert session("POST", raw=b"{}", extra_headers={"content-length": str(staff.MAX_BODY_BYTES + 1)}).status_code == 413
    assert session("POST", raw=b"{").status_code == 400
    assert session("POST", {"token": TOKEN}, extra_headers={"content-type": "text/plain"}).status_code == 415


def test_login_attempts_are_throttled_and_window_recovers(monkeypatch):
    clock = 123.0
    monkeypatch.setattr(staff.time, "monotonic", lambda: clock)
    for _ in range(staff.LOGIN_ATTEMPTS):
        assert session("POST", {"token": "bad"}).status_code == 401
    response = session("POST", {"token": TOKEN})
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0
    clock += staff.LOGIN_WINDOW_SECONDS
    assert session("POST", {"token": TOKEN}).status_code == 200


def test_vercel_cookie_is_secure_even_behind_tls_termination(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    req = request("POST", {"token": TOKEN})
    req.scope["scheme"] = "http"
    req.scope["server"] = ("example.test", 80)
    response = asyncio.run(staff.staff_session(req))
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]
