from __future__ import annotations

import re
from pathlib import Path

REPO_BASE = Path(__file__).resolve().parents[1]
README = REPO_BASE / "README.md"
CONSOLE_DOC = REPO_BASE / "docs" / "console-walkthrough.md"
UX_DOC = REPO_BASE / "docs" / "ux-and-api.md"
DEMO_DOC = REPO_BASE / "docs" / "showcase" / "demo-walkthrough.md"
SPLIT = REPO_BASE / "docs" / "bot-work-split.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _console_section() -> str:
    text = _read(README)
    match = re.search(
        r"^## Streamlit console \(UX\)\s*$(.*?)^## ",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "README Streamlit console section not found"
    return match.group(1)


def _broken_local_links(text: str, base: Path) -> list[str]:
    broken: list[str] = []
    for target in re.findall(r"\]\(([^)]+)\)", text):
        target = target.strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path = target.split("#", 1)[0]
        if not path:
            continue
        if not (base / path).resolve().exists():
            broken.append(target)
    return broken


def test_console_section_is_short_and_scannable() -> None:
    section = _console_section().strip()
    lines = section.splitlines()
    assert len(lines) <= 30, f"README console section grew to {len(lines)} lines"
    assert len(section) <= 2400, f"README console section grew to {len(section)} chars"


def test_console_section_no_longer_contains_mashed_inventory() -> None:
    section = _console_section()
    for stale in (
        "Walkthrough: open **Query Studio**",
        "copy/share",
        "bounded job history",
        "prefers-reduced-motion",
        "First-time users:",
    ):
        assert stale not in section, f"README console section still contains {stale!r}"


def test_console_section_links_to_dedicated_reference() -> None:
    readme = _read(README)
    assert "[docs/console-walkthrough.md](docs/console-walkthrough.md)" in readme
    assert "[docs/showcase/demo-walkthrough.md](docs/showcase/demo-walkthrough.md)" in readme


def test_dedicated_reference_covers_moved_topics() -> None:
    text = _read(CONSOLE_DOC)
    headings = (
        "## Query Studio and recent runs",
        "## Traces and evidence",
        "## Evaluation and datasets",
        "## Governance, guardrails, approvals and admin",
        "## Navigation, onboarding and demo mode",
        "## Keyboard, accessibility and appearance",
        "## Persistent workspace",
        "## First-time entry points",
    )
    for heading in headings:
        assert heading in text, f"console reference omits {heading}"
    for phrase in ("Dataset Studio", "evidence pack", "Role journeys", "Command palette"):
        assert phrase in text, f"console reference omits {phrase}"


def test_dedicated_reference_contains_mock_up_wireframes() -> None:
    text = _read(CONSOLE_DOC)
    assert "## Mock-up wireframes" in text
    assert "not captured screens" in text
    for heading in (
        "### Console shell and navigation",
        "### Query Studio",
        "### Evaluation and dataset authoring",
        "### Traces, governance and evidence",
    ):
        assert heading in text, f"console reference omits wireframe {heading}"
    assert text.count("```mermaid") >= 4


def test_wireframes_are_renderable_mermaid_flowcharts() -> None:
    text = _read(CONSOLE_DOC)
    blocks = re.findall(r"```mermaid\n(.*?)\n```", text, re.DOTALL)
    assert len(blocks) >= 4
    for block in blocks:
        assert block.startswith("flowchart "), f"unexpected Mermaid block: {block[:40]!r}"
        assert "subgraph" in block or "-->" in block


def test_dedicated_reference_local_links_resolve() -> None:
    broken = _broken_local_links(_read(CONSOLE_DOC), CONSOLE_DOC.parent)
    assert not broken, f"console reference links point at missing paths: {broken}"


def test_readme_local_links_still_resolve() -> None:
    broken = _broken_local_links(_read(README), REPO_BASE)
    assert not broken, f"README links point at missing paths: {broken}"


def test_ux_and_demo_docs_point_to_console_reference() -> None:
    ux = _read(UX_DOC)
    demo = _read(DEMO_DOC)
    assert "[`docs/console-walkthrough.md`](console-walkthrough.md)" in ux
    assert "[`docs/console-walkthrough.md`](../console-walkthrough.md)" in demo


def test_work_split_records_the_bot_uni_owner_exception() -> None:
    split = _read(SPLIT)
    assert "#268" in split
    assert "maintainer-assigned exception" in split
    assert "#268 (maintainer-assigned exception) | bot-uni" in split
