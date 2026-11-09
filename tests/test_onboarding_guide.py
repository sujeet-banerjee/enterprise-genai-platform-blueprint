"""Onboarding guide + validation (issue #129, Workstream L).

Guards the guide against drift: the commands it documents must exist in the CLI,
every config file it names must be shipped, its links must resolve, and the
documented scaffold -> validate flow must genuinely work.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.cli import build_parser, main

REPO_BASE = Path(__file__).resolve().parents[1]
GUIDE = REPO_BASE / "docs" / "onboarding.md"


def _guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


def test_guide_exists_and_has_expected_sections() -> None:
    assert GUIDE.is_file()
    text = _guide()
    for section in (
        "## 1. Five-minute path",
        "## 2. Choose a golden path",
        "## 3. What the generated files mean",
        "## 4. First changes you will likely make",
        "## 5. Validate before you deploy",
        "## 6. Troubleshooting",
        "## 7. Where to go next",
    ):
        assert section in text, f"onboarding guide missing section: {section}"


def test_guide_documents_real_cli_commands() -> None:
    text = _guide()
    for command in (
        "genai init",
        "genai templates",
        "genai validate",
        "python -m app.config_validate",
        "--config-dir",
        "GENAI_CONFIG_DIR",
        "uvicorn app.main:app",
        "streamlit run ui/app.py",
    ):
        assert command in text, f"onboarding guide omits `{command}`"

    parser = build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if action.__class__.__name__ == "_SubParsersAction"
    )
    assert set(subparsers.choices) == {"init", "templates", "validate"}


def test_guide_names_every_golden_path() -> None:
    text = _guide()
    templates = REPO_BASE / "deployment" / "templates"
    names = sorted(p.name for p in templates.iterdir() if p.is_dir())
    assert names
    for name in names:
        assert f"`{name}`" in text, f"onboarding guide omits golden path {name}"


def test_guide_config_references_exist() -> None:
    text = _guide()
    referenced = set(re.findall(r"`(config/[A-Za-z0-9_]+\.yaml)`", text))
    assert referenced, "guide should reference concrete config files"
    missing = sorted(name for name in referenced if not (REPO_BASE / name).is_file())
    assert not missing, f"guide references missing config files: {missing}"


def test_guide_local_links_resolve() -> None:
    text = _guide()
    broken = []
    for target in re.findall(r"\]\(([^)]+)\)", text):
        target = target.strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path = target.split("#", 1)[0]
        if path and not (GUIDE.parent / path).resolve().exists():
            broken.append(target)
    assert not broken, f"onboarding guide links point at missing paths: {sorted(set(broken))}"


def test_readme_and_deployment_link_to_the_guide() -> None:
    readme = (REPO_BASE / "README.md").read_text(encoding="utf-8")
    deployment = (REPO_BASE / "docs" / "deployment.md").read_text(encoding="utf-8")
    templates = (REPO_BASE / "deployment" / "templates" / "README.md").read_text(encoding="utf-8")
    assert "docs/onboarding.md" in readme
    assert "onboarding.md" in deployment
    assert "onboarding.md" in templates


def test_guide_troubleshooting_covers_real_failure_modes() -> None:
    text = _guide()
    for marker in (
        "No relevant context available",
        "guardrail_input_blocked",
        "cost_limit_exceeded",
        "503 not_ready",
        "documents_path",
        "HF_TOKEN",
    ):
        assert marker in text, f"troubleshooting omits {marker}"


def test_documented_scaffold_and_validate_flow_works(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "guide-app"
    assert main(["init", str(target), "--template", "local-demo", "--no-data"]) == 0
    capsys.readouterr()
    assert (target / "config" / "models.yaml").is_file()
    assert main(["validate", str(target / "config")]) == 0
    output = capsys.readouterr().out
    assert "OK models.yaml" in output
    assert "OK retrieval.yaml" in output
