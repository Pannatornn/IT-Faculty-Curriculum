import asyncio
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from starlette.testclient import TestClient

import render_app_v2 as legacy
import render_chat_app as chat
import render_server as core
from competition_ai.models import AnswerResult


class PublicPipeline:
    def ask(self, question, forced_program=None):
        return AnswerResult(status="SUPPORTED", answer="Curriculum answer", programs=[forced_program or "AIT"])

    def compare(self, question, programs, focus):
        return AnswerResult(status="SUPPORTED", answer="Comparison answer", programs=programs)

    def _ensure_answer_language(self, question, result):
        return result


@pytest.fixture
def public_api(monkeypatch):
    pipeline = PublicPipeline()
    monkeypatch.setattr(core, "limited", lambda *args, **kwargs: None)
    monkeypatch.setattr(legacy, "resilient_pipe", lambda request: pipeline)
    monkeypatch.setattr(core, "pipe", lambda request: pipeline)
    monkeypatch.setattr(
        core, "request_settings", lambda request: SimpleNamespace(api_key="test-key", model="test-model")
    )
    with TestClient(chat.app) as client:
        yield client, pipeline


@pytest.mark.parametrize("route", ["/api/ask", "/api/compare", "/api/health"])
def test_slow_public_worker_does_not_block_other_requests(public_api, monkeypatch, route):
    _, pipeline = public_api
    started = threading.Event()
    release = threading.Event()

    def slow_result(*args, **kwargs):
        started.set()
        if not release.wait(2):
            raise RuntimeError("concurrency probe did not release the worker")
        if route == "/api/health":
            return SimpleNamespace(status_code=200)
        return AnswerResult(status="SUPPORTED", answer="Completed worker", programs=["AIT"])

    if route == "/api/ask":
        monkeypatch.setattr(pipeline, "ask", slow_result)
    elif route == "/api/compare":
        monkeypatch.setattr(pipeline, "compare", slow_result)
    else:
        monkeypatch.setattr(core.requests, "get", slow_result)

    async def probe():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=chat.app), base_url="http://testserver"
        ) as client:
            if route == "/api/health":
                worker = asyncio.create_task(client.get(route))
            else:
                payload = {"question": "AIT credits?"} if route == "/api/ask" else {
                    "left": "AIT", "right": "DSBA", "focus": "credits"
                }
                worker = asyncio.create_task(client.post(route, json=payload))
            try:
                assert await asyncio.to_thread(started.wait, 1)
                assert not worker.done(), "synchronous work blocked the event loop until completion"
                probe_response = await asyncio.wait_for(client.get("/healthz"), timeout=0.25)
                assert probe_response.status_code == 200
                assert not worker.done()
            finally:
                release.set()
                response = await worker
            assert response.status_code == 200

    asyncio.run(probe())


@pytest.mark.parametrize("route", ["/api/ask", "/api/compare"])
def test_public_query_worker_has_retryable_timeout(public_api, monkeypatch, route):
    client, pipeline = public_api
    monkeypatch.setattr(core, "PUBLIC_QUERY_TIMEOUT_SECONDS", 0.01)

    def slow_result(*args, **kwargs):
        time.sleep(0.08)
        return AnswerResult(status="SUPPORTED", answer="Late answer", programs=["AIT"])

    monkeypatch.setattr(pipeline, "ask" if route == "/api/ask" else "compare", slow_result)
    payload = {"question": "AIT credits?"} if route == "/api/ask" else {
        "left": "AIT", "right": "DSBA", "focus": "credits"
    }
    response = client.post(route, json=payload)
    assert response.status_code == 504
    assert response.json()["type"] == "TIMEOUT"
    assert response.json()["retryable"] is True


@pytest.mark.parametrize("route", ["/api/ask", "/api/compare"])
def test_upstream_exception_retains_existing_nonempty_fallback(public_api, monkeypatch, route):
    client, pipeline = public_api

    def failing_result(*args, **kwargs):
        raise RuntimeError("upstream temporarily unavailable")

    monkeypatch.setattr(pipeline, "ask" if route == "/api/ask" else "compare", failing_result)
    payload = {"question": "AIT credits?"} if route == "/api/ask" else {
        "left": "AIT", "right": "DSBA", "focus": "credits"
    }
    response = client.post(route, json=payload)
    assert response.status_code == 200
    assert response.json()["degraded"] is True
    assert response.json()["answer"].strip()


@pytest.mark.parametrize("route", ["/api/ask", "/api/compare"])
@pytest.mark.parametrize("body", ["{", "[]", '"question"'])
def test_malformed_and_nonobject_bodies_are_bad_requests(public_api, route, body):
    client, _ = public_api
    response = client.post(route, content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 400


@pytest.mark.parametrize("question", [False, {}, "x" * 4001])
def test_public_ask_rejects_invalid_question(public_api, question):
    client, _ = public_api
    assert client.post("/api/ask", json={"question": question}).status_code == 400


@pytest.mark.parametrize("field,value", [("left", []), ("right", "unknown"), ("focus", {}), ("focus", "x" * 4001)])
def test_public_compare_rejects_invalid_scope_or_focus(public_api, field, value):
    client, _ = public_api
    payload = {"left": "AIT", "right": "DSBA", "focus": "credits"}
    payload[field] = value
    assert client.post("/api/compare", json=payload).status_code == 400
