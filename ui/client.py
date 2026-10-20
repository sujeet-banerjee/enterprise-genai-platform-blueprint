"""HTTP client for the public RAG API (issue #40).

Every call goes through :class:`ApiClient`, which talks to the FastAPI backend
over HTTP only. The UI package never imports ``app.*`` or ``core.*``; a test
enforces that, the same way ``docs/ux-and-api.md`` §3.2 requires it.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests


@dataclass
class ApiResult:
    """Result of an API call: status, JSON body and echoed request id."""

    ok: bool
    status_code: int
    data: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None
    error: Optional[str] = None

    @property
    def failure_type(self) -> Optional[str]:
        return self.data.get("failure_type")

    @property
    def failure_tags(self) -> List[str]:
        return list(self.data.get("failure_tags") or [])


class ApiClient:
    """Thin ``requests``-based client for the documented /v1 endpoints."""

    def __init__(self, base_url: str = "http://localhost:8000", api_key: str = "", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    # -- plumbing ---------------------------------------------------------

    def _headers(self, request_id: Optional[str] = None) -> Dict[str, str]:
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if request_id:
            headers["X-Request-ID"] = request_id
        return headers

    def _request(self, method: str, path: str, **kwargs) -> ApiResult:
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method, url, headers=self._headers(kwargs.pop("request_id", None)),
                timeout=self.timeout, **kwargs
            )
        except requests.RequestException as exc:
            return ApiResult(
                ok=False,
                status_code=0,
                error=f"Could not reach the API at {url}: {exc}",
            )
        request_id = response.headers.get("X-Request-ID")
        try:
            body = response.json()
        except ValueError:
            body = {"raw": response.text}
        if not isinstance(body, dict):
            body = {"data": body}
        return ApiResult(
            ok=response.status_code < 400,
            status_code=response.status_code,
            data=body,
            request_id=request_id,
        )

    def get(self, path: str, **kwargs) -> ApiResult:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, json: Optional[Dict[str, Any]] = None, **kwargs) -> ApiResult:
        return self._request("POST", path, json=json or {}, **kwargs)

    # -- status / introspection ------------------------------------------

    def health(self) -> ApiResult:
        return self.get("/health")

    def ready(self) -> ApiResult:
        return self.get("/ready")

    def models(self) -> ApiResult:
        return self.get("/v1/models")

    def embedding_models(self) -> ApiResult:
        return self.get("/v1/embedding-models")

    def retrievers(self) -> ApiResult:
        return self.get("/v1/retrievers")

    def rerankers(self) -> ApiResult:
        return self.get("/v1/rerankers")

    def evaluators(self) -> ApiResult:
        return self.get("/v1/evaluators")

    def effective_config(self) -> ApiResult:
        return self.get("/v1/config")

    # -- query ------------------------------------------------------------

    def query(self, query: str, top_k: Optional[int] = None, include_trace: bool = True) -> ApiResult:
        payload: Dict[str, Any] = {"query": query, "include_trace": include_trace}
        if top_k is not None:
            payload["top_k"] = top_k
        return self.post("/v1/query", payload)

    def batch_query(self, queries: List[str], top_k: Optional[int] = None, include_trace: bool = True) -> ApiResult:
        payload: Dict[str, Any] = {"queries": queries, "include_trace": include_trace}
        if top_k is not None:
            payload["top_k"] = top_k
        return self.post("/v1/query:batch", payload)

    # -- evaluation / experiments ----------------------------------------

    def evaluate(
        self,
        query: str,
        response: str,
        retrieved_docs: Optional[List[Any]] = None,
        ground_truth: Optional[Any] = None,
        evaluator: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> ApiResult:
        payload: Dict[str, Any] = {"query": query, "response": response}
        if retrieved_docs is not None:
            payload["retrieved_docs"] = retrieved_docs
        if ground_truth is not None:
            payload["ground_truth"] = ground_truth
        if evaluator:
            payload["evaluator"] = evaluator
        if top_k is not None:
            payload["top_k"] = top_k
        return self.post("/v1/evaluate", payload)

    def launch_experiment(self, **payload: Any) -> ApiResult:
        return self.post("/v1/experiments", payload)

    def get_experiment(self, exp_id: str) -> ApiResult:
        return self.get(f"/v1/experiments/{exp_id}")

    # -- what-if rebuild --------------------------------------------------

    def rebuild(self, overrides: Dict[str, Any], governance: Optional[Dict[str, Any]] = None,
                allow_governance_override: bool = False) -> ApiResult:
        payload: Dict[str, Any] = {"overrides": overrides}
        if governance is not None:
            payload["governance"] = governance
            payload["allow_governance_override"] = allow_governance_override
        return self.post("/v1/pipeline:rebuild", payload)

    # -- ops --------------------------------------------------------------

    def governance_status(self) -> ApiResult:
        return self.get("/v1/governance/status")

    def trace(self, request_id: str) -> ApiResult:
        return self.get(f"/v1/traces/{request_id}")

    def metrics(self) -> ApiResult:
        return self.get("/v1/metrics")
