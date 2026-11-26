from pathlib import Path

from ui.qa_checks import (
    CAPTURE_SLUGS,
    QA_CSS_TOKENS,
    area_checklist,
    capture_manifest,
    check_capture_doc,
    check_http_only,
    check_pure_helper,
    check_theme_tokens,
    qa_matrix,
    qa_report_markdown,
    qa_summary,
    validate_qa_artifacts,
)

REPO_BASE = Path(__file__).resolve().parents[1]
APP_PATH = REPO_BASE / "ui" / "app.py"
HELPER_PATH = REPO_BASE / "ui" / "qa_checks.py"
THEME_PATH = REPO_BASE / "ui" / "theme.py"
A11Y_PATH = REPO_BASE / "ui" / "a11y.py"
QA_DOC_PATH = REPO_BASE / "docs" / "showcase" / "qa-and-captures.md"
PLAN_DOC_PATH = REPO_BASE / "docs" / "ui-enterprise-look-and-feel-plan.md"
SHOWCASE_INDEX_PATH = REPO_BASE / "docs" / "showcase" / "README.md"
DEMO_DOC_PATH = REPO_BASE / "docs" / "showcase" / "demo-walkthrough.md"
SHOWCASE_DIR = REPO_BASE / "docs" / "showcase"

EXPECTED_TARGETS = {
    "overview-health",
    "query-studio-result",
    "traces-waterfall-compare",
    "governance-cost",
    "guardrails-decisions",
    "approvals-queue",
    "audit-timeline",
    "settings-readonly",
}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_capture_slugs_match_issue_targets() -> None:
    assert set(CAPTURE_SLUGS) == EXPECTED_TARGETS


def test_qa_matrix_covers_every_viewport_theme_and_mode() -> None:
    rows = qa_matrix()
    assert len(rows) == 27
    assert {(row["viewport"], row["theme"], row["mode"]) for row in rows} == {
        (viewport, theme, mode)
        for viewport in ("375", "768", "1280")
        for theme in ("Light", "Dark", "High contrast")
        for mode in ("normal", "demo", "restricted role")
    }
    assert {row["result"] for row in rows} == {"documented"}


def test_qa_summary_counts_matrix_rows() -> None:
    assert qa_summary(qa_matrix()) == {
        "total": 27,
        "by_result": {"documented": 27},
        "by_viewport": {"375": 9, "768": 9, "1280": 9},
    }


def test_area_checklist_covers_plan_areas_with_known_targets() -> None:
    rows = area_checklist()
    assert len(rows) == 8
    assert {row["area"] for row in rows} == {
        "Shell & nav",
        "Status semantics",
        "Raw-data discipline",
        "Tables & cards",
        "Charts/timelines",
        "States",
        "Trust cues",
        "Accessibility",
    }
    for row in rows:
        assert row["captures"]
        assert set(row["captures"]) <= EXPECTED_TARGETS


def test_capture_manifest_has_three_variants_per_target() -> None:
    manifest = capture_manifest()
    assert [row["slug"] for row in manifest] == [
        "overview-health",
        "query-studio-result",
        "traces-waterfall-compare",
        "governance-cost",
        "guardrails-decisions",
        "approvals-queue",
        "audit-timeline",
        "settings-readonly",
    ]
    for row in manifest:
        assert len(row["variants"]) == 3
        assert [variant["slug"] for variant in row["variants"]] == [
            f"{row['slug']}-light-1280",
            f"{row['slug']}-compact",
            f"{row['slug']}-high-contrast",
        ]
        assert "Pending - add external link (#232)" in row["link"]


def test_http_only_guard_rejects_backend_imports_and_literals() -> None:
    issues = check_http_only(
        "import app.pipeline\nfrom core.services import thing\nvalue = 'app.pipeline'\n"
    )
    assert any("imports app" in issue for issue in issues)
    assert any("imports core" in issue for issue in issues)
    assert any("forbidden literal" in issue for issue in issues)


def test_http_only_guard_accepts_http_client_import() -> None:
    assert check_http_only("import requests\nfrom ui.client import ApiClient\n") == []


def test_pure_helper_guard_rejects_streamlit_and_http_clients() -> None:
    issues = check_pure_helper("import streamlit as st\nimport requests\nfrom core import x\n")
    assert any("imports streamlit" in issue for issue in issues)
    assert any("imports requests" in issue for issue in issues)
    assert any("imports core" in issue for issue in issues)
    assert check_pure_helper(_read_text(HELPER_PATH)) == []


def test_theme_token_checks_cover_layout_accessibility_and_trust() -> None:
    css = _read_text(THEME_PATH) + _read_text(A11Y_PATH)
    assert check_theme_tokens(css) == []
    assert check_theme_tokens("") == sorted(QA_CSS_TOKENS)


def test_capture_doc_check_finds_missing_targets() -> None:
    assert check_capture_doc(_read_text(QA_DOC_PATH)) == []
    missing = check_capture_doc("overview-health")
    assert "overview-health" not in missing
    assert set(missing) == EXPECTED_TARGETS - {"overview-health"}


def test_qa_report_matches_generated_helper_output() -> None:
    assert qa_report_markdown().strip() == _read_text(QA_DOC_PATH).strip()
    assert "&amp;" not in qa_report_markdown()


def test_showcase_links_qa_report_without_raster_captures() -> None:
    assert "qa-and-captures.md" in _read_text(SHOWCASE_INDEX_PATH)
    assert "qa-and-captures.md" in _read_text(DEMO_DOC_PATH)
    assert not list(SHOWCASE_DIR.glob("*.png"))
    assert not list(SHOWCASE_DIR.glob("*.jpg"))
    assert not list(SHOWCASE_DIR.glob("*.jpeg"))


def test_validate_qa_artifacts_accepts_shipped_artifacts() -> None:
    css = _read_text(THEME_PATH) + _read_text(A11Y_PATH)
    assert validate_qa_artifacts(
        _read_text(APP_PATH),
        _read_text(HELPER_PATH),
        css,
        _read_text(QA_DOC_PATH),
        _read_text(PLAN_DOC_PATH),
        _read_text(SHOWCASE_INDEX_PATH),
    ) == []
