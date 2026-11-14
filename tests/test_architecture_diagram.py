"""Structural guards for docs/architecture-diagram.md (#188).

The diagram is documentation, but drift is still a defect: a missing layer,
an external dependency painted as delivered, or a code-map path that no longer
exists misleads architects. These tests keep the Mermaid source, legend and
component-to-code map aligned with the repository.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_BASE = Path(__file__).resolve().parents[1]
DIAGRAM = REPO_BASE / "docs" / "architecture-diagram.md"
ARCHITECTURE = REPO_BASE / "docs" / "architecture.md"
README = REPO_BASE / "README.md"
CONTRACT = REPO_BASE / "tests" / "test_api_contract.py"

REQUIRED_COMPONENTS = (
    "API layer",
    "Composition root",
    "RAGPipeline",
    "Registries",
    "evaluation",
    "cost governor",
    "identity",
    "tenancy",
    "guardrails",
    "observability",
    "audit",
    "Persistence",
    "Ingestion",
    "Delivery artefacts",
)

REQUIRED_STAGES = (
    "query_validation",
    "embedding",
    "retrieval",
    "reranking",
    "input_redaction",
    "guardrail_input",
    "token_budget",
    "prompt_construction",
    "llm_generation",
    "guardrail_output",
    "evaluation",
)

CODE_MAP_PREFIXES = (
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


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _mermaid(text: str) -> str:
    match = re.search(r"```mermaid\n(.*?)```", text, re.DOTALL)
    assert match, "architecture-diagram.md must contain a mermaid code block"
    return match.group(1)


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    level = len(heading) - len(heading.lstrip("#"))
    pattern = re.compile(rf"^#{{{1},{level}}} ", re.MULTILINE)
    match = pattern.search(text, start + len(heading))
    end = match.start() if match else len(text)
    return text[start:end]


def _class_members(block: str, css_class: str) -> set[str]:
    line = re.search(rf"^\s*class\s+([^\n]+?)\s+{css_class}\s*$", block, re.MULTILINE)
    assert line, f"missing class assignment for {css_class}"
    return {part.strip() for part in line.group(1).split(",") if part.strip()}


def _declared_nodes(block: str) -> set[str]:
    body = "\n".join(line for line in block.splitlines() if not line.strip().startswith("subgraph"))
    return set(re.findall(r"^\s+([A-Z][A-Z0-9_]*)\[", body, re.MULTILINE))


def test_diagram_exists_and_uses_mermaid():
    assert DIAGRAM.is_file(), "missing docs/architecture-diagram.md"
    block = _mermaid(_read(DIAGRAM))
    assert block.lstrip().startswith("flowchart TB"), "diagram should be a top-down Mermaid flowchart"


def test_required_layers_and_stages_are_present():
    text = _read(DIAGRAM)
    missing = [item for item in REQUIRED_COMPONENTS if item.lower() not in text.lower()]
    assert not missing, f"diagram is missing required areas: {missing}"
    missing_stages = [stage for stage in REQUIRED_STAGES if stage not in text]
    assert not missing_stages, f"diagram is missing pipeline stages: {missing_stages}"


def test_legend_separates_implemented_external_and_planned():
    block = _mermaid(_read(DIAGRAM))
    for css_class in ("implemented", "external", "planned"):
        assert f"classDef {css_class}" in block
        assert _class_members(block, css_class), f"{css_class} has no members"

    planned = _class_members(block, "planned")
    assert {"HA", "DR", "SEC"} <= planned
    assert planned.isdisjoint(_class_members(block, "implemented"))
    assert planned.isdisjoint(_class_members(block, "external"))
    assert "planned" in _read(DIAGRAM).lower()
    assert "external or optional" in _read(DIAGRAM)


def test_every_declared_node_is_classified():
    block = _mermaid(_read(DIAGRAM))
    declared = _declared_nodes(block)
    classified = set()
    for css_class in ("implemented", "external", "planned"):
        classified |= _class_members(block, css_class)
    assert declared, "no Mermaid nodes detected"
    assert declared == classified, f"unclassified nodes: {sorted(declared - classified)}"


def test_mermaid_subgraphs_are_balanced():
    block = _mermaid(_read(DIAGRAM))
    subgraphs = [line for line in block.splitlines() if line.strip().startswith("subgraph ")]
    ends = [line for line in block.splitlines() if line.strip() == "end"]
    assert subgraphs, "expected at least one subgraph"
    assert len(subgraphs) == len(ends), f"{len(subgraphs)} subgraphs but {len(ends)} end markers"


def test_component_to_code_map_paths_exist():
    section = _section(_read(DIAGRAM), "## Component-to-code map")
    paths = []
    for token in re.findall(r"`([^`]+)`", section):
        token = token.strip()
        if token.startswith(CODE_MAP_PREFIXES):
            paths.append(token.rstrip("/"))
    assert paths, "component-to-code map cites no repository paths"
    missing = [path for path in paths if not (REPO_BASE / path).exists()]
    assert not missing, f"component-to-code map cites missing paths: {missing}"


def test_readme_and_architecture_link_to_the_diagram():
    assert "docs/architecture-diagram.md" in _read(README)
    architecture = _read(ARCHITECTURE)
    assert "(architecture-diagram.md)" in architecture


def test_documented_route_count_matches_contract():
    contract = _read(CONTRACT)
    match = re.search(r"EXPECTED_PATHS\s*=\s*\{(.*?)\n\}", contract, re.DOTALL)
    assert match, "EXPECTED_PATHS not found in tests/test_api_contract.py"
    routes = re.findall(r'"(/[^"]*)"', match.group(1))
    assert routes, "no routes parsed from EXPECTED_PATHS"
    assert f"{len(routes)} HTTP routes" in _read(DIAGRAM)


def test_diagram_does_not_overclaim():
    text = _read(DIAGRAM).lower()
    assert "not a production-certified" in text
    assert "planned" in text and "not claimed" in text
    assert re.search(r"(?<!not )production-ready", text) is None


def test_renders_with_mermaid_cli_when_available(tmp_path):
    mmdc = shutil.which("mmdc")
    if not mmdc:
        pytest.skip("mermaid-cli (mmdc) is not installed")
    source = tmp_path / "diagram.mmd"
    output = tmp_path / "diagram.svg"
    source.write_text(_mermaid(_read(DIAGRAM)), encoding="utf-8")
    result = subprocess.run(
        [mmdc, "-i", str(source), "-o", str(output)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert output.is_file() and output.stat().st_size > 0
