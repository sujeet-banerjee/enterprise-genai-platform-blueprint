"""Policy-as-Code engine interface tests (#121)."""

from core.interfaces.policy import NoopPolicyEngine, PolicyDecision
from core.registry.policy_registry import PolicyRegistry


def test_policy_decision_defaults():
    d = PolicyDecision()
    assert d.allowed is True
    assert d.action == "allow"


def test_noop_policy_engine_allows():
    e = NoopPolicyEngine()
    res = e.evaluate("query", {"user": "u"})
    assert res.allowed is True
    assert res.reason == "noop"


def test_noop_policy_engine_load_bundle():
    e = NoopPolicyEngine()
    b = e.load_bundle("/tmp/p.yaml")
    assert b["path"] == "/tmp/p.yaml"


def test_policy_registry_disabled_default(tmp_path):
    cfg = tmp_path / "policies.yaml"
    cfg.write_text("enabled: false\n", encoding="utf-8")
    r = PolicyRegistry(config_path=str(cfg))
    e = r.create()
    assert e.evaluate("x", {}).allowed is True


def test_policy_registry_enabled_noop(tmp_path):
    cfg = tmp_path / "policies.yaml"
    cfg.write_text("enabled: true\nengine: noop\n", encoding="utf-8")
    r = PolicyRegistry(config_path=str(cfg))
    e = r.create()
    assert isinstance(e, NoopPolicyEngine)


def test_policy_registry_unknown_engine_falls_back(tmp_path):
    cfg = tmp_path / "policies.yaml"
    cfg.write_text("enabled: true\nengine: missing\n", encoding="utf-8")
    r = PolicyRegistry(config_path=str(cfg))
    e = r.create()
    assert e.evaluate("x", {}).allowed is True
