"""Streamlit console for the Enterprise GenAI RAG platform (issue #40).

This package is a *pure API client*: it talks to the backend over HTTP only and
must never import ``app.*`` or ``core.*``. The ``X-Request-ID`` header returned
by the API is preserved so a console action can be traced via
``GET /v1/traces/{request_id}``.
"""

__all__ = ["client"]
