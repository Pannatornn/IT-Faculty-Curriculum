from dataclasses import replace
import time

import pytest

from competition_ai.config import SETTINGS
from competition_ai.llm import ThaiLLMClient, ThaiLLMError


def test_expired_budget_does_not_start_another_upstream_call(monkeypatch):
    calls = []
    monkeypatch.setattr("competition_ai.llm.requests.post", lambda *args, **kwargs: calls.append(kwargs))
    client = ThaiLLMClient(replace(SETTINGS, api_key="test-key", request_deadline=time.monotonic() - 1))
    with pytest.raises(ThaiLLMError, match="time limit"):
        client.generate("system", "question")
    assert calls == []


def test_each_upstream_timeout_is_bounded_by_remaining_request_budget(monkeypatch):
    timeouts = []
    class Reply:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "answer"}}]}
    def post(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return Reply()
    monkeypatch.setattr("competition_ai.llm.requests.post", post)
    client = ThaiLLMClient(replace(SETTINGS, api_key="test-key", timeout=120, request_deadline=time.monotonic() + 2))
    assert client.generate("system", "question") == "answer"
    assert 0 < timeouts[0] <= 2
