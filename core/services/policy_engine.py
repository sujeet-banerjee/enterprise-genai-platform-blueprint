"""CEL-like policy evaluator and versioned bundles (#122)."""

from __future__ import annotations

import ast
import json
import operator
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from core.interfaces.policy import BasePolicyEngine, PolicyDecision

_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}
_BOOL = {ast.And: all, ast.Or: any}
_UNARY = {ast.Not: operator.not_, ast.USub: operator.neg, ast.UAdd: operator.pos}


class _Ctx(dict):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _wrap(value: Any) -> Any:
    if isinstance(value, dict) and not isinstance(value, _Ctx):
        return _Ctx({k: _wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_wrap(v) for v in value]
    return value


def eval_expression(expr: str, context: Dict[str, Any]) -> bool:
    """Safely evaluate a CEL-like boolean expression over *context*."""
    if not expr or not str(expr).strip():
        return True
    node = ast.parse(str(expr), mode="eval")
    return bool(_eval(node.body, _wrap(dict(context))))


def _eval(node: ast.AST, ctx: Any) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in {"true", "True"}:
            return True
        if node.id in {"false", "False"}:
            return False
        if node.id in {"null", "None"}:
            return None
        return ctx[node.id] if isinstance(ctx, dict) else getattr(ctx, node.id)
    if isinstance(node, ast.Attribute):
        value = _eval(node.value, ctx)
        if isinstance(value, dict):
            return value.get(node.attr)
        return getattr(value, node.attr, None)
    if isinstance(node, ast.Subscript):
        value = _eval(node.value, ctx)
        key = _eval(node.slice, ctx)
        try:
            return value[key]
        except Exception:
            return None
    if isinstance(node, ast.BoolOp):
        fn = _BOOL.get(type(node.op), all)
        values = (_eval(v, ctx) for v in node.values)
        return fn(bool(v) for v in values)
    if isinstance(node, ast.UnaryOp):
        fn = _UNARY.get(type(node.op))
        if fn is None:
            return False
        return fn(_eval(node.operand, ctx))
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        for op_node, comp in zip(node.ops, node.comparators):
            fn = _CMP.get(type(op_node))
            right = _eval(comp, ctx)
            if fn is None or not fn(left, right):
                return False
            left = right
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_eval(e, ctx) for e in node.elts]
    if isinstance(node, ast.Dict):
        return {_eval(k, ctx): _eval(v, ctx) for k, v in zip(node.keys, node.values) if k is not None}
    if isinstance(node, ast.Call):
        # allow simple helpers: has(obj, key), size(x), matches? no regex by default
        func = node.func.id if isinstance(node.func, ast.Name) else None
        args = [_eval(a, ctx) for a in node.args]
        if func == "has" and len(args) == 2:
            return args[1] in args[0] if isinstance(args[0], (dict, list, tuple, str)) else hasattr(args[0], str(args[1]))
        if func == "size" and len(args) == 1:
            try:
                return len(args[0])
            except Exception:
                return 0
        if func in {"startsWith", "starts_with"} and len(args) == 2:
            return str(args[0]).startswith(str(args[1]))
        if func in {"endsWith", "ends_with"} and len(args) == 2:
            return str(args[0]).endswith(str(args[1]))
        return False
    raise ValueError(f"unsupported expression node: {type(node).__name__}")


def _iter_bundle_paths(bundles: Iterable[Any], base_dir: Optional[Path]) -> List[Path]:
    paths: List[Path] = []
    for item in bundles or []:
        if isinstance(item, str):
            p = Path(item)
            if base_dir and not p.is_absolute():
                p = base_dir / p
            paths.append(p)
        elif isinstance(item, dict) and item.get("path"):
            p = Path(str(item["path"]))
            if base_dir and not p.is_absolute():
                p = base_dir / p
            paths.append(p)
    return paths


class BundlePolicyEngine(BasePolicyEngine):
    """Versioned policy bundles with a safe CEL-like expression evaluator."""

    name = "cel"

    def __init__(self, bundles: Optional[Iterable[Any]] = None, base_dir: Optional[str] = None, dry_run: bool = False):
        self.base_dir = Path(base_dir) if base_dir else None
        self.bundle_specs = list(bundles or [])
        self.dry_run_default = bool(dry_run)
        self.bundles: List[Dict[str, Any]] = []
        self._load_configured_bundles()

    def _load_configured_bundles(self) -> None:
        for path in _iter_bundle_paths(self.bundle_specs, self.base_dir):
            try:
                self.load_bundle(str(path))
            except Exception:
                continue

    def load_bundle(self, path: str) -> Dict[str, Any]:
        p = Path(path)
        if self.base_dir and not p.is_absolute():
            p = self.base_dir / p
        text = p.read_text(encoding="utf-8")
        if p.suffix.lower() == ".json":
            data = json.loads(text) or {}
        else:
            data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            data = {"policies": []}
        data.setdefault("path", str(p))
        data.setdefault("version", data.get("bundle_version") or "1")
        data.setdefault("policies", [])
        self.bundles.append(data)
        return data

    def _matches_action(self, rule: Dict[str, Any], action: str) -> bool:
        actions = rule.get("actions") or rule.get("action")
        if actions is None or actions == "*" or actions == ["*"]:
            return True
        if isinstance(actions, str):
            return actions == action
        try:
            return action in actions
        except Exception:
            return False

    def evaluate(self, action: str, context: Dict[str, Any], dry_run: bool = False) -> PolicyDecision:
        effective_dry_run = bool(dry_run or self.dry_run_default)
        ctx = dict(context or {})
        ctx.setdefault("action", action)
        for bundle in self.bundles:
            for rule in bundle.get("policies") or []:
                if not isinstance(rule, dict):
                    continue
                if not self._matches_action(rule, action):
                    continue
                expr = rule.get("when") or rule.get("condition") or rule.get("cel") or "true"
                try:
                    matched = eval_expression(str(expr), ctx)
                except Exception as exc:
                    decision = PolicyDecision(
                        allowed=not effective_dry_run,
                        action="deny",
                        reason=f"policy_error:{exc}",
                        labels=["policy:error"],
                        dry_run=effective_dry_run,
                        bundle=str(bundle.get("name") or bundle.get("version") or bundle.get("path")),
                        policy_id=str(rule.get("id") or rule.get("name") or "unknown"),
                    )
                    return decision
                if not matched:
                    continue
                effect = str(rule.get("effect") or "deny").lower()
                if effect == "allow":
                    return PolicyDecision(
                        allowed=True,
                        action="allow",
                        reason=str(rule.get("reason") or "allow"),
                        labels=list(rule.get("labels") or []),
                        dry_run=effective_dry_run,
                        bundle=str(bundle.get("name") or bundle.get("version") or bundle.get("path")),
                        policy_id=str(rule.get("id") or rule.get("name") or "rule"),
                    )
                blocked = effect in {"deny", "block"}
                require = effect in {"require_approval", "hitl", "approve"}
                return PolicyDecision(
                    allowed=(not blocked and not require) or effective_dry_run,
                    action=("require_approval" if require else "deny"),
                    reason=str(rule.get("reason") or effect),
                    labels=list(rule.get("labels") or []),
                    dry_run=effective_dry_run,
                    bundle=str(bundle.get("name") or bundle.get("version") or bundle.get("path")),
                    policy_id=str(rule.get("id") or rule.get("name") or "rule"),
                    metadata={"effect": effect, "version": str(bundle.get("version") or "1")},
                )
        return PolicyDecision(allowed=True, action="allow", reason="no_match", dry_run=effective_dry_run)
