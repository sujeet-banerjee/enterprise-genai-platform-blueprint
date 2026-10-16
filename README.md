# enterprise-genai-platform-blueprint
This is a general blueprint for Enterprize Model Lifecycle Management Platform
## Vision

## Architecture diagram
refer to docs/architecture.ml

## Design principles:
The architecture pivots on simple principles as outlined below:
- Interfaces are cleanly separated.
- Implementations are swappable (plug and play).
- Hooks to enforce Governance use cases.
- Services are orthogonal utilities.

### Pluggable models
Models are no sitting ducks. While they have independent evolution-paths, those eventually power the business. Being able to plug-n-play, swap the models like batteries is the key to agility.

### Observable pipeline
While models remain plug-n-play, the decision makers need data based on the impact of (swapping/upgrading) a model on the business. Deep observability is the key to establish 'causation' (cause attribution), and there by enabling fast decision making, updating benchmarks, and the likes.

### Evaluation-first mindset
Before making the production decisions (cut-over, swap, ...) you need all the math, scores, grade-card for your models, against the set benchmarks.

### Governance hooks
Models are no good if they just do good, but the goodness can't be explained to the higher ups! Hooks allow external tools that need to be fed with relevant data to make reports, answer compliance queries, and the likes.

---

## Changes Made

### 1. List of Files Changed and Line Numbers

#### Modified Files
* `app/main.py` (`lines 1–46`): Wired `ModelRegistry`, `SimpleReranker`, and configuration paths (`config/prompt_config.yaml`, `config/models.yaml`, `config/retrieval.yaml`) into the FastAPI service pipeline.
* `app/pipeline.py` (`lines 1–318`): Enhanced `RAGPipeline` to support `retrieve_with_scores`, optional `BaseReranker` execution between retrieval and prompt building, `PromptBuilder`-supplied `system_prompt` (removing hardcoded prompt strings), `TokenBudgetService` document truncation propagation, stage-by-stage latency tracking, secret-redacted structured observability logging, and `FailureClassifier` tagging.
* `config/models.yaml` (`lines 1–44`): Added `active_embedding_model` and `embedding_models` definitions (`all-MiniLM-L6-v2`, `all-mpnet-base-v2`, `sentence-transformers/all-MiniLM-L6-v2`, `sentence-transformers/all-mpnet-base-v2`, `dummy`).
* `config/prompt_config.yaml` (`lines 1–49`): Added configurable prompt profiles (`default`, `concise`, `analytical`) with `system_prompt`, `context_separator`, `empty_context_message`, and `template`.
* `config/retrieval.yaml` (`lines 1–42`): Added configuration sections for `retrieval`, `reranking`, `chunking` (`small` and `large` strategies), `token_budget`, and `observability`.
* `core/interfaces/embedder.py` (`lines 1–30`): Added `model_name` property to `BaseEmbedder`.
* `core/interfaces/retriever.py` (`lines 1–97`): Extended `Document` with `score` attribute and `to_dict()`, added `ScoredDocument` class, and added `retrieve_with_scores()` to `BaseRetriever`.
* `core/implementations/dummy_embedder.py` (`lines 1–19`): Updated `DummyEmbedder` to expose `model_name` and configurable `dimension`.
* `core/implementations/dummy_retriever.py` (`lines 1–39`): Updated `DummyRetriever` to implement `retrieve_with_scores()` and expose similarity scores.
* `core/implementations/simple_embedder.py` (`lines 1–183`): Refactored `SimpleEmbedder` to resolve `model_name` from `config/models.yaml`, support `sentence-transformers/all-MiniLM-L6-v2` (384-d) and `sentence-transformers/all-mpnet-base-v2` (768-d) with offline local execution capability, and dynamically obtain `dimension` from the loaded model.
* `core/implementations/simple_retriever.py` (`lines 1–72`): Added `retrieve_with_scores()` returning `List[ScoredDocument]` with cosine similarity scores and updated `retrieve()` to preserve document score metadata.
* `core/implementations/faiss_retriever.py` (`lines 1–169`): Implemented `FAISSRetriever` using `faiss-cpu` (`IndexFlatIP` / `IndexFlatL2`) supporting index creation, `add_documents()`, `build_index()`, `retrieve()`, `retrieve_with_scores()`, and ID-to-`Document` mapping.
* `core/registry/model_registry.py` (`lines 1–239`): Refactored `ModelRegistry` to replace `if-else` logic with plug-and-play provider and model factory registries for both LLMs and Embedders.
* `core/services/model_registry.py` (`lines 1–3`): Unified service export with `core.registry.model_registry.ModelRegistry`.
* `core/services/prompt_builder.py` (`lines 1–91`): Upgraded `PromptBuilder` to support multiple profiles, configurable context separators, and `get_system_prompt()` / `set_profile()` / `list_profiles()`.
* `core/services/token_budget_service.py` (`lines 1–340`): Enhanced `TokenBudgetService` with explicit `strict` and `truncate` modes, priority-ordered context removal/truncation, and `TokenBudgetExceededError`.
* `pytest.ini` (`lines 1–3`): Enabled full test suite execution including `tests/test_simple_rag.py`.
* `tests/test_model_registry.py` (`lines 1–84`): Extended with tests for plug-and-play LLM/Embedder registration and configured embedding model loading.
* `tests/test_token_budget.py` (`lines 1–93`): Extended with tests for `strict` mode calculations, `strict` mode budget overflow error, `truncate` mode document removal/truncation, and invalid mode validation.

#### Newly Added Files
* `INTERFACE_CHANGES.md` (`lines 1–84`): Documentation of all interface extensions and new contracts.
* `core/interfaces/reranker.py` (`lines 1–39`): `BaseReranker` contract (`rerank`, `rerank_with_scores`, `reranker_name`).
* `core/implementations/simple_reranker.py` (`lines 1–171`): `SimpleReranker` implementation supporting `lexical_hybrid`, `lexical`, `score_desc`, `reverse`, `noop`, and custom `scoring_fn` strategies.
* `core/implementations/dummy_reranker.py` (`lines 1–23`): `DummyReranker` implementation for testing and baselines.
* `core/interfaces/chunker.py` (`lines 1–58`): `BaseChunker` contract (`chunk_text`, `chunk_documents`, `chunk`, `chunk_size`, `chunk_overlap`, `strategy_name`).
* `core/implementations/chunker.py` (`lines 1–204`): `ConfigurableChunker`, `SmallChunker`, `LargeChunker`, and `ChunkerFactory` driven by `config/retrieval.yaml`.
* `core/services/chunker.py` (`lines 1–15`): Service-layer exports for chunking abstractions.
* `core/services/experiment_runner.py` (`lines 1–158`): `ExperimentRunner` / `EmbeddingExperimentRunner` for comparative evaluations across embedding models and chunking strategies.
* `core/services/failure_classifier.py` (`lines 1–74`): `FailureType` taxonomy and `FailureClassifier` for exception and retrieval quality classification.
* `core/services/observability.py` (`lines 1–157`): `SensitiveDataRedactor` and `PipelineObservabilityTracker` for stage-level latency measurement and structured logging with secret redaction.
* `tests/test_retrieval_and_faiss.py` (`lines 1–105`): Unit and integration tests for retrieval scoring and `FAISSRetriever`.
* `tests/test_reranking.py` (`lines 1–74`): Unit and integration tests for `SimpleReranker` and pipeline reranking.
* `tests/test_prompt_chunking_embeddings.py` (`lines 1–124`): Tests for `PromptBuilder` profiles, `SmallChunker` vs `LargeChunker`, `SimpleEmbedder` models, and `ExperimentRunner`.
* `tests/test_observability_and_failures.py` (`lines 1–169`): Tests for stage latency measurement, observability trace fields, secret redaction, and failure classification.

---

### 2. Testcases Added and Updated
* **`tests/test_retrieval_and_faiss.py`**:
  * `test_simple_retriever_returns_similarity_scores`
  * `test_faiss_retriever_index_creation_insertion_querying_and_mapping`
  * `test_faiss_retriever_negative_scenarios`
  * `test_dummy_retriever_exposes_scores`
* **`tests/test_reranking.py`**:
  * `test_simple_reranker_changes_document_ordering`
  * `test_reranker_custom_scoring_callable_and_top_k`
  * `test_reranker_integrated_in_rag_pipeline`
* **`tests/test_token_budget.py`**:
  * `test_token_budget_reduces_output` (preserved)
  * `test_token_budget_strict_mode_exact_calculation`
  * `test_token_budget_strict_mode_raises_when_exceeded`
  * `test_token_budget_truncate_mode_removes_and_truncates_low_priority_docs`
  * `test_token_budget_invalid_mode_raises`
* **`tests/test_model_registry.py`**:
  * `test_registry_loads_config`, `test_registry_returns_active_model`, `test_registry_unknown_provider` (preserved)
  * `test_registry_plug_and_play_custom_llm_and_embedder`
  * `test_registry_loads_configured_embedding_models`
  * `test_registry_invalid_model_raises`
* **`tests/test_prompt_chunking_embeddings.py`**:
  * `test_prompt_builder_loads_profiles_and_pipeline_has_no_hardcoded_prompt`
  * `test_prompt_builder_unknown_profile_raises`
  * `test_chunking_strategies_small_vs_large`
  * `test_chunker_invalid_parameters_raise`
  * `test_embedding_models_selection_and_experiment_comparison`
* **`tests/test_observability_and_failures.py`**:
  * `test_pipeline_stage_latency_and_observability_fields`
  * `test_sensitive_data_redaction_in_observability_logs`
  * `test_failure_classification_no_documents_and_low_retrieval_score`
  * `test_failure_classification_across_pipeline_exceptions`

---

### 3. Configuration Options Added
* **`config/models.yaml`**:
  * `active_embedding_model`: Active embedding model key (`all-MiniLM-L6-v2`).
  * `embedding_models`: Model definitions mapping `all-MiniLM-L6-v2`, `all-mpnet-base-v2`, `sentence-transformers/all-MiniLM-L6-v2`, `sentence-transformers/all-mpnet-base-v2`, and `dummy` to their `provider` and `model_name`.
* **`config/prompt_config.yaml`**:
  * Added `context_separator` and `empty_context_message` per profile.
  * Added `concise` and `analytical` prompt profiles alongside `default`.
* **`config/retrieval.yaml`**:
  * `retrieval`: `default_retriever`, `top_k`, `similarity_metric`, `low_score_threshold`.
  * `reranking`: `enabled`, `strategy`, `lexical_weight`, `initial_score_weight`, `top_k`.
  * `chunking`: `active_strategy`, `strategies.small` (`chunk_size`, `chunk_overlap`, `separator`), `strategies.large` (`chunk_size`, `chunk_overlap`, `separator`).
  * `token_budget`: `default_mode` (`strict` | `truncate`), `max_output_cap`, `min_output_tokens`, `chars_per_token`.
  * `observability`: `log_level`, `redact_sensitive_data`, `low_retrieval_score_threshold`, `sensitive_patterns`.

---

### 4. New Methods Added to Existing Interfaces
* **`BaseRetriever` (`core/interfaces/retriever.py`)**:
  * `retrieve_with_scores(self, embedding: List[float], top_k: int = 3) -> List[ScoredDocument]`
* **`Document` (`core/interfaces/retriever.py`)**:
  * `to_dict(self) -> Dict[str, Any]` (plus `score` attribute and `ScoredDocument` class)
* **`BaseEmbedder` (`core/interfaces/embedder.py`)**:
  * `model_name(self) -> str` (property)
* **`ModelRegistry` (`core/registry/model_registry.py`)**:
  * `register_llm_provider(provider_name, factory)`, `register_provider(provider_name, factory)`, `register_embedder_provider(provider_name, factory)`, `register_model(model_name, model_config, factory)`, `register_embedding_model(model_name, model_config, factory)`, `get_model(model_name)`, `get_embedder(model_name)`, `get_active_embedder()`, `list_models()`, `list_embedding_models()`
* **`PromptBuilder` (`core/services/prompt_builder.py`)**:
  * `set_profile(profile_name)`, `get_system_prompt(profile)`, `list_profiles()`
* **New Interfaces**:
  * `BaseReranker` (`core/interfaces/reranker.py`): `rerank()`, `rerank_with_scores()`, `reranker_name`
  * `BaseChunker` (`core/interfaces/chunker.py`): `chunk_text()`, `chunk_documents()`, `chunk()`, `chunk_size`, `chunk_overlap`, `strategy_name`

