class TokenBudgetService:
    """
    Computes token constraints
    Enforces context window
    Concerned with token economics
    """
    def __init__(self, policy_mode: str = "strict", max_output_cap: int = 512):
        self.policy_mode = policy_mode
        self.max_output_cap = max_output_cap

    def estimate_tokens(self, text: str) -> int:
        # Placeholder: 1 token ≈ 4 chars (rough heuristic)
        return max(1, len(text) // 4)

    def compute_budget(
        self,
        query: str,
        retrieved_docs: list,
        system_prompt: str,
        context_window: int,
        requested_max_tokens: int
    ):
        input_tokens = (
            self.estimate_tokens(system_prompt) +
            self.estimate_tokens(query) +
            sum(self.estimate_tokens(doc.content) for doc in retrieved_docs)
        )

        remaining = context_window - input_tokens

        if remaining <= 0:
            raise ValueError("Context window exceeded before generation.")

        allowed_output = min(remaining, requested_max_tokens, self.max_output_cap)

        return {
            "input_tokens_estimated": input_tokens,
            "remaining_budget": remaining,
            "allowed_output_tokens": allowed_output
        }