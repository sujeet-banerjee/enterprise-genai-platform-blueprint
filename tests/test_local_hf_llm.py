import pytest

from core.config.generation_config import GenerationConfig
from core.implementations.hf_local_llm import LocalHFLLM


@pytest.fixture(scope="module")
def llm():
    return LocalHFLLM(max_new_tokens=64)


def test_generates_non_empty_text(llm):
    out = llm.generate(
        "What is the capital of France?",
        GenerationConfig(temperature=0.0, max_tokens=32),
    )
    assert isinstance(out, str)
    assert out.strip()


def test_answer_contains_relevant_terms(llm):
    out = llm.generate(
        "In one sentence, what is artificial intelligence?",
        GenerationConfig(temperature=0.0, max_tokens=64),
    )
    low = out.lower()
    assert "intelligence" in low or "artificial" in low or "computer" in low


def test_greedy_generation_is_deterministic(llm):
    prompt = "Complete the sentence: the sky is"
    first = llm.generate(prompt, GenerationConfig(temperature=0.0, max_tokens=16))
    second = llm.generate(prompt, GenerationConfig(temperature=0.0, max_tokens=16))
    assert first == second


def test_model_metadata(llm):
    assert llm.model_name == "Qwen/Qwen2.5-0.5B-Instruct"
    assert llm.context_window == 32768


def test_max_new_tokens_cap_bounds_output():
    capped = LocalHFLLM(max_new_tokens=4)
    out = capped.generate(
        "Tell me a very long and detailed story about the ocean.",
        GenerationConfig(temperature=0.0, max_tokens=512),
    )
    assert len(out.split()) <= 8
