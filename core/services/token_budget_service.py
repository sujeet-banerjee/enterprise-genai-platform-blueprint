from pathlib import Path
from typing import List, Optional, Union
import yaml

from core.interfaces.retriever import Document


class TokenBudgetExceededError(ValueError):
    """
    Raised when the token budget cannot fit within the model context window.
    Subclasses ValueError for backward compatibility.
    """

    def __init__(self, message: str, budget_details: Optional[dict] = None):
        super().__init__(message)
        self.failure_type = "token_budget_exceeded"
        self.budget_details = budget_details or {}


class TokenBudgetService:
    """
    Computes token constraints and enforces context window governance.
    Supports two explicitly defined modes:
      - 'strict': Treats context window as a hard constraint and fails if budget <= 0.
      - 'truncate': Removes/truncates lowest-priority retrieved context to fit the window.
    """

    VALID_MODES = ("strict", "truncate")

    def __init__(
        self,
        policy_mode: Optional[str] = None,
        max_output_cap: Optional[int] = None,
        mode: Optional[str] = None,
        budget_mode: Optional[str] = None,
        config_path: Optional[str] = None,
    ):
        cfg = self._load_config(config_path)
        tb_cfg = cfg.get("token_budget", {})

        resolved_mode = (
            mode
            or budget_mode
            or policy_mode
            or tb_cfg.get("default_mode", "strict")
        ).lower()

        if resolved_mode not in self.VALID_MODES:
            raise ValueError(f"Unsupported token budget mode: '{resolved_mode}'. Must be one of {self.VALID_MODES}.")

        self.policy_mode = resolved_mode
        self.budget_mode = resolved_mode
        self.max_output_cap = max_output_cap
        self.min_output_tokens = int(tb_cfg.get("min_output_tokens", 16))
        self.chars_per_token = max(1, int(tb_cfg.get("chars_per_token", 4)))

    @staticmethod
    def _load_config(config_path: Optional[str] = None) -> dict:
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "retrieval.yaml"
            config_path = str(default_path)
        try:
            with open(config_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // self.chars_per_token)

    def _truncate_text_to_tokens(self, text: str, target_tokens: int) -> str:
        if target_tokens <= 0:
            return ""
        max_chars = target_tokens * self.chars_per_token
        return text[:max_chars]

    @staticmethod
    def _extract_doc_score(doc: Union[Document, dict, str], default_rank: int, total: int) -> float:
        if isinstance(doc, Document):
            if getattr(doc, "score", None) is not None:
                return float(doc.score)
            if isinstance(doc.metadata, dict) and doc.metadata.get("score") is not None:
                return float(doc.metadata["score"])
        elif isinstance(doc, dict) and doc.get("score") is not None:
            return float(doc["score"])
        return float(total - default_rank)

    @staticmethod
    def _extract_doc_content(doc: Union[Document, dict, str]) -> str:
        if isinstance(doc, Document):
            return doc.content
        if isinstance(doc, dict):
            return str(doc.get("content", ""))
        return str(doc)

    @staticmethod
    def _clone_doc_with_content(doc: Union[Document, dict, str], new_content: str, truncated: bool = False) -> Document:
        if isinstance(doc, Document):
            meta = dict(doc.metadata) if doc.metadata else {}
            if truncated:
                meta["truncated"] = True
            return Document(content=new_content, metadata=meta, score=doc.score)
        if isinstance(doc, dict):
            meta = dict(doc.get("metadata") or {})
            if truncated:
                meta["truncated"] = True
            return Document(content=new_content, metadata=meta, score=doc.get("score"))
        return Document(content=new_content, metadata={"truncated": truncated})

    def compute_budget(
        self,
        query: str = "",
        retrieved_docs: Optional[List[Union[Document, dict, str]]] = None,
        system_prompt: str = "",
        context_window: int = 4096,
        requested_max_tokens: int = 256,
        *,
        system_prompt_tokens: Optional[int] = None,
        user_query_tokens: Optional[int] = None,
        retrieved_context_tokens: Optional[int] = None,
        requested_max_output_tokens: Optional[int] = None,
        mode: Optional[str] = None,
    ) -> dict:
        active_mode = (mode or self.policy_mode).lower()
        if active_mode not in self.VALID_MODES:
            raise ValueError(f"Unsupported token budget mode: '{active_mode}'.")

        sys_tokens = (
            int(system_prompt_tokens)
            if system_prompt_tokens is not None
            else self.estimate_tokens(system_prompt)
        )
        qry_tokens = (
            int(user_query_tokens)
            if user_query_tokens is not None
            else self.estimate_tokens(query)
        )
        req_max = (
            int(requested_max_output_tokens)
            if requested_max_output_tokens is not None
            else int(requested_max_tokens)
        )
        if self.max_output_cap is not None:
            req_max_capped = min(req_max, int(self.max_output_cap))
        else:
            req_max_capped = req_max

        docs_list = list(retrieved_docs) if retrieved_docs is not None else []
        if retrieved_context_tokens is not None:
            original_context_tokens = int(retrieved_context_tokens)
        else:
            original_context_tokens = sum(
                self.estimate_tokens(self._extract_doc_content(doc)) for doc in docs_list
            )

        base_tokens = sys_tokens + qry_tokens

        if active_mode == "strict":
            available_output_tokens = (
                int(context_window)
                - sys_tokens
                - qry_tokens
                - original_context_tokens
            )

            if available_output_tokens <= 0:
                details = {
                    "requested_max_tokens": req_max,
                    "allowed_output_tokens": 0,
                    "available_output_tokens": available_output_tokens,
                    "original_context_tokens": original_context_tokens,
                    "final_context_tokens": original_context_tokens,
                    "documents_removed": 0,
                    "documents_truncated": 0,
                    "documents_removed_or_truncated": 0,
                    "budget_mode": active_mode,
                    "fits_context_window": False,
                }
                raise TokenBudgetExceededError(
                    "Context window exceeded before generation in strict mode.",
                    budget_details=details,
                )

            allowed_output_tokens = min(req_max_capped, available_output_tokens)
            retained_docs = [
                self._clone_doc_with_content(d, self._extract_doc_content(d))
                for d in docs_list
            ]

            return {
                "requested_max_tokens": req_max,
                "allowed_output_tokens": allowed_output_tokens,
                "available_output_tokens": available_output_tokens,
                "remaining_budget": available_output_tokens,
                "original_context_tokens": original_context_tokens,
                "final_context_tokens": original_context_tokens,
                "input_tokens_estimated": base_tokens + original_context_tokens,
                "system_prompt_tokens": sys_tokens,
                "user_query_tokens": qry_tokens,
                "retrieved_context_tokens": original_context_tokens,
                "documents_removed": 0,
                "documents_truncated": 0,
                "documents_removed_or_truncated": 0,
                "budget_mode": active_mode,
                "fits_context_window": True,
                "retained_docs": retained_docs,
            }

        # Mode 2 — Truncate
        available_for_context_and_output = int(context_window) - base_tokens
        if available_for_context_and_output <= 0:
            details = {
                "requested_max_tokens": req_max,
                "allowed_output_tokens": 0,
                "original_context_tokens": original_context_tokens,
                "final_context_tokens": 0,
                "documents_removed": len(docs_list),
                "documents_truncated": 0,
                "documents_removed_or_truncated": len(docs_list),
                "budget_mode": active_mode,
                "fits_context_window": False,
            }
            raise TokenBudgetExceededError(
                "Context window exceeded by system prompt and user query alone.",
                budget_details=details,
            )

        # Determine how many tokens to reserve for output so the request fits safely
        if available_for_context_and_output > req_max_capped:
            reserved_output = req_max_capped
        else:
            reserved_output = min(
                req_max_capped,
                max(1, min(self.min_output_tokens, available_for_context_and_output // 2 or 1)),
            )

        max_context_budget = max(0, available_for_context_and_output - reserved_output)

        # Check if initial context already fits
        if original_context_tokens <= max_context_budget:
            final_context_tokens = original_context_tokens
            available_output_tokens = int(context_window) - base_tokens - final_context_tokens
            allowed_output_tokens = min(req_max_capped, available_output_tokens)
            retained_docs = [
                self._clone_doc_with_content(d, self._extract_doc_content(d))
                for d in docs_list
            ]
            return {
                "requested_max_tokens": req_max,
                "allowed_output_tokens": allowed_output_tokens,
                "available_output_tokens": available_output_tokens,
                "remaining_budget": available_output_tokens,
                "original_context_tokens": original_context_tokens,
                "final_context_tokens": final_context_tokens,
                "input_tokens_estimated": base_tokens + final_context_tokens,
                "system_prompt_tokens": sys_tokens,
                "user_query_tokens": qry_tokens,
                "retrieved_context_tokens": final_context_tokens,
                "documents_removed": 0,
                "documents_truncated": 0,
                "documents_removed_or_truncated": 0,
                "budget_mode": active_mode,
                "fits_context_window": True,
                "retained_docs": retained_docs,
            }

        # Need to remove/truncate lowest-priority context
        documents_removed = 0
        documents_truncated = 0
        retained_docs: List[Document] = []

        if docs_list:
            total_docs = len(docs_list)
            # Order by priority: highest score first; tie-break by original rank
            prioritized = sorted(
                enumerate(docs_list),
                key=lambda item: (self._extract_doc_score(item[1], item[0], total_docs), -item[0]),
                reverse=True,
            )

            used_context_tokens = 0
            kept_with_index = []

            for orig_idx, doc in prioritized:
                content = self._extract_doc_content(doc)
                doc_tokens = self.estimate_tokens(content)
                remaining_context_space = max_context_budget - used_context_tokens

                if remaining_context_space <= 0:
                    documents_removed += 1
                    continue

                if doc_tokens <= remaining_context_space:
                    kept_with_index.append((orig_idx, self._clone_doc_with_content(doc, content, truncated=False)))
                    used_context_tokens += doc_tokens
                else:
                    # Truncate this document to fit the remaining context space
                    truncated_content = self._truncate_text_to_tokens(content, remaining_context_space)
                    truncated_tokens = self.estimate_tokens(truncated_content)
                    if truncated_content and truncated_tokens <= remaining_context_space:
                        kept_with_index.append(
                            (orig_idx, self._clone_doc_with_content(doc, truncated_content, truncated=True))
                        )
                        used_context_tokens += truncated_tokens
                        documents_truncated += 1
                    else:
                        documents_removed += 1

            # Restore priority order in retained_docs
            retained_docs = [doc_obj for _, doc_obj in kept_with_index]
            final_context_tokens = used_context_tokens
        else:
            # Token-count-only invocation without document objects
            final_context_tokens = max_context_budget
            documents_removed = 1 if final_context_tokens == 0 else 0
            documents_truncated = 1 if 0 < final_context_tokens < original_context_tokens else 0

        available_output_tokens = int(context_window) - base_tokens - final_context_tokens
        allowed_output_tokens = min(req_max_capped, available_output_tokens)

        return {
            "requested_max_tokens": req_max,
            "allowed_output_tokens": allowed_output_tokens,
            "available_output_tokens": available_output_tokens,
            "remaining_budget": available_output_tokens,
            "original_context_tokens": original_context_tokens,
            "final_context_tokens": final_context_tokens,
            "input_tokens_estimated": base_tokens + final_context_tokens,
            "system_prompt_tokens": sys_tokens,
            "user_query_tokens": qry_tokens,
            "retrieved_context_tokens": final_context_tokens,
            "documents_removed": documents_removed,
            "documents_truncated": documents_truncated,
            "documents_removed_or_truncated": documents_removed + documents_truncated,
            "budget_mode": active_mode,
            "fits_context_window": True,
            "retained_docs": retained_docs,
        }
