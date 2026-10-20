# Runnable examples

Small, self-contained scripts that exercise the blueprint end to end. Run them
from the **repository root** (so config paths resolve) after installing the
package (`pip install -e .`).

| Script | What it shows |
| --- | --- |
| [`run_query.py`](run_query.py) | Build the pipeline from config and run one query; prints the response, retrieved docs, scores and latency. |
| [`swap_components.py`](swap_components.py) | Swap the retriever (and optionally the LLM) purely by editing YAML - no code change, no concrete imports. |

## Run one query

```bash
python examples/run_query.py "What is machine learning?"
```

The default config uses local HuggingFace models (Qwen2.5-0.5B + MiniLM), so no
API keys are required. The **first** run downloads the models to the HuggingFace
cache and is slow; later runs are fast.

## Swap a component through config

```bash
python examples/swap_components.py
```

Optionally, to also demonstrate the OpenAI provider swap:

```bash
OPENAI_API_KEY=sk-... python examples/swap_components.py
```

Both scripts go through `app.main.build_pipeline()`, the same composition root
the API uses. Neither script imports a concrete embedder/retriever/reranker
implementation - the whole point of the blueprint.
