"""Tests for issue #195: showcase benchmark corpora + suite config.

Covers the acceptance criteria:
* every shipped corpus loads through the canonical eval-dataset loader;
* labels are internally consistent (valid/unique ids, non-empty references);
* each suite covers multi-hop, unanswerable, injection and PII cases;
* ``config/benchmarks.yaml`` validates, is disabled by default and rejects
  unknown top-level keys;
* the ``quick`` profile resolves a bounded, deterministic subset.
"""

from pathlib import Path

import pytest

from core.config.schema import SCHEMAS, BenchmarksConfig
from core.config.validator import validate_config_data
from core.evaluation.benchmarks import (
    BenchmarkConfigError,
    is_enabled,
    load_benchmarks_config,
    load_suite,
    load_suite_datasets,
    resolve_dataset_specs,
    resolve_suite,
    suite_summary,
)
from core.evaluation.eval_datasets import load_eval_dataset

REPO_ROOT = Path(__file__).resolve().parents[1]
SUITES = ("enterprise-it", "product-docs", "support")


def _config():
    return load_benchmarks_config()


# -- corpora ---------------------------------------------------------------


@pytest.mark.parametrize("name", SUITES)
def test_showcase_corpora_load_with_consistent_labels(name):
    dataset = load_eval_dataset(
        f"benchmarks/data/{name}/benchmark.json", name=name
    )
    assert dataset.kind == "ir_benchmark"
    assert len(dataset.docs) >= 30
    assert len(dataset.cases) >= 25
    assert dataset.metadata.get("version")
    assert dataset.metadata.get("domain") == name

    seen_docs = set()
    for doc in dataset.docs:
        assert doc.get("content", "").strip()
        seen_docs.add(doc["content"])
    assert len(seen_docs) == len(dataset.docs), "documents must be unique"

    for case in dataset.cases:
        assert case.query
        assert case.reference
        assert len(case.relevant_doc_ids) == len(set(case.relevant_doc_ids))
        assert all(0 <= doc_id < len(dataset.docs) for doc_id in case.relevant_doc_ids)


@pytest.mark.parametrize("name", SUITES)
def test_each_corpus_covers_adversarial_and_multi_hop_tags(name):
    dataset = load_eval_dataset(
        f"benchmarks/data/{name}/benchmark.json", name=name
    )
    tags = {tag for case in dataset.cases for tag in case.tags}
    assert {"multi_hop", "unanswerable", "injection", "pii"} <= tags
    unanswerable = [case for case in dataset.cases if "unanswerable" in case.tags]
    assert unanswerable and all(case.relevant_doc_ids == () for case in unanswerable)


# -- config ----------------------------------------------------------------


def test_shipped_benchmark_config_is_valid_and_disabled_by_default():
    assert "benchmarks" in SCHEMAS and SCHEMAS["benchmarks"] is BenchmarksConfig
    config = _config()
    assert is_enabled(config) is False
    assert config["default_suite"] == "showcase"
    assert validate_config_data(config, "benchmarks") == []


def test_schema_rejects_unknown_top_level_keys():
    issues = validate_config_data({"enabled": False, "bogus": 1}, "benchmarks")
    assert issues and any(
        "bogus" in issue.path or "bogus" in issue.message for issue in issues
    )


def test_quick_suite_resolves_bounded_deterministic_subset():
    config = _config()
    suite = resolve_suite(config, "quick")
    assert suite["datasets"] == ["support"]
    assert suite["max_cases"] == 8
    assert suite["max_combinations"] == 4
    first = load_suite_datasets(config, suite)
    second = load_suite_datasets(config, suite)
    assert [dataset.name for dataset in first] == ["support"]
    assert len(first[0].cases) == 8
    assert [case.query for case in first[0].cases] == [
        case.query for case in second[0].cases
    ]
    assert len(first[0].docs) == 40


def test_showcase_suite_resolves_all_datasets_and_paths_exist():
    config = _config()
    suite = resolve_suite(config, "showcase")
    assert suite["datasets"] == list(SUITES)
    assert suite["max_cases"] == 0
    assert suite["max_combinations"] == 24
    specs = resolve_dataset_specs(config, suite)
    assert [name for name, _ in specs] == list(SUITES)
    for _, path in specs:
        assert (REPO_ROOT / path).exists()

    datasets = load_suite_datasets(config, suite)
    assert [dataset.name for dataset in datasets] == list(SUITES)
    assert all(len(dataset.cases) >= 25 for dataset in datasets)


def test_unknown_suite_and_unknown_dataset_raise():
    config = _config()
    with pytest.raises(BenchmarkConfigError, match="Unknown suite"):
        resolve_suite(config, "does-not-exist")

    broken = dict(config)
    broken["suites"] = {
        "broken": {"datasets": ["missing-dataset"], "max_cases": 1}
    }
    broken["default_suite"] = "broken"
    with pytest.raises(BenchmarkConfigError, match="unknown dataset"):
        resolve_suite(broken)


def test_max_cases_zero_keeps_all_cases():
    config = _config()
    suite = resolve_suite(config, "showcase")
    datasets = load_suite_datasets(config, suite)
    for dataset in datasets:
        assert len(dataset.cases) == len(
            load_eval_dataset(dataset.path, name=dataset.name).cases
        )


def test_load_suite_and_summary_shape():
    suite, datasets = load_suite("quick", config_path="config/benchmarks.yaml")
    summary = suite_summary(suite, datasets)
    assert summary["suite"] == "quick"
    assert summary["max_cases"] == 8
    assert summary["datasets"][0]["name"] == "support"
    assert summary["datasets"][0]["num_docs"] == 40
    assert summary["datasets"][0]["num_cases"] == 8
    assert summary["objective"] == {"quality": "context_recall"}
