from typing import List, Dict, Any, Optional
from core.interfaces.retriever import Document


class TokenBudgetService:
    """
    Computes token constraints and enforces context window.
    Supports configurable budget strategies:
    - strict: treats context window as a hard constraint and fails if budget is exceeded.
    - truncate: removes or truncates lowest-priority context to fit within the context window.
    """

    def __init__(self, policy_mode: str = "strict", max_output_cap: int = 512):
        self.policy_mode = policy_mode.lower() if policy_mode else "strict"
        self.max_output_cap = max_output_cap

    def estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        # 1 token ≈ 4 chars (standard heuristic)
        return max(1, len(text) // 4)

    def _get_doc_text(self, doc: Any) -> str:
        if isinstance(doc, Document) or hasattr(doc, "content"):
            return doc.content
        return str(doc)

    def _get_doc_score(self, doc: Any) -> float:
        if hasattr(doc, "score") and doc.score is not None:
            return float(doc.score)
        if hasattr(doc, "metadata") and isinstance(doc.metadata, dict) and "score" in doc.metadata:
            try:
                return float(doc.metadata["score"])
            except (ValueError, TypeError):
                pass
        return 0.0

    def compute_budget(
        self,
        query: str,
        retrieved_docs: List[Any],
        system_prompt: str,
        context_window: int,
        requested_max_tokens: int,
        budget_mode: Optional[str] = None
    ) -> Dict[str, Any]:
        mode = (budget_mode or self.policy_mode).lower()

        system_tokens = self.estimate_tokens(system_prompt)
        query_tokens = self.estimate_tokens(query)
        fixed_tokens = system_tokens + query_tokens

        doc_token_counts = [self.estimate_tokens(self._get_doc_text(d)) for d in retrieved_docs]
        original_context_tokens = sum(doc_token_counts)

        if mode == "truncate":
            return self._compute_truncate(
                query=query,
                retrieved_docs=retrieved_docs,
                fixed_tokens=fixed_tokens,
                original_context_tokens=original_context_tokens,
                context_window=context_window,
                requested_max_tokens=requested_max_tokens
            )
        else:
            return self._compute_strict(
                fixed_tokens=fixed_tokens,
                original_context_tokens=original_context_tokens,
                context_window=context_window,
                requested_max_tokens=requested_max_tokens,
                retrieved_docs=retrieved_docs
            )

    def _compute_strict(
        self,
        fixed_tokens: int,
        original_context_tokens: int,
        context_window: int,
        requested_max_tokens: int,
        retrieved_docs: List[Any]
    ) -> Dict[str, Any]:
        input_tokens = fixed_tokens + original_context_tokens
        available_output_tokens = context_window - input_tokens

        if available_output_tokens <= 0:
            raise ValueError(
                f"Context window exceeded before generation: input tokens ({input_tokens}) "
                f"exceed or equal context window ({context_window})."
            )

        cap = self.max_output_cap if self.max_output_cap and self.max_output_cap > 0 else requested_max_tokens
        allowed_output = min(available_output_tokens, requested_max_tokens, cap)

        return {
            "input_tokens_estimated": input_tokens,
            "remaining_budget": available_output_tokens,
            "allowed_output_tokens": allowed_output,
            "requested_max_tokens": requested_max_tokens,
            "original_context_tokens": original_context_tokens,
            "final_context_tokens": original_context_tokens,
            "documents_removed": 0,
            "retained_docs": list(retrieved_docs),
            "budget_mode": "strict"
        }

    def _compute_truncate(
        self,
        query: str,
        retrieved_docs: List[Any],
        fixed_tokens: int,
        original_context_tokens: int,
        context_window: int,
        requested_max_tokens: int
    ) -> Dict[str, Any]:
        if fixed_tokens >= context_window:
            raise ValueError(
                f"Context window exceeded before generation: fixed prompt tokens ({fixed_tokens}) "
                f"exceed context window ({context_window})."
            )

        target_output = requested_max_tokens
        if self.max_output_cap and self.max_output_cap > 0:
            target_output = min(target_output, self.max_output_cap)

        context_budget_for_docs = context_window - fixed_tokens - target_output

        # Order docs by score/priority (highest score first)
        indexed_docs = list(enumerate(retrieved_docs))
        indexed_docs.sort(key=lambda item: self._get_doc_score(item[1]), reverse=True)

        retained_indexed: List[tuple] = []
        current_context_tokens = 0

        for idx, doc in indexed_docs:
            doc_tokens = self.estimate_tokens(self._get_doc_text(doc))
            if current_context_tokens + doc_tokens <= max(0, context_budget_for_docs):
                retained_indexed.append((idx, doc))
                current_context_tokens += doc_tokens

        # Restore original relative ordering for retained documents
        retained_indexed.sort(key=lambda item: item[0])
        retained_docs = [doc for _, doc in retained_indexed]

        input_tokens = fixed_tokens + current_context_tokens
        available_output = context_window - input_tokens

        if available_output <= 0:
            retained_docs = []
            current_context_tokens = 0
            input_tokens = fixed_tokens
            available_output = context_window - input_tokens

        if available_output <= 0:
            raise ValueError("Context window exceeded before generation.")

        allowed_output = min(available_output, requested_max_tokens, target_output)

        return {
            "input_tokens_estimated": input_tokens,
            "remaining_budget": available_output,
            "allowed_output_tokens": allowed_output,
            "requested_max_tokens": requested_max_tokens,
            "original_context_tokens": original_context_tokens,
            "final_context_tokens": current_context_tokens,
            "documents_removed": len(retrieved_docs) - len(retained_docs),
            "retained_docs": retained_docs,
            "budget_mode": "truncate"
        }
