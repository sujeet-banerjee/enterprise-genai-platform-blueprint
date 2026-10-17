import re
from typing import Dict, List, Optional

from core.config.generation_config import GenerationConfig
from core.interfaces.evaluator import BaseEvaluator
from core.interfaces.llm import BaseLLM
from core.interfaces.retriever import Document


class LLMJudgeEvaluator(BaseEvaluator):
    """
    Genuine evaluator that grades an answer with a real LLM acting as a judge.

    The judge is asked for a 0-10 integer score which is normalized to 0-1. Any
    caller-supplied LLM is used; otherwise a local HF model is created (no API
    key required). When no numeric score can be parsed the score defaults to 0.0.
    """

    _PROMPT = (
        "You are a strict grader. Given a QUESTION, supporting CONTEXT and an "
        "ANSWER, rate how well the ANSWER addresses the QUESTION using the "
        "CONTEXT. Reply with a single integer between 0 and 10.\n\n"
        "QUESTION: {query}\n\nCONTEXT:\n{context}\n\nANSWER: {answer}\n\nSCORE:"
    )

    def __init__(
        self,
        llm: Optional[BaseLLM] = None,
        model_name: str = "Qwen/Qwen2.5-0.5B-Instruct",
        context_window: int = 32768,
        max_new_tokens: int = 128,
    ):
        if llm is not None:
            self._llm = llm
        else:
            from core.implementations.hf_local_llm import LocalHFLLM

            self._llm = LocalHFLLM(
                model_name=model_name,
                context_window=context_window,
                max_new_tokens=max_new_tokens,
            )
        self._config = GenerationConfig(temperature=0.0, max_tokens=16)

    def _judge(self, query: str, context: str, answer: str) -> float:
        prompt = self._PROMPT.format(query=query, context=context, answer=answer)
        raw = self._llm.generate(prompt, self._config)
        match = re.search(r"\d+", raw or "")
        if not match:
            return 0.0
        return max(0.0, min(1.0, int(match.group()) / 10.0))

    def evaluate(
        self,
        query: str,
        retrieved_docs: List[Document],
        response: str,
    ) -> Dict[str, float]:
        docs = list(retrieved_docs or [])
        context = "\n".join(
            doc.content if hasattr(doc, "content") else str(doc) for doc in docs
        )
        score = self._judge(query or "", context, response or "")
        return {
            "llm_judge_score": score,
            "answer_relevance": score,
        }
