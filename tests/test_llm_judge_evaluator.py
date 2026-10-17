from core.implementations.hf_local_llm import LocalHFLLM
from core.implementations.llm_judge_evaluator import LLMJudgeEvaluator
from core.interfaces.llm import BaseLLM
from core.interfaces.retriever import Document


class _FixedLLM(BaseLLM):
    """Deterministic LLM returning a canned reply, for parser unit tests."""

    def __init__(self, reply: str):
        self._reply = reply

    def generate(self, prompt, config=None):
        return self._reply

    @property
    def context_window(self) -> int:
        return 4096

    @property
    def model_name(self) -> str:
        return "fixed-llm"


def test_parses_numeric_score():
    evaluator = LLMJudgeEvaluator(llm=_FixedLLM("My score is 7 out of 10"))
    metrics = evaluator.evaluate("query", [Document(content="context")], "answer")
    assert metrics["llm_judge_score"] == 0.7


def test_missing_score_defaults_to_zero():
    evaluator = LLMJudgeEvaluator(llm=_FixedLLM("no number present"))
    metrics = evaluator.evaluate("query", [], "answer")
    assert metrics["llm_judge_score"] == 0.0


def test_score_is_clamped_to_one():
    evaluator = LLMJudgeEvaluator(llm=_FixedLLM("15"))
    metrics = evaluator.evaluate("query", [], "answer")
    assert metrics["llm_judge_score"] == 1.0


def test_real_local_llm_judge_produces_score():
    evaluator = LLMJudgeEvaluator()
    assert isinstance(evaluator._llm, LocalHFLLM)
    metrics = evaluator.evaluate(
        "What is artificial intelligence?",
        [Document(content="AI is the simulation of human intelligence.")],
        "Artificial intelligence simulates human intelligence in machines.",
    )
    assert 0.0 <= metrics["llm_judge_score"] <= 1.0
