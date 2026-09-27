# Enterprise Gen-AI Platform Blueprint

This repository provides an enterprise reference architecture and modular implementation of a GenAI / RAG pipeline with plug-and-play abstractions for Embedders, Retrievers, LLMs, Rerankers, Chunkers, Token Governance, Observability, and Evaluation.

---

## 1. 'Changes Made' Summary

### A. List of Files Changed and Line Numbers

| File | Changes / Line Numbers | Description |
|---|---|---|
| `app/pipeline.py` | Lines 1–200 | Integrated `retrieve_with_scores`, optional `BaseReranker`, latency measurements across all pipeline stages, failure classification tags, structured logging, and observability payload. |
| `config/models.yaml` | Lines 1–35 | Added `active_embedding_model` and `embedding_models` configurations (`sentence-transformers/all-MiniLM-L6-v2`, `sentence-transformers/all-mpnet-base-v2`, `dummy`). |
| `config/prompt_config.yaml` | Lines 1–43 | Added `concise` and `detailed` prompt profiles alongside `default` profile. |
| `config/retrieval.yaml` | Lines 1–26 | Added chunking strategies (`small`, `large`, `word`), retrieval top_k, index type, similarity threshold, and reranker configurations. |
| `core/interfaces/retriever.py` | Lines 1–34 | Added `score` property to `Document` and added `retrieve_with_scores` method to `BaseRetriever`. |
| `core/interfaces/reranker.py` | Lines 1–24 (New) | Created `BaseReranker` contract with `rerank` and `rerank_with_scores`. |
| `core/interfaces/chunker.py` | Lines 1–35 (New) | Created `BaseChunker` contract with `chunk_text`, `chunk_document`, and `chunk_documents`. |
| `core/interfaces/__init__.py` | Lines 1–14 | Exported `BaseEmbedder`, `BaseRetriever`, `Document`, `BaseLLM`, `BaseEvaluator`, `BaseReranker`. |
| `core/implementations/simple_retriever.py` | Lines 1–66 | Implemented `retrieve_with_scores`, score calculation, and structured `Document` returning with score metadata. |
| `core/implementations/dummy_retriever.py` | Lines 1–17 | Implemented `retrieve_with_scores` alongside `retrieve`. |
| `core/implementations/faiss_retriever.py` | Lines 1–119 | Implemented FAISS CPU vector index retriever (`FAISSRetriever`) supporting document insertion, vector search, score calculation, and document mapping. |
| `core/implementations/simple_embedder.py` | Lines 1–71 | Made model configurable from `config/models.yaml`, auto-dimension detection, and offline deterministic fallback. |
| `core/implementations/simple_reranker.py` | Lines 1–72 (New) | Implemented `SimpleReranker` (hybrid lexical + retrieval score reranker) and `NoOpReranker`. |
| `core/implementations/chunker.py` | Lines 1–80 (New) | Implemented `FixedSizeChunker`, `WordChunker`, `SmallChunker`, `LargeChunker`. |
| `core/implementations/simple_evaluator.py` | Lines 1–30 | Implemented `SimpleEvaluator` using `Metrics`. |
| `core/implementations/__init__.py` | Lines 1–29 | Exported all standard implementations. |
| `core/services/token_budget_service.py` | Lines 1–168 | Enhanced with `strict` and `truncate` budgeting modes, calculating available tokens, removing lowest-priority docs in truncate mode, and returning comprehensive token metadata. |
| `core/services/prompt_builder.py` | Lines 1–62 | Externalized prompt templates and system prompts into `config/prompt_config.yaml`, added `set_profile()` and `get_system_prompt()`. |
| `core/services/chunking_service.py` | Lines 1–38 (New) | Implemented `ChunkingService` factory reading strategies from `config/retrieval.yaml`. |
| `core/services/embedding_experiment_runner.py` | Lines 1–60 (New) | Implemented `EmbeddingExperimentRunner` for comparative evaluation of embedding models. |
| `core/registry/model_registry.py` | Lines 1–114 | Refactored registry map with dynamic provider registration for LLMs and Embedders, config lookup, and model retrieval. |
| `core/services/model_registry.py` | Lines 1–3 | Re-exported `ModelRegistry`. |
| `core/observability/failure_classifier.py` | Lines 1–35 (New) | Defined `FailureType` enum taxonomy and `FailureClassifier`. |
| `core/observability/structured_logger.py` | Lines 1–55 (New) | Implemented `StructuredLogger` with automated sanitization of sensitive keys/passwords. |
| `core/observability/__init__.py` | Lines 1–10 (New) | Exported observability utilities. |
| `pytest.ini` | Lines 1–3 | Enabled all test files in `tests/` directory. |

---

### B. Testcases Added and Updated

#### Existing Testcases Updated/Verified:
- `tests/test_api.py` (FastAPI `/query` endpoint)
- `tests/test_cost_governor.py`
- `tests/test_dimension_mismatch.py`
- `tests/test_evaluation_engine.py`
- `tests/test_metrics_model.py`
- `tests/test_model_registry.py`
- `tests/test_openai_llm.py`
- `tests/test_pipeline.py`
- `tests/test_retrieval_policy.py`
- `tests/test_token_budget.py`
- `tests/test_simple_rag.py` (9 tests unignored and fully passing)

#### New Test Suites Added:
1. `tests/test_retrieval_scoring.py`:
   - `test_document_score_initialization`
   - `test_dummy_retriever_retrieve_with_scores`
   - `test_simple_retriever_retrieve_with_scores`
   - `test_retriever_backward_compatibility`
2. `tests/test_reranker.py`:
   - `test_simple_reranker_reordering`
   - `test_simple_reranker_with_scores`
   - `test_noop_reranker_preserves_order`
   - `test_reranker_in_pipeline`
3. `tests/test_token_budget_modes.py`:
   - `test_strict_mode_within_budget`
   - `test_strict_mode_exceeds_context_window`
   - `test_truncate_mode_removes_low_priority_documents`
   - `test_truncate_mode_fails_if_fixed_tokens_exceed_window`
4. `tests/test_model_registry_enhancements.py`:
   - `test_registry_custom_llm_provider`
   - `test_registry_custom_embedder_provider`
   - `test_registry_get_embedder_from_config`
   - `test_registry_unknown_embedder_raises`
5. `tests/test_prompt_builder_config.py`:
   - `test_prompt_builder_loads_yaml`
   - `test_prompt_builder_profile_switching`
   - `test_prompt_builder_fallback_for_missing_profile`
6. `tests/test_chunking.py`:
   - `test_fixed_size_chunker`
   - `test_word_chunker`
   - `test_chunk_document_preserves_metadata`
   - `test_chunking_service_from_config`
7. `tests/test_embedding_experiments.py`:
   - `test_simple_embedder_dimension_selection`
   - `test_embedding_experiment_runner`
8. `tests/test_faiss_retriever.py`:
   - `test_faiss_retriever_initialization_and_search`
   - `test_faiss_retriever_retrieve_contract`
   - `test_faiss_retriever_clear`
9. `tests/test_pipeline_observability.py`:
   - `test_pipeline_observability_and_latencies`
   - `test_sanitize_text_redacts_secrets`
10. `tests/test_failure_classification.py`:
    - `test_failure_classifier_taxonomy`
    - `test_pipeline_tags_no_documents_retrieved`
    - `test_pipeline_tags_low_retrieval_score`

---

### C. Configuration Options Added

1. **`config/models.yaml`**:
   - `active_embedding_model`: Specifies default active embedding model.
   - `embedding_models`: Section configuring embedding models with providers and model identifiers (`all-MiniLM-L6-v2`, `all-mpnet-base-v2`, `dummy`).

2. **`config/prompt_config.yaml`**:
   - `active_prompt_profile`: Active profile selector.
   - `profiles`: `default`, `concise`, `detailed` profiles with separated `system_prompt` and formatting `template`.

3. **`config/retrieval.yaml`**:
   - `chunking`: `active_strategy`, and strategy definitions (`small`, `large`, `word`) with `chunk_size` and `chunk_overlap`.
   - `retrieval`: `top_k`, `index_type`, `similarity_threshold`.
   - `reranker`: `enabled`, `type`, `initial_weight`, `lexical_weight`.

---

### D. New Methods Added to Existing Interfaces

See `INTERFACE_CHANGES.md` for full interface specifications.

- `BaseRetriever.retrieve_with_scores(self, embedding: List[float], top_k: int = 3) -> List[Tuple[Document, float]]`
- `BaseReranker.rerank(...)` and `BaseReranker.rerank_with_scores(...)`
- `BaseChunker.chunk_text(...)`, `BaseChunker.chunk_document(...)`, and `BaseChunker.chunk_documents(...)`
- `ModelRegistry.register_llm_provider(...)` and `ModelRegistry.register_embedder_provider(...)`
- `ModelRegistry.get_embedder(...)` and `ModelRegistry.get_active_embedder(...)`
- `PromptBuilder.get_system_prompt()` and `PromptBuilder.set_profile(profile_name)`

---

## 2. Design Principles

- **Interfaces are cleanly separated**: Embedder, Retriever, Reranker, LLM, Chunker, and Evaluator follow contracts.
- **Implementations are swappable**: ModelRegistry maps configuration providers to concrete instances.
- **Governance hooks**: Token budget governance prevents context overflow with strict/truncate strategies.
- **Observable pipeline**: Full latency instrumentation, structured logging with secret redaction, and failure taxonomy tagging.
