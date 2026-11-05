"""UX6: Admin/tenancy safety UX tests (#135)."""

from pathlib import Path

from ui import admin


def test_admin_helpers():
    ind = admin.scope_indicator({"enabled": True, "default_tenant": "t1"})
    assert ind["enabled"] is True
    assert "Tenant" in ind["scope_text"]
    c = admin.confirm_action("delete tenant")
    assert "Confirm" in c
    rows = admin.audit_export_rows([{"timestamp": "x", "event_type": "config", "action": "update", "outcome": "ok", "request_id": "r1", "tenant": "t1"}])
    assert rows[0]["action"] == "update"


def test_admin_screen_wired():
    src = Path("ui/app.py").read_text(encoding="utf-8")
    assert "scope_indicator" in src
    assert "confirm_action" in src
    assert "audit_export_rows" in src
    assert "Download audit CSV" in src
