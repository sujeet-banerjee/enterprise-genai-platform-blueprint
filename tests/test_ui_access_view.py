"""Structured Access / RBAC presentation tests (#251)."""

from __future__ import annotations

from pathlib import Path

from ui import access_view

ACCESS = {
    "enabled": True,
    "role": "architect",
    "capabilities": ["query", "batch", "evaluate", "experiment", "rebuild", "admin"],
    "top_k_max": 10,
    "allowed_models": ["local-qwen"],
    "tenant": {"id": "acme", "workspace": "prod", "app": "console"},
    "identity_enabled": True,
    "subject": "alice@example.test",
    "groups": ["team-arch"],
    "request_id": "req-1",
    "api_key": "sk-should-not-appear",
}


def test_access_view_helpers_are_pure() -> None:
    source = Path("ui/access_view.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source
    assert "from app." not in source
    assert "from core." not in source
    assert "import app." not in source
    assert "import core." not in source


def test_identity_summary_resolves_persona_tenant_and_limits() -> None:
    summary = access_view.identity_summary(ACCESS)
    assert summary["role"] == "architect"
    assert summary["access_enabled"] is True
    assert summary["identity_enabled"] is True
    assert summary["subject"] == "alice@example.test"
    assert summary["groups"] == ["team-arch"]
    assert summary["tenant_id"] == "acme"
    assert summary["workspace"] == "prod"
    assert summary["app"] == "console"
    assert summary["top_k_max"] == "10"
    assert summary["allowed_models"] == ["local-qwen"]


def test_identity_summary_handles_missing_and_disabled_fields() -> None:
    summary = access_view.identity_summary({})
    assert summary["role"] == "-"
    assert summary["access_enabled"] is False
    assert summary["identity_enabled"] is False
    assert summary["subject"] == "-"
    assert summary["groups"] == []
    assert summary["top_k_max"] == "Unbounded"
    assert summary["allowed_models"] == []
    assert access_view.identity_summary({"top_k_max": True})["top_k_max"] == "Unbounded"


def test_summary_markdown_uses_plain_labels_and_escapes_values() -> None:
    html = access_view.summary_markdown({**ACCESS, "role": "<script>alert(1)</script>"})
    assert "Current persona" in html
    assert "Access control" in html
    assert "Enabled" in html
    assert "SSO session" in html
    assert "alice@example.test" in html
    assert "acme" in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "sk-should-not-appear" not in html


def test_capability_groups_cover_checklist_and_unknown_grants() -> None:
    groups = access_view.capability_groups({**ACCESS, "capabilities": ["query", "custom"]})
    assert [group["label"] for group in groups] == [
        "Use the platform",
        "Configure and inspect",
        "Oversight",
        "Other grants",
    ]
    first = groups[0]["items"]
    assert first[0]["name"] == "query" and first[0]["allowed"] is True
    assert first[1]["name"] == "batch" and first[1]["allowed"] is False
    assert first[0]["badge"]["tone"] == "success"
    assert first[1]["badge"]["tone"] == "neutral"
    assert groups[-1]["items"][0]["name"] == "custom"


def test_capabilities_markdown_renders_badges_notes_and_empty_state() -> None:
    html = access_view.capabilities_markdown(access_view.capability_groups(ACCESS))
    assert "genai-access-groups" in html
    assert "Granted" in html
    assert "Not granted" in html
    assert "Ask a single question" in html
    assert "genai-chip" in html
    assert "No capability information reported" in access_view.capabilities_markdown([])


def test_capabilities_markdown_escapes_unknown_capability_names() -> None:
    html = access_view.capabilities_markdown(
        access_view.capability_groups({"capabilities": ["<img src=x>"]})
    )
    assert "&lt;img src=x&gt;" in html
    assert "<img src=x>" not in html


def test_policy_notes_explain_enabled_role_in_plain_language() -> None:
    notes = access_view.policy_notes(ACCESS)
    joined = " ".join(notes)
    assert "Access control is on" in joined
    assert "single sign-on" in joined
    assert "team-arch" in joined
    assert "tenant acme" in joined
    assert "at most 10 documents" in joined
    assert "local-qwen" in joined
    assert "top_k_max" not in joined
    assert "sk-should-not-appear" not in joined


def test_policy_notes_explain_disabled_and_single_tenant_mode() -> None:
    notes = access_view.policy_notes({"enabled": False})
    joined = " ".join(notes)
    assert "Access control is off" in joined
    assert "API key" in joined
    assert "Single-tenant mode" in joined
    assert "no explicit limit" in joined
    assert "All configured models" in joined


def test_policy_markdown_is_escaped_and_handles_empty_notes() -> None:
    html = access_view.policy_markdown(["Use <b>care</b>", "", None])
    assert "What this means" in html
    assert "Use &lt;b&gt;care&lt;/b&gt;" in html
    assert "<b>care</b>" not in html
    assert html.count("<li>") == 1
    assert "No policy notes available" in access_view.policy_markdown([])


def test_access_view_models_summarize_kpis_and_redact_raw_payload() -> None:
    view = access_view.access_view_models(ACCESS)
    assert [kpi["label"] for kpi in view["kpis"]] == [
        "Access control",
        "Role",
        "Sign-in",
        "Retrieval depth",
        "Capabilities granted",
    ]
    assert view["kpis"][0]["value"] == "Enabled"
    assert view["kpis"][4]["value"] == "6"
    assert view["summary"]["role"] == "architect"
    assert len(view["groups"]) == 3
    assert len(view["notes"]) == 6
    assert view["raw"]["api_key"] == "[REDACTED]"
    assert "sk-should-not-appear" not in str(view)


def test_app_wires_structured_access_view_without_raw_dumps() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    start = source.index("def screen_access")
    end = source.index("\ndef ", start + 1)
    body = source[start:end]
    assert "access_view_models(" in body
    assert 'kpi_strip_markdown(view["kpis"])' in body
    assert 'view["summary_markdown"]' in body
    assert 'view["capabilities_markdown"]' in body
    assert 'view["policy_markdown"]' in body
    assert "with st.expander(DETAIL_EXPANDER_LABEL)" in body
    assert 'st.json(view["raw"])' in body
    assert "st.dataframe(" not in body
    assert "st.metric(" not in body


def test_access_wireframe_and_theme_are_indexed() -> None:
    assert Path("docs/wireframes/251-access-view.excalidraw").is_file()
    assert Path("docs/wireframes/251-access-view.svg").is_file()
    plan = Path("docs/ui-enterprise-look-and-feel-plan.md").read_text(encoding="utf-8")
    assert "251-access-view.svg" in plan
    theme = Path("ui/theme.py").read_text(encoding="utf-8")
    assert "genai-access-groups" in theme
    assert "genai-access-item" in theme
    assert "genai-access-notes" in theme
