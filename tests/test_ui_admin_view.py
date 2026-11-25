"""Structured Admin presentation tests (#252)."""

from __future__ import annotations

from pathlib import Path

from ui import admin_view

TENANTS = {
    "enabled": True,
    "tenants": [
        {
            "id": "acme",
            "workspace": "prod",
            "app": "console",
            "cost_center": "platform",
            "budget_cap_usd": 25.0,
            "top_k_max": 10,
            "allowed_models": ["local-qwen"],
        }
    ],
}

USERS = {
    "enabled": True,
    "users": [
        {
            "id": "u-1",
            "userName": "alice@example.test",
            "active": True,
            "role": "architect",
            "groups": ["team-arch"],
        },
        {
            "id": "u-2",
            "userName": "bob@example.test",
            "active": False,
            "role": "viewer",
            "groups": [],
        },
    ],
}

AUDIT = {
    "events": [
        {
            "timestamp": "2026-11-25T10:00:00Z",
            "event_type": "config",
            "action": "pipeline_rebuild",
            "outcome": "denied",
            "request_id": "req-1",
            "tenant": "acme",
        }
    ]
}


def test_admin_view_helpers_are_pure() -> None:
    source = Path("ui/admin_view.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source
    assert "from app." not in source
    assert "from core." not in source
    assert "import app." not in source
    assert "import core." not in source


def test_tenant_cards_summarize_policy() -> None:
    cards = admin_view.tenant_cards(TENANTS)
    assert len(cards) == 1
    card = cards[0]
    assert card["id"] == "acme"
    assert card["workspace"] == "prod"
    assert card["app"] == "console"
    assert card["status"] == "Guarded"
    assert card["badge"]["tone"] == "success"
    assert card["details"]["budget_cap_usd"] == "25"
    assert card["details"]["top_k_max"] == "10"
    assert card["details"]["allowed_models"] == "local-qwen"


def test_tenant_cards_handle_disabled_and_empty_payloads() -> None:
    cards = admin_view.tenant_cards({"enabled": False, "tenants": [{"id": "acme"}]})
    assert cards[0]["status"] == "Implicit"
    assert cards[0]["badge"]["tone"] == "warning"
    assert admin_view.tenant_cards({}) == []
    assert "No tenants returned." in admin_view.tenant_cards_markdown([])


def test_tenant_cards_markdown_escapes_tenant_ids() -> None:
    html = admin_view.tenant_cards_markdown(
        admin_view.tenant_cards({"tenants": [{"id": "<script>alert(1)</script>"}]})
    )
    assert "genai-admin-cards" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>" not in html


def test_user_rows_mark_active_and_disabled_users() -> None:
    rows = admin_view.user_rows(USERS)
    assert len(rows) == 2
    assert rows[0]["name"] == "alice@example.test"
    assert rows[0]["status"] == "Active"
    assert rows[0]["badge"]["tone"] == "success"
    assert rows[1]["status"] == "Disabled"
    assert rows[1]["badge"]["tone"] == "danger"
    assert rows[0]["source"] == "SCIM directory"


def test_user_table_markdown_renders_status_table_and_empty_state() -> None:
    html = admin_view.user_table_markdown(admin_view.user_rows(USERS))
    assert "genai-admin-table" in html
    assert "alice@example.test" in html
    assert "team-arch" in html
    assert "Active" in html
    assert "Disabled" in html
    assert "No users returned" in admin_view.user_table_markdown([])


def test_audit_rows_and_table_are_structured_and_escaped() -> None:
    rows = admin_view.recent_audit_rows(AUDIT)
    assert len(rows) == 1
    assert rows[0]["outcome"] == "denied"
    assert rows[0]["badge"]["tone"] == "danger"
    html = admin_view.audit_table_markdown(rows)
    assert "genai-audit-timeline" in html
    assert "pipeline_rebuild" in html
    assert "req-1" in html
    escaped = admin_view.audit_table_markdown(
        admin_view.recent_audit_rows({"events": [{**AUDIT["events"][0], "action": "<img src=x>"}]})
    )
    assert "&lt;img src=x&gt;" in escaped
    assert "<img src=x>" not in escaped


def test_admin_banners_include_scope_change_and_identity_notice() -> None:
    enabled = admin_view.admin_banners(TENANTS, USERS)
    assert len(enabled) == 2
    assert "Tenant isolation is enabled" in enabled[0]["message"]
    assert "Confirm update tenant configuration" in enabled[1]["message"]
    assert enabled[1]["tone"] == "warning"
    disabled = admin_view.admin_banners({}, {})
    assert len(disabled) == 3
    assert "single-tenant mode" in disabled[0]["message"]
    assert "Identity is disabled" in disabled[2]["message"]
    html = admin_view.banners_markdown(enabled)
    assert 'role="alert"' in html
    assert "genai-alert-warning" in html


def test_section_cards_and_change_control_render_segments() -> None:
    sections = admin_view.section_cards("<p>tenants</p>", "<p>users</p>", "<p>audit</p>", "<p>change</p>")
    assert [section["title"] for section in sections] == [
        "Tenants",
        "Users (identity directory)",
        "Recent audit",
        "Change control",
    ]
    html = admin_view.sections_markdown(sections)
    assert "genai-admin-sections" in html
    assert "Tenant updates require explicit confirmation" in html
    assert "Metadata-only CSV export" in html
    assert "Before you update" in admin_view.change_control_markdown()


def test_admin_view_models_summarize_kpis_and_redact_raw_payload() -> None:
    view = admin_view.admin_view_models(
        TENANTS,
        USERS,
        AUDIT,
        {"role": "admin", "api_key": "sk-should-not-appear"},
    )
    assert [kpi["label"] for kpi in view["kpis"]] == [
        "Tenant isolation",
        "Tenants",
        "Directory",
        "Active users",
        "Recent events",
    ]
    assert view["kpis"][1]["value"] == "1"
    assert view["kpis"][4]["value"] == "1"
    assert view["raw"]["access"]["api_key"] == "[REDACTED]"
    assert "sk-should-not-appear" not in str(view)


def test_admin_view_models_handle_empty_payloads() -> None:
    view = admin_view.admin_view_models({}, {}, {})
    assert view["tenants"] == []
    assert view["users"] == []
    assert view["audit"] == []
    assert view["kpis"][0]["value"] == "Disabled"
    assert view["kpis"][2]["value"] == "Disabled"
    assert "No tenants returned." in view["sections_markdown"]
    assert "No users returned" in view["sections_markdown"]
    assert "No recent audit events." in view["sections_markdown"]


def test_app_wires_structured_admin_view_without_raw_dumps() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    start = source.index("def screen_admin")
    end = source.index("\ndef ", start + 1)
    body = source[start:end]
    assert "admin_view_models(" in body
    assert 'kpi_strip_markdown(view["kpis"])' in body
    assert 'view["banners_markdown"]' in body
    assert 'view["sections_markdown"]' in body
    assert "with st.expander(DETAIL_EXPANDER_LABEL)" in body
    assert 'st.json(view["raw"])' in body
    assert "st.checkbox(" in body
    assert "Download audit CSV" in body
    assert "st.dataframe(" not in body
    assert "st.metric(" not in body


def test_admin_wireframe_and_theme_are_indexed() -> None:
    assert Path("docs/wireframes/252-admin-view.excalidraw").is_file()
    assert Path("docs/wireframes/252-admin-view.svg").is_file()
    plan = Path("docs/ui-enterprise-look-and-feel-plan.md").read_text(encoding="utf-8")
    assert "252-admin-view.svg" in plan
    theme = Path("ui/theme.py").read_text(encoding="utf-8")
    assert "genai-admin-sections" in theme
    assert "genai-admin-cards" in theme
    assert "genai-admin-table" in theme
