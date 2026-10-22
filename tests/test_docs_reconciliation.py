"""Guards that keep the docs reconciled with the shipped surface (#81).

These are intentionally cheap and structural: they fail when a route, console
screen, config file or contract section is added without updating the document
that is supposed to describe it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_BASE = Path(__file__).resolve().parents[1]
DOCS = REPO_BASE / "docs"
UX_DOC = DOCS / "ux-and-api.md"
ARCHITECTURE = DOCS / "architecture.md"
README = REPO_BASE / "README.md"
CONTRIBUTING = REPO_BASE / "CONTRIBUTING.md"
INTERFACE_CHANGES = REPO_BASE / "INTERFACE_CHANGES.md"
CONTRACT_TEST = REPO_BASE / "tests" / "test_api_contract.py"
UI_APP = REPO_BASE / "ui" / "app.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _expected_paths() -> set[str]:
    tree = ast.parse(_read(CONTRACT_TEST))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "EXPECTED_PATHS":
                    return set(ast.literal_eval(node.value))
    raise AssertionError("EXPECTED_PATHS not found in tests/test_api_contract.py")


def _console_screens() -> set[str]:
    tree = ast.parse(_read(UI_APP))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SCREENS":
                    assert isinstance(node.value, ast.Dict)
                    return {
                        key.value
                        for key in node.value.keys
                        if isinstance(key, ast.Constant)
                    }
    raise AssertionError("SCREENS not found in ui/app.py")


def test_ux_doc_lists_every_application_route() -> None:
    doc = _read(UX_DOC)
    missing = sorted(path for path in _expected_paths() if path not in doc)
    assert not missing, f"routes missing from docs/ux-and-api.md: {missing}"


def test_ux_doc_page_map_covers_every_console_screen() -> None:
    doc = _read(UX_DOC)
    missing = sorted(screen for screen in _console_screens() if screen not in doc)
    assert not missing, f"console screens missing from the page map: {missing}"


def test_ux_doc_no_longer_reads_as_a_proposal() -> None:
    doc = _read(UX_DOC)
    for stale in ("DRAFT for review", "NOT created yet", "No code and no GitHub issues"):
        assert stale not in doc, f"stale proposal language: {stale}"
    for shipped in ("/v1/guardrails", "/v1/audit", "/v1/access", "/metrics"):
        assert shipped in doc, f"page map/API matrix omits {shipped}"


def test_no_doc_recommends_already_closed_work() -> None:
    architecture = _read(ARCHITECTURE)
    assert "currently\nhardcoded (roadmap #16)" not in architecture
    assert "hardcoded (roadmap #16)" not in architecture

    contributing = _read(CONTRIBUTING)
    assert "the recommended next work since they extend existing services" not in contributing
    assert "H0 - Observability & hardening" in contributing


def test_every_config_file_is_listed_in_the_readme() -> None:
    readme = _read(README)
    configs = sorted(p.name for p in (REPO_BASE / "config").glob("*.yaml"))
    assert len(configs) >= 10
    missing = [name for name in configs if f"config/{name}" not in readme]
    assert not missing, f"config files missing from the README config list: {missing}"


def test_interface_changes_records_later_contracts() -> None:
    text = _read(INTERFACE_CHANGES)
    assert "## 3. Later additions" in text
    for contract in (
        "query_expander",
        "guardrail",
        "pii",
        "resilience",
        "AuditLogger",
        "ResponseCache",
        "docs/architecture.md",
    ):
        assert contract.lower() in text.lower(), f"INTERFACE_CHANGES omits {contract}"


def test_readme_local_links_resolve() -> None:
    text = _read(README)
    broken = []
    for target in re.findall(r"\]\(([^)]+)\)", text):
        target = target.strip()
        if (
            target.startswith(("http://", "https://", "mailto:", "#"))
            or target.startswith("<")
        ):
            continue
        path = target.split("#", 1)[0]
        if not path:
            continue
        resolved = (REPO_BASE / path).resolve()
        if not resolved.exists():
            broken.append(target)
    assert not broken, f"README links point at missing paths: {sorted(set(broken))}"
