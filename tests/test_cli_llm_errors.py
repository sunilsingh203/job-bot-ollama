"""CLI behaviour when Ollama times out (no Ollama, no network, no real data/)."""

from types import SimpleNamespace

import httpx
import pytest
from conftest import ScriptedHandler, ask
from rich.console import Console
from typer.testing import CliRunner

from jobbot import cli
from jobbot.config import Settings
from jobbot.db import JobStore
from jobbot.llm.client import OllamaClient
from jobbot.models import Decision, Job

runner = CliRunner()


def _listing(jk: str) -> Job:
    return Job(
        title="Java Developer",
        company="Acme",
        location="Pune",
        description="",
        platform="indeed",
        job_key=jk,
        easy_apply=True,
        url=f"https://in.indeed.com/viewjob?jk={jk}",
    )


def _counts(settings: Settings) -> dict[str, int]:
    with JobStore(settings.data_dir / "jobs.db") as store:
        return store.counts()


@pytest.fixture
def settings(tmp_path, monkeypatch, llm_settings) -> Settings:
    """Settings pointing at tmp_path, a wide colourless console, and a fake-LLM factory."""
    s = Settings(
        llm=llm_settings,
        data_dir=tmp_path,
        resumes_dir=tmp_path / "resumes",
        config_dir=tmp_path / "config",
    )
    monkeypatch.setattr(cli, "load_settings", lambda: s)
    # Wide and colourless, so long messages are neither wrapped nor full of ANSI codes.
    monkeypatch.setattr(cli, "console", Console(width=400, color_system=None))
    return s


def _seed(settings: Settings, keys: list[str]) -> None:
    with JobStore(settings.data_dir / "jobs.db") as store:
        for jk in keys:
            store.upsert_listing(_listing(jk), snippet=None, search_name="x")
            store.set_description(store.get_by_key("indeed", jk)["id"], f"JD for {jk}")


def _client_factory(monkeypatch, handler) -> None:
    """Make every OllamaClient the CLI builds use a fake transport answering with `handler`."""
    monkeypatch.setattr(
        cli, "OllamaClient", lambda s: OllamaClient(s, transport=httpx.MockTransport(handler))
    )


def _profiling_times_out(monkeypatch) -> None:
    """Run the real CLI profiling path, with a client that times out on its first call."""
    _client_factory(monkeypatch, ScriptedHandler(httpx.ReadTimeout))
    monkeypatch.setattr(cli, "load_library", lambda resumes_dir: SimpleNamespace(resumes=[]))
    monkeypatch.setattr(cli, "build_profiles", lambda library, client, data_dir, **kw: ask(client))


class ScriptedMatcher:
    """Stands in for Matcher: returns or raises scripted results per job key."""

    def __init__(self, script):
        self.script = script
        self.calls = []

    def decide(self, job):
        self.calls.append(job.job_key)
        result = self.script[job.job_key]
        if isinstance(result, Exception):
            raise result
        return result


def test_decide_stops_on_timeout_with_hint(settings, monkeypatch, timeout_error):
    _seed(settings, ["a", "b", "c"])
    apply = Decision(decision="apply", stage="llm", reason="good", resume_id="r1", score=80)
    matcher = ScriptedMatcher({"a": apply, "b": timeout_error, "c": apply})
    # The matcher is fake, so the client must never be called.
    _client_factory(monkeypatch, ScriptedHandler(httpx.Response(599)))
    monkeypatch.setattr(cli, "_build_matcher", lambda client: matcher)

    result = runner.invoke(cli.app, ["decide"])

    assert result.exit_code == 0, result.output  # same exit code as today's stop (OQ-3)
    assert matcher.calls == ["a", "b"]
    out = result.output
    assert "[1/3] Java Developer @ Acme -> pending_review" in out
    assert "Decided 1 (pending_review: 1)" in out
    stop_lines = [line for line in out.splitlines() if line.startswith("Stopped")]
    assert len(stop_lines) == 1 and str(timeout_error) in stop_lines[0]
    assert "-> failed" not in out
    assert _counts(settings) == {"pending_review": 1, "new": 2}


def test_decide_timeout_while_profiling_exits_1(settings, monkeypatch, timeout_error):
    _seed(settings, ["a", "b"])
    before = _counts(settings)
    _profiling_times_out(monkeypatch)

    result = runner.invoke(cli.app, ["decide"])

    assert result.exit_code == 1, result.output
    assert f"Error: {timeout_error}" in result.output
    assert "Error: Ollama timed out after 12.5s (model test-model:1b)." in result.output
    assert before == {"new": 2} and _counts(settings) == before


def test_resumes_index_timeout_exits_1(settings, monkeypatch, timeout_error):
    _profiling_times_out(monkeypatch)

    result = runner.invoke(cli.app, ["resumes", "index"])

    assert result.exit_code == 1, result.output
    assert f"Error: {timeout_error}" in result.output
