"""UX9 (#152): background dataset evaluation jobs.

The job engine lives in ``ui/eval_jobs.py`` and is deliberately free of
Streamlit/backend imports, so state transitions, progress, cancellation,
resume/retry, partial results, persistence bounds, merging and export are
tested deterministically. Structural tests cover the wiring in ``ui/app.py``,
the tour and the workspace deep-link contract.
"""

from __future__ import annotations

import ast
import json
import time
from pathlib import Path

import pytest

from ui import eval_jobs
from ui.eval_jobs import (
    ACTIVE_STATUSES,
    MAX_JOB_CASES,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    TERMINAL_STATUSES,
    EvalJob,
    JobStore,
    execute_case,
    get_job_store,
    job_export_csv,
    job_export_filename,
    job_export_json,
    job_history_rows,
    merge_job_rows,
    run_job,
    status_counts,
)
from ui.evaluation import EvaluationCase
from ui.workspace import (
    apply_workspace,
    workspace_from_query_params,
    workspace_from_session,
    workspace_to_query_params,
)

REPO_BASE = Path(__file__).resolve().parents[1]
APP_PATH = REPO_BASE / "ui" / "app.py"
TOUR_PATH = REPO_BASE / "ui" / "tour.py"
WORKSPACE_PATH = REPO_BASE / "ui" / "workspace.py"

SCREENS = [
    "Overview / Health",
    "Query Studio",
    "Compare (what-if)",
    "Evaluation",
    "Governance & Cost",
    "Guardrails",
    "Approvals",
    "Audit",
    "Access / RBAC",
    "Admin",
    "Traces",
    "Settings (read-only)",
]


def _case(query: str = "What is RAG?", reference: str = "RAG grounds answers.") -> EvaluationCase:
    return EvaluationCase(query=query, reference=reference)


class _FakeResult:
    def __init__(self, ok: bool, data: dict | None = None, status_code: int = 200):
        self.ok = ok
        self.data = data or {}
        self.status_code = status_code


class _FakeApi:
    """Programmable API double: fails queries/evaluations by query text."""

    def __init__(self, fail_queries: tuple[str, ...] = (), fail_evals: tuple[str, ...] = ()):
        self.query_calls: list[str] = []
        self.eval_calls: list[str] = []
        self.fail_queries = set(fail_queries)
        self.fail_evals = set(fail_evals)
        self.on_query: list = []

    def query(self, query: str, top_k: int | None = None, include_trace: bool = True):
        self.query_calls.append(query)
        for hook in self.on_query:
            hook(self, query)
        if query in self.fail_queries:
            return _FakeResult(False, {"error": "query failed upstream"}, status_code=400)
        return _FakeResult(
            True,
            {
                "response": f"answer for {query}",
                "retrieved_docs": [{"content": "doc-a"}],
            },
        )

    def evaluate(
        self,
        query: str,
        response: str,
        retrieved_docs=None,
        ground_truth=None,
        evaluator=None,
        top_k=None,
    ):
        self.eval_calls.append(query)
        if query in self.fail_evals:
            return _FakeResult(False, {"error": "evaluation failed upstream"}, status_code=500)
        return _FakeResult(
            True,
            {
                "evaluator": evaluator or "semantic",
                "metrics": {
                    "context_precision": 0.5,
                    "answer_relevance": 0.9,
                },
                "ground_truth_used": bool(ground_truth),
                "docs_source": "auto",
                "num_retrieved_docs": 1,
                "request_id": f"req-{len(self.eval_calls)}",
            },
        )


def _fixed_clock() -> str:
    return "2026-01-01T00:00:00+00:00"


def _completed_store(
    api: _FakeApi | None = None, jobs_spec: list[list[EvaluationCase]] | None = None
) -> tuple[JobStore, list[EvalJob]]:
    """A store whose jobs all ran to completion inline (deterministic)."""
    store = JobStore(clock=_fixed_clock)
    api = api or _FakeApi()
    jobs = []
    for spec in jobs_spec or []:
        job = store.submit("dataset", spec, api, autostart=False)
        run_job(job, api, clock=_fixed_clock)
        jobs.append(job)
    return store, jobs


# -- state transitions ------------------------------------------------------


def test_run_job_completes_all_cases_with_timestamps():
    cases = [_case(f"q{i}") for i in range(3)]
    job = EvalJob(
        job_id="j1", label="dataset", cases=tuple(cases), case_numbers=(1, 2, 3)
    )
    run_job(job, _FakeApi(), clock=_fixed_clock)
    assert job.status == STATUS_COMPLETED
    snap = job.snapshot()
    assert snap["done"] == 3
    assert snap["total"] == 3
    assert snap["succeeded"] == 3
    assert snap["failed"] == 0
    assert snap["progress"] == 1.0
    assert snap["started_at"] == _fixed_clock()
    assert snap["finished_at"] == _fixed_clock()
    assert [row["case"] for row in snap["rows"]] == [1, 2, 3]


def test_progress_is_reported_case_by_case():
    observed: list[int] = []
    api = _FakeApi()

    def _hook(_api: _FakeApi, _query: str) -> None:
        observed.append(len(job.snapshot()["rows"]))

    api.on_query.append(_hook)
    job = EvalJob(
        job_id="j2", label="dataset", cases=tuple(_case(f"q{i}") for i in range(3)),
        case_numbers=(1, 2, 3),
    )
    run_job(job, api, clock=_fixed_clock)
    # While each case runs, the previously finished rows are already visible.
    assert observed == [0, 1, 2]
    assert job.snapshot()["done"] == 3


def test_cancel_takes_effect_within_one_case_and_keeps_partial_results():
    def _hook(_api: _FakeApi, _query: str) -> None:
        if len(_api.query_calls) == 2:  # pressed while case 2 is in flight
            job.request_cancel()

    api = _FakeApi()
    api.on_query.append(_hook)
    job = EvalJob(
        job_id="j3", label="dataset", cases=tuple(_case(f"q{i}") for i in range(4)),
        case_numbers=(1, 2, 3, 4),
    )
    run_job(job, api, clock=_fixed_clock)
    snap = job.snapshot()
    assert snap["status"] == STATUS_CANCELLED
    assert snap["done"] == 2  # the in-flight case finishes; later cases never start
    assert snap["remaining"] == 2
    assert [row["case"] for row in snap["rows"]] == [1, 2]


def test_cancel_before_start_runs_nothing():
    job = EvalJob(job_id="j4", label="d", cases=(_case("q1"),), case_numbers=(1,))
    assert job.request_cancel() is True
    run_job(job, _FakeApi(), clock=_fixed_clock)
    snap = job.snapshot()
    assert snap["status"] == STATUS_CANCELLED
    assert snap["done"] == 0


def test_failing_case_does_not_abort_the_rest():
    api = _FakeApi(fail_queries=("q1",), fail_evals=("q2",))
    job = EvalJob(
        job_id="j5", label="dataset", cases=tuple(_case(f"q{i}") for i in range(3)),
        case_numbers=(1, 2, 3),
    )
    run_job(job, api, clock=_fixed_clock)
    snap = job.snapshot()
    assert snap["status"] == STATUS_COMPLETED
    assert snap["done"] == 3
    assert [row["status"] for row in snap["rows"]] == ["ok", "error", "error"]
    assert "query failed upstream" in snap["rows"][1]["error"]
    assert "evaluation failed upstream" in snap["rows"][2]["error"]


def test_query_exception_is_isolated_per_case():
    class _ExplodingApi(_FakeApi):
        def query(self, query: str, top_k=None, include_trace=True):
            if query == "boom":
                raise RuntimeError("connection reset")
            return super().query(query, top_k=top_k, include_trace=include_trace)

    job = EvalJob(
        job_id="j6", label="dataset",
        cases=(_case("fine"), _case("boom"), _case("fine2")),
        case_numbers=(1, 2, 3),
    )
    run_job(job, _ExplodingApi(), clock=_fixed_clock)
    snap = job.snapshot()
    assert snap["status"] == STATUS_COMPLETED
    assert snap["failed"] == 1
    assert "query failed: connection reset" in snap["rows"][1]["error"]


def test_unexpected_worker_error_fails_the_job(monkeypatch: pytest.MonkeyPatch):
    def _explode(*args, **kwargs):
        raise RuntimeError("worker bug")

    monkeypatch.setattr(eval_jobs, "execute_case", _explode)
    job = EvalJob(job_id="j7", label="d", cases=(_case("q1"),), case_numbers=(1,))
    run_job(job, _FakeApi(), clock=_fixed_clock)
    snap = job.snapshot()
    assert snap["status"] == STATUS_FAILED
    assert "worker bug" in snap["error"]


def test_execute_case_maps_non_ok_results_to_error_rows():
    row = execute_case(_FakeApi(fail_queries=("bad",)), _case("bad"), 7, None, 3)
    assert row["case"] == 7
    assert row["status"] == "error"
    ok = execute_case(_FakeApi(), _case("good"), 8, "semantic", 3)
    assert ok["status"] == "ok"
    assert ok["case"] == 8


# -- store: submission, bounds, persistence ---------------------------------


def test_submit_starts_worker_thread_and_completes():
    store = JobStore(clock=_fixed_clock)
    api = _FakeApi()
    job = store.submit("dataset", [_case(f"q{i}") for i in range(5)], api)
    assert job.job_id
    deadline = time.time() + 10
    while job.status not in TERMINAL_STATUSES and time.time() < deadline:
        time.sleep(0.01)
    snap = job.snapshot()
    assert snap["status"] == STATUS_COMPLETED
    assert snap["done"] == 5
    assert store.get(job.job_id) is job


def test_submit_rejects_empty_dataset():
    store = JobStore(clock=_fixed_clock)
    with pytest.raises(ValueError):
        store.submit("dataset", [], _FakeApi())


def test_submit_caps_cases_at_max_job_cases():
    store = JobStore(clock=_fixed_clock)
    job = store.submit("dataset", [_case(f"q{i}") for i in range(250)], _FakeApi(), autostart=False)
    snap = job.snapshot()
    assert snap["total"] == MAX_JOB_CASES
    assert snap["total"] > 20  # beyond the old synchronous UI cap
    assert job.case_numbers == tuple(range(1, MAX_JOB_CASES + 1))


def test_hundred_case_run_reports_full_progress():
    store = JobStore(clock=_fixed_clock)
    job = store.submit(
        "dataset", [_case(f"q{i}") for i in range(100)], _FakeApi(), autostart=False
    )
    run_job(job, _FakeApi(), clock=_fixed_clock)
    snap = job.snapshot()
    assert snap["done"] == 100
    assert snap["progress"] == 1.0
    assert snap["succeeded"] == 100


def test_job_history_is_bounded_and_newest_first():
    store = JobStore(clock=_fixed_clock, max_jobs=5)
    api = _FakeApi()
    for _ in range(5):
        job = store.submit("dataset", [_case("q")], api, autostart=False)
        run_job(job, api, clock=_fixed_clock)
    late = store.submit("late job", [_case("late")], api, autostart=False)
    run_job(late, api, clock=_fixed_clock)  # 6th job; oldest evicted on submit
    jobs = store.list()
    assert len(jobs) == 5  # eviction removed the oldest terminal job
    assert jobs[0].label == "late job"  # newest first
    assert all(job.status in TERMINAL_STATUSES for job in jobs)


def test_latest_prefers_active_jobs():
    store, jobs = _completed_store(jobs_spec=[[_case("a")], [_case("b")]])
    running = store.submit("dataset", [_case("c")], _FakeApi(), autostart=False)
    assert store.latest(active_only=True) is running
    assert store.latest() is running
    run_job(running, _FakeApi(), clock=_fixed_clock)
    assert store.latest(active_only=True) is None


def test_get_job_store_is_a_process_singleton():
    assert get_job_store() is get_job_store()
    assert isinstance(get_job_store(), JobStore)


def test_cancel_outcomes():
    store, jobs = _completed_store(jobs_spec=[[_case("a")]])
    assert store.cancel("does-not-exist") == "not_found"
    done = jobs[0]
    assert store.cancel(done.job_id) == "not_active"
    job = store.submit("dataset", [_case("b")], _FakeApi(), autostart=False)
    assert job.status in ACTIVE_STATUSES
    assert store.cancel(job.job_id) == "ok"


def test_remove_only_removes_terminal_jobs():
    store, jobs = _completed_store(jobs_spec=[[_case("a")]])
    done = jobs[0]
    assert store.remove(done.job_id) is True
    assert store.get(done.job_id) is None
    live = store.submit("dataset", [_case("b")], _FakeApi(), autostart=False)
    assert store.remove(live.job_id) is False
    assert store.get(live.job_id) is live


# -- resume / retry -----------------------------------------------------------


def test_retry_failed_only_retries_failed_cases_by_default():
    api = _FakeApi(fail_queries=("q1",))
    store = JobStore(clock=_fixed_clock)
    job = store.submit(
        "dataset", [_case("q1"), _case("q2"), _case("q3")], api, evaluator="semantic", top_k=5,
        autostart=False,
    )
    run_job(job, api, clock=_fixed_clock)
    # The retry autostarts with the (now healthy) API, like a real console retry.
    retry = store.retry_failed(job.job_id, _FakeApi())
    assert retry is not None
    assert retry.resume_of == job.job_id
    assert retry.case_numbers == (1,)  # only the failed case
    assert [case.query for case in retry.cases] == ["q1"]
    assert retry.evaluator == "semantic"
    assert retry.top_k == 5
    assert retry.label.endswith("(retry failed)")
    deadline = time.time() + 10
    while retry.status not in TERMINAL_STATUSES and time.time() < deadline:
        time.sleep(0.01)
    snap = retry.snapshot()
    assert snap["status"] == STATUS_COMPLETED
    assert snap["rows"][0]["status"] == "ok"


def test_resume_includes_failed_and_unstarted_cases():
    api = _FakeApi(fail_queries=("q2",))

    def _hook(_api: _FakeApi, _query: str) -> None:
        if len(_api.query_calls) == 2:  # stop after case 2
            job.request_cancel()

    api.on_query.append(_hook)
    store = JobStore(clock=_fixed_clock)
    job = store.submit(
        "dataset", [_case(f"q{i}") for i in range(1, 5)], api, autostart=False
    )
    run_job(job, api, clock=_fixed_clock)
    assert job.snapshot()["status"] == STATUS_CANCELLED
    resumed = store.retry_failed(job.job_id, _FakeApi(), include_pending=True)
    assert resumed is not None
    assert resumed.case_numbers == (2, 3, 4)  # failed + never started
    assert resumed.label.endswith("(resume)")
    deadline = time.time() + 10
    while resumed.status not in TERMINAL_STATUSES and time.time() < deadline:
        time.sleep(0.01)
    assert resumed.snapshot()["status"] == STATUS_COMPLETED


def test_retry_returns_none_when_nothing_to_retry():
    api = _FakeApi(fail_queries=("q1",))
    store = JobStore(clock=_fixed_clock)
    job = store.submit("dataset", [_case("q1"), _case("q2")], api, autostart=False)
    run_job(job, api, clock=_fixed_clock)
    # Nothing pending and... q1 failed, so a plain retry exists.
    assert store.retry_failed(job.job_id, api) is not None
    clean = store.submit("dataset", [_case("ok")], api, autostart=False)
    run_job(clean, api, clock=_fixed_clock)
    assert store.retry_failed(clean.job_id, api) is None
    assert store.retry_failed(clean.job_id, api, include_pending=True) is None
    assert store.retry_failed("missing", api) is None


def test_merge_job_rows_overlays_retries_by_case_number():
    base = [
        {"case": 1, "status": "ok", "answer_relevance": 0.9},
        {"case": 2, "status": "error", "error": "boom"},
        {"case": 3, "status": "ok", "answer_relevance": 0.8},
    ]
    retry = [
        {"case": 2, "status": "ok", "answer_relevance": 0.7},
        {"case": 5, "status": "ok"},
    ]
    merged = merge_job_rows(base, retry)
    assert [row["case"] for row in merged] == [1, 2, 3, 5]
    by_case = {row["case"]: row for row in merged}
    assert by_case[2]["status"] == "ok"
    assert by_case[1]["answer_relevance"] == 0.9  # untouched


# -- snapshots, counts, export -------------------------------------------------


def test_snapshot_is_detached_from_job_state():
    job = EvalJob(job_id="j8", label="d", cases=(_case("q"),), case_numbers=(1,))
    run_job(job, _FakeApi(), clock=_fixed_clock)
    snap = job.snapshot()
    snap["rows"][0]["status"] = "tampered"
    snap["done"] = 99
    fresh = job.snapshot()
    assert fresh["rows"][0]["status"] == "ok"
    assert fresh["done"] == 1


def test_status_counts_and_history_rows():
    rows = [{"status": "ok"}, {"status": "error"}, {"status": "ok"}]
    assert status_counts(rows) == {"succeeded": 2, "failed": 1}
    history = job_history_rows(
        [
            {
                "job_id": "abc", "label": "benchmark", "status": STATUS_COMPLETED,
                "total": 3, "done": 3, "succeeded": 2, "failed": 1,
                "created_at": "t1", "finished_at": "t2", "resume_of": None,
            }
        ]
    )
    assert history[0]["job_id"] == "abc"
    assert history[0]["resumes"] == "-"


def test_job_exports_round_trip():
    store = JobStore(clock=_fixed_clock)
    api = _FakeApi(fail_queries=("q1",))
    job = store.submit("dataset", [_case("q1"), _case("q2")], api, autostart=False)
    run_job(job, api, clock=_fixed_clock)
    snap = job.snapshot()

    payload = json.loads(job_export_json(snap))
    assert payload["job_id"] == snap["job_id"]
    assert payload["status"] == STATUS_COMPLETED
    assert payload["failed"] == 1
    assert len(payload["rows"]) == 2
    assert "sk-" not in job_export_json(snap)

    csv_text = job_export_csv(snap)
    assert csv_text.splitlines()[0].startswith("case,")
    assert "q1" in csv_text
    assert job_export_filename(snap, "json") == f"eval-job-{snap['job_id']}.json"


# -- workspace deep-link contract ----------------------------------------------


def test_workspace_carries_focused_eval_job_id():
    state = {"eval_job_id": "abc123def456"}
    workspace = workspace_from_session(state)
    assert workspace["evaluation"]["job_id"] == "abc123def456"

    params = workspace_to_query_params(workspace)
    assert params["eval_job"] == "abc123def456"

    restored = workspace_from_query_params({"screen": "Evaluation", "eval_job": "abc123def456"})
    assert restored["evaluation"]["job_id"] == "abc123def456"

    target: dict = {}
    screen = apply_workspace(restored, target, {"ok": True, "role": "admin", "capabilities": ["evaluate"]}, SCREENS)
    assert screen == "Evaluation"
    assert target["eval_job_id"] == "abc123def456"

    # Invalid ids are sanitized, never crash the workspace codec.
    bad = workspace_from_query_params({"eval_job": "not; a valid !! id"})
    assert bad["evaluation"]["job_id"] == "notavalidid"


# -- structural wiring (app.py, tour, HTTP-only) -------------------------------


def test_app_wires_background_evaluation_jobs():
    src = APP_PATH.read_text(encoding="utf-8")
    assert "get_job_store" in src
    assert "Start background job" in src
    assert "_render_eval_jobs" in src
    assert "eval_job_id" in src
    assert "st.fragment" in src  # auto-refresh panel
    assert "run_dataset_evaluation" not in src  # synchronous path retired
    assert "eval_dataset_run" not in src
    tree = ast.parse(src)
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "_render_eval_job_detail"
        for node in ast.walk(tree)
    )


def test_eval_jobs_module_stays_http_only_and_pure():
    src = (REPO_BASE / "ui" / "eval_jobs.py").read_text(encoding="utf-8")
    assert "import streamlit" not in src
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith(("app", "core")) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or node.module.split(".")[0] not in ("app", "core")


def test_tour_step_mentions_background_jobs():
    src = TOUR_PATH.read_text(encoding="utf-8")
    assert "background job" in src
    assert "cancel" in src.lower()
    assert "retry" in src.lower()


def test_workspace_module_carries_eval_job_param():
    src = WORKSPACE_PATH.read_text(encoding="utf-8")
    assert '"eval_job"' in src
    assert '"eval_job_id"' in src
