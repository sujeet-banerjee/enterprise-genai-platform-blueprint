"""Reference load/latency harness (issue #197, Workstream K / showcase H5).

Runs a bounded, deterministic plan of HTTP requests against the API and reports
reference CPU latency/throughput numbers: p50/p95/p99, requests/sec, error rate
and a per-stage latency breakdown (read from the ``/v1/query`` observability
block). Output is JSON + Markdown with provenance so a published number can be
regenerated.

This module is **client-agnostic** and does not import ``app.*`` or ``ui.*`` (so
the CLI in ``benchmarks/load/run_load.py`` and the tests can share it). The
caller supplies a ``client_factory`` returning an object with
``request(method, url, json=...)`` (``httpx.Client`` in production, a
``TestClient`` in tests).

The numbers produced here are **reference CPU baselines**, not production
throughput or SLO claims.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

REPORT_SCHEMA_VERSION = "1.0"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"

MAX_CONCURRENCY = 64
MAX_REQUESTS_PER_SCENARIO = 5000
MAX_PLAN_RUNS = 64

DEFAULT_LABEL = (
    "Reference CPU baselines measured on a single machine. These are not "
    "production throughput, capacity or SLO claims."
)
DEFAULT_CAVEATS: Tuple[str, ...] = (
    "Single-process API; results do not describe a multi-replica deployment.",
    "Dummy providers (unless a real-model config is supplied) so quality is "
    "not measured here.",
    "Latency is wall-clock client time and includes HTTP and serialization.",
    "Re-measure on your own hardware before making capacity decisions.",
)


class LoadHarnessError(ValueError):
    """Raised when a load plan is invalid or exceeds the bounded limits."""


@dataclass(frozen=True)
class LoadScenario:
    """A single request shape exercised by the harness."""

    name: str
    method: str
    path: str
    payload: Optional[Dict[str, Any]] = None
    description: str = ""


DEFAULT_SCENARIOS: Tuple[LoadScenario, ...] = (
    LoadScenario("health", "GET", "/health", description="liveness probe"),
    LoadScenario("ready", "GET", "/ready", description="readiness probe (pipeline built)"),
    LoadScenario(
        "query",
        "POST",
        "/v1/query",
        payload={"query": "How do I reset my password?", "top_k": 3},
        description="single RAG query",
    ),
    LoadScenario(
        "batch",
        "POST",
        "/v1/query:batch",
        payload={
            "queries": [
                "How do I reset my password?",
                "I lost my MFA device, what should I do?",
            ],
            "top_k": 3,
        },
        description="batched RAG queries",
    ),
)

DEFAULT_CONCURRENCIES: Tuple[int, ...] = (1, 4, 8, 16)


def percentile(samples: Sequence[float], pct: float) -> float:
    """Linear-interpolation percentile (``pct`` in ``[0, 100]``)."""
    if not samples:
        return 0.0
    if pct < 0 or pct > 100:
        raise LoadHarnessError(f"percentile must be within [0, 100], got {pct!r}")
    ordered = sorted(float(value) for value in samples)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (float(pct) / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def summarize(samples: Sequence[float]) -> Dict[str, float]:
    """Return count/mean/min/max/p50/p95/p99 for a latency sample list."""
    values = [float(value) for value in samples]
    if not values:
        return {
            "count": 0,
            "mean_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
        }
    return {
        "count": len(values),
        "mean_ms": statistics.fmean(values),
        "min_ms": min(values),
        "max_ms": max(values),
        "p50_ms": percentile(values, 50),
        "p95_ms": percentile(values, 95),
        "p99_ms": percentile(values, 99),
    }


def _coerce_concurrencies(concurrencies: Sequence[int]) -> List[int]:
    if not concurrencies:
        raise LoadHarnessError("at least one concurrency level is required")
    out: List[int] = []
    for value in concurrencies:
        if isinstance(value, bool) or not isinstance(value, int):
            raise LoadHarnessError(f"concurrency levels must be integers, got {value!r}")
        if value < 1:
            raise LoadHarnessError(f"concurrency must be >= 1, got {value}")
        if value > MAX_CONCURRENCY:
            raise LoadHarnessError(
                f"concurrency {value} exceeds MAX_CONCURRENCY={MAX_CONCURRENCY}"
            )
        if value not in out:
            out.append(value)
    return out


def expand_plan(
    scenarios: Sequence[LoadScenario],
    concurrencies: Sequence[int] = DEFAULT_CONCURRENCIES,
    requests_per_scenario: int = 50,
) -> List[Dict[str, Any]]:
    """Return a bounded, deterministic ``[{scenario, concurrency, requests}]`` plan."""
    if not scenarios:
        raise LoadHarnessError("at least one scenario is required")
    names = [scenario.name for scenario in scenarios]
    if len(names) != len(set(names)):
        raise LoadHarnessError("scenario names must be unique")
    if isinstance(requests_per_scenario, bool) or not isinstance(requests_per_scenario, int):
        raise LoadHarnessError("requests_per_scenario must be an integer")
    if requests_per_scenario < 1:
        raise LoadHarnessError("requests_per_scenario must be >= 1")
    if requests_per_scenario > MAX_REQUESTS_PER_SCENARIO:
        raise LoadHarnessError(
            f"requests_per_scenario {requests_per_scenario} exceeds "
            f"MAX_REQUESTS_PER_SCENARIO={MAX_REQUESTS_PER_SCENARIO}"
        )
    levels = _coerce_concurrencies(concurrencies)
    if len(scenarios) * len(levels) > MAX_PLAN_RUNS:
        raise LoadHarnessError(
            f"plan expands to {len(scenarios) * len(levels)} runs, "
            f"above MAX_PLAN_RUNS={MAX_PLAN_RUNS}"
        )
    plan: List[Dict[str, Any]] = []
    for scenario in scenarios:
        for level in levels:
            plan.append(
                {
                    "scenario": scenario,
                    "concurrency": level,
                    "requests": requests_per_scenario,
                }
            )
    return plan


def _thread_client(factory: Callable[[], Any], local: threading.local) -> Any:
    client = getattr(local, "client", None)
    if client is None:
        client = factory()
        local.client = client
    return client


def _close_all(clients: Sequence[Any]) -> None:
    for client in clients:
        closer = getattr(client, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass


def _execute_run(
    scenario: LoadScenario,
    concurrency: int,
    requests: int,
    warmup: int,
    client_factory: Callable[[], Any],
    base_url: str,
    clock: Callable[[], float],
) -> Dict[str, Any]:
    created: List[Any] = []

    def factory() -> Any:
        client = client_factory()
        created.append(client)
        return client

    local = threading.local()
    lock = threading.Lock()
    latencies: List[float] = []
    stages: Dict[str, List[float]] = {}
    status_counts: Dict[int, int] = {}
    errors = 0
    error_samples: List[str] = []
    url = f"{base_url}{scenario.path}"

    def do_request() -> None:
        nonlocal errors
        client = _thread_client(factory, local)
        start = clock()
        status = 0
        body: Any = None
        ok = False
        try:
            response = client.request(scenario.method, url, json=scenario.payload)
            status = int(getattr(response, "status_code", 0) or 0)
            ok = 0 < status < 400
            try:
                body = response.json()
            except Exception:
                body = None
        except Exception as exc:
            status = 0
            ok = False
            with lock:
                error_samples.append(f"{type(exc).__name__}: {exc}")
        elapsed_ms = (clock() - start) * 1000.0
        with lock:
            latencies.append(elapsed_ms)
            status_counts[status] = status_counts.get(status, 0) + 1
            if not ok:
                errors += 1
            if isinstance(body, Mapping):
                latency = body.get("latency")
                if isinstance(latency, Mapping):
                    for key, value in latency.items():
                        if (
                            str(key).endswith("_ms")
                            and isinstance(value, (int, float))
                            and not isinstance(value, bool)
                        ):
                            stages.setdefault(str(key), []).append(float(value))

    try:
        for _ in range(max(0, warmup)):
            do_request()
        latencies.clear()
        stages.clear()
        status_counts.clear()
        error_samples.clear()
        errors = 0

        wall_start = clock()
        if concurrency <= 1:
            for _ in range(requests):
                do_request()
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                list(pool.map(lambda _index: do_request(), range(requests)))
        wall_ms = (clock() - wall_start) * 1000.0
    finally:
        _close_all(created)

    count = len(latencies)
    rps = (count / (wall_ms / 1000.0)) if wall_ms > 0 else 0.0
    stage_summary = {
        name: {"mean_ms": statistics.fmean(values), "p95_ms": percentile(values, 95)}
        for name, values in sorted(stages.items())
        if values
    }
    return {
        "scenario": scenario.name,
        "method": scenario.method,
        "path": scenario.path,
        "concurrency": concurrency,
        "requests": requests,
        "count": count,
        "errors": errors,
        "error_rate": (errors / count) if count else 0.0,
        "requests_per_second": rps,
        "wall_ms": wall_ms,
        "latency": summarize(latencies),
        "status_counts": {str(key): value for key, value in sorted(status_counts.items())},
        "stages": stage_summary,
        "sample_errors": error_samples[:5],
    }


def run_load(
    scenarios: Sequence[LoadScenario] = DEFAULT_SCENARIOS,
    *,
    concurrencies: Sequence[int] = DEFAULT_CONCURRENCIES,
    requests_per_scenario: int = 50,
    warmup: int = 2,
    client_factory: Callable[[], Any],
    base_url: str = "",
    clock: Callable[[], float] = time.perf_counter,
) -> Dict[str, Any]:
    """Execute a bounded load plan and return ``{"runs": [...], "summary": {...}}``."""
    if warmup < 0:
        raise LoadHarnessError("warmup must be >= 0")
    if not callable(client_factory):
        raise LoadHarnessError("client_factory must be callable")
    plan = expand_plan(scenarios, concurrencies, requests_per_scenario)
    runs = [
        _execute_run(
            item["scenario"],
            item["concurrency"],
            item["requests"],
            warmup,
            client_factory,
            base_url,
            clock,
        )
        for item in plan
    ]
    total_requests = sum(run["count"] for run in runs)
    total_errors = sum(run["errors"] for run in runs)
    return {
        "runs": runs,
        "summary": {
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate": (total_errors / total_requests) if total_requests else 0.0,
            "scenarios": sorted({run["scenario"] for run in runs}),
            "runs": len(runs),
        },
    }


def _git_sha() -> str:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            stderr=subprocess.DEVNULL,
        )
        return output.decode("utf-8").strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def collect_provenance(
    config_dir: str | Path = DEFAULT_CONFIG_DIR,
    *,
    base_url: str = "",
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Provenance block so a published number can be regenerated."""
    return {
        "git_sha": _git_sha(),
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "python_version": platform.python_version(),
        "config_dir": str(config_dir),
        "target": base_url or "in-process",
    }


def build_report(
    scenarios: Sequence[LoadScenario] = DEFAULT_SCENARIOS,
    *,
    concurrencies: Sequence[int] = DEFAULT_CONCURRENCIES,
    requests_per_scenario: int = 50,
    warmup: int = 2,
    client_factory: Callable[[], Any],
    base_url: str = "",
    config_dir: str | Path = DEFAULT_CONFIG_DIR,
    label: str = DEFAULT_LABEL,
    clock: Callable[[], float] = time.perf_counter,
) -> Dict[str, Any]:
    """Run the plan and wrap it in a provenance-stamped report."""
    result = run_load(
        scenarios,
        concurrencies=concurrencies,
        requests_per_scenario=requests_per_scenario,
        warmup=warmup,
        client_factory=client_factory,
        base_url=base_url,
        clock=clock,
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "kind": "reference_load",
        "reference_baselines": True,
        "label": label,
        "caveats": list(DEFAULT_CAVEATS),
        "provenance": collect_provenance(config_dir, base_url=base_url),
        "configuration": {
            "concurrencies": list(concurrencies),
            "requests_per_scenario": requests_per_scenario,
            "warmup": warmup,
            "scenarios": [scenario.name for scenario in scenarios],
        },
        **result,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a load report as Markdown (all numbers come from the report)."""
    provenance = report.get("provenance") or {}
    configuration = report.get("configuration") or {}
    runs = report.get("runs") or []
    summary = report.get("summary") or {}

    lines: List[str] = [
        "# Reference load/latency report",
        "",
        f"> {report.get('label', DEFAULT_LABEL)}",
        "",
    ]
    for caveat in report.get("caveats") or []:
        lines.append(f"> - {caveat}")
    lines += [
        "",
        "## Provenance",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Git commit | `{provenance.get('git_sha', '')}` |",
        f"| Generated (UTC) | {provenance.get('timestamp', '')} |",
        f"| Platform | {provenance.get('platform', '')} |",
        f"| CPU | {provenance.get('processor', 'unknown')} "
        f"({provenance.get('cpu_count', '?')} cores) |",
        f"| Python | {provenance.get('python_version', '')} |",
        f"| Target | {provenance.get('target', '')} |",
        f"| Config dir | `{provenance.get('config_dir', '')}` |",
        "",
        "## Configuration",
        "",
        f"- Scenarios: {', '.join(configuration.get('scenarios') or [])}",
        f"- Concurrency levels: {', '.join(str(c) for c in configuration.get('concurrencies') or [])}",
        f"- Requests per scenario: {configuration.get('requests_per_scenario')}",
        f"- Warmup requests (uncounted): {configuration.get('warmup')}",
        "",
        "## Results",
        "",
        "| Scenario | Concurrency | Requests | Errors | Error rate | Req/s | "
        "p50 (ms) | p95 (ms) | p99 (ms) | Mean (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in runs:
        latency = run.get("latency") or {}
        lines.append(
            f"| {run.get('scenario')} | {run.get('concurrency')} | {run.get('count')} | "
            f"{run.get('errors')} | {float(run.get('error_rate') or 0.0):.4f} | "
            f"{float(run.get('requests_per_second') or 0.0):.2f} | "
            f"{float(latency.get('p50_ms') or 0.0):.2f} | "
            f"{float(latency.get('p95_ms') or 0.0):.2f} | "
            f"{float(latency.get('p99_ms') or 0.0):.2f} | "
            f"{float(latency.get('mean_ms') or 0.0):.2f} |"
        )

    stage_runs = [run for run in runs if run.get("stages")]
    if stage_runs:
        lines += [
            "",
            "## Per-stage latency (mean / p95, ms)",
            "",
            "| Scenario | Concurrency | Stage | Mean | p95 |",
            "| --- | ---: | --- | ---: | ---: |",
        ]
        for run in stage_runs:
            for stage, values in (run.get("stages") or {}).items():
                lines.append(
                    f"| {run.get('scenario')} | {run.get('concurrency')} | {stage} | "
                    f"{float(values.get('mean_ms') or 0.0):.2f} | "
                    f"{float(values.get('p95_ms') or 0.0):.2f} |"
                )

    lines += [
        "",
        "## Summary",
        "",
        f"- Total requests: {summary.get('total_requests')}",
        f"- Total errors: {summary.get('total_errors')} "
        f"(error rate {float(summary.get('error_rate') or 0.0):.4f})",
        f"- Runs: {summary.get('runs')}",
        "",
        "These are reference CPU baselines; do not present them as production "
        "throughput or SLO compliance.",
        "",
    ]
    return "\n".join(lines)


def write_report(
    report: Mapping[str, Any],
    *,
    out: Optional[str | Path] = None,
    markdown: Optional[str | Path] = None,
) -> None:
    if out:
        Path(out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if markdown:
        Path(markdown).write_text(render_markdown(report), encoding="utf-8")
