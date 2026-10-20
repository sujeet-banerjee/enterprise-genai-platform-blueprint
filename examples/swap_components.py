"""Runnable example: swap a component purely through configuration.

This shows the core promise of the blueprint - changing a vendor is a YAML
change, not a code change. The script copies the repo's config files into a
temporary workspace, rewrites a few values, then builds a pipeline against the
modified config using the same ``build_pipeline`` composition root.

Run from the repository root:

    python examples/swap_components.py

If you have an OpenAI key you can additionally print an OpenAI-backed pipeline's
model name; otherwise the example stays fully local (no network, no API keys):

    OPENAI_API_KEY=sk-... python examples/swap_components.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from app.main import build_pipeline  # noqa: E402


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _dump(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False)


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="genai-example-"))
    try:
        config_dir = workdir / "config"
        shutil.copytree(REPO_ROOT / "config", config_dir)

        # Retrievers resolve ``documents_path`` relative to the repo root (the
        # config dir's parent), so mirror the data directory into the workspace.
        data_dir = REPO_ROOT / "data"
        if data_dir.is_dir():
            shutil.copytree(data_dir, workdir / "data")

        models_path = config_dir / "models.yaml"
        retrieval_path = config_dir / "retrieval.yaml"

        retrieval = _load(retrieval_path)
        retrieval.setdefault("retrieval", {})

        print("1) Default retriever from config:")
        default_retriever = retrieval["retrieval"].get("default_retriever")
        print(f"   default_retriever = {default_retriever}")

        # Swap the retriever to the vector ``simple`` provider (a different
        # implementation selected entirely from YAML).
        retrieval["retrieval"]["default_retriever"] = "simple"
        retrieval["retrieval"]["similarity_metric"] = "cosine"
        _dump(retrieval_path, retrieval)

        pipeline = build_pipeline(
            models_config_path=models_path,
            retrieval_config_path=retrieval_path,
        )
        retriever_name = type(pipeline.retriever).__name__
        print("2) After editing YAML (no code change):")
        print(f"   retriever class  = {retriever_name}")
        print(f"   similarity metric= {retrieval['retrieval']['similarity_metric']}")

        # Show that the LLM is also resolved from config.
        llm = pipeline.llm
        print(f"3) LLM resolved from config: {type(llm).__name__}")

        if os.environ.get("OPENAI_API_KEY"):
            models = _load(models_path)
            models.setdefault("models", {})
            models["models"].setdefault("openai-gpt", {})
            models["models"]["openai-gpt"].update(
                {"provider": "openai", "model_name": "gpt-4o-mini"}
            )
            models["active_model"] = "openai-gpt"
            _dump(models_path, models)

            openai_pipeline = build_pipeline(
                models_config_path=models_path,
                retrieval_config_path=retrieval_path,
            )
            print("4) With active_model=openai-gpt:")
            print(f"   LLM class        = {type(openai_pipeline.llm).__name__}")
        else:
            print("4) Set OPENAI_API_KEY to also see the OpenAI provider swap.")

        print()
        print("The pipeline never named a concrete class - only YAML changed.")
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
