import time

class CostTracker:

    def compute(self, model_name: str, start_time: float) -> dict:
        latency_ms = (time.time() - start_time) * 1000

        # Dummy cost logic for now
        estimated_cost = 0.001

        return {
            "model": model_name,
            "latency_ms": round(latency_ms, 2),
            "estimated_cost_usd": estimated_cost
        }