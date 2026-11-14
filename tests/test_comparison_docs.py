"""Structural guards for docs/comparison.md (#199).

These tests keep the comparison honest and maintainable: every cited code path
must exist, every external source needs a URL and an access date, local links
must resolve, and comparative language must stay criterion-based.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_BASE = Path(__file__).resolve().parents[1]
COMPARISON = REPO_BASE / "docs" / "comparison.md"
README = REPO_BASE / "README.md"

REQUIRED_DIMENSIONS = (
    "Config-driven vendor neutrality",
    "Evaluation",
    "Governance and guardrails",
    "Observability",
    "Deployment",
    "Console",
    "Multi-tenancy and identity",
    "Persistence",
    "Licence",
)

REQUIRED_ALTERNATIVES = (
    "LangChain",
    "LlamaIndex",
    "RAGAS",
    "Amazon Bedrock",
    "Google Cloud Vertex AI",
    "Azure AI Foundry",
    "Databricks (Mosaic AI)",
    "Glean",
    "LangSmith",
    "Langfuse",
    "Arize",
    "TruLens",
)

SOURCE_RE = re.compile(
    r"\*\*Source:\*\*\s+(https?://\S+)\s+\(accessed\s+(\d{4}-\d{2}-\d{2})\)"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    level = len(heading) - len(heading.lstrip("#"))
    pattern = re.compile(rf"^#{{{1},{level}}} ", re.MULTILINE)
    match = pattern.search(text, start + len(heading))
    end = match.start() if match else len(text)
    return text[start:end]


def _evidence_paths(text: str) -> list[str]:
    section = _section(text, "## What this repository implements (evidence)")
    prefixes = (
        "core/",
        "app/",
        "config/",
        "docs/",
        "ui/",
        "tests/",
        "benchmarks/",
        "deployment/",
        ".devcontainer/",
    )
    paths: list[str] = []
    for token in re.findall(r"`([^`]+)`", section):
        token = token.strip()
        if token.startswith(prefixes):
            paths.append(token.rstrip("/"))
    return paths


def test_comparison_doc_covers_every_required_dimension() -> None:
    doc = _read(COMPARISON)
    missing = [dimension for dimension in REQUIRED_DIMENSIONS if dimension not in doc]
    assert not missing, f"comparison.md omits dimensions: {missing}"


def test_every_alternative_has_a_source_url_and_access_date() -> None:
    doc = _read(COMPARISON)
    alternatives = _section(doc, "## Alternatives")
    sections = re.split(r"^### ", alternatives, flags=re.MULTILINE)[1:]
    found = {section.splitlines()[0].strip(): section for section in sections}
    missing = [name for name in REQUIRED_ALTERNATIVES if name not in found]
    assert not missing, f"comparison.md omits alternatives: {missing}"
    for name in REQUIRED_ALTERNATIVES:
        match = SOURCE_RE.search(found[name])
        assert match, f"{name} needs a Source URL with an access date"
        assert match.group(1).startswith("https://"), f"{name} source must use HTTPS"


def test_alternative_sections_list_where_the_alternative_is_stronger() -> None:
    doc = _read(COMPARISON)
    alternatives = _section(doc, "## Alternatives")
    sections = re.split(r"^### ", alternatives, flags=re.MULTILINE)[1:]
    for section in sections:
        name = section.splitlines()[0].strip()
        assert "**Where it is stronger:**" in section, (
            f"{name} must state where the alternative is stronger"
        )


def test_every_cited_capability_path_exists() -> None:
    paths = _evidence_paths(_read(COMPARISON))
    assert len(paths) >= 20, f"expected a substantial evidence table, found {len(paths)}"
    missing = sorted({path for path in paths if not (REPO_BASE / path).exists()})
    assert not missing, f"evidence table cites missing paths: {missing}"


def test_no_unqualified_superiority_claims() -> None:
    doc = _read(COMPARISON).lower()
    for phrase in ("better than", "superior to", "outperforms", "better product"):
        assert phrase not in doc, f"unqualified comparative claim: {phrase!r}"
    assert "where alternatives are stronger" in doc


def test_where_alternatives_are_stronger_states_its_criteria() -> None:
    doc = _read(COMPARISON)
    section = _section(doc, "## Where alternatives are stronger")
    assert section.count("Criterion:") >= 6, (
        "each weakness must name the criterion it is judged on"
    )
    for expected in ("operational burden", "connector coverage", "metric", "UI"):
        assert expected.lower() in section.lower(), f"missing criterion: {expected}"


def test_local_links_resolve_from_the_docs_directory() -> None:
    broken: list[str] = []
    for target in re.findall(r"\]\(([^)]+)\)", _read(COMPARISON)):
        target = target.strip()
        if target.startswith(("http://", "https://", "mailto:", "#")) or target.startswith("<"):
            continue
        path = target.split("#", 1)[0]
        if not path:
            continue
        if not (COMPARISON.parent / path).resolve().exists():
            broken.append(target)
    assert not broken, f"comparison.md links point at missing paths: {sorted(set(broken))}"


def test_readme_links_the_comparison_from_the_proof_sections() -> None:
    readme = _read(README)
    assert "### How this compares to alternatives" in readme
    assert "docs/comparison.md" in readme
    assert (REPO_BASE / "docs" / "comparison.md").exists()
