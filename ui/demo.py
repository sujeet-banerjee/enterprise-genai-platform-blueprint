"""Local demo-mode API adapter (issue #157).

``DemoApi`` subclasses the real HTTP client but overrides the single request
seam, so every console screen keeps working against built-in fixtures. No
``requests`` call is ever issued while demo mode is active, which is what makes
the demo safe: it cannot read or write production tenant data.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ui.client import ApiClient, ApiResult
from ui.journeys import demo_fixture


class DemoApi(ApiClient):
    """Serve the console from local fixtures instead of the backend."""

    def __init__(self, role: str = "architect") -> None:
        super().__init__(base_url="demo://local", api_key="", timeout=1.0)
        self.role = role

    def _request(self, method: str, path: str, **kwargs) -> ApiResult:
        payload: Optional[Dict[str, Any]] = kwargs.get("json")
        data = demo_fixture(path, method=method, payload=payload)
        if path == "/v1/access":
            data = {**data, "role": self.role}
        return ApiResult(ok=True, status_code=200, data=data, request_id=None)
