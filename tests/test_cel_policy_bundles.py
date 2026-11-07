"""CEL evaluator and versioned policy bundles tests (#122)."""

import json

from core.registry.policy_registry import PolicyRegistry
from core.services.policy_engine import BundlePolicyEngine, eval_expression


def test_eval_expression_basic_comparisons():
    assert eval_expression("action == 'query'", {"action": "query"}) is True
    assert eval_expression("action == 'query'", {"action": "delete"}) is False
    assert eval_expression("tenant != 'prod'", {"tenant": "dev"}) is True


def test_eval_expression_nested_context_and_helpers():
    ctx = {"user": {"role": "admin"}, "action": "query", "tags": ["a"]}
    assert eval_expression("user.role == 'admin'", ctx) is True
    assert eval_expression("has(user, 'role')", ctx) is True
    assert eval_expression("size(tags) == 1", ctx) is True
    assert eval_expression("startsWith(action, 'q')", ctx) is True


def test_bundle_policy_engine_versioned_deny_and_allow(tmp_path):
    bundle = tmp_path / "bundle-v1.yaml"
    bundle.write_text(
        "name: b1\nversion: '1'\npolicies:\n"
        "  - id: deny-admin-delete\n    actions: [delete]\n    when: \"user.role == 'admin'\"\n    effect: deny\n    reason: blocked\n"
        "  - id: allow-query\n    actions: [query]\n    when: 'true'\n    effect: allow\n",
        encoding="utf-8",
    )
    e = BundlePolicyEngine(bundles=[str(bundle)])
    res = e.evaluate("delete", {"user": {"role": "admin"}})
    assert res.allowed is False and res.action == "deny" and res.policy_id == "deny-admin-delete"
    assert e.evaluate("query", {"user": {"role": "admin"}}).allowed is True


def test_bundle_policy_engine_dry_run_records_decision(tmp_path):
    bundle = tmp_path / "bundle.json"
    bundle.write_text(
        json.dumps({"name": "b2", "version": "2", "policies": [{"id": "p", "actions": ["delete"], "effect": "deny"}]}),
        encoding="utf-8",
    )
    e = BundlePolicyEngine(bundles=[str(bundle)], dry_run=True)
    res = e.evaluate("delete", {})
    assert res.allowed is True and res.action == "deny" and res.dry_run is True
    assert res.bundle in {"b2", "2", str(bundle)}


def test_bundle_policy_engine_require_approval(tmp_path):
    bundle = tmp_path / "bundle.yaml"
    bundle.write_text(
        "name: b3\nversion: '3'\npolicies:\n  - id: hitl\n    actions: [publish]\n    effect: require_approval\n",
        encoding="utf-8",
    )
    e = BundlePolicyEngine(bundles=[str(bundle)])
    res = e.evaluate("publish", {})
    assert res.allowed is False and res.action == "require_approval"


def test_policy_registry_cel_engine_and_bundle_resolution(tmp_path):
    bundle = tmp_path / "policy_bundles" / "v1.yaml"
    bundle.parent.mkdir()
    bundle.write_text("name: v1\nversion: '1'\npolicies:\n  - id: d\n    actions: [delete]\n    effect: deny\n", encoding="utf-8")
    cfg = tmp_path / "policies.yaml"
    cfg.write_text(
        "enabled: true\nengine: cel\nbundles:\n  - policy_bundles/v1.yaml\ndry_run: false\nhitl:\n  enabled: false\n  require_approval_for: []\n",
        encoding="utf-8",
    )
    r = PolicyRegistry(config_path=str(cfg))
    e = r.create()
    res = e.evaluate("delete", {})
    assert res.allowed is False and res.policy_id == "d"


def test_default_policies_yaml_kept_disabled():
    r = PolicyRegistry()
    e = r.create()
    assert e.evaluate("delete", {}).allowed is True
