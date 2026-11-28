"""Shared fixtures: a fake Ollama client on httpx.MockTransport (no Ollama, no network).

Plain helpers (Echo, ScriptedHandler, ask, chat_answer) live in `tests/llm_fakes.py`.
"""

from __future__ import annotations

import httpx
import pytest
from llm_fakes import ScriptedHandler, ask, chat_answer

from jobbot.config import LLMSettings
from jobbot.llm.client import LLMError, LLMTimeout, OllamaClient


@pytest.fixture
def llm_settings() -> LLMSettings:
    # Non-default values, so message checks can't pass on the defaults. `think` keeps its
    # default ("low"), so the no-think retry path is reachable.
    return LLMSettings(model="test-model:1b", timeout_s=12.5)


@pytest.fixture
def make_client(llm_settings):
    """Factory: an OllamaClient whose HTTP layer is `httpx.MockTransport(handler)`."""
    clients: list[OllamaClient] = []

    def make(handler, settings: LLMSettings | None = None) -> OllamaClient:
        client = OllamaClient(settings or llm_settings, transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


def _error_from(client: OllamaClient) -> LLMError:
    try:
        ask(client)
    except LLMError as e:
        return e
    raise AssertionError("expected the fake client to raise an LLMError")


@pytest.fixture
def timeout_error(make_client) -> LLMTimeout:
    """The real exception the client raises when Ollama times out."""
    error = _error_from(make_client(ScriptedHandler(httpx.ReadTimeout)))
    assert type(error) is LLMTimeout
    return error


@pytest.fixture
def invalid_json_error(make_client) -> LLMError:
    """The real per-job error the client raises after two invalid JSON answers."""
    error = _error_from(make_client(ScriptedHandler(chat_answer("not json"))))
    assert type(error) is LLMError
    return error
