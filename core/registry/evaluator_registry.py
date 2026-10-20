from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from core.evaluation.evaluation_engine import EvaluationEngine
from core.implementations.dummy_evaluator import DummyEvaluator
from core.implementations.null_evaluator import NullEvaluator
from core.interfaces.evaluator import BaseEvaluator


class EvaluatorRegistry:
    """
    Configuration-driven registry and factory for evaluators.

    Reads the ``evaluation`` block from config/retrieval.yaml:

        evaluation:
          enabled: true
          active_evaluator: dummy
          evaluators:
            dummy:  {provider: dummy}
            engine: {provider: engine}
            noop:   {provider: noop}

    Setting ``enabled: false`` returns a NullEvaluator so evaluation can be
    switched off without changing the pipeline.
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "retrieval.yaml"
            config_path = str(default_path)

        self.config_path = config_path
        with open(self.config_path, "r") as f:
            self.config = yaml.safe_load(f) or {}

        self._providers: Dict[str, Callable[..., BaseEvaluator]] = {}
        self._register_default_providers()

    def _register_default_providers(self) -> None:
        self.register("dummy", lambda **_: DummyEvaluator())
        self.register("engine", self._build_engine)
        self.register("semantic", self._build_semantic)
        self.register("llm_judge", self._build_llm_judge)
        self.register("noop", lambda **_: NullEvaluator())
        self.register("null", lambda **_: NullEvaluator())

    @staticmethod
    def _build_engine(**options: Any) -> BaseEvaluator:
        return EvaluationEngine(
            model_name=options.get("model_name", "sentence-transformers/all-MiniLM-L6-v2")
        )

    @staticmethod
    def _build_semantic(**options: Any) -> BaseEvaluator:
        from core.implementations.semantic_evaluator import SemanticEvaluator

        model_name = options.get("model_name", "sentence-transformers/all-MiniLM-L6-v2")
        return SemanticEvaluator(model_name=model_name)

    @staticmethod
    def _build_llm_judge(**options: Any) -> BaseEvaluator:
        from core.implementations.llm_judge_evaluator import LLMJudgeEvaluator

        return LLMJudgeEvaluator(
            model_name=options.get("model_name", "Qwen/Qwen2.5-0.5B-Instruct"),
            context_window=options.get("context_window", 32768),
            max_new_tokens=options.get("max_new_tokens", 128),
        )

    def register(self, provider_name: str, factory: Callable[..., BaseEvaluator]) -> None:
        self._providers[str(provider_name).lower()] = factory

    def list_providers(self) -> List[str]:
        return sorted(self._providers.keys())

    def list_evaluators(self) -> List[str]:
        return sorted((self.config.get("evaluation") or {}).get("evaluators", {}).keys())

    def is_enabled(self) -> bool:
        evaluation = self.config.get("evaluation") or {}
        return bool(evaluation.get("enabled", True))

    def resolve(self, name: Optional[str] = None) -> Tuple[str, str, Dict[str, Any]]:
        evaluation = self.config.get("evaluation") or {}
        evaluators = evaluation.get("evaluators") or {}

        key = name if name is not None else evaluation.get("active_evaluator", "dummy")
        if not key:
            raise ValueError("No evaluator specified and 'evaluation.active_evaluator' is missing.")

        if key in evaluators and isinstance(evaluators[key], dict):
            entry = dict(evaluators[key])
            provider = str(entry.get("provider", key)).lower()
        else:
            entry = {}
            provider = str(key).lower()

        if provider not in self._providers:
            raise ValueError(
                f"Unknown evaluator provider: '{provider}'. "
                f"Registered providers: {self.list_providers()}"
            )
        return str(key), provider, entry

    def create(self, name: Optional[str] = None, enabled: Optional[bool] = None) -> BaseEvaluator:
        if enabled is None:
            enabled = self.is_enabled()
        if not enabled:
            return NullEvaluator()

        _key, provider, entry = self.resolve(name)
        return self._providers[provider](**entry)
