"""Fake Ollama pieces for tests: an httpx.MockTransport script (no Ollama, no network).

Plain helpers live here so test modules import them like `tests/fakes.py`; pytest fixtures that
use them stay in `conftest.py`.
"""

from __future__ import annotations

import json

import httpx
from pydantic import BaseModel

from jobbot.llm.client import OllamaClient


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
