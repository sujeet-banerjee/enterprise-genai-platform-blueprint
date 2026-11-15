"""Structural guards for the adoption and pilot kit (#204).

The kit must stay an evaluation aid: every claim links to evidence, no success
numbers are pre-filled, support/SLA/certification are explicitly not offered,
and the adopter-owned work is separated from repository evidence.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_BASE = Path(__file__).resolve().parents[1]
ADOPTION = REPO_BASE / "docs" / "adoption"
README = ADOPTION / "README.md"
PILOT = ADOPTION / "pilot-brief.md"
CHECKLIST = ADOPTION / "checklist.md"
SCORECARD = ADOPTION / "scorecard.md"
REPO_README = REPO_BASE / "README.md"
ONBOARDING = REPO_BASE / "docs" / "onboarding.md"

FORBIDDEN_CLAIMS = (
    "production-ready",
    "battle-tested",
    "proven at scale",
    "enterprise-grade",
    "production-certified",
    "sla-backed",
    "trusted by",
)

EVIDENCE_PREFIXES = (
    "core/",
    "app/",
    "config/",
    "docs/",
    "ui/",
    "tests/",
    "benchmarks/",
    "deployment/",
    ".devcontainer/",
    ".github/",
)

NUMBER_RE = re.compile(r"\b0\.\d+\b")
URL_RE = re.compile(r"https?://[^\s<>)\"']+")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _local_links(path: Path) -> list[str]:
    broken = []
    for target in re.findall(r"\]\(([^)]+)\)", _read(path)):
        target = target.strip()
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        destination = target.split("#", 1)[0]
        if destination and not (path.parent / destination).resolve().exists():
            broken.append(target)
    return broken


def test_kit_files_exist_and_local_links_resolve() -> None:
    for path in (README, PILOT, CHECKLIST, SCORECARD):
        assert path.is_file(), f"missing adoption artefact: {path.name}"
        assert _local_links(path) == [], f"broken links in {path.name}: {_local_links(path)}"


def test_landing_page_indexes_the_existing_evidence() -> None:
    doc = _read(README)
    for target in (
        "../architecture-diagram.md",
        "../architecture.md",
        "../capability-status.md",
        "../production-readiness.md",
        "../comparison.md",
        "../deployment.md",
        "../benchmarks/README.md",
        "../onboarding.md",
        "pilot-brief.md",
        "checklist.md",
        "scorecard.md",
    ):
        assert target in doc, f"adoption landing page does not link {target}"


def test_maturity_and_support_boundaries_are_explicit() -> None:
    doc = _read(README)
    assert "reference implementation" in doc.lower()
    for phrase in (
        "no SLA",
        "no independent security certification",
        "no customer references",
    ):
        assert phrase.lower() in doc.lower(), f"missing boundary statement: {phrase}"


def test_forbidden_claims_are_negated() -> None:
    for path in (README, PILOT, CHECKLIST, SCORECARD):
        violations = []
        for number, line in enumerate(_read(path).splitlines(), start=1):
            lowered = line.lower()
            for phrase in FORBIDDEN_CLAIMS:
                if phrase in lowered and not re.search(
                    r"\b(not|never|no)\b|isn't|rather than", lowered
                ):
                    violations.append(f"{path.name}:{number}: {phrase!r}")
        assert not violations, f"unqualified maturity claims: {violations}"


def test_pilot_brief_covers_required_sections() -> None:
    doc = _read(PILOT)
    for heading in (
        "## 1. Scope",
        "## 2. Prerequisites",
        "## 3. Data handling and security constraints",
        "## 4. Deployment options",
        "## 5. Configuration and identity assumptions",
        "## 6. Time-boxed plan",
        "## 7. Success criteria (adopter-owned)",
        "## 8. Exit and rollback",
    ):
        assert heading in doc, f"pilot brief missing section: {heading}"
    assert "adopter" in doc.lower()


def test_checklist_separates_evidence_from_adopter_work() -> None:
    doc = _read(CHECKLIST)
    for heading in (
        "## A. Demo prerequisites",
        "## B. Technical evaluation",
        "## C. Security review",
        "## D. Production qualification (adopter-owned)",
        "## E. Adopter-owned responsibilities",
    ):
        assert heading in doc, f"checklist missing section: {heading}"
    assert "Repo evidence" in doc and "Adopter-owned" in doc
    assert doc.count("**Adopter-owned:**") >= 3


def test_scorecard_has_metrics_but_no_prefilled_numbers() -> None:
    doc = _read(SCORECARD)
    for metric in (
        "`context_precision`",
        "`context_recall`",
        "MRR",
        "nDCG",
        "`answer_correctness`",
    ):
        assert metric in doc, f"scorecard missing metric: {metric}"
    assert "Adopter to set" in doc or "adopter to set" in doc
    assert "[ ]" in doc and "[Go / Go with conditions / No-go]" in doc
    assert not NUMBER_RE.search(doc), "scorecard must not ship pre-filled success numbers"
    assert not NUMBER_RE.search(_read(PILOT)), "pilot brief must not pre-fill thresholds"


def test_cited_evidence_paths_exist() -> None:
    missing = []
    for path in (README, PILOT, CHECKLIST, SCORECARD):
        for token in re.findall(r"`([^`]+)`", _read(path)):
            token = token.strip()
            if token.startswith(EVIDENCE_PREFIXES) and "*" not in token:
                if not (REPO_BASE / token.rstrip("/")).exists():
                    missing.append(token)
    assert not missing, f"cited paths do not exist: {sorted(set(missing))}"


def test_external_urls_are_allowlisted() -> None:
    allowed = "https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint"
    for path in (README, PILOT, CHECKLIST, SCORECARD):
        for url in URL_RE.findall(_read(path)):
            assert url.rstrip(".,;:").startswith(allowed), f"unexpected URL in {path.name}: {url}"


def test_adoption_kit_is_wired_into_readme_onboarding_and_split() -> None:
    assert "docs/adoption/README.md" in _read(REPO_README)
    assert "adoption/README.md" in _read(ONBOARDING)
    split = _read(REPO_BASE / "docs" / "bot-work-split.md")
    row = next(line for line in split.splitlines() if line.startswith("| #204 "))
    assert "In review" in row or "Done" in row, f"#204 row not updated: {row}"


def test_capability_status_marks_the_kit_implemented() -> None:
    doc = _read(REPO_BASE / "docs" / "capability-status.md")
    row = next(
        line
        for line in doc.splitlines()
        if line.startswith("| Engineering-team adoption / pilot kit ")
    )
    assert "Implemented" in row, f"capability row not updated: {row}"
    assert "docs/adoption/README.md" in row
