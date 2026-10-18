"""Tests for issue #13: the OpenAI provider must honor model/generation config.

Acceptance criteria:
1. The configured model name is the model actually called.
2. GenerationConfig fields reach the provider request.
3. model_name / context_window reflect configuration (not hardcoded).
4. The prompt's system role is emitted as a distinct system message.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from app.main import build_pipeline
from core.config.generation_config import GenerationConfig
from core.implementations.openai_llm import OpenAILLM
from core.registry.model_registry import ModelRegistry


def _mock_client(response_text: str = "Mock response"):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=response_text))]
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


def test_configured_model_name_is_the_model_called():
    with patch("core.implementations.openai_llm.OpenAI") as mock_openai:
        mock_openai.return_value = _mock_client()
        llm = OpenAILLM(api_key="fake", model_name="gpt-4")
        llm.generate("Hello")

        kwargs = mock_openai.return_value.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == "gpt-4"


def test_context_window_and_model_name_reflect_configuration():
    with patch("core.implementations.openai_llm.OpenAI"):
        llm = OpenAILLM(api_key="fake", model_name="gpt-4-turbo", context_window=128000)

    assert llm.model_name == "gpt-4-turbo"
    assert llm.context_window == 128000


def test_default_model_name_is_preserved():
    with patch("core.implementations.openai_llm.OpenAI"):
        llm = OpenAILLM(api_key="fake")

    assert llm.model_name == "gpt-4o-mini"
    assert llm.context_window == 128000


def test_generation_config_fields_reach_provider_request():
    with patch("core.implementations.openai_llm.OpenAI") as mock_openai:
        mock_openai.return_value = _mock_client()
        llm = OpenAILLM(api_key="fake", model_name="gpt-4")
        llm.generate(
            "Hello",
            GenerationConfig(temperature=0.2, max_tokens=321, top_p=0.55, stop=["\n"]),
        )

        kwargs = mock_openai.return_value.chat.completions.create.call_args.kwargs
        assert kwargs["temperature"] == 0.2
        assert kwargs["max_tokens"] == 321
        assert kwargs["top_p"] == 0.55
        assert kwargs["stop"] == ["\n"]


def test_system_prompt_emitted_as_system_role():
    with patch("core.implementations.openai_llm.OpenAI") as mock_openai:
        mock_openai.return_value = _mock_client()
        llm = OpenAILLM(api_key="fake")
        llm.generate(
            "What is AI?",
            GenerationConfig(system_prompt="You are a helpful assistant."),
        )

        kwargs = mock_openai.return_value.chat.completions.create.call_args.kwargs
        messages = kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful assistant."
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "What is AI?"


def test_inlined_system_prompt_not_duplicated_in_user_message():
    system = "You are a helpful assistant."
    prompt = f"{system}\n\nContext:\ndocs\n\nQuestion:\nWhat is AI?"

    with patch("core.implementations.openai_llm.OpenAI") as mock_openai:
        mock_openai.return_value = _mock_client()
        llm = OpenAILLM(api_key="fake")
        llm.generate(prompt, GenerationConfig(system_prompt=system))

        kwargs = mock_openai.return_value.chat.completions.create.call_args.kwargs
        user_content = kwargs["messages"][1]["content"]
        assert user_content.count(system) == 0
        assert "What is AI?" in user_content


def test_no_system_message_without_system_prompt():
    with patch("core.implementations.openai_llm.OpenAI") as mock_openai:
        mock_openai.return_value = _mock_client()
        llm = OpenAILLM(api_key="fake")
        llm.generate("Hello")

        kwargs = mock_openai.return_value.chat.completions.create.call_args.kwargs
        roles = [m["role"] for m in kwargs["messages"]]
        assert roles == ["user"]


def test_registry_passes_model_config_to_openai_provider():
    with patch("core.implementations.openai_llm.OpenAI"):
        registry = ModelRegistry()
        registry.register_model(
            "custom-gpt",
            {
                "provider": "openai",
                "context_window": 64000,
                "api_key": "fake-key",
            },
        )
        llm = registry.get_model("custom-gpt")

        assert isinstance(llm, OpenAILLM)
        assert llm.model_name == "custom-gpt"
        assert llm.context_window == 64000


def _write_yaml(path: Path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path)


def test_pipeline_passes_system_prompt_to_llm_via_generation_config(tmp_path):
    models = _write_yaml(
        tmp_path / "models.yaml",
        {
            "active_model": "dummy",
            "active_embedding_model": "dummy",
            "models": {"dummy": {"provider": "dummy", "context_window": 4096}},
            "embedding_models": {"dummy": {"provider": "dummy", "model_name": "dummy-embedder"}},
        },
    )
    prompt_cfg = _write_yaml(
        tmp_path / "prompt_config.yaml",
        {
            "active_prompt_profile": "default",
            "profiles": {
                "default": {
                    "system_prompt": "You are a helpful assistant.",
                    "template": "{system_prompt}\n\nQuestion:\n{query}",
                }
            },
        },
    )
    retrieval = _write_yaml(
        tmp_path / "retrieval.yaml",
        {
            "retrieval": {
                "default_retriever": "dummy",
                "top_k": 3,
                "similarity_metric": "cosine",
                "retrievers": {"dummy": {"provider": "dummy"}},
            },
            "evaluation": {"enabled": False},
            "reranking": {"strategy": "lexical_hybrid", "top_k": 3},
            "token_budget": {"default_mode": "strict", "max_output_cap": 512},
            "observability": {"low_retrieval_score_threshold": 0.0},
        },
    )

    pipeline = build_pipeline(
        models_config_path=Path(models),
        prompt_config_path=Path(prompt_cfg),
        retrieval_config_path=Path(retrieval),
    )
    result = pipeline.run("What is artificial intelligence?", raise_on_failure=False)

    # DummyLLM echoes the GenerationConfig it received; the configured system
    # prompt must ride along as config.system_prompt for chat-role providers.
    assert "system_prompt='You are a helpful assistant.'" in result["response"]
