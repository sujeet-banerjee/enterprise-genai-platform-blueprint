import re
from typing import Dict, List, Optional, Union

from core.config.generation_config import GenerationConfig
from core.interfaces.evaluator import BaseEvaluator, normalize_references
from core.interfaces.llm import BaseLLM
from core.interfaces.retriever import Document


class LLMJudgeEvaluator(BaseEvaluator):
    """
    Genuine evaluator that grades an answer with a real LLM acting as a judge.

    The judge is asked for a 0-10 integer score which is normalized to 0-1. Any
    caller-supplied LLM is used; otherwise a local HF model is created (no API
    key required). When no numeric score can be parsed the score defaults to 0.0.

    When a ground-truth reference is supplied via
    :meth:`evaluate_with_ground_truth`, the judge additionally scores the ANSWER
    against the GROUND TRUTH and reports a 0-1 ``answer_correctness``.
    """

    supports_ground_truth = True

    _PROMPT = (
        "You are a strict grader. Given a QUESTION, supporting CONTEXT and an "
        "ANSWER, rate how well the ANSWER addresses the QUESTION using the "
        "CONTEXT. Reply with a single integer between 0 and 10.\n\n"
        "QUESTION: {query}\n\nCONTEXT:\n{context}\n\nANSWER: {answer}\n\nSCORE:"
    )

    _GROUND_TRUTH_PROMPT = (
        "You are a strict grader. Given a QUESTION, a REFERENCE answer and a "
        "CANDIDATE answer, rate how factually correct the CANDIDATE is compared "
        "with the REFERENCE. Reply with a single integer between 0 and 10.\n\n"
        "QUESTION: {query}\n\nREFERENCE:\n{reference}\n\nCANDIDATE: {answer}\n\nSCORE:"
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

    def _score_from(self, raw: str) -> float:
        match = re.search(r"\d+", raw or "")
        if not match:
            return 0.0
        return max(0.0, min(1.0, int(match.group()) / 10.0))

    def _judge(self, query: str, context: str, answer: str) -> float:
        prompt = self._PROMPT.format(query=query, context=context, answer=answer)
        raw = self._llm.generate(prompt, self._config)
        return self._score_from(raw)

    def _judge_against_reference(self, query: str, reference: str, answer: str) -> float:
        prompt = self._GROUND_TRUTH_PROMPT.format(
            query=query, reference=reference, answer=answer
        )
        raw = self._llm.generate(prompt, self._config)
        return self._score_from(raw)

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

    def evaluate_with_ground_truth(
        self,
        query: str,
        retrieved_docs: List[Document],
        response: str,
        ground_truth: Optional[Union[str, List[str]]] = None,
    ) -> Dict[str, float]:
        metrics = self.evaluate(
            query=query, retrieved_docs=retrieved_docs, response=response
        )

        references = normalize_references(ground_truth)
        if not references:
            return metrics

        # Multiple references: the best-matching reference defines correctness.
        correctness = max(
            self._judge_against_reference(query or "", reference, response or "")
            for reference in references
        )
        metrics["answer_correctness"] = correctness
        return metrics


