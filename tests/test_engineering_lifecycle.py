"""Structural guards for docs/engineering-lifecycle.md (#190).

The lifecycle document makes operational claims (which checks block a merge,
what agents may assume, how evidence is reported). These tests keep it honest:
required checks must match the CI workflow and branch-protection snapshot, links
must resolve, and the document must not invent review gates that are not enforced.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_BASE = Path(__file__).resolve().parents[1]
LIFECYCLE = REPO_BASE / "docs" / "engineering-lifecycle.md"
CONTRIBUTING = REPO_BASE / "CONTRIBUTING.md"
README = REPO_BASE / "README.md"
WORKFLOW = REPO_BASE / ".github" / "workflows" / "ci.yml"

REQUIRED_CHECKS = {
    "Lint (ruff)",
    "Type check (mypy)",
    "Tests (Python 3.11)",
    "Tests (Python 3.13)",
}

ADVISORY_CHECKS = (
    "Deploy smoke (chart + image)",
    "Eval regression gates",
    "CodeQL",
)

LIFECYCLE_STAGES = (
    "issue",
    "branch",
    "commit",
    "pull request",
    "required checks",
    "merge",
    "close",
)

FORBIDDEN_APPROVAL_CLAIMS = (
    r"requires?\s+(at\s+least\s+)?(one|1|\d+)\s+approv",
    r"must\s+be\s+approved",
    r"approval\s+from\s+a\s+reviewer\s+is\s+required",
    r"mandatory\s+review",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _workflow_job_names(text: str) -> set[str]:
    return set(re.findall(r"^    name: (.+)$", text, re.MULTILINE))


def _local_links(text: str) -> list[str]:
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
    return [
        link
        for link in links
        if not link.startswith(("http://", "https://", "mailto:", "#"))
    ]


def test_document_exists_and_covers_the_lifecycle():
    assert LIFECYCLE.is_file(), "missing docs/engineering-lifecycle.md"
    text = _read(LIFECYCLE).lower()
    missing = [stage for stage in LIFECYCLE_STAGES if stage not in text]
    assert not missing, f"lifecycle stages missing: {missing}"


def test_required_checks_match_branch_protection_snapshot():
    text = _read(LIFECYCLE)
    assert "required" in text.lower()
    missing = [check for check in REQUIRED_CHECKS if check not in text]
    assert not missing, f"document does not list required checks: {missing}"


def test_required_checks_exist_in_the_ci_workflow():
    jobs = _workflow_job_names(_read(WORKFLOW))
    assert "Lint (ruff)" in jobs
    assert "Type check (mypy)" in jobs
    assert "Tests (Python ${{ matrix.python-version }})" in jobs
    text = _read(LIFECYCLE)
    assert "Tests (Python ${{ matrix.python-version }})" in text or "matrix" in text
    assert "4" in text or "four" in text.lower()


def test_advisory_checks_are_named_and_marked_non_required():
    text = _read(LIFECYCLE)
    plain = text.replace("**", "")
    for check in ADVISORY_CHECKS:
        assert check in text, f"advisory check not documented: {check}"
    assert "not configured as required" in plain
    assert "advisory" in plain.lower()


def test_no_unenforced_review_gate_is_claimed():
    text = _read(LIFECYCLE)
    assert "no approving review is required" in text
    assert "0 approvals" in text
    assert "enforce_admins=false" in text
    for pattern in FORBIDDEN_APPROVAL_CLAIMS:
        assert re.search(pattern, text, re.IGNORECASE) is None, f"unsupported approval claim: {pattern}"


def test_agent_working_agreement_covers_scope_and_evidence():
    text = _read(LIFECYCLE).lower()
    for phrase in (
        "inspect first",
        "one issue per branch",
        "unrelated",
        "evidence",
        "secrets",
        "never claim human review",
    ):
        assert phrase in text, f"agent agreement missing: {phrase}"


def test_worked_example_links_a_real_issue_and_pr():
    text = _read(LIFECYCLE)
    assert "issues/188" in text
    assert "pull/215" in text
    assert "Closes #188" in text


def test_document_is_linked_from_contributing_and_readme():
    assert "docs/engineering-lifecycle.md" in _read(CONTRIBUTING)
    assert "docs/engineering-lifecycle.md" in _read(README)


def test_local_links_resolve():
    for source in (LIFECYCLE, CONTRIBUTING, README):
        for link in _local_links(_read(source)):
            target = (source.parent / link.split("#", 1)[0]).resolve()
            assert target.exists(), f"{source.name} links to missing {link}"


def test_stale_roadmap_bridge_claim_removed_from_contributing():
    text = _read(CONTRIBUTING)
    assert "The open bridge is workstreams I-L" not in text
    assert "roadmap document, open issues and the GitHub Project board" in text
