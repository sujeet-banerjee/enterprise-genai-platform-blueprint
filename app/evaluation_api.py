"""Evaluation and experiment endpoints (issue #36).

`POST /v1/evaluate` runs the configured `BaseEvaluator` over a query/response
pair; `POST /v1/experiments` / `GET /v1/experiments/{id}` launch and poll runs
backed by `ExperimentRunner` with a bounded in-memory store.

Routes are registered on an existing application via `register_evaluation_routes`
so `app/main.py` keeps its composition-root role.
"""

import json
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.schemas import (
    EvaluateRequest,
    EvaluateResponse,
    ExperimentLaunchRequest,
    ExperimentLaunchResponse,
    ExperimentStatusResponse,
)
from core.interfaces.retriever import Document
from core.registry.evaluator_registry import EvaluatorRegistry
from core.services.experiment_runner import ExperimentRunner
from core.services.failure_classifier import FailureClassifier, FailureType

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DOCS_PATH = BASE_DIR / "data" / "docs.json"

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


class UnknownEvaluatorError(LookupError):
    """Raised when the caller names an evaluator that is not configured."""


class _ExperimentStore:
    """Bounded in-memory store of experiment runs (oldest entries evicted)."""

    def __init__(self, max_entries: int = 50):
        self.max_entries = int(max_entries)
        self._entries: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._lock = threading.Lock()

    def create(
        self, exp_id: str, kind: str, tenant: Optional[str] = None
    ) -> Dict[str, Any]:
        with self._lock:
            entry = {
                "id": exp_id,
                "kind": kind,
                "tenant": tenant,
                "status": STATUS_RUNNING,
                "created_at": time.time(),
                "finished_at": None,
                "result": None,
                "error": None,
                "failure_type": None,
            }
            self._entries[exp_id] = entry
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
            return dict(entry)

    def get(self, exp_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self._entries.get(exp_id)
            return dict(entry) if entry is not None else None

    def complete(self, exp_id: str, result: Any) -> None:
        with self._lock:
            entry = self._entries.get(exp_id)
            if entry is None:
                return
            entry.update(
                status=STATUS_COMPLETED,
                finished_at=time.time(),
                result=result,
                error=None,
                failure_type=None,
            )

    def fail(self, exp_id: str, error: str, failure_type: str) -> None:
        with self._lock:
            entry = self._entries.get(exp_id)
            if entry is None:
                return
            entry.update(
                status=STATUS_FAILED,
                finished_at=time.time(),
                result=None,
                error=error,
                failure_type=failure_type,
            )


def jsonable(value: Any) -> Any:
    """Recursively coerce experiment results into JSON-serialisable values."""
    if isinstance(value, Document):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def coerce_document(entry: Union[str, Dict[str, Any], Document]) -> Document:
    if isinstance(entry, Document):
        return entry
    if isinstance(entry, str):
        return Document(content=entry)
    if isinstance(entry, dict):
        content = entry.get("content", entry.get("text", entry.get("page_content", "")))
        metadata = entry.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, dict) else {}
        score = entry.get("score")
        return Document(content=str(content), metadata=metadata, score=score)
    raise ValueError(f"Unsupported retrieved_docs entry: {type(entry).__name__}")


class EvaluationService:
    """Holds the evaluator registry, experiment runner, store and executor."""

    def __init__(
        self,
        models_config_path: Path,
        prompt_config_path: Path,
        retrieval_config_path: Path,
        max_workers: int = 1,
        governance_config_path: Optional[Path] = None,
    observability_config_path: Optional[Path] = None,
    resilience_config_path: Optional[Path] = None,
    guardrails_config_path: Optional[Path] = None,
    acl_config_path: Optional[Path] = None,
    ):
        self.models_config_path = Path(models_config_path)
        self.prompt_config_path = Path(prompt_config_path)
        self.retrieval_config_path = Path(retrieval_config_path)
        self.evaluator_registry = EvaluatorRegistry(str(self.retrieval_config_path))
        self.experiment_runner = ExperimentRunner(
            models_config_path=str(self.models_config_path),
            prompt_config_path=str(self.prompt_config_path),
            retrieval_config_path=str(self.retrieval_config_path),
            governance_config_path=(
                str(governance_config_path) if governance_config_path else None
            ),
            observability_config_path=(
                str(observability_config_path) if observability_config_path else None
            ),
            resilience_config_path=(
                str(resilience_config_path) if resilience_config_path else None
            ),
            guardrails_config_path=(
                str(guardrails_config_path) if guardrails_config_path else None
            ),
            acl_config_path=(str(acl_config_path) if acl_config_path else None),
        )
        self.store = _ExperimentStore()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="experiment"
        )

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)

    # -- evaluation -------------------------------------------------------

    @staticmethod
    def _auto_retrieve(pipeline: Any, query: str, top_k: Optional[int]) -> List[Document]:
        retriever = getattr(pipeline, "retriever", None)
        embedder = getattr(pipeline, "embedder", None)
        if retriever is None or embedder is None:
            raise ValueError(
                "No retrieved_docs supplied and the live pipeline exposes no retriever."
            )
        effective_top_k = int(top_k or getattr(pipeline, "top_k", 3) or 3)
        embedding = embedder.embed(query)
        try:
            docs = retriever.retrieve(embedding, top_k=effective_top_k)
        except TypeError:
            docs = retriever.retrieve(embedding)
        return [coerce_document(doc) for doc in (docs or [])]

    def evaluate(
        self,
        *,
        query: str,
        response: str,
        retrieved_docs: Optional[Sequence[Union[str, Dict[str, Any]]]] = None,
        ground_truth: Optional[Union[str, List[str]]] = None,
        evaluator: Optional[str] = None,
        top_k: Optional[int] = None,
        pipeline: Any = None,
    ) -> Dict[str, Any]:
        if retrieved_docs:
            docs = [coerce_document(entry) for entry in retrieved_docs]
            docs_source = "request"
        elif pipeline is not None:
            docs = self._auto_retrieve(pipeline, query, top_k)
            docs_source = "retrieval"
        else:
            raise ValueError(
                "retrieved_docs is required when no live pipeline is available."
            )

        if evaluator is not None and evaluator not in self.evaluator_registry.list_evaluators():
            raise UnknownEvaluatorError(
                f"Unknown evaluator '{evaluator}'. "
                f"Configured evaluators: {sorted(self.evaluator_registry.list_evaluators())}"
            )

        active_evaluator = self.evaluator_registry.create(name=evaluator)
        evaluator_key, _, _ = self.evaluator_registry.resolve(evaluator)

        ground_truth_used = False
        if ground_truth is not None:
            with_ground_truth = getattr(active_evaluator, "evaluate_with_ground_truth", None)
            supports_ground_truth = bool(
                getattr(active_evaluator, "supports_ground_truth", False)
            )
            if callable(with_ground_truth) and supports_ground_truth:
                metrics = with_ground_truth(
                    query=query,
                    retrieved_docs=docs,
                    response=response,
                    ground_truth=ground_truth,
                )
                ground_truth_used = True
            else:
                metrics = active_evaluator.evaluate(
                    query=query, retrieved_docs=docs, response=response
                )
        else:
            metrics = active_evaluator.evaluate(
                query=query, retrieved_docs=docs, response=response
            )

        return {
            "evaluator": active_evaluator.__class__.__name__,
            "evaluator_key": evaluator_key,
            "metrics": jsonable(metrics or {}),
            "ground_truth": ground_truth,
            "ground_truth_used": ground_truth_used,
            "num_retrieved_docs": len(docs),
            "docs_source": docs_source,
        }

    # -- experiments ------------------------------------------------------

    def _resolve_docs(
        self,
        docs: Optional[List[Union[str, Dict[str, Any]]]],
        documents_path: Optional[str],
    ) -> List[Union[str, Dict[str, Any], Document]]:
        if docs:
            return list(docs)
        path = Path(documents_path) if documents_path else DEFAULT_DOCS_PATH
        if not path.is_absolute():
            path = BASE_DIR / path
        with open(path, "r") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, list):
            raise ValueError(f"Expected a JSON list of documents in {path}")
        return loaded

    def launch_experiment(
        self, payload: ExperimentLaunchRequest, tenant: Optional[str] = None
    ) -> Dict[str, Any]:
        docs = self._resolve_docs(payload.docs, payload.documents_path)
        params = payload.model_dump()
        params.pop("docs", None)
        params.pop("documents_path", None)

        exp_id = str(uuid.uuid4())
        self.store.create(exp_id, payload.kind, tenant=tenant)
        self._executor.submit(self._run_experiment, exp_id, params, docs)
        return {"id": exp_id, "kind": payload.kind, "status": STATUS_RUNNING, "tenant": tenant}

    def _run_experiment(
        self,
        exp_id: str,
        params: Dict[str, Any],
        docs: List[Union[str, Dict[str, Any], Document]],
    ) -> None:
        kind = params.pop("kind")
        runner = self.experiment_runner
        try:
            if kind == "single":
                result = runner.run_single_experiment(
                    docs=docs,
                    query=params["query"],
                    embedding_model=params.get("embedding_model"),
                    chunk_strategy=params.get("chunk_strategy"),
                    retriever_backend=params.get("retriever_backend"),
                    use_reranker=params.get("use_reranker"),
                    top_k=params.get("top_k", 3),
                )
            elif kind == "compare_embedding_models":
                result = runner.compare_embedding_models(
                    docs=docs,
                    query=params["query"],
                    model_names=params.get("model_names"),
                    chunk_strategy=params.get("chunk_strategy"),
                    retriever_backend=params.get("retriever_backend"),
                    top_k=params.get("top_k", 3),
                )
            elif kind == "compare_chunking_strategies":
                result = runner.compare_chunking_strategies(
                    docs=docs,
                    query=params["query"],
                    strategies=tuple(params.get("strategies") or ("small", "large")),
                    embedding_model=params.get("embedding_model"),
                    retriever_backend=params.get("retriever_backend"),
                    top_k=params.get("top_k", 3),
                )
            else:
                raise ValueError(f"Unsupported experiment kind: {kind}")
            self.store.complete(exp_id, jsonable(result))
        except Exception as exc:  # noqa: BLE001 - surfaced through the store
            failure_type = FailureClassifier.classify_exception(exc)
            self.store.fail(exp_id, str(exc), failure_type)

    def get_experiment(self, exp_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get(exp_id)


def register_evaluation_routes(
    application: FastAPI,
    error_envelope: Callable[..., dict],
) -> None:
    def _service(request: Request):
        service = getattr(request.app.state, "evaluate", None)
        if service is None:
            request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
            return None, JSONResponse(
                status_code=503,
                content=error_envelope(
                    "Evaluation service is not ready.",
                    FailureType.NOT_READY.value,
                    [],
                    request_id,
                ),
            )
        return service, None

    @application.post("/v1/evaluate", response_model=EvaluateResponse)
    def evaluate_endpoint(request: Request, payload: EvaluateRequest):
        service, error = _service(request)
        if error is not None:
            return error
        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        pipeline = getattr(request.app.state, "pipeline", None)
        try:
            result = service.evaluate(
                query=payload.query,
                response=payload.response,
                retrieved_docs=payload.retrieved_docs,
                ground_truth=payload.ground_truth,
                evaluator=payload.evaluator,
                top_k=payload.top_k,
                pipeline=pipeline,
            )
        except UnknownEvaluatorError as exc:
            return JSONResponse(
                status_code=404,
                content=error_envelope(
                    str(exc),
                    FailureType.EVALUATION_FAILURE.value,
                    ["unknown_evaluator"],
                    request_id,
                ),
            )
        except ValueError as exc:
            return JSONResponse(
                status_code=400,
                content=error_envelope(
                    str(exc),
                    FailureType.EVALUATION_FAILURE.value,
                    ["invalid_evaluation_input"],
                    request_id,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - mapped to the taxonomy
            return JSONResponse(
                status_code=500,
                content=error_envelope(
                    str(exc),
                    FailureType.EVALUATION_FAILURE.value,
                    ["evaluation_error"],
                    request_id,
                ),
            )
        result["request_id"] = request_id
        return EvaluateResponse(**result)

    @application.post(
        "/v1/experiments",
        response_model=ExperimentLaunchResponse,
        status_code=202,
    )
    def launch_experiment_endpoint(request: Request, payload: ExperimentLaunchRequest):
        service, error = _service(request)
        if error is not None:
            return error
        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        try:
            result = service.launch_experiment(
                payload, tenant=getattr(request.state, "tenant_id", None)
            )
        except FileNotFoundError as exc:
            return JSONResponse(
                status_code=400,
                content=error_envelope(
                    str(exc), FailureType.UNKNOWN_FAILURE.value, ["documents_not_found"],
                    request_id,
                ),
            )
        except ValueError as exc:
            return JSONResponse(
                status_code=400,
                content=error_envelope(
                    str(exc), FailureType.UNKNOWN_FAILURE.value, ["invalid_documents"],
                    request_id,
                ),
            )
        result["request_id"] = request_id
        return ExperimentLaunchResponse(**result)

    @application.get("/v1/experiments/{exp_id}", response_model=ExperimentStatusResponse)
    def experiment_status_endpoint(request: Request, exp_id: str):
        service, error = _service(request)
        if error is not None:
            return error
        entry = service.get_experiment(exp_id)
        resolver = getattr(request.app.state, "tenants", None)
        caller_tenant = getattr(request.state, "tenant_id", None)
        if (
            entry is not None
            and resolver is not None
            and getattr(resolver, "enabled", False)
            and entry.get("tenant") not in (None, caller_tenant)
        ):
            entry = None
        if entry is None:
            request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
            return JSONResponse(
                status_code=404,
                content=error_envelope(
                    f"Unknown experiment id '{exp_id}'.",
                    FailureType.UNKNOWN_FAILURE.value,
                    ["experiment_not_found"],
                    request_id,
                ),
            )
        request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
        entry["request_id"] = request_id
        return ExperimentStatusResponse(**entry)
