"""Glue between the job store and the matcher."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from jobbot.db import JobStore, row_to_job
from jobbot.llm.client import LLMError, LLMUnavailable
from jobbot.matcher.decide import Matcher
from jobbot.models import Decision, Job

OnDecision = Callable[[int, int, Job, Decision | None, str | None], None]


@dataclass
class DecideStats:
    decided: int = 0
    failed: int = 0
    by_status: Counter[str] = field(default_factory=Counter)
    aborted: str | None = None  # set when the LLM became unavailable


def decide_pending(
    store: JobStore,
    matcher: Matcher,
    *,
    limit: int | None = None,
    on_decision: OnDecision | None = None,
) -> DecideStats:
    """Run the matcher on every job with status 'new' that has a description.

    A bad answer for one job marks only that job 'failed'. If Ollama itself is unavailable the
    run stops, leaving the remaining jobs 'new' for next time.
    """
    stats = DecideStats()
    rows = store.to_decide(limit)
    for i, row in enumerate(rows, 1):
        job = row_to_job(row)
        try:
            decision = matcher.decide(job)
        except LLMUnavailable as e:
            stats.aborted = str(e)
            break
        except LLMError as e:
            store.mark_failed(row["id"], str(e))
            stats.failed += 1
            stats.by_status["failed"] += 1
            if on_decision:
                on_decision(i, len(rows), job, None, str(e))
            continue
        status = store.save_decision(row["id"], decision)
        stats.decided += 1
        stats.by_status[status] += 1
        if on_decision:
            on_decision(i, len(rows), job, decision, status)
    return stats
