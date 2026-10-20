"""Minimal runnable example: build the pipeline from config and run one query.

Run from the repository root:

    python examples/run_query.py "What is machine learning?"

Behaviour is entirely configuration-driven - this script never names a concrete
model, retriever, reranker or evaluator. Swapping vendors is a YAML change in
``config/models.yaml`` / ``config/retrieval.yaml``.

The default config uses local HuggingFace models (Qwen2.5-0.5B + MiniLM), so no
API keys are required. The first run downloads the models to the HuggingFace
cache and is slow; later runs are fast.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.main import build_pipeline  # noqa: E402

DEFAULT_QUERY = "What is machine learning?"


def _config_kwargs() -> dict:
    """Allow overriding config paths via env vars (handy for tests/other setups)."""
    overrides = {}
    for env_var, param in (
        ("GENAI_MODELS_CONFIG", "models_config_path"),
        ("GENAI_RETRIEVAL_CONFIG", "retrieval_config_path"),
        ("GENAI_PROMPT_CONFIG", "prompt_config_path"),
    ):
        value = os.environ.get(env_var)
        if value:
            overrides[param] = Path(value)
    return overrides


def main(argv: list[str]) -> int:
    query = " ".join(argv[1:]).strip() or DEFAULT_QUERY

    # build_pipeline() resolves every component from the config files; no
    # concrete implementation is imported by this script (or by app/main.py).
    pipeline = build_pipeline(**_config_kwargs())

    result = pipeline.run(query, top_k=3, raise_on_failure=False)

    print(f"Query: {query}")
    print("-" * 60)
    print(f"Response: {result.get('response')}")
    print()

    docs = result.get("retrieved_docs") or []
    print(f"Retrieved {len(docs)} document(s):")
    for index, content in enumerate(docs, start=1):
        snippet = content.replace("\n", " ")[:100]
        print(f"  {index}. {snippet}")

    scores = result.get("retrieval_scores") or []
    if scores:
        print()
        print("Retrieval scores: " + ", ".join(f"{s:.3f}" for s in scores))

    failure_tags = result.get("failure_tags") or []
    if failure_tags:
        print()
        print(f"Failure tags (degraded run): {failure_tags}")
    latency = result.get("latency") or {}
    if latency:
        total = latency.get("total_ms")
        if total is not None:
            print()
            print(f"Total latency: {total:.1f} ms")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
