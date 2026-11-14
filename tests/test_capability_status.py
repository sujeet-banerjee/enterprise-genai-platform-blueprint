"""Guards for the capability status matrix (#191).

docs/capability-status.md is the canonical, evidence-based answer to "what is
actually implemented here?". These tests fail when a row cites a path that no
longer exists, when an unknown status word appears, when a tracked gap loses its
issue link, or when the README/roadmap stop pointing at the matrix.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_BASE = Path(__file__).resolve().parents[1]
CAPABILITY = REPO_BASE / "docs" / "capability-status.md"
README = REPO_BASE / "README.md"
ROADMAP = REPO_BASE / "docs" / "enterprise-roadmap.md"

ALLOWED_STATUSES = {"Tested", "Implemented", "Partial", "Planned", "External"}
FORBIDDEN_CLAIMS = (
    "production-ready",
    "production ready",
    "battle-tested",
    "proven at scale",
    "trusted by",
    "sla-backed",
    "certified for production",
    "enterprise-grade",
)
# Every gap the matrix must keep visible (the current open roadmap/qualification set).
REQUIRED_GAP_ISSUES = {"#43", "#192", "#204", "#205", "#206"}
# Sections the matrix must keep so coverage cannot silently shrink.
REQUIRED_SECTIONS = (
    "## How to read the status",
    "## Platform core",
    "## Evaluation, experiments and gating",
    "## Governance, identity and safety",
    "## Observability and operations",
    "## Console and delivery",
    "## Planned or unqualified",
    "## Where the gaps are tracked",
    "## Maintenance",
)

PATH_RE = re.compile(r"`([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+)`")
ISSUE_RE = re.compile(r"#(\d+)")
STATUS_ROW_RE = re.compile(r"^\| ([^|]+?) \| (Tested|Implemented|Partial|Planned|External) \|", re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _cited_paths(text: str) -> set[str]:
    paths: set[str] = set()
    for token in PATH_RE.findall(text):
        if token.startswith(("http", "www")):
            continue
        paths.add(token)
    return paths


def _assert_local_links_resolve(path: Path) -> None:
    broken: list[str] = []
    for target in re.findall(r"\]\(([^)]+)\)", _read(path)):
        target = target.strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        destination = target.split("#", 1)[0]
        if destination and not (path.parent / destination).resolve().exists():
            broken.append(target)
    assert not broken, f"{path.name} links point at missing paths: {sorted(set(broken))}"


def test_capability_document_exists_with_an_h1_and_legend() -> None:
    assert CAPABILITY.is_file(), "docs/capability-status.md is missing"
    text = _read(CAPABILITY)
    assert text.splitlines()[0].startswith("# "), "capability-status.md needs an H1"
    for status in ALLOWED_STATUSES:
        assert f"**{status}**" in text, f"legend omits the {status!r} status"


def test_capability_document_keeps_its_sections() -> None:
    text = _read(CAPABILITY)
    for section in REQUIRED_SECTIONS:
        assert section in text, f"capability-status.md lost section {section!r}"


def test_every_status_word_in_a_row_is_in_the_vocabulary() -> None:
    text = _read(CAPABILITY)
    status_rows = STATUS_ROW_RE.findall(text)
    assert len(status_rows) >= 40, f"expected a substantial matrix, found {len(status_rows)} status rows"
    for _capability, status in status_rows:
        assert status in ALLOWED_STATUSES


def test_cited_code_and_test_paths_exist() -> None:
    text = _read(CAPABILITY)
    missing: list[str] = []
    for token in sorted(_cited_paths(text)):
        if token.endswith((".md", ".py", ".json", ".yaml", ".yml", ".sh", ".toml", ".cfg")):
            if not (REPO_BASE / token).exists():
                missing.append(token)
        elif token.endswith("/"):
            if not (REPO_BASE / token).is_dir():
                missing.append(token)
        elif "." in Path(token).name and not (REPO_BASE / token).exists():
            # A file-looking token (has an extension) that is neither dir nor file.
            if not (REPO_BASE / token).is_dir():
                missing.append(token)
    assert not missing, f"capability-status.md cites non-existent paths: {sorted(set(missing))}"


def test_every_cited_test_file_exists() -> None:
    tokens = [t for t in _cited_paths(_read(CAPABILITY)) if t.startswith("tests/")]
    assert tokens, "the matrix must cite test evidence"
    missing = [t for t in sorted(set(tokens)) if not (REPO_BASE / t).exists()]
    assert not missing, f"capability-status.md cites missing test files: {missing}"


def test_tracked_gaps_stay_linked() -> None:
    text = _read(CAPABILITY)
    for issue in REQUIRED_GAP_ISSUES:
        assert issue in text, f"capability-status.md no longer references tracked gap {issue}"
    assert "issues/" in text, "gap references should link to GitHub issues"


def test_capability_copy_avoids_unsupported_claims() -> None:
    lowered = _read(CAPABILITY).lower()
    for claim in FORBIDDEN_CLAIMS:
        assert claim not in lowered, f"capability-status.md makes unsupported claim {claim!r}"


def test_readme_links_to_the_capability_matrix() -> None:
    assert "docs/capability-status.md" in _read(README)
    _assert_local_links_resolve(README)


def test_roadmap_links_to_the_capability_matrix() -> None:
    assert "capability-status.md" in _read(ROADMAP), "roadmap must point at the capability matrix"


def test_capability_document_local_links_resolve() -> None:
    _assert_local_links_resolve(CAPABILITY)


def test_roadmap_reconciliation_removed_stale_markers() -> None:
    text = _read(ROADMAP)
    assert "507 tests" not in text, "roadmap still quotes the stale test count"
    assert "20+ endpoints" not in text, "roadmap still quotes the stale endpoint count"
    assert "Issue IDs are placeholders (`E-*`)" not in text, "roadmap still claims issues are uncreated"
