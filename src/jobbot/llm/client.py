"""Minimal Ollama client that always returns schema-validated JSON."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from jobbot.config import LLMSettings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """The local model could not be reached or did not return valid output."""


class LLMUnavailable(LLMError):
    """Ollama is down, the model is missing, it cannot load (e.g. out of memory), or a call
    timed out (`LLMTimeout`). Retrying other jobs is pointless; callers should stop."""


class LLMTimeout(LLMUnavailable):
    """An Ollama call timed out (connect, read, write or pool). Treated like
    LLMUnavailable: the model is almost always stuck, still loading or too slow,
    so callers stop instead of failing every remaining job. No retry."""


@dataclass
class LLMCallInfo:
    model: str
    latency_s: float
    attempts: int
    prompt_tokens: int | None = None
    output_tokens: int | None = None


class OllamaClient:
    def __init__(
        self, settings: LLMSettings, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        # `transport` is a test seam (e.g. httpx.MockTransport); None = httpx's normal transport.
        self.settings = settings
        self._http = httpx.Client(
            base_url=settings.base_url, timeout=settings.timeout_s, transport=transport
        )

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def chat_json(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        schema: dict[str, Any] | None = None,
        max_attempts: int = 2,
    ) -> tuple[T, LLMCallInfo]:
        """Ask the model for JSON matching `schema` and validate it into `output_model`.

        Retries once (slightly warmer) on invalid output, then raises LLMError. Never guesses.
        """
        s = self.settings
        payload: dict[str, Any] = {
            "model": s.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema or output_model.model_json_schema(),
            "stream": False,
            "options": {"temperature": s.temperature, "num_ctx": s.num_ctx},
        }
        if s.think is not None:
            payload["think"] = s.think

        start = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                payload["options"]["temperature"] = max(s.temperature, 0.3)
            data = self._post(payload)
            content = (data.get("message") or {}).get("content", "")
            try:
                parsed = output_model.model_validate_json(content)
            except ValidationError as e:
                last_error = e
                continue
            return parsed, LLMCallInfo(
                model=s.model,
                latency_s=round(time.perf_counter() - start, 2),
                attempts=attempt,
                prompt_tokens=data.get("prompt_eval_count"),
                output_tokens=data.get("eval_count"),
            )
        raise LLMError(f"Model returned invalid JSON after {max_attempts} attempts: {last_error}")

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        s = self.settings
        try:
            r = self._http.post("/api/chat", json=payload)
        except httpx.ConnectError as e:
            raise LLMUnavailable(
                f"Cannot reach Ollama at {s.base_url}. Is it running? (`ollama serve`)"
            ) from e
        except httpx.TimeoutException as e:
            # Stop-the-run error, not per-job: a timeout almost always means the model is stuck.
            # Keep "[" out of this message: cli._fail prints it as Rich markup.
            raise LLMTimeout(
                f"Ollama timed out after {s.timeout_s:g}s (model {s.model})."
                " The model may be stuck, still loading or too slow for this machine."
                " Try a smaller model (jobbot --model <name> ...)"
                " or a larger llm.timeout_s in config/settings.yaml."
            ) from e
        if r.status_code == 400 and "think" in payload and "thinking" in r.text.lower():
            # Model has no thinking mode (e.g. llama3.2): retry once without the option.
            payload.pop("think")
            return self._post(payload)
        if r.status_code != 200:
            raise LLMUnavailable(f"Ollama error {r.status_code}: {r.text[:300]}")
        return r.json()
