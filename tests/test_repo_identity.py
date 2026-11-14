"""Guards for the public repository identity (#187).

The canonical name, one-liner, GitHub metadata and maturity vocabulary live in
docs/positioning.md. These tests fail when the README, architecture document,
comparison page or positioning file drift apart, or when unsupported maturity
claims creep into the first screen.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_BASE = Path(__file__).resolve().parents[1]
README = REPO_BASE / "README.md"
ARCHITECTURE = REPO_BASE / "docs" / "architecture.md"
POSITIONING = REPO_BASE / "docs" / "positioning.md"
COMPARISON = REPO_BASE / "docs" / "comparison.md"

NAME_RE = re.compile(r"^- \*\*Name:\*\* `([^`]+)`", re.MULTILINE)
ONE_LINER_RE = re.compile(r"^- \*\*One-liner:\*\* (.+)$", re.MULTILINE)
ABOUT_RE = re.compile(r"^- \*\*GitHub About:\*\* (.+)$", re.MULTILINE)
TOPICS_RE = re.compile(r"^- \*\*Topics:\*\* (.+)$", re.MULTILINE)
TOPIC_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

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


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _h1(text: str) -> str:
    first = text.splitlines()[0].strip()
    assert first.startswith("# "), f"expected an H1, found {first!r}"
    return first[2:].strip()


def _field(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    assert match, f"missing canonical field for pattern {pattern.pattern!r}"
    return match.group(1).strip()


def _readme_opening() -> str:
    return _read(README).split("## Architecture", 1)[0]


def _topics() -> list[str]:
    return re.findall(r"`([^`]+)`", _field(TOPICS_RE, _read(POSITIONING)))


def _assert_local_links_resolve(path: Path) -> None:
    broken: list[str] = []
    for target in re.findall(r"\]\(([^)]+)\)", _read(path)):
        target = target.strip()
        if target.startswith(("http://", "https://", "mailto:", "#")) or target.startswith("<"):
            continue
        destination = target.split("#", 1)[0]
        if destination and not (path.parent / destination).resolve().exists():
            broken.append(target)
    assert not broken, f"{path.name} links point at missing paths: {sorted(set(broken))}"


def test_repository_title_matches_positioning_and_architecture() -> None:
    canonical = _field(NAME_RE, _read(POSITIONING))
    assert _h1(_read(README)) == canonical
    assert _h1(_read(ARCHITECTURE)) == canonical
    assert canonical == "Enterprise GenAI Platform Blueprint"
    assert "Enterprise-Grade" not in canonical


def test_readme_opening_uses_the_canonical_one_liner() -> None:
    one_liner = _field(ONE_LINER_RE, _read(POSITIONING))
    opening = _readme_opening()
    assert one_liner in opening, "README opening must reuse the canonical one-liner verbatim"


def test_readme_opening_covers_the_platform_domains() -> None:
    opening = _readme_opening().lower()
    for term in (
        "modular",
        "vendor-neutral",
        "self-hostable",
        "reference implementation",
        "rag",
        "evaluation",
        "governance",
        "security",
        "observability",
        "operations",
    ):
        assert term in opening, f"README opening omits {term!r}"


def test_readme_opening_states_maturity_boundaries() -> None:
    opening = _readme_opening().lower().replace("**", "")
    assert "not a production-certified product" in opening
    assert "managed ai platform" in opening
    assert "what it is not" in opening


def test_identity_copy_avoids_unsupported_claims() -> None:
    for path in (README, POSITIONING):
        text = _read(path)
        if path is README:
            text = _readme_opening()
        # The positioning doc lists these phrases in its "avoid" guidance.
        text = re.sub(r"Avoid unsupported claims:.*?(?=\n\n)", "", text, flags=re.DOTALL)
        lowered = text.lower()
        for claim in FORBIDDEN_CLAIMS:
            assert claim not in lowered, f"{path.name} makes unsupported claim {claim!r}"


def test_github_about_description_fits_the_github_limit() -> None:
    about = _field(ABOUT_RE, _read(POSITIONING))
    assert 0 < len(about) <= 350, f"GitHub About is {len(about)} characters (max 350)"
    lowered = about.lower()
    for required in ("reference implementation", "mit", "not a production-certified product"):
        assert required in lowered, f"GitHub About omits {required!r}"


def test_positioning_topics_are_valid_github_topics() -> None:
    topics = _topics()
    assert 1 <= len(topics) <= 20, f"expected 1-20 topics, found {len(topics)}"
    for topic in topics:
        assert TOPIC_RE.match(topic), f"invalid GitHub topic {topic!r}"
    for required in ("genai", "rag", "evaluation", "guardrails", "governance", "observability"):
        assert required in topics, f"topics omit {required!r}"


def test_maturity_vocabulary_is_consistent_across_documents() -> None:
    for path in (README, ARCHITECTURE, POSITIONING, COMPARISON):
        assert "reference implementation" in _read(path).lower(), (
            f"{path.name} does not use the canonical 'reference implementation' vocabulary"
        )


def test_readme_and_positioning_local_links_resolve() -> None:
    assert "docs/positioning.md" in _read(README)
    _assert_local_links_resolve(README)
    _assert_local_links_resolve(POSITIONING)
