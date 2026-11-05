"""UX5: Governance/metrics filters & export tests (#134)."""

from pathlib import Path

from ui import governance


def test_governance_helpers():
    assert "Last hour" in governance.time_windows()
    m = {"totals": {"requests": 100, "failures": 5}, "failures_by_type": {"timeout": 5}}
    out = governance.filter_metrics(m, tenant="t1", app="app")
    assert out["_ui_filters"]["tenant"] == "t1"
    csvv = governance.metrics_to_csv(m)
    assert "totals" in csvv
    js = governance.metrics_to_json(m)
    assert "totals" in js
    alerts = governance.alerts_preview(m)
    assert isinstance(alerts, list)


def test_governance_screen_wired():
    src = Path("ui/app.py").read_text(encoding="utf-8")
    assert "time_windows" in src
    assert "Download JSON" in src
    assert "Download CSV" in src
    assert "Alerts preview" in src
