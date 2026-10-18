import time
from typing import Dict, Optional

# Placeholder list prices used when a model declares no pricing of its own.
# Non-zero so cost governance remains meaningful for unpriced (e.g. local) models.
DEFAULT_INPUT_COST_PER_1K = 0.001
DEFAULT_OUTPUT_COST_PER_1K = 0.002


class CostTracker:
    """
    Computes per-request cost from input/output token counts and per-model
    pricing (models.yaml). Rates are resolved in order: explicit constructor
    values (active model), a model_pricing map keyed by model name, then the
    module defaults (issue #14).
    """

    def __init__(
        self,
        input_cost_per_1k: Optional[float] = None,
        output_cost_per_1k: Optional[float] = None,
        model_pricing: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
    ):
        self.input_cost_per_1k = (
            float(input_cost_per_1k) if input_cost_per_1k is not None else None
        )
        self.output_cost_per_1k = (
            float(output_cost_per_1k) if output_cost_per_1k is not None else None
        )
        self.model_pricing = model_pricing or {}

    def rates_for(self, model_name: str) -> tuple:
        """
        Return (input_cost_per_1k, output_cost_per_1k) for a model. Explicit
        rates win, then the model_pricing map, then the module defaults.
        """
        priced = self.model_pricing.get(model_name, {}) or {}
        priced_in = priced.get("input_cost_per_1k")
        priced_out = priced.get("output_cost_per_1k")
        in_rate = (
            self.input_cost_per_1k
            if self.input_cost_per_1k is not None
            else (float(priced_in) if priced_in is not None else DEFAULT_INPUT_COST_PER_1K)
        )
        out_rate = (
            self.output_cost_per_1k
            if self.output_cost_per_1k is not None
            else (float(priced_out) if priced_out is not None else DEFAULT_OUTPUT_COST_PER_1K)
        )
        return in_rate, out_rate

    def compute(
        self,
        model_name: str,
        start_time: float,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ) -> dict:
        """
        Estimate cost as (input_tokens / 1000 * input_rate) +
        (output_tokens / 1000 * output_rate). Callers that supply no token
        counts get a cost of 0 (nothing to price).
        """
        latency_ms = (time.time() - start_time) * 1000
        in_rate, out_rate = self.rates_for(model_name)

        in_tokens = int(input_tokens) if input_tokens is not None else 0
        out_tokens = int(output_tokens) if output_tokens is not None else 0
        estimated_cost = (in_tokens / 1000.0) * in_rate + (out_tokens / 1000.0) * out_rate

        return {
            "model": model_name,
            "latency_ms": round(latency_ms, 2),
            "estimated_cost_usd": estimated_cost,
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "input_cost_per_1k": in_rate,
            "output_cost_per_1k": out_rate,
        }
