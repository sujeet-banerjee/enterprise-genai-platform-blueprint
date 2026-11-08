from fastapi.testclient import TestClient

from app.main import create_app
from core.services.approval import ApprovalService


def _app(tmp_path):
    pol = tmp_path / "policies.yaml"
    pol.write_text(
        "enabled: true\nengine: noop\ndry_run: false\nhitl:\n  enabled: true\n  require_approval_for: [pipeline_rebuild]\n",
        encoding="utf-8",
    )
    return create_app(pipeline_builder=lambda **k: None, guardrails_config_path=None)


def test_approval_service_disabled_by_default(tmp_path):
    cfg = tmp_path / "policies.yaml"
    cfg.write_text("enabled: false\nhitl:\n  enabled: false\n", encoding="utf-8")
    svc = ApprovalService(config_path=str(cfg))
    assert svc.enabled() is False
    assert svc.requires_approval("pipeline_rebuild") is False
    assert svc.list_requests() == []


def test_approval_service_create_decide_and_gate(tmp_path):
    cfg = tmp_path / "policies.yaml"
    cfg.write_text(
        "hitl:\n  enabled: true\n  require_approval_for: [pipeline_rebuild]\n", encoding="utf-8"
    )
    svc = ApprovalService(config_path=str(cfg), clock=lambda: 1.0)
    assert svc.requires_approval("pipeline_rebuild") is True
    req = svc.create_request("pipeline_rebuild", context={"x": 1}, reason="r")
    assert req.status == "pending" and req.action == "pipeline_rebuild"
    got = svc.get(req.request_id)
    assert got is not None and got.request_id == req.request_id
    decided = svc.decide(req.request_id, "approved", decided_by="u", note="ok")
    assert decided.status == "approved" and decided.decided_by == "u"
    # idempotent on already decided
    again = svc.decide(req.request_id, "rejected")
    assert again.status == "approved"
    try:
        svc.decide(req.request_id, "bogus")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    try:
        svc.gate("pipeline_rebuild")
        raise AssertionError("expected gate")
    except Exception as exc:
        assert "approval required" in str(exc)


def test_approval_api_list_when_initialized(tmp_path):
    pol = tmp_path / "policies.yaml"
    pol.write_text("hitl:\n  enabled: false\n", encoding="utf-8")
    app = create_app(pipeline_builder=lambda **k: object())
    with TestClient(app) as c:
        c.app.state.approvals = ApprovalService(config_path=str(pol))
        r = c.get("/v1/approvals")
        assert r.status_code == 200
        body = r.json()
        assert "requests" in body and body["enabled"] is False


def test_approval_api_list_get_decision_and_not_found(tmp_path):
    pol = tmp_path / "policies.yaml"
    pol.write_text("hitl:\n  enabled: true\n  require_approval_for: ['*']\n", encoding="utf-8")
    app = create_app(pipeline_builder=lambda **k: None)
    with TestClient(app) as c:
        # replace service with enabled test config
        c.app.state.approvals = ApprovalService(config_path=str(pol), clock=lambda: 2.0)
        req = c.app.state.approvals.create_request(
            "sensitive_action", context={"k": "v"}, reason="needs review"
        )
        lst = c.get("/v1/approvals")
        assert lst.status_code == 200
        assert lst.json()["count"] == 1
        one = c.get(f"/v1/approvals/{req.request_id}")
        assert one.status_code == 200 and one.json()["status"] == "pending"
        bad = c.get("/v1/approvals/nope")
        assert bad.status_code == 404
        assert bad.json()["failure_type"] == "approval_not_found"
        dec = c.post(
            f"/v1/approvals/{req.request_id}/decision",
            json={"decision": "approved", "decided_by": "admin"},
        )
        assert dec.status_code == 200 and dec.json()["status"] == "approved"
        bad_dec = c.post(f"/v1/approvals/{req.request_id}/decision", json={"decision": "nope"})
        assert bad_dec.status_code in (400, 422)


def test_approval_api_invalid_decision_and_request_ids(tmp_path):
    pol = tmp_path / "policies.yaml"
    pol.write_text("hitl:\n  enabled: true\n  require_approval_for: ['*']\n", encoding="utf-8")
    app = create_app(pipeline_builder=lambda **k: None)
    with TestClient(app) as c:
        c.app.state.approvals = ApprovalService(config_path=str(pol))
        req = c.app.state.approvals.create_request("x")
        r = c.post(f"/v1/approvals/{req.request_id}/decision", json={"decision": "approved"})
        assert r.status_code == 200
        nf = c.post("/v1/approvals/missing/decision", json={"decision": "rejected"})
        assert nf.status_code == 404


def test_approval_requires_approval_matches_policy_decision(tmp_path):
    from core.interfaces.policy import PolicyDecision

    cfg = tmp_path / "policies.yaml"
    cfg.write_text("hitl:\n  enabled: true\n  require_approval_for: []\n", encoding="utf-8")
    svc = ApprovalService(config_path=str(cfg))
    assert (
        svc.requires_approval("anything", PolicyDecision(allowed=False, action="require_approval"))
        is True
    )
    assert svc.requires_approval("anything", PolicyDecision(allowed=True, action="allow")) is False
