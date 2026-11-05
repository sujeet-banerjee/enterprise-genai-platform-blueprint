"""UX7: UX polish, a11y, empty states, error remediation tests (#136)."""

from pathlib import Path

from ui import polish


def test_polish_helpers():
    assert polish.tooltip("api_base")
    es = polish.empty_state("No data")
    assert es["message"]
    rem = polish.error_remediation(503, "not_ready")
    assert rem["title"]
    rem2 = polish.error_remediation(403, "guardrail_input_blocked")
    assert "Forbidden" in rem2["title"] or "guardrail" in rem2["hint"]
    assert polish.a11y_label(" Query ")


def test_polish_screen_wired():
    src = Path("ui/app.py").read_text(encoding="utf-8")
    assert "error_remediation" in src
    assert "tooltip" in src
