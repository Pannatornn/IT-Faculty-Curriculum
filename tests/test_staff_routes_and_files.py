import base64
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import render_chat_app as chat
from competition_ai.models import AnswerResult
from staff_access import _attempts


ROOT = Path(__file__).resolve().parents[1]
TEST_TOKEN = "test-only-staff-token-not-a-production-secret"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("STAFF_ACCESS_TOKEN", TEST_TOKEN)
    monkeypatch.delenv("VERCEL", raising=False)
    chat.core.REQ.clear()
    _attempts.clear()
    with TestClient(chat.app) as c:
        yield c


def unlock(client):
    response = client.post("/api/staff/session", headers={"Origin": "http://testserver"}, json={"token": TEST_TOKEN})
    assert response.status_code == 200
    assert response.json()["authorized"] is True


@pytest.mark.parametrize("path", ["/api/import-questions", "/api/run-batch", "/api/benchmark"])
def test_actual_staff_routes_reject_public_requests_even_with_upstream_key(client, path):
    response = client.post(path, headers={"X-ThaiLLM-API-Key": "not-a-staff-token"}, json={})
    assert response.status_code == 401
    assert response.json()["authorized"] is False


@pytest.mark.parametrize("filename", ["data/evaluation/Easy.xlsx", "knowledge/question_sets/hard_hard10_blank.csv"])
def test_imports_real_repository_question_files_after_staff_login(client, filename):
    unlock(client)
    path = ROOT / filename
    response = client.post("/api/import-questions", headers={"Origin": "http://testserver"}, json={
        "filename": path.name, "contentBase64": base64.b64encode(path.read_bytes()).decode("ascii"),
    })
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 10
    assert len(data["rowNumbers"]) == 10
    assert all(isinstance(q, str) and q.strip() for q in data["questions"])
    assert data["header"].casefold() == "question"


def test_batch_returns_clean_answer_and_retry_metadata(client, monkeypatch):
    unlock(client)
    class Pipeline:
        def ask(self, question):
            if question == "retry":
                return AnswerResult(status="RETRY_REQUIRED", answer="Please retry")
            return AnswerResult(status="SUPPORTED", answer="120 credits [E1].\nEVIDENCE:\n[E1] ID=FACT-AIT-1\nSOURCE=AIT.pdf")
    monkeypatch.setattr(chat.legacy, "resilient_pipe", lambda req: Pipeline())
    response = client.post("/api/run-batch", headers={"Origin": "http://testserver"}, json={"questions": ["AIT credits", "retry"]})
    assert response.status_code == 200
    rows = response.json()["rows"]
    assert rows[0]["answer"] == "120 credits [E1]."
    assert rows[0]["degraded"] is False
    assert rows[1]["degraded"] is True
    assert response.json()["blankAnswers"] == 0


def test_staff_mutation_rejects_cross_site_request_with_valid_cookie(client):
    unlock(client)
    response = client.post("/api/import-questions", headers={"Origin": "https://evil.example"}, json={})
    assert response.status_code == 403


@pytest.mark.parametrize("payload", [[], {}, {"questions": "AIT"}, {"questions": []}, {"questions": [None]}, {"questions": [123]}, {"questions": [{}]}, {"questions": ["x" * 4001]}])
def test_invalid_batch_schema_never_reaches_pipeline(client, monkeypatch, payload):
    unlock(client)
    monkeypatch.setattr(chat.legacy, "resilient_pipe", lambda req: pytest.fail("Invalid input must not call the pipeline"))
    response = client.post("/api/run-batch", headers={"Origin": "http://testserver"}, json=payload)
    assert response.status_code == 400


def test_invalid_batch_json_returns_400(client):
    unlock(client)
    response = client.post("/api/run-batch", headers={"Origin": "http://testserver", "Content-Type": "application/json"}, content="{")
    assert response.status_code == 400


def test_original_documents_are_real_pdf_and_support_inline_range(client):
    response = client.get("/documents/AIT.pdf", headers={"Range": "bytes=0-15"})
    assert response.status_code == 206
    assert response.content.startswith(b"%PDF-")
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.head("/documents/IT2565.pdf").status_code == 200
    assert client.get("/documents/.env").status_code == 404
    assert client.get("/documents/unknown.pdf").status_code == 404


def test_staff_tools_fail_closed_when_unconfigured(client, monkeypatch):
    monkeypatch.delenv("STAFF_ACCESS_TOKEN")
    assert client.get("/api/staff/session").status_code == 503
    assert client.post("/api/run-batch", json={"questions": ["AIT credits"]}).status_code == 503
