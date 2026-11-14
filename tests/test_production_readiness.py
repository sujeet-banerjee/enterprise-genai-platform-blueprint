"""Guards for the production-readiness gap assessment (#192).

docs/production-readiness.md must stay grounded: every cited path must exist,
only the approved status vocabulary may appear, the tracked issues must remain
linked, and the README / deployment playbook must point at it. The assessment
must also keep its "not a certification" framing.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_BASE = Path(__file__).resolve().parents[1]
ASSESSMENT = REPO_BASE / "docs" / "production-readiness.md"
README = REPO_BASE / "README.md"
DEPLOYMENT = REPO_BASE / "docs" / "deployment.md"

ALLOWED_STATUSES = {"Implemented", "Partial", "Unvalidated", "Planned"}
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
REQUIRED_AREA_HEADINGS = (
    "## 1. Durable and shared persistence",
    "## 2. Multi-process and multi-replica consistency and coordination",
    "## 3. Deployment topology, secrets, configuration and environment separation",
    "## 4. Authentication, authorization and tenant-isolation validation",
    "## 5. Security testing, threat modelling and independent validation",
    "## 6. Load, performance, capacity and SLOs",
    "## 7. Resilience, backup/restore and disaster recovery",
    "## 8. Operational monitoring, alerting and runbooks",
)
REQUIRED_GAP_ISSUES = {"#43", "#204", "#205", "#206"}

PATH_RE = re.compile(r"`([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+)`")
STATUS_LINE_RE = re.compile(r"^\*\*Status: (Implemented|Partial|Unvalidated|Planned)\.\*\*$", re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _cited_paths(text: str) -> set[str]:
    return {t for t in PATH_RE.findall(text) if not t.startswith(("http", "www"))}


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


def test_assessment_exists_with_an_h1() -> None:
    assert ASSESSMENT.is_file(), "docs/production-readiness.md is missing"
    assert _read(ASSESSMENT).splitlines()[0].startswith("# "), "assessment needs an H1"


def test_assessment_covers_every_required_area() -> None:
    text = _read(ASSESSMENT)
    for heading in REQUIRED_AREA_HEADINGS:
        assert heading in text, f"production-readiness.md omits area {heading!r}"


def test_every_area_declares_an_allowed_status() -> None:
    statuses = STATUS_LINE_RE.findall(_read(ASSESSMENT))
    assert len(statuses) >= len(REQUIRED_AREA_HEADINGS), (
        f"expected a status per area, found {len(statuses)}"
    )
    for status in statuses:
        assert status in ALLOWED_STATUSES


def test_assessment_cites_only_existing_paths() -> None:
    missing: list[str] = []
    for token in sorted(_cited_paths(_read(ASSESSMENT))):
        candidate = REPO_BASE / token
        if candidate.exists() or candidate.is_dir():
            continue
        if token.endswith((".md", ".py", ".json", ".yaml", ".yml", ".sh", ".toml", ".cfg")):
            missing.append(token)
    assert not missing, f"production-readiness.md cites non-existent paths: {sorted(set(missing))}"


def test_tracked_issues_stay_linked() -> None:
    text = _read(ASSESSMENT)
    for issue in REQUIRED_GAP_ISSUES:
        assert issue in text, f"assessment no longer references tracked issue {issue}"
    assert "issues/" in text, "issue references should link to GitHub"


def test_assessment_frames_itself_as_not_a_certification() -> None:
    lowered = _read(ASSESSMENT).lower()
    assert "not a certification" in lowered
    assert "does **not** claim" in lowered or "not claim" in lowered
    assert "no duplicate" in lowered or "no new duplicate" in lowered or "does **not** introduce" in lowered


def test_assessment_avoids_unsupported_claims() -> None:
    lowered = _read(ASSESSMENT).lower()
    for claim in FORBIDDEN_CLAIMS:
        assert claim not in lowered, f"production-readiness.md makes unsupported claim {claim!r}"


def test_readme_links_to_the_assessment() -> None:
    assert "docs/production-readiness.md" in _read(README)
    _assert_local_links_resolve(README)


def test_deployment_playbook_links_to_the_assessment() -> None:
    assert "production-readiness.md" in _read(DEPLOYMENT)


def test_assessment_local_links_resolve() -> None:
    _assert_local_links_resolve(ASSESSMENT)
