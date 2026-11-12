"""Budget-aware regression gates (issue #180).

Quality metrics are lower bounds (``min``); cost and latency budgets are upper
bounds (``max``). The gate must fail a candidate config that is cheaper-but-worse
or better-but-slower/pricier, and must accept a pre-computed experiment report.
"""

from __future__ import annotations

import json

import yaml

from app.eval_gate import main
from core.evaluation.regression_gate import (
    configured_regression_thresholds,
    evaluate_report_thresholds,
    normalize_threshold_spec,
)


def test_normalize_threshold_spec_quality_and_budget_directions():
    spec = normalize_threshold_spec(
        {
            "recall": {"min": 0.7},
            "cost_usd": 0.01,
            "p95_latency_ms": {"max": 200},
            "avg_latency_ms": 150,
            "unknown_metric": 1.0,
        }
    )
    assert spec["context_recall"] == (0.7, "min")
    assert spec["max_cost_per_request_usd"] == (0.01, "max")
    assert spec["max_p95_latency_ms"] == (200.0, "max")
    assert spec["max_avg_latency_ms"] == (150.0, "max")
    assert "unknown_metric" not in spec


def test_quality_only_thresholds_remain_backward_compatible():
    result = evaluate_report_thresholds(
        {"context_precision": 0.8, "context_recall": 0.9},
        {"context_precision": 0.8, "context_recall": 0.9},
    )
    assert result.passed is True
    assert result.directions == {"context_precision": "min", "context_recall": "min"}
    assert result.to_dict()["directions"] == result.directions


def test_passes_when_quality_and_budgets_are_within_limits():
    report = {
        "metrics": {"context_recall": 0.85},
        "cost": {"estimated_cost_usd": 0.004},
        "latency": {"total_ms": 120.0, "p95_ms": 180.0},
    }
    result = evaluate_report_thresholds(
        report,
        {
            "context_recall": 0.8,
            "max_cost_per_request_usd": 0.01,
            "max_p95_latency_ms": 200,
            "max_avg_latency_ms": 150,
        },
    )
    assert result.passed is True
    assert result.failures == []
    assert result.metrics["max_cost_per_request_usd"] == 0.004


def test_fails_when_cost_exceeds_budget():
    report = {"metrics": {"context_recall": 0.9}, "cost": {"estimated_cost_usd": 0.02}}
    result = evaluate_report_thresholds(
        report, {"context_recall": 0.8, "max_cost_per_request_usd": 0.01}
    )
    assert result.passed is False
    assert any(
        "max_cost_per_request_usd" in failure and "0.020000 > 0.010000" in failure
        for failure in result.failures
    )


def test_fails_when_p95_latency_exceeds_budget():
    report = {"latency": {"p95_ms": 450.0}}
    result = evaluate_report_thresholds(report, {"max_p95_latency_ms": 300})
    assert result.passed is False
    assert any("450.000000 > 300.000000" in failure for failure in result.failures)


def test_fails_when_budget_metric_is_missing():
    result = evaluate_report_thresholds({"context_recall": 0.9}, {"max_p95_latency_ms": 100})
    assert result.passed is False
    assert any(
        "max_p95_latency_ms: missing (required <= 100" in failure
        for failure in result.failures
    )


def test_extracts_nested_experiment_run_shape():
    run = {
        "metrics": {"context_recall": 0.85},
        "cost": {"estimated_cost_usd": 0.02},
        "latency": {"total_ms": 250.0},
        "latency_summary": {"total_ms": 250.0},
    }
    result = evaluate_report_thresholds(
        run,
        {
            "context_recall": 0.8,
            "max_cost_per_request_usd": 0.05,
            "max_avg_latency_ms": 300,
            "max_total_latency_ms": 300,
        },
    )
    assert result.passed is True


def test_extracts_comparison_summary_shape():
    comparison = {
        "runs": {"a": {"cost_usd": 0.01}, "b": {"cost_usd": 0.02}},
        "avg_cost_usd": 0.015,
        "avg_total_latency_ms": 120.0,
    }
    result = evaluate_report_thresholds(
        comparison,
        {"max_cost_per_request_usd": 0.02, "max_avg_latency_ms": 150},
    )
    assert result.passed is True
    assert result.metrics["max_cost_per_request_usd"] == 0.015
    assert result.metrics["max_avg_latency_ms"] == 120.0


def test_configured_thresholds_reads_regression_block(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "eval_datasets.yaml").write_text(
        yaml.safe_dump(
            {
                "eval_datasets": {
                    "regression": {
                        "enabled": True,
                        "thresholds": {"context_recall": 0.5, "max_cost_per_request_usd": 0.02},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert configured_regression_thresholds(config_dir) == {
        "context_recall": 0.5,
        "max_cost_per_request_usd": 0.02,
    }


def test_cli_report_passes_then_fails(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "dataset": "bench",
                "metrics": {"context_recall": 0.9},
                "cost": {"estimated_cost_usd": 0.005},
                "latency": {"total_ms": 100.0},
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--report",
                str(report_path),
                "--threshold",
                "context_recall=0.8",
                "--threshold",
                "max_cost_per_request_usd=0.01",
                "--json",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--report",
                str(report_path),
                "--threshold",
                "max_cost_per_request_usd=0.001",
                "--json",
            ]
        )
        == 1
    )


def test_cli_report_without_thresholds_returns_2(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"metrics": {"context_recall": 0.9}}), encoding="utf-8")
    empty_config = tmp_path / "config"
    empty_config.mkdir()
    assert main(["--report", str(report_path), "--config-dir", str(empty_config)]) == 2


def test_cli_report_invalid_json_returns_2(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text("{not json", encoding="utf-8")
    assert main(["--report", str(report_path), "--threshold", "context_recall=0.5"]) == 2


def test_cli_report_supports_list_of_reports(tmp_path):
    report_path = tmp_path / "reports.json"
    report_path.write_text(
        json.dumps(
            [
                {"dataset": "a", "metrics": {"context_recall": 0.9}, "cost": {"estimated_cost_usd": 0.001}},
                {"dataset": "b", "metrics": {"context_recall": 0.4}, "cost": {"estimated_cost_usd": 0.001}},
            ]
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--report",
                str(report_path),
                "--threshold",
                "context_recall=0.5",
                "--threshold",
                "max_cost_per_request_usd=0.01",
                "--json",
            ]
        )
        == 1
    )
