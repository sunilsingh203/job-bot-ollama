import pytest

from jobbot.db import JobStore, row_to_job, status_for
from jobbot.llm.client import LLMError, LLMUnavailable
from jobbot.models import Decision, Job
from jobbot.pipeline import decide_pending


def listing(jk: str, easy: bool = True, title: str = "Java Developer") -> Job:
    return Job(
        title=title,
        company="Acme",
        location="Pune",
        description="",
        platform="indeed",
        job_key=jk,
        easy_apply=easy,
        url=f"https://in.indeed.com/viewjob?jk={jk}",
    )


@pytest.fixture
def store(tmp_path):
    with JobStore(tmp_path / "jobs.db") as s:
        yield s


def test_upsert_is_idempotent(store):
    assert store.upsert_listing(listing("a"), snippet="s", search_name="x") is True
    assert store.upsert_listing(listing("a"), snippet="s", search_name="y") is False
    assert store.counts() == {"new": 1}
    assert store.needs_description("indeed", "a")


def test_upsert_keeps_decision_and_status(store):
    store.upsert_listing(listing("a"), snippet=None, search_name="x")
    row = store.get_by_key("indeed", "a")
    store.set_description(row["id"], "JD text")
    store.save_decision(row["id"], Decision(decision="skip", stage="llm", reason="no"))
    store.upsert_listing(listing("a"), snippet=None, search_name="x")  # seen again later
    row = store.get_by_key("indeed", "a")
    assert row["status"] == "skipped" and row["description"] == "JD text"


def test_duplicate_descriptions(store):
    for jk in ("a", "b"):
        store.upsert_listing(listing(jk), snippet=None, search_name="x")
    a, b = store.get_by_key("indeed", "a"), store.get_by_key("indeed", "b")
    assert store.set_description(a["id"], "Same JD") == "new"
    assert store.set_description(b["id"], "Same JD") == "duplicate"
    assert [r["job_key"] for r in store.to_decide()] == ["a"]


@pytest.mark.parametrize(
    ("decision", "easy", "expected"),
    [
        (Decision(decision="skip", stage="filter", reason="r"), True, "filtered_out"),
        (Decision(decision="skip", stage="llm", reason="r"), True, "skipped"),
        (Decision(decision="apply", stage="llm", reason="r"), True, "pending_review"),
        (Decision(decision="apply", stage="llm", reason="r"), False, "manual"),
        (Decision(decision="apply", stage="llm", reason="r"), None, "manual"),
    ],
)
def test_status_for(decision, easy, expected):
    assert status_for(decision, easy) == expected


def test_row_to_job_roundtrip(store):
    store.upsert_listing(listing("a", easy=False), snippet=None, search_name="x")
    row = store.get_by_key("indeed", "a")
    store.set_description(row["id"], "Full JD")
    job = row_to_job(store.get(row["id"]))
    assert job.description == "Full JD" and job.easy_apply is False and job.job_key == "a"


class FakeMatcher:
    """Stands in for Matcher: returns scripted results per job key."""

    def __init__(self, script):
        self.script = script
        self.calls = []

    def decide(self, job):
        self.calls.append(job.job_key)
        result = self.script[job.job_key]
        if isinstance(result, Exception):
            raise result
        return result


def _seed(store, keys, easy=True):
    for jk in keys:
        store.upsert_listing(listing(jk, easy=easy), snippet=None, search_name="x")
        store.set_description(store.get_by_key("indeed", jk)["id"], f"JD for {jk}")


def test_decide_pending_sets_statuses(store):
    _seed(store, ["a", "b", "c"])
    matcher = FakeMatcher(
        {
            "a": Decision(decision="apply", stage="llm", reason="good", resume_id="r1", score=80),
            "b": Decision(decision="skip", stage="filter", reason="too senior"),
            "c": LLMError("bad json"),
        }
    )
    stats = decide_pending(store, matcher)
    assert stats.decided == 2 and stats.failed == 1 and stats.aborted is None
    assert store.counts() == {"pending_review": 1, "filtered_out": 1, "failed": 1}
    a = store.get_by_key("indeed", "a")
    assert a["resume_id"] == "r1" and a["score"] == 80

    # failed jobs can be retried
    assert store.reset_failed() == 1
    assert [r["job_key"] for r in store.to_decide()] == ["c"]


def test_decide_pending_aborts_when_llm_unavailable(store):
    _seed(store, ["a", "b"])
    matcher = FakeMatcher({"a": LLMUnavailable("out of memory"), "b": None})
    stats = decide_pending(store, matcher)
    assert stats.aborted == "out of memory"
    assert matcher.calls == ["a"]  # did not keep hammering the LLM
    assert store.counts() == {"new": 2}  # untouched, will be retried next run


def test_decide_pending_stops_on_timeout(store, timeout_error):
    _seed(store, ["a", "b", "c"])
    apply = Decision(decision="apply", stage="llm", reason="good", resume_id="r1", score=80)
    matcher = FakeMatcher({"a": apply, "b": timeout_error, "c": apply})
    reported = []
    stats = decide_pending(
        store, matcher, on_decision=lambda i, n, job, d, s: reported.append(job.job_key)
    )
    assert matcher.calls == ["a", "b"]  # stopped at the first timeout, no retry
    assert stats.decided == 1 and stats.failed == 0
    assert stats.aborted == str(timeout_error)
    assert reported == ["a"]  # no "failed" report for the timed-out job

    # The stop touches no job: a keeps its decision, b and c stay new for the next run.
    assert store.counts() == {"pending_review": 1, "new": 2}
    for jk in ("b", "c"):
        row = store.get_by_key("indeed", jk)
        assert row["error"] is None and row["decision"] is None and row["decided_at"] is None
    assert [r["job_key"] for r in store.to_decide()] == ["b", "c"]


def test_decide_pending_marks_failed_on_client_invalid_json(store, invalid_json_error):
    _seed(store, ["a", "b", "c"])
    apply = Decision(decision="apply", stage="llm", reason="good", resume_id="r1", score=80)
    matcher = FakeMatcher({"a": apply, "b": invalid_json_error, "c": apply})
    stats = decide_pending(store, matcher)
    assert matcher.calls == ["a", "b", "c"]  # the run continued after the per-job error
    assert stats.decided == 2 and stats.failed == 1 and stats.aborted is None
    assert store.counts() == {"pending_review": 2, "failed": 1}
    b = store.get_by_key("indeed", "b")
    assert b["status"] == "failed" and b["error"] == str(invalid_json_error)[:1000]


def test_jobs_without_description_are_not_decided(store):
    store.upsert_listing(listing("a"), snippet=None, search_name="x")
    assert store.to_decide() == []
