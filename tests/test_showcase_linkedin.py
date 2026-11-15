"""Structural guards for the LinkedIn showcase package (#193).

These tests keep the public-facing copy honest and maintainable: the canonical
name is reused, unsupported maturity claims stay negated, cited evidence paths
must exist, external URLs are allowlisted, and the copy fits LinkedIn's field
limits. Nothing here publishes anything.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_BASE = Path(__file__).resolve().parents[1]
SHOWCASE_DIR = REPO_BASE / "docs" / "showcase"
INDEX = SHOWCASE_DIR / "README.md"
LINKEDIN = SHOWCASE_DIR / "linkedin.md"
POSITIONING = REPO_BASE / "docs" / "positioning.md"
README = REPO_BASE / "README.md"

REPO_URL = "https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint"
PROFILE_URL = "https://www.linkedin.com/in/sujeetbanerjee/"

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

URL_RE = re.compile(r"https?://[^\s<>)\"']+")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    level = len(heading) - len(heading.lstrip("#"))
    pattern = re.compile(rf"^#{{{1},{level}}} ", re.MULTILINE)
    match = pattern.search(text, start + len(heading))
    end = match.start() if match else len(text)
    return text[start:end]


def _blockquote_body(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if not line.startswith(">"):
            continue
        stripped = line[1:]
        if stripped.startswith(" "):
            stripped = stripped[1:]
        lines.append(stripped)
    return "\n".join(lines).strip()


def _local_links_resolve(path: Path) -> list[str]:
    broken = []
    for target in re.findall(r"\]\(([^)]+)\)", _read(path)):
        target = target.strip()
        if target.startswith(("http://", "https://", "#")):
            continue
        destination = target.split("#", 1)[0]
        if destination and not (path.parent / destination).resolve().exists():
            broken.append(target)
    return broken


def test_showcase_package_exists_and_local_links_resolve() -> None:
    assert INDEX.is_file(), "docs/showcase/README.md is missing"
    assert LINKEDIN.is_file(), "docs/showcase/linkedin.md is missing"
    assert _local_links_resolve(INDEX) == []
    assert _local_links_resolve(LINKEDIN) == []


def test_canonical_name_is_reused() -> None:
    positioning = _read(POSITIONING)
    canonical = re.search(r"^- \*\*Name:\*\* `([^`]+)`", positioning, re.MULTILINE)
    assert canonical, "positioning.md must declare the canonical name"
    name = canonical.group(1)
    doc = _read(LINKEDIN)
    assert name in doc, "showcase must use the canonical repository name"
    assert name in _read(README), "README must still use the canonical name"


def test_forbidden_maturity_claims_are_negated() -> None:
    doc = _read(LINKEDIN)
    violations = []
    for number, line in enumerate(doc.splitlines(), start=1):
        lowered = line.lower()
        for phrase in FORBIDDEN_CLAIMS:
            if phrase in lowered and not re.search(
                r"\b(not|never|no)\b|isn't|rather than", lowered
            ):
                violations.append(f"line {number}: {phrase!r} -> {line.strip()}")
    assert not violations, "unqualified maturity claims:\n" + "\n".join(violations)


def test_cited_evidence_paths_exist() -> None:
    missing = []
    for token in re.findall(r"`([^`]+)`", _read(LINKEDIN)):
        token = token.strip()
        if token.startswith(EVIDENCE_PREFIXES):
            if not (REPO_BASE / token.rstrip("/")).exists():
                missing.append(token)
    assert not missing, f"cited evidence paths do not exist: {sorted(set(missing))}"


def test_required_sections_are_present() -> None:
    doc = _read(LINKEDIN)
    for heading in (
        "## 1. Profile entry (review-ready)",
        "### Description (first person, ready to paste)",
        "### Skills (suggest five)",
        "### Featured section (supporting media)",
        "## 2. Announcement post (ready to paste)",
        "## 3. Consistency and honesty rules",
        "## 4. Evidence map",
        "## 5. User approval checklist",
        "## 6. Maintenance",
    ):
        assert heading in doc, f"missing required section: {heading}"


def test_external_urls_are_allowlisted() -> None:
    allowed_prefixes = (REPO_URL, PROFILE_URL)
    for url in URL_RE.findall(_read(LINKEDIN) + "\n" + _read(INDEX)):
        url = url.rstrip(".,;:")
        assert url.startswith(allowed_prefixes), f"unexpected external URL: {url}"


def test_profile_entry_flags_unconfirmed_fields_and_links_repository() -> None:
    doc = _read(LINKEDIN)
    entry = _section(doc, "## 1. Profile entry (review-ready)")
    assert REPO_URL in entry, "the project URL must be the public repository"
    for field in ("Start date", "End date", "Associated with"):
        row = next(line for line in entry.splitlines() if line.startswith(f"| {field} "))
        assert "CONFIRM" in row, f"{field} must be flagged for user confirmation"
    assert "Do not infer" in entry or "Do not attach" in entry


def test_profile_description_fits_linkedin_limit_and_is_first_person() -> None:
    section = _section(_read(LINKEDIN), "### Description (first person, ready to paste)")
    body = _blockquote_body(section)
    assert 400 <= len(body) <= 2000, f"description length {len(body)} outside 400-2000"
    assert re.search(r"\bI\b", body), "description should be first person"


def test_announcement_post_fits_linkedin_limit() -> None:
    section = _section(_read(LINKEDIN), "## 2. Announcement post (ready to paste)")
    long_post = _blockquote_body(section.split("Short variant", 1)[0])
    assert 600 <= len(long_post) <= 3000, f"post length {len(long_post)} outside 600-3000"
    assert REPO_URL in long_post, "the post must link the public repository"
    assert "reference implementation" in long_post.lower()


def test_showcase_is_linked_from_readme_and_split() -> None:
    assert "docs/showcase/linkedin.md" in _read(README), "README must link the showcase package"
    split = _read(REPO_BASE / "docs" / "bot-work-split.md")
    row = next(line for line in split.splitlines() if line.startswith("| #193 "))
    assert "In review" in row or "Done" in row, f"#193 row not updated: {row}"
