import pytest
import yaml

from core.evaluation.evaluation_engine import EvaluationEngine
from core.implementations.dummy_evaluator import DummyEvaluator
from core.implementations.null_evaluator import NullEvaluator
from core.interfaces.evaluator import BaseEvaluator
from core.registry.evaluator_registry import EvaluatorRegistry


def _write_config(tmp_path, payload: dict) -> str:
    path = tmp_path / "retrieval.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return str(path)


def test_registry_loads_evaluation_section():
    registry = EvaluatorRegistry()
    assert registry.is_enabled() is True
    assert registry.config["evaluation"]["active_evaluator"] == "dummy"


def test_registry_lists_builtin_providers():
    registry = EvaluatorRegistry()
    assert set(["dummy", "engine", "noop"]).issubset(set(registry.list_providers()))


def test_registry_lists_configured_evaluators():
    registry = EvaluatorRegistry()
    assert set(registry.list_evaluators()) == {"dummy", "engine", "noop"}


def test_resolve_default_evaluator():
    registry = EvaluatorRegistry()
    key, provider, _entry = registry.resolve()
    assert key == "dummy"
    assert provider == "dummy"


def test_resolve_explicit_evaluator():
    registry = EvaluatorRegistry()
    _key, provider, _entry = registry.resolve("engine")
    assert provider == "engine"


def test_resolve_unknown_provider_raises(tmp_path):
    config_path = _write_config(
        tmp_path,
        {"evaluation": {"enabled": True, "active_evaluator": "nope", "evaluators": {}}},
    )
    registry = EvaluatorRegistry(config_path)
    with pytest.raises(ValueError, match="Unknown evaluator provider"):
        registry.resolve()


def test_create_returns_dummy_evaluator():
    registry = EvaluatorRegistry()
    evaluator = registry.create()
    assert isinstance(evaluator, DummyEvaluator)
    metrics = evaluator.evaluate("q", [], "r")
    assert "faithfulness" in metrics


def test_create_engine_evaluator_returns_metrics():
    registry = EvaluatorRegistry()
    evaluator = registry.create("engine")
    assert isinstance(evaluator, EvaluationEngine)
    metrics = evaluator.evaluate("what is ai", [], "ai is ...")
    assert "context_precision" in metrics


def test_disabled_evaluation_returns_null_evaluator():
    registry = EvaluatorRegistry()
    evaluator = registry.create(enabled=False)
    assert isinstance(evaluator, NullEvaluator)
    assert evaluator.evaluate("q", [], "r") == {}


def test_is_enabled_false_from_config(tmp_path):
    config_path = _write_config(
        tmp_path,
        {"evaluation": {"enabled": False, "active_evaluator": "dummy", "evaluators": {"dummy": {"provider": "dummy"}}}},
    )
    registry = EvaluatorRegistry(config_path)
    assert registry.is_enabled() is False
    assert isinstance(registry.create(), NullEvaluator)


def test_missing_evaluation_section_defaults_enabled(tmp_path):
    config_path = _write_config(tmp_path, {"retrieval": {"top_k": 3}})
    registry = EvaluatorRegistry(config_path)
    assert registry.is_enabled() is True
    assert isinstance(registry.create(), DummyEvaluator)


def test_register_custom_evaluator_is_plug_and_play(tmp_path):
    class _AlwaysZero(BaseEvaluator):
        def evaluate(self, query, retrieved_docs, response):
            return {"faithfulness": 0.0}

    config_path = _write_config(
        tmp_path,
        {"evaluation": {"enabled": True, "active_evaluator": "zero", "evaluators": {"zero": {"provider": "zero"}}}},
    )
    registry = EvaluatorRegistry(config_path)
    registry.register("zero", lambda **_: _AlwaysZero())
    evaluator = registry.create()
    assert evaluator.evaluate("q", [], "r") == {"faithfulness": 0.0}


def test_null_evaluator_returns_empty_metrics():
    assert NullEvaluator().evaluate("q", [], "r") == {}
