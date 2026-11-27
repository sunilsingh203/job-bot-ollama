"""OllamaClient error classification, with a fake HTTP layer (no Ollama, no network).

Each error type is chosen by its effect on the whole decide run: `LLMUnavailable` (including
`LLMTimeout`) stops the run; a plain `LLMError` (invalid JSON) fails only that job.
"""

import httpx
import pytest
from conftest import Echo, ScriptedHandler, ask, chat_answer

from jobbot.llm.client import LLMError, LLMTimeout, LLMUnavailable


def test_valid_answer_returns_parsed_model(make_client):
    handler = ScriptedHandler(chat_answer('{"ok": true}'))
    parsed, info = ask(make_client(handler))
    assert parsed == Echo(ok=True)
    assert info.model == "test-model:1b" and info.attempts == 1
    assert info.prompt_tokens == 7 and info.output_tokens == 3
    assert handler.urls == ["http://localhost:11434/api/chat"]
    body = handler.calls[0]
    assert body["model"] == "test-model:1b"
    assert body["stream"] is False
    assert body["format"] == Echo.model_json_schema()


@pytest.mark.parametrize(
    "timeout", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout]
)
def test_timeout_raises_llm_timeout(make_client, timeout):
    handler = ScriptedHandler(timeout)
    with pytest.raises(LLMTimeout) as raised:
        ask(make_client(handler))
    error = raised.value
    assert isinstance(error, LLMUnavailable) and isinstance(error, LLMError)
    assert isinstance(error.__cause__, timeout)
    assert len(handler.calls) == 1  # no retry after a timeout
    message = str(error)
    assert "test-model:1b" in message and "12.5s" in message
    assert "--model" in message and "llm.timeout_s" in message  # the hint
    assert "[" not in message  # cli._fail prints it as Rich markup


def test_timeout_on_second_attempt_after_invalid_json(make_client):
    handler = ScriptedHandler(chat_answer("not json"), httpx.ReadTimeout)
    with pytest.raises(LLMTimeout) as raised:
        ask(make_client(handler))
    assert "invalid JSON" not in str(raised.value)
    assert len(handler.calls) == 2


def test_timeout_on_no_think_retry(make_client):
    no_thinking = httpx.Response(400, json={"error": '"test-model:1b" does not support thinking'})
    handler = ScriptedHandler(no_thinking, httpx.ReadTimeout)
    with pytest.raises(LLMTimeout):
        ask(make_client(handler))
    assert len(handler.calls) == 2
    assert "think" in handler.calls[0] and "think" not in handler.calls[1]


def test_invalid_json_twice_is_per_job_error(make_client):
    handler = ScriptedHandler(chat_answer("not json"))
    with pytest.raises(LLMError) as raised:
        ask(make_client(handler))
    assert not isinstance(raised.value, LLMUnavailable)  # fails one job, doesn't stop the run
    assert "invalid JSON after 2 attempts" in str(raised.value)
    assert len(handler.calls) == 2


def test_connect_error_is_unavailable(make_client):
    handler = ScriptedHandler(httpx.ConnectError)
    with pytest.raises(LLMUnavailable) as raised:
        ask(make_client(handler))
    assert not isinstance(raised.value, LLMTimeout)
    assert "Cannot reach Ollama" in str(raised.value)
    assert len(handler.calls) == 1


def test_non_200_is_unavailable(make_client):
    handler = ScriptedHandler(httpx.Response(500, text="model failed to load: out of memory"))
    with pytest.raises(LLMUnavailable) as raised:
        ask(make_client(handler))
    assert not isinstance(raised.value, LLMTimeout)
    assert "Ollama error 500" in str(raised.value)
    assert len(handler.calls) == 1
