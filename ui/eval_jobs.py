"""Background dataset evaluation jobs (issue #152, UX9).

Dataset evaluations no longer block the console: each job runs
``POST /v1/query`` followed by ``POST /v1/evaluate`` per case on a daemon
thread, while the Evaluation screen renders progress, per-case rows, partial
results, cancellation (effective between cases), retry of failed cases and a
bounded job history that survives a page refresh within the console process.

This module is deliberately free of Streamlit and backend imports so the job
state machine, cancellation, resume, merging and export contracts can be
unit-tested deterministically without a browser or a live API. The console only
talks to the backend through :class:`ui.client.ApiClient` instances it hands
to the store (HTTP-only rule, ``docs/ux-and-api.md`` §3.2).
"""

from __future__ import annotations

import copy
import csv
import io
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ui.evaluation import (
    EvaluationCase,
    _api_error,
    build_evaluation_row,
    metric_matrix,
)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_CANCELLING = "cancelling"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"
STATUS_FAILED = "failed"

ACTIVE_STATUSES = frozenset({STATUS_QUEUED, STATUS_RUNNING, STATUS_CANCELLING})
TERMINAL_STATUSES = frozenset({STATUS_COMPLETED, STATUS_CANCELLED, STATUS_FAILED})

MAX_JOB_CASES = 200
MAX_JOBS = 20
MAX_PREVIEW_ROWS = 50

Clock = Callable[[], str]


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _short_id() -> str:
    return uuid.uuid4().hex[:12]


def _selected_evaluator(evaluator: Optional[str]) -> Optional[str]:
    return None if not evaluator or evaluator == "(active)" else evaluator


def execute_case(
    api: Any,
    case: EvaluationCase,
    number: int,
    evaluator: Optional[str],
    top_k: int,
) -> Dict[str, Any]:
    """Run query -> evaluate for one case, isolating failures to that case."""
    try:
        query_result = api.query(case.query, top_k=top_k, include_trace=False)
    except Exception as exc:  # per-case isolation: never abort the job
        return build_evaluation_row(case, index=number, error=f"query failed: {exc}")
    if not getattr(query_result, "ok", False):
        return build_evaluation_row(case, index=number, error=_api_error(query_result))
    query_data = getattr(query_result, "data", {}) or {}
    response = str(query_data.get("response") or query_data.get("answer") or "")
    docs = query_data.get("retrieved_docs")
    retrieved_docs = docs if isinstance(docs, list) and docs else None
    try:
        evaluation = api.evaluate(
            case.query,
            response,
            retrieved_docs=retrieved_docs,
            ground_truth=case.reference or None,
            evaluator=_selected_evaluator(evaluator),
            top_k=top_k,
        )
    except Exception as exc:  # per-case isolation: never abort the job
        return build_evaluation_row(
            case, index=number, error=f"evaluation failed: {exc}"
        )
    if not getattr(evaluation, "ok", False):
        return build_evaluation_row(case, index=number, error=_api_error(evaluation))
    return build_evaluation_row(
        case, getattr(evaluation, "data", {}) or {}, index=number
    )


@dataclass
class EvalJob:
    """One background dataset evaluation and its thread-safe state."""

    job_id: str
    label: str
    cases: Tuple[EvaluationCase, ...]
    case_numbers: Tuple[int, ...]
    evaluator: Optional[str] = None
    top_k: int = 3
    source: str = ""
    resume_of: Optional[str] = None
    status: str = STATUS_QUEUED
    cancel_requested: bool = False
    rows: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    error: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if len(self.case_numbers) != len(self.cases):
            self.case_numbers = tuple(range(1, len(self.cases) + 1))

    # -- worker-side mutations -------------------------------------------

    def mark_started(self, now: str) -> None:
        with self.lock:
            self.status = STATUS_RUNNING
            self.started_at = self.started_at or now

    def request_cancel(self) -> bool:
        """Ask the worker to stop after the current case."""
        with self.lock:
            if self.status in TERMINAL_STATUSES:
                return False
            self.cancel_requested = True
            if self.status == STATUS_QUEUED:
                self.status = STATUS_CANCELLING
            return True

    def append_row(self, row: Mapping[str, Any]) -> None:
        with self.lock:
            self.rows.append(dict(row))

    def finish(self, now: str) -> None:
        with self.lock:
            if self.status != STATUS_FAILED:
                self.status = STATUS_CANCELLED if self.cancel_requested else STATUS_COMPLETED
            self.finished_at = self.finished_at or now

    def fail(self, error: str, now: str) -> None:
        with self.lock:
            self.status = STATUS_FAILED
            self.error = self.error or str(error)
            self.finished_at = self.finished_at or now

    # -- reader-side snapshot ---------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a plain, detached copy of the job state for rendering."""
        with self.lock:
            rows = copy.deepcopy(self.rows)
            status = self.status
            cancel_requested = self.cancel_requested
            total = len(self.cases)
            done = len(rows)
            current_index = done if status == STATUS_RUNNING else None
        succeeded = sum(1 for row in rows if row.get("status") == "ok")
        failed = done - succeeded
        current_case = ""
        if current_index is not None and 0 <= current_index < total:
            current_case = self.cases[current_index].query
        return {
            "job_id": self.job_id,
            "label": self.label,
            "source": self.source,
            "status": status,
            "cancel_requested": cancel_requested,
            "evaluator": self.evaluator or "(active)",
            "top_k": self.top_k,
            "resume_of": self.resume_of,
            "total": total,
            "done": done,
            "succeeded": succeeded,
            "failed": failed,
            "remaining": max(0, total - done),
            "progress": (done / total) if total else 0.0,
            "current_case": current_case,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "rows": rows,
        }


def run_job(job: EvalJob, api: Any, clock: Clock = _default_clock) -> EvalJob:
    """Drive one job to a terminal state, case by case (worker entrypoint).

    Cancellation is honored between cases: the in-flight case always finishes
    and its result is preserved. A failing case is recorded as an error row and
    never aborts the remaining cases.
    """
    job.mark_started(clock())
    try:
        for number, case in zip(job.case_numbers, job.cases):
            with job.lock:
                if job.cancel_requested:
                    break
            row = execute_case(api, case, number, job.evaluator, job.top_k)
            job.append_row(row)
    except Exception as exc:  # unexpected worker failure (not per-case)
        job.fail(str(exc), clock())
        return job
    job.finish(clock())
    return job


class JobStore:
    """Bounded, process-wide registry of background evaluation jobs."""

    def __init__(self, clock: Optional[Clock] = None, max_jobs: int = MAX_JOBS) -> None:
        self._clock = clock or _default_clock
        self._max_jobs = max_jobs
        self._jobs: List[EvalJob] = []
        self._lock = threading.Lock()

    # -- registry ---------------------------------------------------------

    def submit(
        self,
        label: str,
        cases: Sequence[EvaluationCase],
        api: Any,
        *,
        evaluator: Optional[str] = None,
        top_k: int = 3,
        source: str = "",
        resume_of: Optional[str] = None,
        case_numbers: Optional[Sequence[int]] = None,
        autostart: bool = True,
    ) -> EvalJob:
        """Register a new job (bounded to the first ``MAX_JOB_CASES`` cases)."""
        limited = list(cases)[:MAX_JOB_CASES]
        if not limited:
            raise ValueError("Dataset has no cases to evaluate")
        numbers = tuple(case_numbers or range(1, len(limited) + 1))
        job = EvalJob(
            job_id=_short_id(),
            label=label,
            cases=tuple(limited),
            case_numbers=numbers,
            evaluator=_selected_evaluator(evaluator),
            top_k=max(1, min(10, int(top_k))),
            source=source,
            resume_of=resume_of,
            created_at=self._clock(),
        )
        with self._lock:
            self._jobs.append(job)
            self._evict_locked()
        if autostart:
            self.start(job, api)
        return job

    def start(self, job: EvalJob, api: Any) -> threading.Thread:
        thread = threading.Thread(
            target=run_job, args=(job, api, self._clock), daemon=True,
            name=f"eval-job-{job.job_id}",
        )
        thread.start()
        return thread

    def _evict_locked(self) -> None:
        """Drop the oldest terminal job once history exceeds the cap."""
        while len(self._jobs) > self._max_jobs:
            for index, job in enumerate(self._jobs):
                if job.status in TERMINAL_STATUSES:
                    del self._jobs[index]
                    break
            else:
                return  # every job is still active; keep them all for now

    def get(self, job_id: str) -> Optional[EvalJob]:
        with self._lock:
            for job in self._jobs:
                if job.job_id == job_id:
                    return job
        return None

    def list(self, limit: int = MAX_JOBS) -> List[EvalJob]:
        """Newest-first bounded job history."""
        with self._lock:
            jobs = list(self._jobs)
        return list(reversed(jobs[-limit:]))

    def latest(self, active_only: bool = False) -> Optional[EvalJob]:
        with self._lock:
            jobs = list(self._jobs)
        for job in reversed(jobs):
            if not active_only or job.status in ACTIVE_STATUSES:
                return job
        return None

    # -- lifecycle actions --------------------------------------------------

    def cancel(self, job_id: str) -> str:
        """Request cancellation; returns ``ok`` / ``not_found`` / ``not_active``."""
        job = self.get(job_id)
        if job is None:
            return "not_found"
        with job.lock:
            active = job.status in ACTIVE_STATUSES
        if not active:
            return "not_active"
        job.request_cancel()
        return "ok"

    def retry_failed(self, job_id: str, api: Any, *, include_pending: bool = False) -> Optional[EvalJob]:
        """Submit a new job for the failed (and optionally unstarted) cases.

        By default only failed cases are retried; pass ``include_pending=True``
        to also resume cases that never ran (for example after a cancel).
        """
        job = self.get(job_id)
        if job is None:
            return None
        snap = job.snapshot()
        rows_by_case = {row.get("case"): row for row in snap["rows"]}
        numbers: List[int] = []
        for number in job.case_numbers:
            row = rows_by_case.get(number)
            if row is None:
                if include_pending:
                    numbers.append(number)
                continue
            if row.get("status") == "error":
                numbers.append(number)
        if not numbers:
            return None
        number_set = set(numbers)
        subset = [
            case for number, case in zip(job.case_numbers, job.cases)
            if number in number_set
        ]
        suffix = " (resume)" if include_pending else " (retry failed)"
        return self.submit(
            job.label + suffix,
            subset,
            api,
            evaluator=job.evaluator,
            top_k=job.top_k,
            source=job.source,
            resume_of=job.job_id,
            case_numbers=numbers,
        )

    def remove(self, job_id: str) -> bool:
        """Remove a terminal job from the history."""
        with self._lock:
            for index, job in enumerate(self._jobs):
                if job.job_id == job_id:
                    if job.status in ACTIVE_STATUSES:
                        return False
                    del self._jobs[index]
                    return True
        return False


_STORE: Optional[JobStore] = None
_STORE_LOCK = threading.Lock()


def get_job_store() -> JobStore:
    """Process-wide singleton so jobs survive a page refresh (same process)."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = JobStore()
        return _STORE


# -- pure rendering / export helpers ---------------------------------------


def status_counts(rows: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    succeeded = sum(1 for row in rows if row.get("status") == "ok")
    return {"succeeded": succeeded, "failed": len(rows) - succeeded}


def merge_job_rows(
    base_rows: Sequence[Mapping[str, Any]],
    retry_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Overlay retry rows on the original run, keyed by case number."""
    merged: Dict[Any, Dict[str, Any]] = {}
    for row in base_rows:
        if isinstance(row, Mapping):
            merged[row.get("case")] = dict(row)
    for row in retry_rows:
        if isinstance(row, Mapping):
            merged[row.get("case")] = dict(row)

    def _sort_key(case: Any) -> Tuple[bool, int]:
        try:
            return (False, int(case))
        except (TypeError, ValueError):
            return (True, 0)

    return [merged[key] for key in sorted(merged, key=_sort_key)]


def job_history_rows(snapshots: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Rows for the job-history dataframe (newest first)."""
    rows: List[Dict[str, Any]] = []
    for snap in snapshots:
        rows.append(
            {
                "job_id": snap.get("job_id"),
                "label": snap.get("label"),
                "status": snap.get("status"),
                "cases": snap.get("total"),
                "done": snap.get("done"),
                "succeeded": snap.get("succeeded"),
                "failed": snap.get("failed"),
                "created_at": snap.get("created_at"),
                "finished_at": snap.get("finished_at"),
                "resumes": snap.get("resume_of") or "-",
            }
        )
    return rows


def job_export_json(snapshot: Mapping[str, Any]) -> str:
    """Full job export (metadata + per-case rows) as pretty JSON."""
    payload = {
        key: copy.deepcopy(snapshot.get(key))
        for key in (
            "job_id",
            "label",
            "source",
            "evaluator",
            "top_k",
            "status",
            "created_at",
            "started_at",
            "finished_at",
            "resume_of",
            "total",
            "done",
            "succeeded",
            "failed",
            "error",
        )
    }
    payload["rows"] = copy.deepcopy(list(snapshot.get("rows") or []))
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)


def job_export_csv(snapshot: Mapping[str, Any]) -> str:
    """Case/metric matrix export as CSV (safe: cells are strings/numbers)."""
    matrix = metric_matrix(list(snapshot.get("rows") or []))
    columns: List[str] = []
    for row in matrix:
        for key in row:
            if key not in columns:
                columns.append(key)
    if not columns:
        columns = ["case"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in matrix:
        writer.writerow({key: row.get(key, "") for key in columns})
    return buffer.getvalue()


def job_export_filename(snapshot: Mapping[str, Any], extension: str) -> str:
    return f"eval-job-{snapshot.get('job_id') or 'latest'}.{extension}"
