# ADR-0001: Local-only LLM via Ollama, no cloud APIs

**Status:** Accepted, 2026-11-26

## Context
jobbot sends resumes (or summaries of them), the candidate's facts and job descriptions to an LLM
on every decision. That is personal data. The developer wants it to stay on the machine. The
machine has an RTX 4050 with 6 GB VRAM and ~22 GB RAM, so large models run mostly on the CPU
and are slow.

## Options
1. **Cloud LLM API** (OpenAI, Anthropic, Gemini): fast and accurate, but personal data leaves
   the machine, it costs money per call, and it needs API keys (secrets to manage).
2. **Local LLM via Ollama**: data stays local, no keys, free per call. Slower, and small models
   are less reliable. Ollama supports JSON-schema structured output.
3. **Local LLM via another runtime** (llama.cpp server, vLLM, LM Studio): similar privacy;
   more setup, and vLLM doesn't suit Windows with 6 GB VRAM.

## Decision
Use **Ollama only**, at `http://localhost:11434`, with `gpt-oss:20b` as the default model. The
model name is a setting (`llm.model`, or `jobbot --model`) so a smaller model can replace it. No
cloud LLM APIs, analytics or telemetry anywhere in the project.

## Consequences
- Decisions are slow (the 20B model runs mostly on CPU). Calls run one at a time; prompts stay
  short (resume summaries, truncated JDs); scan and decide are separate commands.
- Every decision call uses structured output (JSON schema) plus pydantic validation, retries once
  and then fails, because local models make more format mistakes.
- Model loading can fail for local reasons (e.g. the page-file out-of-memory issue in `CLAUDE.md`);
  `LLMUnavailable` stops the run instead of failing every job.
- Accuracy must be measured locally (`jobbot eval`) whenever the model or prompt changes.
- Adding a cloud provider would reverse this ADR and break a non-negotiable rule; it needs the
  developer's explicit decision and a new ADR.
