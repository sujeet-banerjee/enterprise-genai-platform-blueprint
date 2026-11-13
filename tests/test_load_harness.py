"""Tests for the reference load/latency harness (issue #197)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from core.evaluation import load_harness
from core.evaluation.load_harness import (
    DEFAULT_SCENARIOS,
    MAX_CONCURRENCY,
    LoadHarnessError,
    LoadScenario,
    build_report,
    expand_plan,
    percentile,
    render_markdown,
    run_load,
    summarize,
    write_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "benchmarks" / "load" / "run_load.py"
SMOKE_CONFIG = "deployment/smoke/config"


class _FakeResponse:
    def __init__(self, status_code: int, body: Optional[Dict[str, Any]] = None) -> None:
        self.status_code = status_code
        self._body = body if body is not None else {}

    def json(self) -> Dict[str, Any]:
        return self._body


class _CountingClient:
    """Deterministic fake client; can inject the first ``fail_first`` failures."""

    def __init__(
        self,
        *,
        fail_first: int = 0,
        status: int = 200,
        body: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.fail_first = fail_first
        self.status = status
        self.body = body if body is not None else {}
        self.calls = 0

    def request(self, method: str, url: str, json: Any = None) -> _FakeResponse:
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError("injected failure")
        return _FakeResponse(self.status, self.body)


def _scenario(name: str = "query") -> LoadScenario:
    return LoadScenario(name, "POST", "/v1/query", payload={"query": "hi"})


def _load_cli() -> Any:
    spec = importlib.util.spec_from_file_location("load_run_cli", CLI_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_percentile_matches_known_samples() -> None:
    samples = [1, 2, 3, 4]
    assert percentile(samples, 0) == pytest.approx(1.0)
    assert percentile(samples, 50) == pytest.approx(2.5)
    assert percentile(samples, 95) == pytest.approx(3.85)
    assert percentile(samples, 99) == pytest.approx(3.97)
    assert percentile(samples, 100) == pytest.approx(4.0)
    assert percentile([7], 95) == pytest.approx(7.0)
    assert percentile([], 95) == 0.0
    with pytest.raises(LoadHarnessError):
        percentile([1, 2], 101)


def test_summarize_reports_all_percentiles() -> None:
    summary = summarize([10.0, 20.0, 30.0, 40.0])
    assert summary["count"] == 4
    assert summary["mean_ms"] == pytest.approx(25.0)
    assert summary["min_ms"] == 10.0
    assert summary["max_ms"] == 40.0
    assert summary["p50_ms"] == pytest.approx(25.0)
    assert summary["p95_ms"] == pytest.approx(38.5)
    assert summarize([])["count"] == 0


def test_expand_plan_is_deterministic_and_bounded() -> None:
    plan = expand_plan([_scenario("a"), _scenario("b")], [1, 4, 4], 5)
    assert [(item["scenario"].name, item["concurrency"]) for item in plan] == [
        ("a", 1),
        ("a", 4),
        ("b", 1),
        ("b", 4),
    ]
    assert all(item["requests"] == 5 for item in plan)

    with pytest.raises(LoadHarnessError):
        expand_plan([], [1], 5)
    with pytest.raises(LoadHarnessError):
        expand_plan([_scenario()], [1], 0)
    with pytest.raises(LoadHarnessError):
        expand_plan([_scenario()], [MAX_CONCURRENCY + 1], 5)
    with pytest.raises(LoadHarnessError):
        expand_plan([_scenario()], [1], load_harness.MAX_REQUESTS_PER_SCENARIO + 1)
    with pytest.raises(LoadHarnessError):
        expand_plan([_scenario("dup"), _scenario("dup")], [1], 5)


def test_run_load_counts_requests_and_errors() -> None:
    client = _CountingClient(fail_first=3)
    report = run_load(
        [_scenario()],
        concurrencies=[1],
        requests_per_scenario=10,
        warmup=0,
        client_factory=lambda: client,
    )
    run = report["runs"][0]
    assert run["count"] == 10
    assert run["errors"] == 3
    assert run["error_rate"] == pytest.approx(0.3)
    assert run["status_counts"] == {"0": 3, "200": 7}
    assert run["sample_errors"]
    assert report["summary"]["total_requests"] == 10
    assert report["summary"]["total_errors"] == 3
    assert report["summary"]["error_rate"] == pytest.approx(0.3)


def test_run_load_records_stage_latency_and_one_run_per_plan_item() -> None:
    body = {"latency": {"total_ms": 5.0, "retrieval_ms": 2.0, "note": "ignored"}}
    report = run_load(
        [DEFAULT_SCENARIOS[2], DEFAULT_SCENARIOS[0]],
        concurrencies=[1, 2],
        requests_per_scenario=3,
        warmup=0,
        client_factory=lambda: _CountingClient(body=body),
    )
    assert len(report["runs"]) == 4
    assert all(run["count"] == 3 for run in report["runs"])
    query_run = next(run for run in report["runs"] if run["scenario"] == "query")
    assert query_run["stages"]["total_ms"]["mean_ms"] == pytest.approx(5.0)
    assert query_run["stages"]["retrieval_ms"]["p95_ms"] == pytest.approx(2.0)
    assert "note" not in query_run["stages"]


def test_build_report_has_provenance_and_reference_label() -> None:
    report = build_report(
        [_scenario()],
        concurrencies=[1],
        requests_per_scenario=2,
        warmup=0,
        client_factory=lambda: _CountingClient(),
        config_dir=SMOKE_CONFIG,
    )
    assert report["schema_version"] == load_harness.REPORT_SCHEMA_VERSION
    assert report["kind"] == "reference_load"
    assert report["reference_baselines"] is True
    assert "not production throughput" in report["label"]
    assert report["caveats"]

    provenance = report["provenance"]
    assert provenance["git_sha"] not in ("", "unknown")
    assert provenance["timestamp"]
    assert provenance["platform"]
    assert provenance["python_version"]
    assert provenance["cpu_count"]
    assert provenance["config_dir"] == SMOKE_CONFIG
    assert provenance["target"] == "in-process"


def test_render_markdown_contains_provenance_and_rows() -> None:
    report = build_report(
        DEFAULT_SCENARIOS[:2],
        concurrencies=[1],
        requests_per_scenario=2,
        warmup=0,
        client_factory=lambda: _CountingClient(body={"latency": {"total_ms": 3.0}}),
        config_dir=SMOKE_CONFIG,
    )
    markdown = render_markdown(report)
    assert "# Reference load/latency report" in markdown
    assert report["provenance"]["git_sha"] in markdown
    assert report["label"] in markdown
    assert "health" in markdown and "ready" in markdown
    assert "Per-stage latency" in markdown
    assert "reference CPU baselines" in markdown


def test_write_report_round_trips_json_and_markdown(tmp_path: Path) -> None:
    report = build_report(
        [_scenario()],
        concurrencies=[1],
        requests_per_scenario=2,
        warmup=0,
        client_factory=lambda: _CountingClient(),
        config_dir=SMOKE_CONFIG,
    )
    out = tmp_path / "load.json"
    md = tmp_path / "load.md"
    write_report(report, out=out, markdown=md)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["runs"] == report["runs"]
    assert loaded["provenance"]["git_sha"] == report["provenance"]["git_sha"]
    assert md.read_text(encoding="utf-8").startswith("# Reference load/latency report")


def test_cli_rejects_unknown_scenario_and_invalid_requests() -> None:
    cli = _load_cli()
    assert (
        cli.main(
            ["--in-process", "--config-dir", SMOKE_CONFIG, "--scenarios", "bogus"]
        )
        == 2
    )
    assert (
        cli.main(
            ["--in-process", "--config-dir", SMOKE_CONFIG, "--requests", "0"]
        )
        == 2
    )


def test_cli_in_process_e2e_boots_api_and_emits_json_and_markdown(tmp_path: Path) -> None:
    out = tmp_path / "load.json"
    md = tmp_path / "load.md"
    result = subprocess.run(
        [
            sys.executable,
            str(CLI_PATH),
            "--in-process",
            "--config-dir",
            SMOKE_CONFIG,
            "--concurrency",
            "1",
            "--requests",
            "2",
            "--warmup",
            "1",
            "--scenarios",
            "health,ready,query",
            "--out",
            str(out),
            "--markdown",
            str(md),
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["kind"] == "reference_load"
    assert report["reference_baselines"] is True
    assert report["provenance"]["git_sha"] not in ("", "unknown")
    assert report["summary"]["total_requests"] == 6
    assert {run["scenario"] for run in report["runs"]} == {"health", "ready", "query"}
    assert all(run["errors"] == 0 for run in report["runs"])
    assert all(run["status_counts"].get("200") == 2 for run in report["runs"])
    assert "Reference load/latency report" in md.read_text(encoding="utf-8")
