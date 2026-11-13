"""Guards for committed benchmark result artifacts (issue #198).

These tests treat ``docs/benchmarks`` as published evidence: every committed
report must be internally consistent, its dataset/config hashes must still
match the repo, the generated index must not drift, and every documented link
must resolve.
"""

from __future__ import annotations

import re
from typing import List

import pytest

from app import benchmark_results as benchmark_results_cli
from core.evaluation.benchmark_results import (
    discover_results,
    index_problems,
    render_results_index,
    validate_result,
)
from core.evaluation.showcase_report import REPO_ROOT

BENCHMARKS_DIR = REPO_ROOT / "docs" / "benchmarks"
RESULTS_DIR = BENCHMARKS_DIR / "results"
INDEX_PATH = BENCHMARKS_DIR / "README.md"
README = REPO_ROOT / "README.md"

DISCOVERED = discover_results(RESULTS_DIR)


def _result_entries():
    return DISCOVERED["entries"]


def test_at_least_one_reference_result_is_published() -> None:
    entries = _result_entries()
    assert entries, "expected a committed reference result under docs/benchmarks/results"
    for entry in entries:
        assert entry.suite.get("suite") == "reference"


@pytest.mark.parametrize("entry", _result_entries(), ids=lambda entry: entry.stem)
def test_committed_result_passes_integrity_checks(entry) -> None:
    assert entry.problems == []
    assert validate_result(entry.report, path=entry.json_path) == []
    assert entry.md_path is not None
    assert entry.csv_path is not None
    assert {path.name for path in entry.svg_paths} == {
        f"{entry.stem}-pareto.svg",
        f"{entry.stem}-latency.svg",
    }


def test_committed_results_cover_all_corpora() -> None:
    for entry in _result_entries():
        assert entry.dataset_names == ["enterprise-it", "product-docs", "support"]
        assert entry.report["num_combinations"] == 4
        for dataset in entry.report["datasets"]:
            assert dataset["path"].startswith("benchmarks/data/")


def test_no_orphaned_or_invalid_artifacts() -> None:
    assert DISCOVERED["orphans"] == []
    assert index_problems(DISCOVERED) == []


def test_generated_index_matches_the_reports() -> None:
    assert INDEX_PATH.exists()
    expected = render_results_index(DISCOVERED)
    assert INDEX_PATH.read_text(encoding="utf-8") == expected
    assert benchmark_results_cli.main(["--check"]) == 0


def test_index_links_resolve() -> None:
    index = INDEX_PATH.read_text(encoding="utf-8")
    links: List[str] = re.findall(r"\]\((?!https?://)([^)#]+)\)", index)
    assert links
    for link in links:
        target = (INDEX_PATH.parent / link).resolve()
        assert target.exists(), f"broken link in {INDEX_PATH}: {link}"


def test_results_index_links_quality_and_load_evidence() -> None:
    index = INDEX_PATH.read_text(encoding="utf-8")
    assert "[methodology.md](methodology.md)" in index
    assert "[load.md](load.md)" in index
    assert "[load-methodology.md](load-methodology.md)" in index
    for name in ("methodology.md", "load.md", "load-methodology.md"):
        assert (BENCHMARKS_DIR / name).exists()


def test_readme_points_at_published_results() -> None:
    readme = README.read_text(encoding="utf-8")
    assert "docs/benchmarks/README.md" in readme
    assert "docs/benchmarks/methodology.md" in readme
    assert (REPO_ROOT / "docs/benchmarks/README.md").exists()
    assert (REPO_ROOT / "docs/benchmarks/methodology.md").exists()


def test_reports_are_reproducible_from_their_recorded_snapshot() -> None:
    for entry in _result_entries():
        provenance = entry.provenance
        snapshot = provenance["config_snapshot"]
        assert "reference:" in snapshot
        assert entry.stem.endswith(provenance["git_sha"][:7])
        assert entry.stem.startswith(provenance["timestamp"][:10])
