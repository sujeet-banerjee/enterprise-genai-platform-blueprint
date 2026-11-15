"""Structural guards for the security qualification package (issue #205).

These tests keep the threat model, test plan and findings table consistent with
the repository: cited tests must exist, threat IDs must be mapped, relative links
must resolve, and the package must not overclaim. They do **not** validate that a
control is correct - the cited tests do that.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import List, Set
from urllib.parse import urlparse

REPO_BASE = Path(__file__).resolve().parents[1]
SECURITY_DIR = REPO_BASE / "docs" / "security"
README = SECURITY_DIR / "README.md"
THREAT_MODEL = SECURITY_DIR / "threat-model.md"
TEST_PLAN = SECURITY_DIR / "test-plan.md"
SECURITY_POLICY = REPO_BASE / "SECURITY.md"
SECURITY_DOCS = (README, THREAT_MODEL, TEST_PLAN)

THREAT_ID = re.compile(r"\bT-[A-Z]+-\d+\b")
TEST_REF = re.compile(r"tests/[\w/]+\.py::\w+")
LINK = re.compile(r"\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)
NUMBERED_FINDING = re.compile(r"^\| (F-\d{2}) \|", re.MULTILINE)
PYTEST_PIN = re.compile(r"pytest(?:==|>=)\s*(\d+)\.(\d+)\.(\d+)")

FINDING_STATUSES = {
    "tracked",
    "accepted",
    "mitigated",
    "fixed",
    "not performed",
}
BANNED_CLAIMS = [
    "is production-ready",
    "are production-ready",
    "is battle-tested",
    "proven at scale",
    "enterprise-grade",
    "fully secure",
    "security certified",
    "is penetration tested",
]
ALLOWED_EXTERNAL_HOSTS = {
    "github.com",
    "docs.github.com",
    "www.linkedin.com",
    "linkedin.com",
}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _slug(heading: str) -> str:
    without_links = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading)
    cleaned = re.sub(r"[^\w\s-]", "", without_links.strip().lower())
    return re.sub(r"\s+", "-", cleaned).strip("-")


def _headings(path: Path) -> Set[str]:
    return {_slug(match.group(1)) for match in HEADING.finditer(_text(path))}


def _function_names(path: Path) -> Set[str]:
    tree = ast.parse(_text(path))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _test_refs() -> List[str]:
    refs: Set[str] = set()
    for path in SECURITY_DOCS:
        refs.update(TEST_REF.findall(_text(path)))
    return sorted(refs)


def test_required_security_files_exist():
    for path in (*SECURITY_DOCS, SECURITY_POLICY):
        assert path.exists(), f"missing {path.relative_to(REPO_BASE)}"
        assert path.stat().st_size > 0


def test_threat_model_has_required_sections_and_boundaries():
    text = _text(THREAT_MODEL)
    for section in (
        "## 1. Assets",
        "## 2. Trust boundaries",
        "## 3. Attacker assumptions",
        "## 4. Abuse cases",
        "## 5. Assumptions and out of scope",
    ):
        assert section in text, f"missing section: {section}"
    assert text.count("```mermaid") == 1
    assert "Priority" in text and "P0" in text and "P1" in text and "P2" in text


def test_every_threat_id_has_priority_and_test_mapping():
    threat_text = _text(THREAT_MODEL)
    plan = _text(TEST_PLAN)
    threat_ids = set(THREAT_ID.findall(threat_text))
    assert len(threat_ids) >= 20, "threat model lost abuse cases"

    for threat_id in sorted(threat_ids):
        row = re.search(rf"^\| {re.escape(threat_id)} \| (P[0-2]) \|", threat_text, re.MULTILINE)
        assert row, f"{threat_id} has no priority row in the threat model"
        mapping = re.search(rf"^\| {re.escape(threat_id)} \|", plan, re.MULTILINE)
        assert mapping, f"{threat_id} is not mapped in test-plan.md"

    mapped_ids = set(re.findall(r"^\| (T-[A-Z]+-\d+) \|", plan, re.MULTILINE))
    assert mapped_ids == threat_ids, (
        "threat IDs differ between model and plan: "
        f"model-only={sorted(threat_ids - mapped_ids)} plan-only={sorted(mapped_ids - threat_ids)}"
    )


def test_cited_tests_exist():
    missing = []
    for ref in _test_refs():
        path_part, function_name = ref.split("::")
        path = REPO_BASE / path_part
        if not path.exists():
            missing.append(f"{ref} (missing file)")
            continue
        if function_name not in _function_names(path):
            missing.append(f"{ref} (missing function)")
    assert not missing, "security docs cite unknown tests: " + ", ".join(missing)


def test_security_qualification_matrix_names_are_cited():
    matrix = REPO_BASE / "tests" / "test_security_qualification.py"
    matrix_functions = _function_names(matrix)
    cited = {
        ref.split("::")[1]
        for ref in _test_refs()
        if ref.startswith("tests/test_security_qualification.py::")
    }
    assert cited, "test plan cites none of the adversarial matrix"
    assert cited <= matrix_functions, f"plan cites unknown matrix tests: {cited - matrix_functions}"
    assert len(matrix_functions) >= 15


def test_relative_links_and_anchors_resolve():
    problems = []
    for document in SECURITY_DOCS:
        for target in LINK.findall(_text(document)):
            if target.startswith(("http://", "https://", "mailto:")):
                host = urlparse(target).hostname or ""
                if host not in ALLOWED_EXTERNAL_HOSTS:
                    problems.append(f"{document.name}: unexpected external host {host}")
                continue
            path_part, _, anchor = target.partition("#")
            target_path = (document.parent / path_part).resolve() if path_part else document
            if not target_path.exists():
                problems.append(f"{document.name}: broken link {target}")
                continue
            if anchor and target_path.suffix == ".md" and _slug(anchor) not in _headings(target_path):
                problems.append(f"{document.name}: missing anchor in {path_part or document.name}#{anchor}")
    assert not problems, "; ".join(problems)


def test_findings_table_is_complete_and_statuses_are_known():
    text = _text(README)
    header = next(
        line for line in text.splitlines() if line.startswith("| ID | Finding |")
    )
    for column in ("Severity", "Exploitability", "Status", "Owner", "Evidence / link"):
        assert column in header, f"findings table missing column: {column}"

    rows = [line for line in text.splitlines() if re.match(r"^\| F-\d{2} \|", line)]
    assert len(rows) >= 10, "findings table shrank unexpectedly"
    finding_ids = [row.split("|")[1].strip() for row in rows]
    assert finding_ids == sorted(finding_ids)
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert len(cells) >= 7, f"malformed findings row: {row}"
        status = cells[4].replace("*", "").strip()
        assert any(status.lower().startswith(value) for value in FINDING_STATUSES), status
        assert cells[5], f"finding {cells[0]} has no owner"
        assert cells[6], f"finding {cells[0]} has no evidence or link"


def test_package_does_not_overclaim():
    offenders = []
    for document in (*SECURITY_DOCS, SECURITY_POLICY):
        for line in _text(document).splitlines():
            lowered = line.lower()
            for phrase in BANNED_CLAIMS:
                if phrase in lowered and not re.search(r"\b(not|no|never)\b", lowered):
                    offenders.append(f"{document.name}: {phrase}")
    assert not offenders, "unqualified security claims: " + "; ".join(offenders)
    assert "not performed" in _text(README).lower()
    assert "not a certification" in _text(README).lower()


def test_scanning_status_matches_repository_configuration():
    text = _text(README)
    assert "| CodeQL default setup" in text
    assert "**No** - advisory check" in text
    assert "Dependabot alerts" in text and "Enabled" in text
    assert "Dependency audit (pip-audit / SCA)" in text
    assert "Container image scan (Trivy/Grype/Snyk)" in text
    assert "Not run" in text
    assert "Secret scanning + push protection" in text

    dependabot = REPO_BASE / ".github" / "dependabot.yml"
    assert dependabot.exists(), ".github/dependabot.yml is missing"
    config = _text(dependabot)
    assert "package-ecosystem: pip" in config
    assert "package-ecosystem: github-actions" in config
    assert "interval: weekly" in config


def _pytest_version(text: str, source: str) -> tuple:
    versions = PYTEST_PIN.findall(text)
    assert versions, f"{source} no longer pins pytest"
    return max(tuple(int(part) for part in version) for version in versions)


def test_pytest_is_patched_for_ghsa_6w46_j5rx_g56g():
    requirement = _pytest_version(_text(REPO_BASE / "requirements.txt"), "requirements.txt")
    assert requirement >= (9, 0, 3), f"pytest pinned at {requirement}, GHSA fix is 9.0.3"

    pyproject = _pytest_version(_text(REPO_BASE / "pyproject.toml"), "pyproject.toml")
    assert pyproject >= (9, 0, 3), f"pyproject pytest pin {pyproject} is below the GHSA fix"


def test_pytest_version_guard_accepts_upgrades_but_rejects_vulnerable_pins():
    assert _pytest_version('pytest==9.2.0', "fixture") >= (9, 0, 3)
    assert _pytest_version('"pytest>=9.0.3"', "fixture") >= (9, 0, 3)
    assert _pytest_version("pytest==9.0.2", "fixture") < (9, 0, 3)


def test_security_package_is_linked_from_repository_docs():
    readme = _text(REPO_BASE / "README.md")
    assert "docs/security/README.md" in readme

    readiness = _text(REPO_BASE / "docs" / "production-readiness.md")
    assert "security/README.md" in readiness

    capability = _text(REPO_BASE / "docs" / "capability-status.md")
    assert "Security qualification" in capability

    lifecycle = _text(REPO_BASE / "docs" / "engineering-lifecycle.md")
    assert "security/test-plan.md" in lifecycle
