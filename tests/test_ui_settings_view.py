"""Structured Settings presentation tests (#253)."""

from __future__ import annotations

from pathlib import Path

from ui import settings_view

MODEL_CONFIG = {
    "active_model": "local-qwen",
    "models": {
        "local-qwen": {"provider": "huggingface", "model_name": "Qwen/Qwen2.5-0.5B"},
        "gpt": {"provider": "openai", "api_key": "sk-live-abcdefgh"},
    },
}

RETRIEVAL_CONFIG = {
    "retrieval": {
        "retrieval": {"default_retriever": "faiss", "top_k": 3},
        "reranking": {"enabled": True, "active_reranker": "simple"},
        "evaluation": {"enabled": True, "active_evaluator": "semantic"},
        "cache": {"enabled": False, "max_entries": 128},
    }
}

EFFECTIVE_CONFIG = {
    "models": MODEL_CONFIG,
    **RETRIEVAL_CONFIG,
}

PROVIDERS = {
    "models": {"active": "local-qwen", "models": MODEL_CONFIG["models"]},
    "embedding-models": {"active": "local-minilm", "embedding_models": {"local-minilm": {"provider": "sentence_transformers"}}},
    "retrievers": {"default_retriever": "faiss", "providers": [{"name": "faiss"}, "simple"]},
    "rerankers": {"enabled": True, "active_reranker": "simple", "providers": [{"provider": "simple"}]},
    "evaluators": {"enabled": True, "active_evaluator": "semantic", "providers": {"semantic": {}}},
    "guardrails": {"enabled": False, "profile": "standard", "input": ["injection"], "output": [], "errors": []},
}


def test_settings_view_helpers_are_pure() -> None:
    source = Path("ui/settings_view.py").read_text(encoding="utf-8")
    assert "import streamlit" not in source
    assert "from app." not in source
    assert "from core." not in source
    assert "import app." not in source
    assert "import core." not in source


def test_redact_settings_payload_masks_keys_literals_and_env_refs() -> None:
    payload = {
        "api_key": "sk-live-abcdefgh",
        "authorization": "Bearer abc.def",
        "dsn": "env:GENAI_SECRET",
        "nested": {"token": "${JWT_TOKEN}", "note": "sk-should-not-appear"},
    }
    safe = settings_view.redact_settings_payload(payload)
    assert safe["api_key"] == "[REDACTED]"
    assert safe["authorization"] == "[REDACTED]"
    assert safe["dsn"] == "[ENV REFERENCE]"
    assert safe["nested"]["token"] == "[REDACTED]"
    assert safe["nested"]["note"] == "[REDACTED]"
    assert "sk-live-abcdefgh" not in str(safe)
    assert "Bearer abc.def" not in str(safe)


def test_flatten_config_rows_groups_paths_and_bounds_output() -> None:
    rows = settings_view.flatten_config_rows(RETRIEVAL_CONFIG["retrieval"])
    labels = [row["label"] for row in rows]
    assert "retrieval › default retriever" in labels
    assert "reranking › enabled" in labels
    assert "cache › max entries" in labels
    values = {row["label"]: row["value"] for row in rows}
    assert values["retrieval › default retriever"] == "faiss"
    assert values["reranking › enabled"] == "Yes"
    assert values["cache › enabled"] == "No"
    many = {f"key_{index}": index for index in range(40)}
    limited = settings_view.flatten_config_rows(many, max_rows=5)
    assert len(limited) == 6
    assert limited[-1]["value"] == "Full configuration is in Raw (redacted) below."


def test_provider_rows_summarize_runtime_payloads() -> None:
    assert settings_view.provider_rows("models", PROVIDERS["models"])[0]["value"] == "local-qwen"
    retriever_values = {row["label"]: row["value"] for row in settings_view.provider_rows("retrievers", PROVIDERS["retrievers"])}
    assert retriever_values["Default"] == "faiss"
    assert retriever_values["Providers"] == "faiss, simple"
    guardrail_values = {row["label"]: row["value"] for row in settings_view.provider_rows("guardrails", PROVIDERS["guardrails"])}
    assert guardrail_values["Profile"] == "standard"
    assert guardrail_values["Input Rules"] == "1"
    assert guardrail_values["Enabled"] == "No"
    assert settings_view.provider_rows("unknown", PROVIDERS["models"]) == []
    assert settings_view.provider_rows("models", {}) == []


def test_config_sections_cover_all_required_groups() -> None:
    sections = settings_view.config_sections(EFFECTIVE_CONFIG, PROVIDERS)
    assert [section["title"] for section in sections] == [
        "Models",
        "Retrieval",
        "Reranking",
        "Evaluation",
        "Guardrails",
        "Observability",
        "Cache",
    ]
    models = sections[0]
    assert "active model" in [row["label"] for row in models["rows"]]
    assert "Runtime providers" in models["body_html"]
    assert sections[5]["rows"] == []


def test_settings_view_models_summarize_kpis_and_redact_raw_payload() -> None:
    view = settings_view.settings_view_models(EFFECTIVE_CONFIG, PROVIDERS)
    assert [kpi["label"] for kpi in view["kpis"]] == [
        "Active model",
        "Retriever",
        "Reranking",
        "Evaluator",
        "Cache",
    ]
    assert [kpi["value"] for kpi in view["kpis"]] == [
        "local-qwen",
        "faiss",
        "Enabled",
        "semantic",
        "Disabled",
    ]
    assert view["raw"]["config"]["models"]["models"]["gpt"]["api_key"] == "[REDACTED]"
    assert "sk-live-abcdefgh" not in str(view)
    assert view["expander_label"] == "Raw (redacted)"


def test_settings_view_models_handle_empty_payloads() -> None:
    view = settings_view.settings_view_models()
    assert len(view["sections"]) == 7
    assert view["raw"] == {"config": {}, "providers": {}}
    assert [kpi["value"] for kpi in view["kpis"]] == ["-", "-", "-", "-", "-"]
    assert "No details available." in view["sections_markdown"]


def test_settings_markdown_escapes_config_values() -> None:
    sections = settings_view.config_sections({"models": {"summary": "<img src=x>", "active_model": "local-qwen"}})
    html = settings_view.settings_sections_markdown(sections)
    assert "genai-settings-sections" in html
    assert "&lt;img src=x&gt;" in html
    assert "<img src=x>" not in html
    assert "No configuration sections available." in settings_view.settings_sections_markdown([])


def test_app_wires_structured_settings_without_raw_dumps() -> None:
    source = Path("ui/app.py").read_text(encoding="utf-8")
    start = source.index("def screen_settings")
    end = source.index("\nSCREENS", start)
    body = source[start:end]
    assert "settings_view_models(" in body
    assert 'view["kpis_markdown"]' in body
    assert 'view["sections_markdown"]' in body
    assert "with st.expander(RAW_EXPANDER_LABEL, expanded=False)" in body
    assert 'st.json(view["raw"])' in body
    for call in ("api.models", "api.embedding_models", "api.retrievers", "api.rerankers", "api.evaluators", "api.guardrails"):
        assert call in body
    assert 'st.json(config.data.get("config", {}))' not in body
    assert 'st.subheader("Providers")' not in body


def test_settings_wireframe_and_theme_are_indexed() -> None:
    assert Path("docs/wireframes/253-settings-view.excalidraw").is_file()
    assert Path("docs/wireframes/253-settings-view.svg").is_file()
    plan = Path("docs/ui-enterprise-look-and-feel-plan.md").read_text(encoding="utf-8")
    assert "253-settings-view.svg" in plan
    theme = Path("ui/theme.py").read_text(encoding="utf-8")
    assert "genai-settings-sections" in theme
