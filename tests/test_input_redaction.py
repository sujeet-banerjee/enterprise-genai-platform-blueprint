"""Input-side redaction (issue #72).

Redaction must happen on the *data path* - the user query and retrieved doc
content - **before** they are templated into the prompt, sent to the model
provider, or returned to the caller. Previously only observability output was
redacted, so secrets in the query/doc flow leaked to the provider and client.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from core.interfaces.llm import BaseLLM
from core.interfaces.retriever import Document
from core.services.observability import SensitiveDataRedactor


class _CapturingLLM(BaseLLM):
    """Fake LLM that captures the exact prompt it was asked to generate from."""

    def __init__(self, context_window: int = 4096):
        self.prompts: list[str] = []
        self._context_window = context_window

    def generate(self, prompt, config=None):  # noqa: D102
        self.prompts.append(prompt)
        return "ok"

    @property
    def context_window(self):  # noqa: D102
        return self._context_window

    @property
    def model_name(self):  # noqa: D102
        return "capturing-llm"


SECRET_QUERY = "please use api_key=sk-live-1234567890 to call the service"
SECRET_DOC = "server config: password = hunter2secret and other notes"


def _redactor(enabled: bool = True, patterns=None) -> SensitiveDataRedactor:
    return SensitiveDataRedactor(enabled=enabled, patterns=patterns)


# -- data path: query ------------------------------------------------------


def test_query_secret_redacted_before_prompt(make_pipeline):
    llm = _CapturingLLM()
    pipeline = make_pipeline(llm=llm, redactor=_redactor())
    result = pipeline.run(SECRET_QUERY, raise_on_failure=False)

    assert llm.prompts, "the LLM should have been called"
    prompt = llm.prompts[0]
    assert "sk-live-1234567890" not in prompt
    assert "[REDACTED]" in prompt
    # the raw secret never reaches the returned envelope either
    assert "sk-live-1234567890" not in str(result)


def test_query_secret_redacted_in_response_and_docs(make_pipeline):
    pipeline = make_pipeline(redactor=_redactor())
    result = pipeline.run(SECRET_QUERY, raise_on_failure=False)

    assert "sk-live-1234567890" not in str(result["response"])
    assert "sk-live-1234567890" not in str(result["retrieved_docs"])
    assert result["observability"]["redaction_enabled"] is True


# -- data path: retrieved docs --------------------------------------------


def test_doc_secret_redacted_before_prompt(make_pipeline):
    llm = _CapturingLLM()
    docs = [{"content": SECRET_DOC}, {"content": "a totally benign document"}]
    pipeline = make_pipeline(docs=docs, llm=llm, redactor=_redactor())
    result = pipeline.run("what is the server configuration?", raise_on_failure=False)

    prompt = llm.prompts[0]
    assert "hunter2secret" not in prompt
    assert "[REDACTED]" in prompt
    # benign content is preserved
    assert "benign document" in prompt
    assert "hunter2secret" not in str(result)


# -- toggle: explicit opt-out ---------------------------------------------


def test_disabled_redactor_passes_through(make_pipeline):
    llm = _CapturingLLM()
    docs = [{"content": SECRET_DOC}]
    pipeline = make_pipeline(docs=docs, llm=llm, redactor=_redactor(enabled=False))
    result = pipeline.run(SECRET_QUERY, raise_on_failure=False)

    assert "sk-live-1234567890" in llm.prompts[0]
    assert "hunter2secret" in llm.prompts[0]
    assert result["observability"]["redaction_enabled"] is False


def test_no_redactor_is_byte_identical(make_pipeline):
    """With no redactor injected the data path is unchanged (backward compatible)."""
    llm = _CapturingLLM()
    pipeline = make_pipeline(docs=[{"content": SECRET_DOC}], llm=llm)
    result = pipeline.run(SECRET_QUERY, raise_on_failure=False)

    assert "sk-live-1234567890" in llm.prompts[0]
    assert result["observability"]["redaction_enabled"] is False


# -- config-driven patterns -----------------------------------------------


def test_custom_pattern_redacts_custom_token(make_pipeline):
    llm = _CapturingLLM()
    pipeline = make_pipeline(
        llm=llm, redactor=_redactor(patterns=["accountnumber"])
    )
    pipeline.run("customer accountnumber: 9988776655 is flagged", raise_on_failure=False)

    assert "9988776655" not in llm.prompts[0]
    assert "[REDACTED]" in llm.prompts[0]


def test_removing_pattern_disables_that_redaction(make_pipeline):
    llm = _CapturingLLM()
    pipeline = make_pipeline(
        llm=llm, redactor=_redactor(patterns=["ssn"])
    )
    pipeline.run("customer accountnumber: 9988776655", raise_on_failure=False)

    # accountnumber is not a configured pattern -> its value survives
    assert "9988776655" in llm.prompts[0]


# -- unit: _redact_inputs helper ------------------------------------------


def test_redact_inputs_helper_returns_new_documents(make_pipeline):
    pipeline = make_pipeline(redactor=_redactor())
    original = Document(content=SECRET_DOC, metadata={"doc_id": 1}, score=0.9)
    query, docs, applied = pipeline._redact_inputs("api_key=sk-live-9999999999", [original])

    assert applied is True
    assert "sk-live-9999999999" not in query
    assert "hunter2secret" not in docs[0].content
    assert docs[0].metadata.get("doc_id") == 1
    # the original document object is not mutated
    assert original.content == SECRET_DOC


# -- composition root wiring ----------------------------------------------


def _write_yaml(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


def _models_config(tmp_path: Path) -> str:
    return _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": "dummy",
            "active_embedding_model": "dummy",
            "models": {"dummy": {"provider": "dummy", "context_window": 4096}},
            "embedding_models": {
                "dummy": {"provider": "dummy", "model_name": "dummy-embedder"}
            },
        },
    )


def _retrieval_config(tmp_path: Path) -> str:
    return _write_yaml(
        tmp_path / "retrieval.yaml",
        {
            "retrieval": {
                "default_retriever": "dummy",
                "top_k": 3,
                "retrievers": {"dummy": {"provider": "dummy"}},
            },
            "evaluation": {"enabled": False, "active_evaluator": "dummy"},
        },
    )


def _observability_config(tmp_path: Path, enabled: bool) -> str:
    return _write_yaml(
        tmp_path / "observability.yaml",
        {"redact_sensitive_data": enabled, "sensitive_patterns": ["sk-[A-Za-z0-9]{8,}"]},
    )


def test_composition_root_wires_input_redactor(tmp_path):
    from app.main import build_pipeline

    pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(_retrieval_config(tmp_path)),
        observability_config_path=Path(_observability_config(tmp_path, True)),
        governance_config_path=None,
    )
    assert pipeline.redactor is not None
    assert pipeline.redactor.enabled is True
    assert "[REDACTED]" in pipeline.redactor.redact_text("api_key=sk-abcdef1234")


def test_composition_root_respects_redaction_toggle(tmp_path):
    from app.main import build_pipeline

    pipeline = build_pipeline(
        models_config_path=Path(_models_config(tmp_path)),
        retrieval_config_path=Path(_retrieval_config(tmp_path)),
        observability_config_path=Path(_observability_config(tmp_path, False)),
        governance_config_path=None,
    )
    assert pipeline.redactor is not None
    assert pipeline.redactor.enabled is False
    assert pipeline.redactor.redact_text("api_key=sk-abcdef1234") == "api_key=sk-abcdef1234"
