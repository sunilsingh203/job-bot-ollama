"""Shared test helpers: a fake Ollama client on httpx.MockTransport (no Ollama, no network)."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from jobbot.config import LLMSettings
from jobbot.llm.client import LLMError, LLMTimeout, OllamaClient


class Echo(BaseModel):
    """A tiny output model for `OllamaClient.chat_json`."""

    ok: bool


def chat_answer(content: str) -> httpx.Response:
    """A 200 answer from Ollama's /api/chat whose message content is `content`."""
    return httpx.Response(
        200, json={"message": {"content": content}, "prompt_eval_count": 7, "eval_count": 3}
    )


class ScriptedHandler:
    """MockTransport handler that answers requests in order from a script.

    Each step is an `httpx.Response` (returned) or an httpx exception class (raised, like a real
    transport error). The last step repeats. Every request is recorded in `calls` (JSON body)
    and `urls`.
    """

    def __init__(self, *steps: httpx.Response | type[httpx.TransportError]) -> None:
        self.steps = list(steps)
        self.calls: list[dict] = []
        self.urls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(json.loads(request.content))
        self.urls.append(str(request.url))
        step = self.steps[min(len(self.calls), len(self.steps)) - 1]
        if isinstance(step, type):
            raise step("simulated by the test", request=request)
        # A fresh copy, so a repeated step never reuses a consumed response.
        return httpx.Response(step.status_code, headers=step.headers, content=step.content)


def ask(client: OllamaClient):
    """One `chat_json` call with throwaway prompts."""
    return client.chat_json(system="s", user="u", output_model=Echo)


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
