"""Runtime what-if rebuild endpoint (issue #37).

Construct-then-swap: a candidate configuration is materialised, all components
are built (validation), and only then is the live pipeline reference replaced.
A failed validation leaves the running pipeline untouched.
"""

import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.introspection import IntrospectionService
from app.schemas import RebuildRequest, RebuildResponse
from core.services.failure_classifier import FailureType

MODEL_OVERRIDE_KEYS = ("active_model", "active_embedding_model")
RETRIEVAL_OVERRIDE_KEYS = ("default_retriever", "similarity_metric", "top_k")


class RebuildError(Exception):
    """Base class for rebuild failures."""


class RebuildNotAllowedError(RebuildError):
    """Raised when ``api.allow_rebuild`` is false."""


class GovernanceOverrideError(RebuildError):
    """Raised when governance is overridden without explicit opt-in."""


class RebuildValidationError(RebuildError):
    """Raised when the candidate configuration fails to build."""


def _name(obj: Any) -> Optional[str]:
    if obj is None:
        return None
    for attr in ("model_name", "retriever_name", "reranker_name", "evaluator_name", "name"):
        value = getattr(obj, attr, None)
        if isinstance(value, str) and value:
            return value
    return obj.__class__.__name__


def describe_pipeline(pipeline: Any) -> Dict[str, Optional[str]]:
    """Component summary used by ``/ready`` and the rebuild response."""
    if pipeline is None:
        return {
            "llm": None,
            "retriever": None,
            "reranker": None,
            "evaluator": None,
            "query_expander": None,
        }
    return {
        "llm": _name(getattr(pipeline, "llm", None)),
        "retriever": _name(getattr(pipeline, "retriever", None)),
        "reranker": _name(getattr(pipeline, "reranker", None)),
        "evaluator": _name(getattr(pipeline, "evaluator", None)),
        "query_expander": _name(getattr(pipeline, "query_expander", None)),
    }


def _load_yaml(path: Path) -> dict:
    with open(path, "r") as handle:
        loaded = yaml.safe_load(handle) or {}
    return loaded if isinstance(loaded, dict) else {}


def _write_yaml(path: Path, payload: dict) -> None:
    with open(path, "w") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)


class PipelineRebuildService:
    """Materialises candidate configs and swaps the live pipeline atomically."""

    def __init__(
        self,
        pipeline_builder: Callable[..., Any],
        base_paths: Dict[str, Path],
        allow_rebuild: bool,
        workspace_root: Optional[Path] = None,
    ):
        self._builder = pipeline_builder
        self._base_paths = {key: Path(value) for key, value in base_paths.items()}
        self.allow_rebuild = bool(allow_rebuild)
        self._workspace_root = Path(workspace_root) if workspace_root else None
        self._lock = threading.Lock()
        self._workspaces: list = []

    # -- lifecycle --------------------------------------------------------

    def cleanup(self) -> None:
        for workspace in self._workspaces:
            shutil.rmtree(workspace, ignore_errors=True)
        self._workspaces.clear()

    # -- config materialisation ------------------------------------------

    def _materialize(self, request: RebuildRequest) -> Dict[str, Path]:
        workspace = Path(
            tempfile.mkdtemp(prefix="pipeline-rebuild-", dir=self._workspace_root)
        )
        self._workspaces.append(workspace)
        paths = dict(self._base_paths)

        overrides = request.overrides.model_dump(exclude_none=True)
        model_overrides = {k: v for k, v in overrides.items() if k in MODEL_OVERRIDE_KEYS}
        retrieval_overrides = {k: v for k, v in overrides.items() if k in RETRIEVAL_OVERRIDE_KEYS}

        if model_overrides:
            config = _load_yaml(self._base_paths["models_config_path"])
            config.update(model_overrides)
            target = workspace / "models.yaml"
            _write_yaml(target, config)
            paths["models_config_path"] = target

        if retrieval_overrides:
            config = _load_yaml(self._base_paths["retrieval_config_path"])
            section = config.setdefault("retrieval", {})
            if not isinstance(section, dict):
                raise RebuildValidationError("retrieval section is not a mapping")
            section.update(retrieval_overrides)
            target = workspace / "retrieval.yaml"
            _write_yaml(target, config)
            paths["retrieval_config_path"] = target

        if request.governance:
            config = _load_yaml(self._base_paths["governance_config_path"])
            config.update(request.governance)
            target = workspace / "governance.yaml"
            _write_yaml(target, config)
            paths["governance_config_path"] = target

        return paths

    def _builder_kwargs(self, paths: Dict[str, Path]) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "models_config_path": paths["models_config_path"],
            "prompt_config_path": paths["prompt_config_path"],
            "retrieval_config_path": paths["retrieval_config_path"],
            "governance_config_path": paths["governance_config_path"],
            "observability_config_path": paths["observability_config_path"],
        }
        if "resilience_config_path" in paths:
            kwargs["resilience_config_path"] = paths["resilience_config_path"]
        if "guardrails_config_path" in paths:
            kwargs["guardrails_config_path"] = paths["guardrails_config_path"]
        if "acl_config_path" in paths:
            kwargs["acl_config_path"] = paths["acl_config_path"]
        return kwargs

    # -- rebuild ----------------------------------------------------------

    def rebuild(
        self,
        request: RebuildRequest,
        swap: Callable[[Any, Any], None],
    ) -> Dict[str, Any]:
        if not self.allow_rebuild:
            raise RebuildNotAllowedError(
                "Runtime pipeline rebuild is disabled; set api.allow_rebuild: true to enable it."
            )
        if request.governance and not request.allow_governance_override:
            raise GovernanceOverrideError(
                "Governance overrides require allow_governance_override=true."
            )

        with self._lock:
            paths = self._materialize(request)
            try:
                pipeline = self._builder(**self._builder_kwargs(paths))
            except Exception as exc:  # noqa: BLE001 - surfaced as a 400 to the caller
                raise RebuildValidationError(f"Candidate configuration is invalid: {exc}") from exc

            introspection = IntrospectionService(
                models_config_path=paths["models_config_path"],
                retrieval_config_path=paths["retrieval_config_path"],
                prompt_config_path=paths["prompt_config_path"],
                governance_config_path=paths["governance_config_path"],
                observability_config_path=paths["observability_config_path"],
                api_config_path=paths.get("api_config_path"),
                guardrails_config_path=paths.get("guardrails_config_path"),
            )
            swap(pipeline, introspection)

        return {
            "status": "rebuilt",
            "components": describe_pipeline(pipeline),
            "applied_overrides": request.overrides.model_dump(exclude_none=True),
            "governance_overrides_applied": bool(request.governance),
            "effective_config": introspection.effective_config(),
        }


def register_whatif_routes(
    application: FastAPI,
    error_envelope: Callable[..., dict],
) -> None:
    @application.post("/v1/pipeline:rebuild", response_model=RebuildResponse)
    def rebuild_endpoint(request: Request, payload: RebuildRequest):
        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        audit = getattr(request.app.state, "audit", None)

        def _emit(outcome: str, action: str, details: dict) -> None:
            if audit is not None and getattr(audit, "enabled", False):
                audit.record("config", action, outcome, details=details, request_id=request_id)

        service = getattr(request.app.state, "rebuild", None)
        if service is None:
            return JSONResponse(
                status_code=503,
                content=error_envelope(
                    "Rebuild service is not ready.",
                    FailureType.NOT_READY.value,
                    [],
                    request_id,
                ),
            )

        def _swap(pipeline, introspection) -> None:
            request.app.state.pipeline = pipeline
            request.app.state.introspect = introspection
            request.app.state.config_revision = (
                int(getattr(request.app.state, "config_revision", 0)) + 1
            )

        try:
            result = service.rebuild(payload, _swap)
        except RebuildNotAllowedError as exc:
            _emit("denied", "pipeline_rebuild", {"reason": "rebuild_disabled"})
            return JSONResponse(
                status_code=403,
                content=error_envelope(
                    str(exc), FailureType.UNKNOWN_FAILURE.value, ["rebuild_disabled"], request_id
                ),
            )
        except GovernanceOverrideError as exc:
            _emit(
                "denied",
                "pipeline_rebuild",
                {"reason": "governance_override_requires_opt_in"},
            )
            return JSONResponse(
                status_code=400,
                content=error_envelope(
                    str(exc),
                    FailureType.UNKNOWN_FAILURE.value,
                    ["governance_override_requires_opt_in"],
                    request_id,
                ),
            )
        except RebuildValidationError as exc:
            _emit("failure", "pipeline_rebuild", {"reason": "invalid_rebuild_config"})
            return JSONResponse(
                status_code=400,
                content=error_envelope(
                    str(exc),
                    FailureType.UNKNOWN_FAILURE.value,
                    ["invalid_rebuild_config"],
                    request_id,
                ),
            )

        result["config_revision"] = getattr(request.app.state, "config_revision", 0)
        result["request_id"] = request_id
        _emit(
            "success",
            "pipeline_rebuild",
            {
                "config_revision": result["config_revision"],
                "applied_overrides": result.get("applied_overrides"),
            },
        )
        return RebuildResponse(**result)
