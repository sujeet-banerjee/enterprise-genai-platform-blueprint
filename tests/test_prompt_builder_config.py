import pytest
from core.services.prompt_builder import PromptBuilder
from core.interfaces.retriever import Document


def test_prompt_builder_loads_yaml():
    builder = PromptBuilder("config/prompt_config.yaml")
    assert builder.system_prompt is not None
    assert "{context}" in builder.template
    assert "{query}" in builder.template


def test_prompt_builder_profile_switching():
    builder = PromptBuilder("config/prompt_config.yaml", profile="concise")
    assert builder.active_profile == "concise"

    docs = [Document(content="Doc content here.")]
    prompt = builder.build("What is the result?", docs)
    assert "Doc content here." in prompt
    assert "What is the result?" in prompt


def test_prompt_builder_fallback_for_missing_profile():
    builder = PromptBuilder("config/prompt_config.yaml", profile="non_existent_profile")
    assert builder.system_prompt is not None
    docs = [Document(content="Some context")]
    prompt = builder.build("My query", docs)
    assert "Some context" in prompt
    assert "My query" in prompt
