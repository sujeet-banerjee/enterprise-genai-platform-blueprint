"""Read-only introspection over the configured registries (issue #35).

Builds listings from the *same* config files the composition root uses, so what
the API reports is what the pipeline actually runs. The effective-config view is
passed through ``SensitiveDataRedactor`` before it ever leaves the process.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from core.registry.evaluator_registry import EvaluatorRegistry
from core.registry.model_registry import ModelRegistry
from core.registry.pii_registry import PiiRegistry
from core.registry.reranker_registry import RerankerRegistry
from core.registry.retriever_registry import RetrieverRegistry
from core.services.observability import SensitiveDataRedactor


def _read_yaml(path: Optional[Path]) -> dict:
    if not path:
        return {}
    try:
        with open(path, "r") as f:
            loaded = yaml.safe_load(f) or {}
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


class IntrospectionService:
    def __init__(
        self,
        models_config_path: Path,
        retrieval_config_path: Path,
        prompt_config_path: Optional[Path] = None,
        governance_config_path: Optional[Path] = None,
        observability_config_path: Optional[Path] = None,
        api_config_path: Optional[Path] = None,
        guardrails_config_path: Optional[Path] = None,
    ):
        self.models_config_path = Path(models_config_path)
        self.retrieval_config_path = Path(retrieval_config_path)
        self.prompt_config_path = Path(prompt_config_path) if prompt_config_path else None
        self.governance_config_path = Path(governance_config_path) if governance_config_path else None
        self.observability_config_path = (
            Path(observability_config_path) if observability_config_path else None
        )
        self.api_config_path = Path(api_config_path) if api_config_path else None
        self.guardrails_config_path = (
            Path(guardrails_config_path) if guardrails_config_path else None
        )

        self.model_registry = ModelRegistry(str(self.models_config_path))
        self.retriever_registry = RetrieverRegistry(str(self.retrieval_config_path))
        self.reranker_registry = RerankerRegistry(str(self.retrieval_config_path))
        self.evaluator_registry = EvaluatorRegistry(str(self.retrieval_config_path))

        retrieval_config = self.retriever_registry.config or {}
        legacy_obs = retrieval_config.get("observability") or {}
        dedicated_obs = _read_yaml(self.observability_config_path)
        obs_config = dedicated_obs or legacy_obs
        # PII / DLP scrubbing (issue #54): the config view must not leak
        # personal data either, so the redactor gets the PII detector.
        pii_registry = PiiRegistry(config=obs_config)
        pii_detector = pii_registry.build_detector()
        self._redactor = SensitiveDataRedactor(
            enabled=bool(obs_config.get("redact_sensitive_data", True)),
            patterns=obs_config.get("sensitive_patterns")
            if isinstance(obs_config, dict)
            else None,
            pii_detector=pii_detector,
            pii_classes=pii_registry.classes() if pii_detector is not None else None,
        )

    # -- effective config -------------------------------------------------

    def effective_config(self) -> Dict[str, Any]:
        merged = {
            "models": self.model_registry.config,
            "retrieval": self.retriever_registry.config,
            "prompt": _read_yaml(self.prompt_config_path),
            "governance": _read_yaml(self.governance_config_path),
            "observability": _read_yaml(self.observability_config_path),
            "api": _read_yaml(self.api_config_path),
            "guardrails": _read_yaml(self.guardrails_config_path),
        }
        redacted = self._redactor.redact_obj(merged)
        return redacted if isinstance(redacted, dict) else merged

    # -- listings ---------------------------------------------------------

    @property
    def _models_config(self) -> dict:
        return self.model_registry.config or {}

    @property
    def _retrieval_config(self) -> dict:
        return self.retriever_registry.config or {}

    def active_model(self) -> str:
        return str(self._models_config.get("active_model") or "")

    def active_embedding_model(self) -> Optional[str]:
        value = self._models_config.get("active_embedding_model")
        return str(value) if value else None

    def list_models(self) -> Dict[str, Any]:
        models_cfg = self._models_config.get("models") or {}
        active = self.active_model()
        models = []
        for name, cfg in models_cfg.items():
            cfg = cfg or {}
            models.append(
                {
                    "name": str(name),
                    "active": str(name) == active,
                    "provider": cfg.get("provider"),
                    "context_window": cfg.get("context_window"),
                    "input_cost_per_1k": cfg.get("input_cost_per_1k"),
                    "output_cost_per_1k": cfg.get("output_cost_per_1k"),
                }
            )

        active_config: Dict[str, Any] = self.model_registry.get_active_model_config()
        active_config = dict(active_config)
        active_config.setdefault("name", active)
        return {"active": active, "models": models, "active_config": active_config}

    def list_embedding_models(self) -> Dict[str, Any]:
        embedding_cfg = self._models_config.get("embedding_models") or {}
        active = self.active_embedding_model()
        embedding_models = []
        for name, cfg in embedding_cfg.items():
            cfg = cfg or {} if isinstance(cfg, dict) else {"model_name": cfg}
            embedding_models.append(
                {
                    "name": str(name),
                    "active": str(name) == active,
                    "provider": cfg.get("provider"),
                    "model_name": cfg.get("model_name"),
                    "dimension": cfg.get("dimension"),
                }
            )
        return {"active": active, "embedding_models": embedding_models}

    def list_retrievers(self) -> Dict[str, Any]:
        retrieval_cfg = self._retrieval_config.get("retrieval") or {}
        retrievers = []
        for name, cfg in (retrieval_cfg.get("retrievers") or {}).items():
            cfg = cfg or {} if isinstance(cfg, dict) else {}
            options = {k: v for k, v in cfg.items() if k != "provider"}
            retrievers.append(
                {"key": str(name), "provider": cfg.get("provider"), "options": options}
            )
        return {
            "default_retriever": retrieval_cfg.get("default_retriever"),
            "similarity_metric": retrieval_cfg.get("similarity_metric"),
            "providers": self.retriever_registry.list_providers(),
            "retrievers": retrievers,
        }

    def list_rerankers(self) -> Dict[str, Any]:
        reranking_cfg = self._retrieval_config.get("reranking") or {}
        rerankers = []
        for name, cfg in (reranking_cfg.get("rerankers") or {}).items():
            cfg = cfg or {} if isinstance(cfg, dict) else {}
            options = {k: v for k, v in cfg.items() if k != "provider"}
            rerankers.append(
                {"key": str(name), "provider": cfg.get("provider"), "options": options}
            )
        return {
            "enabled": self.reranker_registry.is_enabled(),
            "active_reranker": reranking_cfg.get("active_reranker"),
            "providers": self.reranker_registry.list_providers(),
            "rerankers": rerankers,
        }

    def list_evaluators(self) -> Dict[str, Any]:
        evaluation_cfg = self._retrieval_config.get("evaluation") or {}
        evaluators = []
        for name, cfg in (evaluation_cfg.get("evaluators") or {}).items():
            cfg = cfg or {} if isinstance(cfg, dict) else {}
            options = {k: v for k, v in cfg.items() if k != "provider"}
            evaluators.append(
                {"key": str(name), "provider": cfg.get("provider"), "options": options}
            )
        return {
            "enabled": self.evaluator_registry.is_enabled(),
            "active_evaluator": evaluation_cfg.get("active_evaluator"),
            "providers": self.evaluator_registry.list_providers(),
            "evaluators": evaluators,
        }

    def listing_keys(self) -> List[str]:
        return ["config", "models", "embedding-models", "retrievers", "rerankers", "evaluators"]
